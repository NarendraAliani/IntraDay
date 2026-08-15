# tests/unit/communication/test_signal_communication_engine.py
#
# Checkpoint 37 Part 6/13: proves SIGNAL TRUTH != EXECUTION TRUTH end
# to end using an in-memory fake provider (never a real Telegram/
# Discord call in a unit test) plus a real NotificationRouter/
# SignalCommunicationService.
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
    RiskDecisionOutcome,
    SignalCommunicationContext,
    derive_execution_status,
)
from intraday.communication.contracts.templates import render_message
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side, SignalId, StrategyId
from intraday.domain.signal.contracts import SignalStatus

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)


@dataclass
class FakeProvider:
    """In-memory `CommunicationProvider` - records every send, never
    touches the network."""

    channel: CommunicationChannel
    provider_name: str
    destination_masked: str = "****abcd"
    should_fail: bool = False
    is_retryable: bool = False
    fail_first_n_attempts: int = 0
    sent: list[str] = field(default_factory=list)

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        self.sent.append(text)
        if self.fail_first_n_attempts > 0:
            self.fail_first_n_attempts -= 1
            return False, None, "TRANSIENT_ERROR", "simulated transient failure", True
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
        targets=(Decimal("1438.00"), Decimal("1450.00"), Decimal("1465.00")),
        trailing_stop_enabled=True,
        confidence=Decimal("0.87"),
        signal_status=SignalStatus.VALIDATED,
        execution_status=ExecutionStatus.NOT_EVALUATED,
    )
    defaults.update(overrides)
    return SignalCommunicationContext(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------
# ExecutionStatus derivation (Part 4 - signal vs execution independence)
# --------------------------------------------------------------------


def test_no_risk_decision_yet_is_not_evaluated() -> None:
    assert (
        derive_execution_status(risk_outcome=None, order_status=None)
        is ExecutionStatus.NOT_EVALUATED
    )


def test_risk_rejected_is_blocked_regardless_of_order_status() -> None:
    assert (
        derive_execution_status(risk_outcome=RiskDecisionOutcome.REJECTED, order_status=None)
        is ExecutionStatus.BLOCKED
    )


def test_risk_approved_no_order_yet_is_approved() -> None:
    assert (
        derive_execution_status(risk_outcome=RiskDecisionOutcome.APPROVED, order_status=None)
        is ExecutionStatus.APPROVED
    )


def test_risk_approved_and_filled_is_filled() -> None:
    assert (
        derive_execution_status(
            risk_outcome=RiskDecisionOutcome.APPROVED, order_status=OrderStatus.FILLED
        )
        is ExecutionStatus.FILLED
    )


# --------------------------------------------------------------------
# Template rendering (Part 5)
# --------------------------------------------------------------------


def test_validated_signal_template_renders_all_key_fields() -> None:
    text = render_message(MessageTemplateId.VALIDATED_SIGNAL, _context())
    assert "VALIDATED SIGNAL" in text
    assert "RELIANCE" in text
    assert "BUY" in text
    assert "1,427.00" in text
    assert "1,418.00" in text
    assert "1,438.00" in text
    assert "Signal Status: VALIDATED" in text
    assert "Execution Status: NOT_EVALUATED" in text


def test_validated_signal_template_never_fabricates_missing_stop_loss() -> None:
    text = render_message(MessageTemplateId.VALIDATED_SIGNAL, _context(stop_loss=None, targets=()))
    assert "Stop Loss: -" in text


def test_execution_blocked_template_includes_reason() -> None:
    ctx = _context(execution_status=ExecutionStatus.BLOCKED, block_reason="Insufficient funds")
    text = render_message(MessageTemplateId.VALIDATED_SIGNAL_EXECUTION_BLOCKED, ctx)
    assert "EXECUTION BLOCKED" in text
    assert "Insufficient funds" in text


def test_order_filled_template_includes_fill_details() -> None:
    ctx = _context(
        execution_status=ExecutionStatus.FILLED,
        order_id="ord-1",
        fill_price=Decimal("1427.50"),
        filled_quantity=Decimal("10"),
    )
    text = render_message(MessageTemplateId.ORDER_FILLED, ctx)
    assert "ORDER FILLED" in text
    assert "ord-1" in text
    assert "1,427.50" in text


# --------------------------------------------------------------------
# Scenarios B-J (Part 6): signal communication independent of execution
# --------------------------------------------------------------------


def _service(
    *providers: FakeProvider, ledger: FakeLedger | None = None
) -> tuple[SignalCommunicationService, FakeLedger]:
    ledger = ledger or FakeLedger()
    router = NotificationRouter(providers=tuple(providers), ledger=ledger)
    return SignalCommunicationService(router=router), ledger


def test_scenario_b_insufficient_funds_still_communicates_signal_and_block_reason() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    service, ledger = _service(telegram)

    outcome = service.communicate(
        signal_id=SignalId("sig-b"),
        template_id=MessageTemplateId.VALIDATED_SIGNAL_EXECUTION_BLOCKED,
        context=_context(
            signal_id=SignalId("sig-b"),
            execution_status=ExecutionStatus.BLOCKED,
            block_reason="Insufficient funds",
        ),
        correlation_id="corr-b",
    )

    assert len(outcome.attempts) == 1
    assert outcome.attempts[0].delivery_status is DeliveryStatus.SENT
    assert "Insufficient funds" in telegram.sent[0]
    assert len(ledger.attempts) == 1


def test_scenario_e_broker_disconnected_still_communicates() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    service, _ = _service(telegram)

    outcome = service.communicate(
        signal_id=SignalId("sig-e"),
        template_id=MessageTemplateId.BROKER_DISCONNECTED,
        context=_context(signal_id=SignalId("sig-e"), extra_text="Dhan connection lost"),
        correlation_id="corr-e",
    )

    assert outcome.attempts[0].delivery_status is DeliveryStatus.SENT
    assert "Dhan connection lost" in telegram.sent[0]


def test_scenario_j_same_signal_same_event_is_not_double_communicated() -> None:
    """Duplicate EVALUATION of the same lifecycle fact must not create
    a second visible message - but a DIFFERENT template_id for the same
    signal (a legitimate lifecycle update) is never deduplicated."""
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    ledger = FakeLedger()
    service, _ = _service(telegram, ledger=ledger)

    ctx = _context(signal_id=SignalId("sig-j"))
    first = service.communicate(
        signal_id=SignalId("sig-j"),
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        context=ctx,
        correlation_id="corr-j",
    )
    # A second, independent event (new event_id) for the SAME signal -
    # simulating a legitimate lifecycle update (e.g. ORDER_FILLED) -
    # must still be delivered.
    second = service.communicate(
        signal_id=SignalId("sig-j"),
        template_id=MessageTemplateId.ORDER_FILLED,
        context=ctx,
        correlation_id="corr-j",
    )

    assert first.attempts[0].delivery_status is DeliveryStatus.SENT
    assert second.attempts[0].delivery_status is DeliveryStatus.SENT
    assert len(telegram.sent) == 2

    # Re-dispatching the EXACT SAME event object again (a caller retry
    # of the same lifecycle fact) IS deduplicated.
    router_with_ledger = NotificationRouter(providers=(telegram,), ledger=ledger)
    repeated_attempts = router_with_ledger.dispatch(first.event)
    assert repeated_attempts[0].delivery_status is DeliveryStatus.SKIPPED_DUPLICATE
    assert len(telegram.sent) == 2  # unchanged - no third send


def test_provider_failure_is_recorded_not_raised() -> None:
    failing = FakeProvider(CommunicationChannel.DISCORD, "discord", should_fail=True)
    service, ledger = _service(failing)

    outcome = service.communicate(
        signal_id=SignalId("sig-fail"),
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        context=_context(signal_id=SignalId("sig-fail")),
        correlation_id="corr-fail",
    )

    assert outcome.attempts[0].delivery_status is DeliveryStatus.FAILED
    assert outcome.attempts[0].error_code == "PROVIDER_ERROR"
    assert ledger.attempts[0].delivery_status is DeliveryStatus.FAILED


def test_multiple_providers_all_receive_the_same_event() -> None:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    service, _ = _service(telegram, discord)

    outcome = service.communicate(
        signal_id=SignalId("sig-multi"),
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        context=_context(signal_id=SignalId("sig-multi")),
        correlation_id="corr-multi",
    )

    assert len(outcome.attempts) == 2
    assert {a.channel for a in outcome.attempts} == {
        CommunicationChannel.TELEGRAM,
        CommunicationChannel.DISCORD,
    }
    assert len(telegram.sent) == 1
    assert len(discord.sent) == 1


def test_no_providers_configured_produces_no_attempts_and_never_raises() -> None:
    service, ledger = _service()
    outcome = service.communicate(
        signal_id=SignalId("sig-none"),
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        context=_context(signal_id=SignalId("sig-none")),
        correlation_id="corr-none",
    )
    assert outcome.attempts == ()
    assert ledger.attempts == []


# --------------------------------------------------------------------
# Bounded retry (Checkpoint 38 Part 8)
# --------------------------------------------------------------------


def test_transient_failure_is_retried_and_eventually_succeeds() -> None:
    """Fails twice with a TRANSIENT error, succeeds on the 3rd (final)
    attempt - proves the bounded retry loop actually retries."""
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram", fail_first_n_attempts=2)
    sleeps: list[float] = []
    router = NotificationRouter(providers=(telegram,), max_attempts=3, sleep=sleeps.append)
    service = SignalCommunicationService(router=router)

    outcome = service.communicate(
        signal_id=SignalId("sig-retry"),
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        context=_context(signal_id=SignalId("sig-retry")),
        correlation_id="corr-retry",
    )

    assert outcome.attempts[0].delivery_status is DeliveryStatus.SENT
    assert outcome.attempts[0].retry_count == 2  # 2 failed attempts before success
    assert len(telegram.sent) == 3  # 3 real send() calls total
    assert len(sleeps) == 2  # slept before the 2nd and 3rd attempts only


def test_retry_is_bounded_and_gives_up_after_max_attempts() -> None:
    telegram = FakeProvider(
        CommunicationChannel.TELEGRAM, "telegram", should_fail=True, is_retryable=True
    )
    router = NotificationRouter(providers=(telegram,), max_attempts=3, sleep=lambda _: None)
    service = SignalCommunicationService(router=router)

    outcome = service.communicate(
        signal_id=SignalId("sig-give-up"),
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        context=_context(signal_id=SignalId("sig-give-up")),
        correlation_id="corr-give-up",
    )

    assert outcome.attempts[0].delivery_status is DeliveryStatus.FAILED
    assert outcome.attempts[0].retry_count == 2  # 3 attempts total, 2 retries
    assert len(telegram.sent) == 3  # never more than max_attempts - no retry storm


def test_permanent_failure_is_never_retried() -> None:
    """A permanent failure (bad token/webhook, is_retryable=False) must
    not waste attempts - one send() call, no retries."""
    telegram = FakeProvider(
        CommunicationChannel.TELEGRAM, "telegram", should_fail=True, is_retryable=False
    )
    router = NotificationRouter(providers=(telegram,), max_attempts=3, sleep=lambda _: None)
    service = SignalCommunicationService(router=router)

    outcome = service.communicate(
        signal_id=SignalId("sig-permanent"),
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        context=_context(signal_id=SignalId("sig-permanent")),
        correlation_id="corr-permanent",
    )

    assert outcome.attempts[0].delivery_status is DeliveryStatus.FAILED
    assert outcome.attempts[0].retry_count == 0
    assert len(telegram.sent) == 1  # never retried a permanent failure
