# File: src/intraday/application/services/exit_plan_policy.py
#
# Checkpoint 43 Part 4: `ema_crossover` does not define a stop-loss/
# target model in its own specification - no strategy specification in
# this repository does. Rather than silently inventing production
# semantics inside the strategy itself, this module is an explicit,
# clearly-labelled `PROJECT_POLICY` (not a Dhan/NSE/SEBI requirement,
# not a claim about what `ema_crossover` "should" do) - a conservative,
# fixed-percentage default any strategy MAY opt into, kept entirely
# separate from strategy evaluation itself (Checkpoint 42 Part 4's own
# "the strategy/risk/position layer determines WHY, the broker executes
# orders" separation, extended here to "policy defines the numbers,
# strategy evaluation never does math about risk").
#
# HONEST LIMITATION: this is a fixed-percentage default, not a
# strategy-aware, volatility-aware, or instrument-aware risk model
# (e.g. ATR-based). A real production exit model would very likely
# need one - this module exists so `PositionMonitorService` has
# something real, non-fabricated-but-explicitly-policy-based to
# consume THIS checkpoint, not as a claim that percentage-based exits
# are correct for every strategy or instrument.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.shared_kernel.contracts import Side
from intraday.trading_engine.position_management.contracts import ExitPlan

# PROJECT_POLICY - conservative defaults, not sourced from any
# broker/exchange/regulatory requirement. Percentages are of entry
# price. Deliberately asymmetric (targets widen faster than the stop
# is placed) - a common, but NOT researched-for-this-project,
# risk/reward shaping choice; documented as policy, not fact.
DEFAULT_STOP_LOSS_PERCENT = Decimal("0.01")  # 1%
DEFAULT_TARGET_1_PERCENT = Decimal("0.015")  # 1.5%
DEFAULT_TARGET_2_PERCENT = Decimal("0.025")  # 2.5%
DEFAULT_TARGET_3_PERCENT = Decimal("0.04")  # 4%
DEFAULT_TRAILING_STOP_PERCENT = Decimal("0.01")  # 1%


def derive_default_exit_plan(*, entry_price: Decimal, direction: Side) -> ExitPlan:
    """PROJECT_POLICY, opt-in only - never called automatically by
    `PaperSignalExecutionService` unless a caller explicitly requests
    it (see that service's `apply_default_exit_plan` parameter,
    Checkpoint 43). A strategy that defines its OWN exit semantics in
    the future should bypass this function entirely, not extend it."""
    sign = Decimal("1") if direction is Side.BUY else Decimal("-1")
    return ExitPlan(
        stop_loss=entry_price - sign * entry_price * DEFAULT_STOP_LOSS_PERCENT,
        target_1=entry_price + sign * entry_price * DEFAULT_TARGET_1_PERCENT,
        target_2=entry_price + sign * entry_price * DEFAULT_TARGET_2_PERCENT,
        target_3=entry_price + sign * entry_price * DEFAULT_TARGET_3_PERCENT,
        trailing_stop_distance=entry_price * DEFAULT_TRAILING_STOP_PERCENT,
    )
