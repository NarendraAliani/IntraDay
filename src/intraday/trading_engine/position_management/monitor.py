# File: src/intraday/trading_engine/position_management/monitor.py
#
# Checkpoint 42 Part 5: automatic position monitoring - a PURE function
# (mirrors `risk_engine.evaluator.evaluate_order_risk()`'s own "pure
# function over an explicit context, checks run in fixed order"
# discipline) that turns "a new price arrived" into, at most, ONE
# `ExitDecision` per call. Never mutates `ManagedPosition` itself -
# the caller (a future stateful position-monitoring SERVICE, not yet
# built this checkpoint - see the gap register) is responsible for
# applying the decision and updating `highest_favorable_price` between
# calls.
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import Side, ensure_utc
from intraday.trading_engine.position_management.contracts import (
    ExitDecision,
    ExitReason,
    ManagedPosition,
    PositionLifecycleStatus,
)

# Checkpoint 42/43's own "partial exits" requirement, given a
# concrete, DOCUMENTED assumption rather than an invented one: T1/T2
# each exit ONE THIRD of the REMAINING quantity at the moment they
# fire (not one third of the original entry size) - self-consistent
# across successive partial exits, so a T3 (or any target hit with
# less than one third left) exit always closes EXACTLY what remains,
# with no rounding-drift residual ever left open. This is a policy
# choice, not a Dhan/exchange requirement - documented explicitly so a
# future checkpoint can make it configurable instead of silently
# assuming this specific split is correct for every strategy.
_PARTIAL_EXIT_FRACTION = Decimal("1") / Decimal("3")


def evaluate_position_exit(
    *, managed: ManagedPosition, current_price: Decimal, now: datetime
) -> ExitDecision | None:
    """Checked in a FIXED order (mirrors the risk engine's own
    documented discipline): stop-loss first (risk always wins), then
    targets in sequence (never skipping ahead - T2 cannot fire before
    T1 has), then trailing stop last. Returns `None` - not a
    fabricated "no exit needed" reason - when the position has no
    `ExitPlan` at all (Checkpoint 36's `ema_crossover`, today) or no
    exit rule within it fires."""
    ensure_utc(now, field_name="now")

    if managed.lifecycle_status.is_terminal():
        return None
    if managed.exit_plan is None or not managed.exit_plan.has_any_exit_rule():
        return None

    plan = managed.exit_plan
    is_long = managed.position.direction is Side.BUY
    position_id = str(managed.position.position_id)

    # 1. Stop loss - checked first, unconditionally, mirrors the risk
    #    engine's own "kill switch checked first" precedent (a stop
    #    loss is this layer's equivalent non-negotiable safety check).
    if plan.stop_loss is not None:
        stop_hit = current_price <= plan.stop_loss if is_long else current_price >= plan.stop_loss
        if stop_hit:
            return ExitDecision(
                position_id=position_id,
                reason=ExitReason.STOP_LOSS,
                exit_price=current_price,
                exit_quantity=managed.remaining_quantity,
                new_lifecycle_status=PositionLifecycleStatus.STOPPED,
                decided_at=now,
            )

    # 2. Targets, strictly in sequence - a later target can never fire
    #    before an earlier one has already been passed.
    for target_price, reason, status in (
        (plan.target_1, ExitReason.TARGET_1, PositionLifecycleStatus.TARGET_1),
        (plan.target_2, ExitReason.TARGET_2, PositionLifecycleStatus.TARGET_2),
        (plan.target_3, ExitReason.TARGET_3, PositionLifecycleStatus.TARGET_3),
    ):
        if target_price is None or managed.has_passed(status):
            continue
        target_hit = current_price >= target_price if is_long else current_price <= target_price
        if not target_hit:
            break  # targets are ordered - if this one hasn't hit, later ones cannot have either
        # Basis is the position's CURRENT remaining_quantity (not the
        # original entry size) - self-consistent across successive
        # partial exits, so the FINAL target always exits exactly what
        # is actually left (never a rounding-drift residual). This
        # does mean each partial exit is "one third of what's left,"
        # not "one third of the original size" - see this module's own
        # policy note above.
        partial = (managed.remaining_quantity * _PARTIAL_EXIT_FRACTION).quantize(Decimal("0.0001"))
        exit_quantity = (
            managed.remaining_quantity
            if status is PositionLifecycleStatus.TARGET_3 or partial >= managed.remaining_quantity
            else partial
        )
        return ExitDecision(
            position_id=position_id,
            reason=reason,
            exit_price=current_price,
            exit_quantity=exit_quantity,
            new_lifecycle_status=status,
            decided_at=now,
        )

    # 3. Trailing stop - only meaningful once a trailing distance is
    #    defined; trails behind the best price seen since entry.
    if plan.trailing_stop_distance is not None:
        trailing_level = (
            managed.highest_favorable_price - plan.trailing_stop_distance
            if is_long
            else managed.highest_favorable_price + plan.trailing_stop_distance
        )
        trailing_hit = (
            current_price <= trailing_level if is_long else current_price >= trailing_level
        )
        if trailing_hit:
            return ExitDecision(
                position_id=position_id,
                reason=ExitReason.TRAILING_STOP,
                exit_price=current_price,
                exit_quantity=managed.remaining_quantity,
                new_lifecycle_status=PositionLifecycleStatus.STOPPED,
                decided_at=now,
            )

    return None
