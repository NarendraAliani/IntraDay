# File: src/intraday/domain/risk/contracts.py
#
# Canonical risk-policy/decision/state contracts (Checkpoint 5). Defines
# WHAT a risk limit or decision looks like — never HOW it is evaluated.
# No risk calculation, stop-loss logic, or risk-engine implementation
# exists anywhere in this file (Checkpoint 5 Section 13); that belongs to
# trading_engine/risk_engine in a later checkpoint.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import OrderId, SignalId, StrategyId, ensure_utc


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """A configured set of risk limits — a user-configurable trading
    parameter (Checkpoint 3 §13), whose fields `application/config_schema`
    will validate configuration instances against in a later checkpoint."""

    max_intraday_loss: Decimal
    max_position_size: Decimal
    max_per_trade_risk: Decimal

    def __post_init__(self) -> None:
        for field_name, value in (
            ("max_intraday_loss", self.max_intraday_loss),
            ("max_position_size", self.max_position_size),
            ("max_per_trade_risk", self.max_per_trade_risk),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"RiskLimits.{field_name} must be a Decimal")
            if value <= 0:
                raise ValueError(f"RiskLimits.{field_name} must be positive, got {value}")


class RiskDecisionOutcome(enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """The recorded outcome of the risk engine evaluating one Signal — the
    non-bypassable chokepoint's decision (Rule 5.2), never the evaluation
    logic itself. `reasons` is mandatory on rejection so a rejected signal
    is always auditable (feeds `control_plane/audit` in a later
    checkpoint)."""

    signal_id: SignalId
    strategy_id: StrategyId
    outcome: RiskDecisionOutcome
    decided_at: datetime
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ensure_utc(self.decided_at, field_name="RiskDecision.decided_at")
        if self.outcome is RiskDecisionOutcome.REJECTED and not self.reasons:
            raise ValueError("RiskDecision.reasons must be provided when outcome is REJECTED")


class TradingHaltStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"


@dataclass(frozen=True, slots=True)
class TradingHaltState:
    """The kill-switch's current state (Checkpoint 2 §10:
    `control_plane`'s binary, supervisory authority) — a value object
    representing that state, not the kill-switch implementation itself."""

    status: TradingHaltStatus
    reason: str | None = None
    changed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status is TradingHaltStatus.HALTED and not self.reason:
            raise ValueError("TradingHaltState.reason must be provided when status is HALTED")
        if self.changed_at is not None:
            ensure_utc(self.changed_at, field_name="TradingHaltState.changed_at")


# Checkpoint 64.24: `RiskRejectionReason`/`OrderRiskDecision` relocated
# here verbatim from `trading_engine/risk_engine/contracts.py`
# (Checkpoint 34 Part 10) as part of moving the canonical order-risk
# policy into `intraday.domain` — the one layer every part of this
# codebase (trading_engine, application, AND research) is permitted to
# import (`.importlinter` contracts 1-3). No logic changed; this is a
# relocation, not a rewrite. `trading_engine/risk_engine/contracts.py`
# now re-exports these names for backward compatibility.
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
