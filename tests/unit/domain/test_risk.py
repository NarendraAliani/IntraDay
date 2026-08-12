# tests/unit/domain/test_risk.py
#
# Unit tests for the RiskLimits/RiskDecision/TradingHaltState contracts
# (Checkpoint 5).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.risk.contracts import (
    RiskDecision,
    RiskDecisionOutcome,
    RiskLimits,
    TradingHaltState,
    TradingHaltStatus,
)

NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def test_risk_limits_reject_non_positive_values() -> None:
    with pytest.raises(ValueError):
        RiskLimits(
            max_intraday_loss=Decimal("0"),
            max_position_size=Decimal("1"),
            max_per_trade_risk=Decimal("1"),
        )


def test_rejected_decision_requires_reasons() -> None:
    with pytest.raises(ValueError):
        RiskDecision(
            signal_id="sig-1",
            strategy_id="orb-v1",
            outcome=RiskDecisionOutcome.REJECTED,
            decided_at=NOW,
        )


def test_approved_decision_does_not_require_reasons() -> None:
    decision = RiskDecision(
        signal_id="sig-1",
        strategy_id="orb-v1",
        outcome=RiskDecisionOutcome.APPROVED,
        decided_at=NOW,
    )
    assert decision.reasons == ()


def test_halted_state_requires_a_reason() -> None:
    with pytest.raises(ValueError):
        TradingHaltState(status=TradingHaltStatus.HALTED)


def test_active_state_needs_no_reason() -> None:
    state = TradingHaltState(status=TradingHaltStatus.ACTIVE)
    assert state.reason is None
