# tests/unit/communication/test_scanner_notification_routing.py
#
# Checkpoint 64.94: proves the exact gap named by 64.93 is closed -
# `ScannerConfiguration.selected_notification_channels` (via the
# EFFECTIVE channel set a caller computes and passes in) now genuinely
# controls `NotificationRouter` fan-out, never merely the UI. Uses the
# SAME in-memory `FakeProvider`/`FakeLedger` fixtures already proven at
# Checkpoint 37 (`test_signal_communication_engine.py`) - no real
# Telegram/Discord call, no live Dhan call anywhere in this file.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from intraday.application.services.signal_communication import (
    NotificationRouter,
    SignalCommunicationService,
)
from intraday.communication.contracts.signal_communication import (
    CommunicationChannel,
    DeliveryAttempt,
    DeliveryStatus,
    ExecutionStatus,
    MessageTemplateId,
    SignalCommunicationContext,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Side, SignalId, StrategyId
from intraday.domain.signal.contracts import SignalStatus

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)


@dataclass
class FakeProvider:
    channel: CommunicationChannel
    provider_name: str
    destination_masked: str = "****abcd"
    should_fail: bool = False
    is_retryable: bool = False
    sent: list[str] = field(default_factory=list)

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        self.sent.append(text)
        if self.should_fail:
            return False, None, "PROVIDER_ERROR", "simulated failure", self.is_retryable
        return True, "msg-1", None, None, False


@dataclass
class FakeLedger:
    attempts: list[DeliveryAttempt] = field(default_factory=list)

    def record_attempt(self, attempt: DeliveryAttempt) -> None:
        self.attempts.append(attempt)

    def already_sent(self, *, signal_id: str, event_id: str, channel: CommunicationChannel) -> bool:
        return any(
            a.signal_id == signal_id
            and a.event_id == event_id
            and a.channel == channel
            and a.delivery_status in (DeliveryStatus.SENT, DeliveryStatus.FAILED)
            for a in self.attempts
        )


def _context(**overrides: object) -> SignalCommunicationContext:
    defaults: dict[str, object] = dict(  # noqa: C408
        strategy_id=StrategyId("ema_crossover"),
        strategy_version="v1",
        signal_id=SignalId("sig-1"),
        symbol="RELIANCE",
        exchange="NSE",
        signal_time=NOW,
        timeframe="1m",
        spot_price=Decimal("1425.40"),
        direction=Side.BUY,
        entry_price=Decimal("1427.00"),
        stop_loss=Decimal("1418.00"),
        targets=(Decimal("1438.00"),),
        trailing_stop_enabled=False,
        confidence=Decimal("0.87"),
        signal_status=SignalStatus.VALIDATED,
        execution_status=ExecutionStatus.NOT_EVALUATED,
    )
    defaults.update(overrides)
    return SignalCommunicationContext(**defaults)  # type: ignore[arg-type]


def _service(
    telegram: FakeProvider,
    discord: FakeProvider,
    *,
    selected: frozenset[CommunicationChannel] | None,
) -> tuple[SignalCommunicationService, FakeLedger]:
    ledger = FakeLedger()
    router = NotificationRouter(
        providers=(telegram, discord), ledger=ledger, selected_channels=selected
    )
    return SignalCommunicationService(router=router), ledger


def _communicate(service: SignalCommunicationService, signal_id: str = "sig-1"):
    return service.communicate(
        signal_id=SignalId(signal_id),
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        context=_context(signal_id=SignalId(signal_id)),
        correlation_id="corr-1",
    )


# A. Telegram selected -> Telegram delivery occurs.
def test_telegram_selected_delivers() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord, selected=frozenset({CommunicationChannel.TELEGRAM}))
    outcome = _communicate(service)
    tg = next(a for a in outcome.attempts if a.channel is CommunicationChannel.TELEGRAM)
    assert tg.delivery_status is DeliveryStatus.SENT
    assert telegram.sent


# B. Telegram unselected -> Telegram delivery does not occur.
def test_telegram_unselected_never_sends() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord, selected=frozenset({CommunicationChannel.DISCORD}))
    outcome = _communicate(service)
    tg = next(a for a in outcome.attempts if a.channel is CommunicationChannel.TELEGRAM)
    assert tg.delivery_status is DeliveryStatus.SKIPPED_NOT_SELECTED
    assert not telegram.sent


# C. Discord selected -> Discord delivery occurs.
def test_discord_selected_delivers() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord, selected=frozenset({CommunicationChannel.DISCORD}))
    outcome = _communicate(service)
    dc = next(a for a in outcome.attempts if a.channel is CommunicationChannel.DISCORD)
    assert dc.delivery_status is DeliveryStatus.SENT
    assert discord.sent


# D. Discord unselected -> Discord delivery does not occur.
def test_discord_unselected_never_sends() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord, selected=frozenset({CommunicationChannel.TELEGRAM}))
    outcome = _communicate(service)
    dc = next(a for a in outcome.attempts if a.channel is CommunicationChannel.DISCORD)
    assert dc.delivery_status is DeliveryStatus.SKIPPED_NOT_SELECTED
    assert not discord.sent


# E. Both selected -> both are attempted.
def test_both_selected_both_attempted() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(
        telegram,
        discord,
        selected=frozenset({CommunicationChannel.TELEGRAM, CommunicationChannel.DISCORD}),
    )
    outcome = _communicate(service)
    assert telegram.sent and discord.sent
    assert all(a.delivery_status is DeliveryStatus.SENT for a in outcome.attempts)


# F. A failed selected channel does not remove the signal from the live
# console - proven at the communication layer by showing the OTHER
# channel and the event itself are entirely unaffected by one
# provider's failure (the live console reads `SignalRecord`/
# `EnrichedSignal`, which this call never touches or blocks).
def test_failed_selected_channel_does_not_block_other_channel_or_event() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram", should_fail=True)
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(
        telegram,
        discord,
        selected=frozenset({CommunicationChannel.TELEGRAM, CommunicationChannel.DISCORD}),
    )
    outcome = _communicate(service)
    tg = next(a for a in outcome.attempts if a.channel is CommunicationChannel.TELEGRAM)
    dc = next(a for a in outcome.attempts if a.channel is CommunicationChannel.DISCORD)
    assert tg.delivery_status is DeliveryStatus.FAILED
    assert dc.delivery_status is DeliveryStatus.SENT
    assert outcome.event.signal_id == SignalId("sig-1")


# G. An unselected channel does not enter retry - no send is ever
# attempted, so `retry_count` stays 0 and the provider's `send()` is
# never called at all.
def test_unselected_channel_never_enters_retry() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord, selected=frozenset({CommunicationChannel.TELEGRAM}))
    outcome = _communicate(service)
    dc = next(a for a in outcome.attempts if a.channel is CommunicationChannel.DISCORD)
    assert dc.retry_count == 0
    assert dc.attempted_at is None
    assert discord.sent == []


# H. Effective configuration, not desired configuration, determines
# delivery - simulated by the caller passing the EFFECTIVE (already
# intersected with global configured/enabled) set, never the raw
# desired list. A channel present in "desired" but absent from the
# effective set passed to the router is never sent to.
def test_effective_not_desired_governs_delivery() -> None:
    desired_selection = {"telegram", "discord"}  # what the operator asked for
    # Discord is NOT globally configured/enabled right now, so the
    # EFFECTIVE set (computed exactly like
    # `scanner_configuration_views.effective_notification_channel_ids`)
    # excludes it - this is what a real caller would pass, never the
    # raw `desired_selection` above.
    effective_ids = {"telegram"}
    selected = frozenset(
        CommunicationChannel(c.upper())
        for c in effective_ids
        if c.upper() in CommunicationChannel.__members__
    )
    assert "discord" in desired_selection and "discord" not in effective_ids

    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord, selected=selected)
    outcome = _communicate(service)
    dc = next(a for a in outcome.attempts if a.channel is CommunicationChannel.DISCORD)
    assert dc.delivery_status is DeliveryStatus.SKIPPED_NOT_SELECTED
    assert not discord.sent


# I is exercised in test_scanner_configuration_api.py (desired/
# effective lifecycle for the configuration endpoint itself) -
# unrelated to this module's own scope, which is the delivery ROUTING
# decision given an already-resolved effective channel set.


# J. No duplicate notification is generated due to configuration
# polling - `communicate()` is called once per signal by construction
# (guarded upstream by `already_processed_signal_ids`); calling the
# SAME router/event twice (simulating a second, redundant poll/dispatch
# for the identical signal+event pair) must not send a second time -
# the existing `SKIPPED_DUPLICATE` idempotency mechanism, untouched by
# this checkpoint, still governs it.
def test_repeated_dispatch_of_same_event_does_not_duplicate_send() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(
        telegram,
        discord,
        selected=frozenset({CommunicationChannel.TELEGRAM, CommunicationChannel.DISCORD}),
    )
    outcome_1 = _communicate(service)
    # Re-dispatch the SAME event object (as a naive duplicate scheduler
    # invocation might) - the ledger's `already_sent()` must short-
    # circuit the second attempt.
    attempts_2 = service.router.dispatch(outcome_1.event)
    tg2 = next(a for a in attempts_2 if a.channel is CommunicationChannel.TELEGRAM)
    assert tg2.delivery_status is DeliveryStatus.SKIPPED_DUPLICATE
    assert len(telegram.sent) == 1


# --------------------------------------------------------------------
# Backward compatibility: `selected_channels=None` (every pre-existing
# caller) must be byte-for-byte the prior "send to every configured
# provider" behavior.
# --------------------------------------------------------------------
def test_none_selected_channels_preserves_prior_global_behavior() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord, selected=None)
    outcome = _communicate(service)
    assert telegram.sent and discord.sent
    assert all(a.delivery_status is DeliveryStatus.SENT for a in outcome.attempts)


def test_empty_selection_skips_every_channel() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord, selected=frozenset())
    outcome = _communicate(service)
    assert not telegram.sent and not discord.sent
    assert all(a.delivery_status is DeliveryStatus.SKIPPED_NOT_SELECTED for a in outcome.attempts)
