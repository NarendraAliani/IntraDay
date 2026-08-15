# tests/unit/application/services/test_exit_plan_policy.py
#
# Checkpoint 43 Part 4: proves the PROJECT_POLICY default exit plan is
# computed correctly and symmetrically for both directions - clearly a
# policy default, tested independently of any strategy.
from __future__ import annotations

from decimal import Decimal

from intraday.application.services.exit_plan_policy import derive_default_exit_plan
from intraday.domain.shared_kernel.contracts import Side


def test_long_position_stop_below_and_targets_above_entry() -> None:
    plan = derive_default_exit_plan(entry_price=Decimal("100"), direction=Side.BUY)
    assert plan.stop_loss == Decimal("99.00")
    assert plan.target_1 == Decimal("101.50")
    assert plan.target_2 == Decimal("102.50")
    assert plan.target_3 == Decimal("104.00")
    assert plan.trailing_stop_distance == Decimal("1.00")
    assert plan.stop_loss < plan.target_1 < plan.target_2 < plan.target_3


def test_short_position_stop_above_and_targets_below_entry() -> None:
    plan = derive_default_exit_plan(entry_price=Decimal("100"), direction=Side.SELL)
    assert plan.stop_loss == Decimal("101.00")
    assert plan.target_1 == Decimal("98.50")
    assert plan.target_2 == Decimal("97.50")
    assert plan.target_3 == Decimal("96.00")
    assert plan.target_3 < plan.target_2 < plan.target_1 < plan.stop_loss


def test_plan_has_a_real_rule_set() -> None:
    plan = derive_default_exit_plan(entry_price=Decimal("50"), direction=Side.BUY)
    assert plan.has_any_exit_rule()
