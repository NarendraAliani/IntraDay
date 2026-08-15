# File: src/intraday/trading_engine/risk_engine/contracts.py
#
# Checkpoint 34 Part 10: the risk-engine's own contracts. Reuses
# `domain.risk.contracts.RiskDecisionOutcome`/`RiskLimits`/
# `TradingHaltState` verbatim (Checkpoint 5's own domain contracts,
# explicitly deferred to "trading_engine/risk_engine in a later
# checkpoint" - this is that checkpoint) rather than inventing parallel
# ones. `OrderRiskDecision` is new here because Checkpoint 5's
# `RiskDecision` is signal-scoped (mandatory `signal_id`); an order does
# not always originate from a signal (e.g. a manual square-off has no
# `signal_id` either - `domain.order.OrderIntent.signal_id` is already
# optional for exactly this reason) - this dataclass is order-scoped
# instead, reusing the same `RiskDecisionOutcome` vocabulary.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from intraday.domain.risk.contracts import RiskDecisionOutcome
from intraday.domain.shared_kernel.contracts import OrderId, ensure_utc


class RiskRejectionReason(enum.Enum):
    """One member per required control (Checkpoint 34 Part 10), plus
    nothing else - an exhaustive, closed vocabulary. Every rejection
    must cite exactly one of these, never a free-text-only reason."""

    MAX_DAILY_LOSS_EXCEEDED = "MAX_DAILY_LOSS_EXCEEDED"
    MAX_POSITION_SIZE_EXCEEDED = "MAX_POSITION_SIZE_EXCEEDED"
    MAX_TOTAL_EXPOSURE_EXCEEDED = "MAX_TOTAL_EXPOSURE_EXCEEDED"
    MAX_CONCURRENT_POSITIONS_EXCEEDED = "MAX_CONCURRENT_POSITIONS_EXCEEDED"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    STALE_DATA = "STALE_DATA"
    STRATEGY_NOT_ACTIVE = "STRATEGY_NOT_ACTIVE"
    MARKET_SESSION_CLOSED = "MARKET_SESSION_CLOSED"
    KILL_SWITCH_ENGAGED = "KILL_SWITCH_ENGAGED"
    # Checkpoint 39 Part I: closes gaps Checkpoint 38 found (configured
    # but unenforced/nonexistent controls).
    INSTRUMENT_NOT_ALLOWED = "INSTRUMENT_NOT_ALLOWED"
    DAILY_TRADE_LIMIT_EXCEEDED = "DAILY_TRADE_LIMIT_EXCEEDED"
    PER_TRADE_RISK_UNKNOWN = "PER_TRADE_RISK_UNKNOWN"
    """The caller could not determine this order's per-trade risk (e.g.
    the originating strategy computes no stop loss - `ema_crossover`,
    Checkpoint 36). Per Checkpoint 39 Part I's explicit instruction,
    "execution should be BLOCKED rather than pretending the risk can be
    calculated" - this is NOT the same as MAX_PER_TRADE_RISK_EXCEEDED
    (a KNOWN risk that exceeds the limit); it is "unknown, therefore
    refused," a distinct and equally auditable reason."""
    MAX_PER_TRADE_RISK_EXCEEDED = "MAX_PER_TRADE_RISK_EXCEEDED"


@dataclass(frozen=True, slots=True)
class OrderRiskDecision:
    """The risk engine's recorded, auditable decision for one
    `OrderIntent` - always explicit APPROVED/REJECTED (Part 10's own
    requirement), never a bypassable "warning" or partial approval."""

    order_id: OrderId
    outcome: RiskDecisionOutcome
    reason_code: RiskRejectionReason | None
    explanation: str
    evaluated_at: datetime
    risk_configuration_version: str

    def __post_init__(self) -> None:
        ensure_utc(self.evaluated_at, field_name="OrderRiskDecision.evaluated_at")
        if self.outcome is RiskDecisionOutcome.REJECTED and self.reason_code is None:
            raise ValueError("OrderRiskDecision.reason_code is required when outcome is REJECTED")
        if self.outcome is RiskDecisionOutcome.APPROVED and self.reason_code is not None:
            raise ValueError("OrderRiskDecision.reason_code must be None when outcome is APPROVED")
        if not self.explanation.strip():
            raise ValueError("OrderRiskDecision.explanation must not be empty")
        if not self.risk_configuration_version.strip():
            raise ValueError("OrderRiskDecision.risk_configuration_version must not be empty")
