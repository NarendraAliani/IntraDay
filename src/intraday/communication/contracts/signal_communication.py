# File: src/intraday/communication/contracts/signal_communication.py
#
# Checkpoint 37 Part 3-5: the BROKER-INDEPENDENT SIGNAL COMMUNICATION
# ENGINE's contracts. Governing principle: SIGNAL TRUTH != EXECUTION
# TRUTH — a strategically audited signal is a valid product event
# whether or not an order is ever placed, so nothing here has a
# mandatory dependency on an OrderIntent/BrokerOrderStatusReport
# existing.
#
# Reuses existing canonical domain vocabulary rather than duplicating
# it (Checkpoint 37 Part 4's explicit instruction): `domain.signal.
# SignalStatus` remains the ONLY signal-lifecycle enum; execution
# status is not a new stored field but a VALUE derived by
# `derive_execution_status()` below from the existing
# `domain.risk.RiskDecisionOutcome` and `domain.order.OrderStatus` —
# composing two already-canonical enums rather than inventing a third,
# parallel one that could drift out of sync with either.
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.order.contracts import OrderStatus
from intraday.domain.risk.contracts import RiskDecisionOutcome
from intraday.domain.shared_kernel.contracts import Side, SignalId, StrategyId
from intraday.domain.signal.contracts import SignalStatus


class ExecutionStatus(enum.Enum):
    """Execution-side status, independent of `SignalStatus`. NEVER a
    stored/persisted enum on its own — always derived (see
    `derive_execution_status`) from a `RiskDecisionOutcome` and,
    once an order exists, an `OrderStatus`. This is what lets a
    message say "Signal: VALIDATED, Execution: BLOCKED" — two
    independent truths, never collapsed into one status field."""

    NOT_EVALUATED = "NOT_EVALUATED"
    PENDING_RISK = "PENDING_RISK"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


_ORDER_STATUS_TO_EXECUTION_STATUS: dict[OrderStatus, ExecutionStatus] = {
    OrderStatus.CREATED: ExecutionStatus.ORDER_SUBMITTED,
    OrderStatus.SUBMITTED: ExecutionStatus.ORDER_SUBMITTED,
    OrderStatus.TRANSIT: ExecutionStatus.ORDER_SUBMITTED,
    OrderStatus.ACKNOWLEDGED: ExecutionStatus.ACKNOWLEDGED,
    OrderStatus.PENDING: ExecutionStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED: ExecutionStatus.PARTIALLY_FILLED,
    OrderStatus.FILLED: ExecutionStatus.FILLED,
    OrderStatus.REJECTED: ExecutionStatus.REJECTED,
    OrderStatus.CANCEL_REQUESTED: ExecutionStatus.ACKNOWLEDGED,
    OrderStatus.CANCELLED: ExecutionStatus.CANCELLED,
    OrderStatus.EXPIRED: ExecutionStatus.EXPIRED,
    OrderStatus.ERROR: ExecutionStatus.ERROR,
}


def derive_execution_status(
    *,
    risk_outcome: RiskDecisionOutcome | None,
    order_status: OrderStatus | None,
) -> ExecutionStatus:
    """Pure function, no stored state of its own. `risk_outcome is None`
    means risk was never evaluated (e.g. no strategy active yet);
    `order_status is None` with `risk_outcome is APPROVED` means risk
    approved but the broker call has not yet returned/happened."""
    if risk_outcome is None:
        return ExecutionStatus.NOT_EVALUATED
    if risk_outcome is RiskDecisionOutcome.REJECTED:
        return ExecutionStatus.BLOCKED
    if order_status is None:
        return ExecutionStatus.APPROVED
    return _ORDER_STATUS_TO_EXECUTION_STATUS.get(order_status, ExecutionStatus.ERROR)


class MessageTemplateId(enum.Enum):
    """The 18 templates Checkpoint 37 Part 5 requires, at minimum."""

    VALIDATED_SIGNAL = "VALIDATED_SIGNAL"
    VALIDATED_SIGNAL_EXECUTION_BLOCKED = "VALIDATED_SIGNAL_EXECUTION_BLOCKED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    PARTIAL_FILL = "PARTIAL_FILL"
    ORDER_REJECTED = "ORDER_REJECTED"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    TARGET_3_HIT = "TARGET_3_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    TRAILING_STOP_UPDATED = "TRAILING_STOP_UPDATED"
    POSITION_CLOSED = "POSITION_CLOSED"
    RISK_LIMIT_REACHED = "RISK_LIMIT_REACHED"
    DAILY_TRADE_LIMIT_REACHED = "DAILY_TRADE_LIMIT_REACHED"
    BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    KILL_SWITCH_ALERT = "KILL_SWITCH_ALERT"
    END_OF_DAY_SUMMARY = "END_OF_DAY_SUMMARY"


TEMPLATE_VERSION = "v1"


class CommunicationChannel(enum.Enum):
    TELEGRAM = "TELEGRAM"
    DISCORD = "DISCORD"


class DeliveryStatus(enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED_NOT_CONFIGURED = "SKIPPED_NOT_CONFIGURED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"


@dataclass(frozen=True, slots=True)
class SignalCommunicationContext:
    """Every field a template MAY reference. Optional fields are
    genuinely optional — a template renders only the fields relevant to
    it, and no field is ever fabricated to fill a gap (Checkpoint 37
    Part 5's "use human-readable formatting" applied to REAL data
    only)."""

    strategy_id: StrategyId
    strategy_version: str
    signal_id: SignalId
    symbol: str
    exchange: str
    signal_time: datetime
    timeframe: str
    spot_price: Decimal
    direction: Side
    entry_price: Decimal
    stop_loss: Decimal | None
    """`None` when the originating strategy does not compute a stop
    loss (e.g. `ema_crossover` - see Checkpoint 36/37's own honesty
    that current strategies do not produce stop-loss/target levels).
    NEVER fabricated to fill this field - the VALIDATED_SIGNAL template
    renders "-" rather than inventing a number."""
    targets: tuple[Decimal, ...]
    trailing_stop_enabled: bool
    confidence: Decimal | None
    signal_status: SignalStatus
    execution_status: ExecutionStatus
    block_reason: str | None = None
    order_id: str | None = None
    fill_price: Decimal | None = None
    filled_quantity: Decimal | None = None
    rejection_reason: str | None = None
    target_hit_price: Decimal | None = None
    trailing_stop_price: Decimal | None = None
    realized_pnl: Decimal | None = None
    extra_text: str | None = None  # for BROKER_DISCONNECTED/STALE/KILL_SWITCH free text
    evidence_fields: tuple[tuple[str, str], ...] = ()
    """Checkpoint 64.19 §2/§3: `(label, value)` pairs - the SAME generic
    shape `trading_engine.strategy_execution.evidence.SignalEvidence.
    fields` already carries (Checkpoint 64.18), deliberately NOT that
    type itself - `communication` is a bounded context and Contract 4
    (`.importlinter`) forbids it depending on `trading_engine` (bounded-
    context independence). The CALLER (`application.services.
    paper_signal_execution`, which is allowed to depend on both)
    converts `SignalEvidence.fields` into this plain tuple-of-tuples
    shape when building the context - never a duplicated evidence
    formatter inside this module. Empty when no evidence was produced
    (e.g. a directional-only strategy, or a strategy with no registered
    describer) - never fabricated."""


@dataclass(frozen=True, slots=True)
class SignalCommunicationEvent:
    """One point-in-time communication-worthy fact about a signal's
    lifecycle — NOT tied 1:1 with a broker call. `event_id` is what
    idempotency/dedup keys off; the SAME `event_id` re-communicated
    must not create a second visible message per channel (Part 6/7's
    "legitimate lifecycle update" vs "duplicate" distinction — a
    different `template_id` for the SAME `signal_id` is a legitimate
    update, e.g. VALIDATED_SIGNAL then ORDER_FILLED; the SAME
    `template_id` for the SAME `signal_id` re-evaluated is a
    duplicate)."""

    event_id: str
    signal_id: SignalId
    template_id: MessageTemplateId
    template_version: str
    context: SignalCommunicationContext
    created_at: datetime
    correlation_id: str

    @staticmethod
    def new(
        *,
        signal_id: SignalId,
        template_id: MessageTemplateId,
        context: SignalCommunicationContext,
        correlation_id: str,
        clock: datetime | None = None,
    ) -> SignalCommunicationEvent:
        return SignalCommunicationEvent(
            event_id=str(uuid.uuid4()),
            signal_id=signal_id,
            template_id=template_id,
            template_version=TEMPLATE_VERSION,
            context=context,
            created_at=clock or datetime.now(UTC),
            correlation_id=correlation_id,
        )


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """One provider-facing delivery result — a `SignalCommunicationEvent`
    fans out into one `DeliveryAttempt` per configured/enabled channel."""

    communication_id: str
    signal_id: SignalId
    event_id: str
    channel: CommunicationChannel
    provider: str
    destination_masked: str
    template_id: MessageTemplateId
    template_version: str
    created_at: datetime
    attempted_at: datetime | None
    delivery_status: DeliveryStatus
    provider_message_id: str | None
    error_code: str | None
    error_message: str | None
    retry_count: int
    correlation_id: str


@dataclass(frozen=True, slots=True)
class CommunicationOutcome:
    """What `SignalCommunicationService.communicate()` returns — one
    event fanned out across every configured channel."""

    event: SignalCommunicationEvent
    attempts: tuple[DeliveryAttempt, ...] = field(default_factory=tuple)
