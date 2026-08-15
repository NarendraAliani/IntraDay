# tests/unit/trading_engine/position_management/test_monitor.py
#
# Checkpoint 42 Part 3-5: proves the deterministic position-exit rules
# genuinely fire in the documented order, and - critically - that a
# position with no ExitPlan (the honest state of every position this
# codebase can currently produce, since ema_crossover computes no
# stop-loss/targets) is NEVER given a fabricated automatic exit.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.shared_kernel.contracts import Exchange, OrderId, PositionId, Side
from intraday.trading_engine.position_management.contracts import (
    ExitPlan,
    ExitReason,
    ManagedPosition,
    PositionLifecycleStatus,
)
from intraday.trading_engine.position_management.monitor import evaluate_position_exit

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def _position(direction: Side = Side.BUY, quantity: Decimal = Decimal("30")) -> Position:
    return Position(
        position_id=PositionId("pos-1"),
        instrument_id=RELIANCE,
        direction=direction,
        quantity=quantity,
        average_entry_price=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        opened_at=NOW,
        status=PositionStatus.OPEN,
    )


def _managed(
    *,
    direction: Side = Side.BUY,
    quantity: Decimal = Decimal("30"),
    exit_plan: ExitPlan | None,
    lifecycle_status: PositionLifecycleStatus = PositionLifecycleStatus.OPEN,
    remaining_quantity: Decimal | None = None,
    highest_favorable_price: Decimal = Decimal("100"),
) -> ManagedPosition:
    position = _position(direction=direction, quantity=quantity)
    return ManagedPosition(
        position=position,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        strategy_version="v1",
        entry_order_id=OrderId("ord-1"),
        exit_plan=exit_plan,
        lifecycle_status=lifecycle_status,
        remaining_quantity=remaining_quantity if remaining_quantity is not None else quantity,
        highest_favorable_price=highest_favorable_price,
    )


def test_a_position_with_no_exit_plan_never_produces_an_automatic_exit() -> None:
    """The single most important test in this file: honesty over
    completeness. ema_crossover produces positions with no exit plan
    today - this must NEVER silently invent a stop-loss/target."""
    managed = _managed(exit_plan=None)
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("1"), now=NOW)
    assert decision is None


def test_an_exit_plan_with_no_rules_set_produces_no_exit_either() -> None:
    managed = _managed(exit_plan=ExitPlan(stop_loss=None))
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("1"), now=NOW)
    assert decision is None


def test_price_between_stop_and_target_produces_no_exit() -> None:
    plan = ExitPlan(stop_loss=Decimal("95"), target_1=Decimal("110"))
    managed = _managed(exit_plan=plan)
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("102"), now=NOW)
    assert decision is None


def test_stop_loss_hit_on_a_long_position() -> None:
    plan = ExitPlan(stop_loss=Decimal("95"), target_1=Decimal("110"))
    managed = _managed(exit_plan=plan)
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("94"), now=NOW)
    assert decision is not None
    assert decision.reason is ExitReason.STOP_LOSS
    assert decision.new_lifecycle_status is PositionLifecycleStatus.STOPPED
    assert decision.exit_quantity == Decimal("30")  # full exit on stop


def test_stop_loss_hit_on_a_short_position() -> None:
    plan = ExitPlan(stop_loss=Decimal("105"))
    managed = _managed(direction=Side.SELL, exit_plan=plan)
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("106"), now=NOW)
    assert decision is not None
    assert decision.reason is ExitReason.STOP_LOSS


def test_target_1_hit_produces_a_partial_exit_of_one_third() -> None:
    plan = ExitPlan(stop_loss=Decimal("95"), target_1=Decimal("110"))
    managed = _managed(exit_plan=plan, quantity=Decimal("30"))
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("111"), now=NOW)
    assert decision is not None
    assert decision.reason is ExitReason.TARGET_1
    assert decision.new_lifecycle_status is PositionLifecycleStatus.TARGET_1
    assert decision.exit_quantity == Decimal("10.0000")  # one third of 30


def test_target_1_already_passed_evaluates_target_2_instead() -> None:
    plan = ExitPlan(stop_loss=Decimal("95"), target_1=Decimal("110"), target_2=Decimal("120"))
    managed = _managed(
        exit_plan=plan,
        quantity=Decimal("30"),
        remaining_quantity=Decimal("20"),
        lifecycle_status=PositionLifecycleStatus.TARGET_1,
    )
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("121"), now=NOW)
    assert decision is not None
    assert decision.reason is ExitReason.TARGET_2


def test_target_3_hit_exits_the_full_remaining_quantity() -> None:
    plan = ExitPlan(
        stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("120"),
        target_3=Decimal("130"),
    )
    managed = _managed(
        exit_plan=plan,
        quantity=Decimal("30"),
        remaining_quantity=Decimal("10"),
        lifecycle_status=PositionLifecycleStatus.TARGET_2,
    )
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("131"), now=NOW)
    assert decision is not None
    assert decision.reason is ExitReason.TARGET_3
    assert decision.exit_quantity == Decimal("10")  # everything still open


def test_trailing_stop_fires_when_price_falls_below_the_trailing_level() -> None:
    plan = ExitPlan(stop_loss=Decimal("90"), trailing_stop_distance=Decimal("5"))
    managed = _managed(exit_plan=plan, highest_favorable_price=Decimal("115"))
    # trailing level = 115 - 5 = 110
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("109"), now=NOW)
    assert decision is not None
    assert decision.reason is ExitReason.TRAILING_STOP
    assert decision.new_lifecycle_status is PositionLifecycleStatus.STOPPED


def test_a_closed_position_never_produces_a_further_exit_decision() -> None:
    plan = ExitPlan(stop_loss=Decimal("95"))
    managed = _managed(
        exit_plan=plan,
        lifecycle_status=PositionLifecycleStatus.CLOSED,
        remaining_quantity=Decimal("0"),
    )
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("1"), now=NOW)
    assert decision is None


def test_stop_loss_is_always_checked_before_targets_even_if_both_would_fire() -> None:
    """An adversarial case that should never happen in practice (stop
    below entry, target also below entry) - but the FIXED order
    (Part 5's own requirement, mirroring the risk engine's own fixed-
    order discipline) must still resolve deterministically to the
    stop-loss."""
    plan = ExitPlan(stop_loss=Decimal("101"), target_1=Decimal("100"))
    managed = _managed(exit_plan=plan)
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("99"), now=NOW)
    assert decision is not None
    assert decision.reason is ExitReason.STOP_LOSS
