# File: src/intraday/application/services/signal_communication.py
#
# Checkpoint 37 Part 3/6/7: the orchestration layer of the
# BROKER-INDEPENDENT SIGNAL COMMUNICATION ENGINE. `NotificationRouter`
# fans one `SignalCommunicationEvent` out to every configured/enabled
# `CommunicationProvider`; `SignalCommunicationService` is the single
# call site strategy-execution code (or, in a future checkpoint, a
# scheduler) uses - mirroring `PaperSignalExecutionService`'s own
# "caller supplies inputs, service does not reach out for its own data"
# discipline (Checkpoint 36).
#
# Providers are looked up via `application.repositories`-style
# Protocols (dependency inversion, Contract 6 - this module must never
# import `infrastructure.*` directly); concrete Telegram/Discord
# adapters are wired at the `infrastructure/api` composition root,
# exactly like `paper_trading_runtime.py` composes `PaperTradingService`.
from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from intraday.communication.contracts.signal_communication import (
    CommunicationChannel,
    CommunicationOutcome,
    DeliveryAttempt,
    DeliveryStatus,
    MessageTemplateId,
    SignalCommunicationContext,
    SignalCommunicationEvent,
)
from intraday.communication.contracts.templates import render_message
from intraday.domain.shared_kernel.contracts import SignalId


class CommunicationProvider(Protocol):
    """One configured, enabled destination for one channel. `send()`
    returns `(success, provider_message_id_or_None, error_code,
    error_message, is_retryable)` - never raises for an ordinary
    delivery failure (a rejected webhook, an invalid token); only a
    genuinely unexpected condition may raise. `is_retryable`
    (Checkpoint 38 Part 8) classifies the failure per each provider's
    own documented semantics - a 429/5xx is transient (worth retrying);
    401/403/404 is permanent (retrying can never succeed, so the
    router must not waste attempts on it).

    Fields are declared as read-only `@property`-shaped members (not
    plain settable attributes) so that frozen dataclass implementations
    (`TelegramCommunicationProvider`/`DiscordCommunicationProvider`)
    satisfy this Protocol structurally without mypy demanding a
    settable attribute a frozen dataclass can never offer."""

    @property
    def channel(self) -> CommunicationChannel: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def destination_masked(self) -> str: ...

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]: ...


class CommunicationLedger(Protocol):
    """Persistence surface - `application.repositories`-style
    interface; the Django implementation lives in
    `infrastructure/persistence` (Contract 6)."""

    def record_attempt(self, attempt: DeliveryAttempt) -> None: ...

    def already_sent(
        self, *, signal_id: str, event_id: str, channel: CommunicationChannel
    ) -> bool: ...


def _default_backoff_seconds(attempt_number: int) -> float:
    """Exponential backoff, capped - `attempt_number` is 1-indexed (the
    delay BEFORE the 2nd attempt, 3rd attempt, etc.). Capped at 4
    seconds so a bounded retry loop (max 3 attempts total, see
    `NotificationRouter.max_attempts`) can never itself become a
    multi-minute stall - Checkpoint 38 Part 8's explicit "do not create
    infinite retry loops... do not allow retry storms.\" """
    return min(0.5 * (2 ** (attempt_number - 1)), 4.0)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class NotificationRouter:
    """Fans one event out across every configured provider. Contains
    NO template knowledge and NO signal/execution-status knowledge -
    its only job is "render once, send to every provider, record every
    attempt.\"

    Bounded retry (Checkpoint 38 Part 8): a TRANSIENT failure (rate
    limit, 5xx, timeout) is retried up to `max_attempts` times total
    with exponential backoff; a PERMANENT failure (bad token/webhook)
    is never retried. The ledger records only the FINAL outcome per
    provider, with `retry_count` set to how many attempts it actually
    took - the ledger stays the authoritative answer to "was this
    delivered?" without exploding into one row per attempt."""

    providers: tuple[CommunicationProvider, ...]
    ledger: CommunicationLedger | None = None
    max_attempts: int = 3
    backoff_seconds: Callable[[int], float] = field(default=_default_backoff_seconds)
    sleep: Callable[[float], None] = field(default=time.sleep)

    def dispatch(self, event: SignalCommunicationEvent) -> tuple[DeliveryAttempt, ...]:
        if not self.providers:
            return ()
        text = render_message(event.template_id, event.context)
        attempts: list[DeliveryAttempt] = []
        for provider in self.providers:
            attempts.append(self._dispatch_one(event, provider, text))
        return tuple(attempts)

    def _dispatch_one(
        self,
        event: SignalCommunicationEvent,
        provider: CommunicationProvider,
        text: str,
    ) -> DeliveryAttempt:
        communication_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)

        if self.ledger is not None and self.ledger.already_sent(
            signal_id=str(event.signal_id), event_id=event.event_id, channel=provider.channel
        ):
            attempt = DeliveryAttempt(
                communication_id=communication_id,
                signal_id=event.signal_id,
                event_id=event.event_id,
                channel=provider.channel,
                provider=provider.provider_name,
                destination_masked=provider.destination_masked,
                template_id=event.template_id,
                template_version=event.template_version,
                created_at=created_at,
                attempted_at=None,
                delivery_status=DeliveryStatus.SKIPPED_DUPLICATE,
                provider_message_id=None,
                error_code=None,
                error_message=None,
                retry_count=0,
                correlation_id=event.correlation_id,
            )
            self.ledger.record_attempt(attempt)
            return attempt

        attempt_number = 0
        success = False
        provider_message_id: str | None = None
        error_code: str | None = None
        error_message: str | None = None
        is_retryable = True
        while attempt_number < self.max_attempts:
            attempt_number += 1
            success, provider_message_id, error_code, error_message, is_retryable = provider.send(
                text
            )
            if success or not is_retryable:
                break
            if attempt_number < self.max_attempts:
                self.sleep(self.backoff_seconds(attempt_number))

        attempt = DeliveryAttempt(
            communication_id=communication_id,
            signal_id=event.signal_id,
            event_id=event.event_id,
            channel=provider.channel,
            provider=provider.provider_name,
            destination_masked=provider.destination_masked,
            template_id=event.template_id,
            template_version=event.template_version,
            created_at=created_at,
            attempted_at=datetime.now(UTC),
            delivery_status=DeliveryStatus.SENT if success else DeliveryStatus.FAILED,
            provider_message_id=provider_message_id,
            error_code=error_code,
            error_message=error_message,
            retry_count=attempt_number - 1,
            correlation_id=event.correlation_id,
        )
        if self.ledger is not None:
            self.ledger.record_attempt(attempt)
        return attempt


@dataclass(frozen=True, slots=True)
class SignalCommunicationService:
    """The single call site: builds one `SignalCommunicationEvent` for
    one signal lifecycle fact and routes it. Deliberately does NOT
    require an order, a risk decision, or any execution fact to exist -
    SIGNAL TRUTH != EXECUTION TRUTH is enforced structurally by this
    method signature never demanding execution-side arguments."""

    router: NotificationRouter

    def communicate(
        self,
        *,
        signal_id: SignalId,
        template_id: MessageTemplateId,
        context: SignalCommunicationContext,
        correlation_id: str,
    ) -> CommunicationOutcome:
        event = SignalCommunicationEvent.new(
            signal_id=signal_id,
            template_id=template_id,
            context=context,
            correlation_id=correlation_id,
        )
        attempts = self.router.dispatch(event)
        return CommunicationOutcome(event=event, attempts=attempts)
