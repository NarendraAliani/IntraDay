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

from intraday.domain.shared_kernel.contracts import SignalId, StrategyId, ensure_utc


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
