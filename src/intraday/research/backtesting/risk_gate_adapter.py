# File: src/intraday/research/backtesting/risk_gate_adapter.py
#
# Checkpoint 64.29 Target 1: standalone, UNWIRED adapter infrastructure
# proving `research/backtesting/` COULD call the canonical
# `evaluate_order_risk()` (`domain/risk/policy.py`) for an entry
# decision, without wiring it into `run_backtest()`'s actual control
# flow this checkpoint. Mirrors the discipline `tradeplan_execution.py`
# (64.21) and `historical_execution.py` (64.23) established: build and
# unit-test standalone infrastructure first, wire it into the engine's
# real loop only in a LATER checkpoint, once the wiring itself can be
# proven non-invasive to existing numerical results.
#
# WHY THIS IS NOT WIRED INTO `run_backtest()` THIS CHECKPOINT: wiring a
# real risk-rejection into the entry branch of `run_backtest()`'s main
# loop (`engine.py` lines ~230-270) would change `rejected_trades`
# counting, would need a NEW `RiskRejectionReason`-shaped outcome
# distinct from today's "zero-quantity => rejected_trades += 1" path,
# and would require deciding what a backtest-level `RiskLimits`
# configuration even IS (there is no existing `BacktestConfiguration`
# field for one) - all of that is real design/control-flow work this
# checkpoint's own safety rules forbid ("do NOT rewrite engine.py's
# core loop"). This module proves the adapter is CORRECT and CALLABLE
# in isolation; the future seam is: `run_backtest()` would need an
# optional `risk_limits: RiskLimits | None` parameter, and the entry
# branch would need to call `evaluate_order_risk()` via this adapter
# and branch on `.outcome` similarly to how it already branches on
# `quantity > 0` - a small, precisely scoped, but still real control-flow
# change, correctly deferred.
#
# P&L SEMANTIC USED FOR `current_daily_realized_pnl` (documented here,
# per the checkpoint directive, not silently chosen): this adapter uses
# the SUM OF `SimulatedTrade.net_pnl` FOR ALL TRADES CLOSED SO FAR - i.e.
# `running_equity - initial_capital` at the moment of the entry decision,
# which is `engine.py`'s own existing running-equity bookkeeping
# (`engine.py`, the `running_equity += trades[-1].net_pnl` lines).
# `SimulatedTrade.net_pnl` is ALREADY cost-inclusive
# (`net_pnl = gross_pnl - trade_costs`, `engine.py`'s `_close_trade()`),
# so this happens to already be the NET (cost-inclusive) convention
# Checkpoint 64.28 recommended for a real risk gate - but this is NOT a
# new semantic decision made by this checkpoint. It is simply "whichever
# P&L figure the backtest already, honestly computes at this point,"
# which happens to be net rather than gross ONLY because that is what
# `SimulatedTrade.net_pnl` already means. Contrast with `PaperBroker.
# Position.realized_pnl`, which IS cost-exclusive (64.27/64.28's
# documented conflict) - the two engines still disagree with each other
# on this point; this adapter does not resolve that conflict, it only
# reports honestly which side of it the backtest engine's own existing
# figure happens to fall on.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.order.contracts import OrderIntent
from intraday.domain.risk.contracts import OrderRiskDecision, RiskLimits, TradingHaltStatus
from intraday.domain.risk.policy import RiskEvaluationContext, evaluate_order_risk

__all__ = [
    "BacktestRiskGateInputs",
    "build_backtest_risk_context",
    "evaluate_backtest_entry_risk",
]


@dataclass(frozen=True, slots=True)
class BacktestRiskGateInputs:
    """Every fact `run_backtest()`'s bar loop honestly has available, at
    the moment of an entry decision, that `RiskEvaluationContext` needs.
    Deliberately narrow - only what the CURRENT single-position, single-
    instrument POC engine (`max_concurrent_positions` hardcoded to 1,
    `BacktestConfiguration.__post_init__`) actually tracks. A future,
    genuinely multi-position engine would need more fields; this is not
    a general-purpose forward-looking shape, it is honest about what
    exists TODAY."""

    risk_limits: RiskLimits
    risk_configuration_version: str
    now: datetime
    cumulative_closed_trade_net_pnl: Decimal
    """Sum of `SimulatedTrade.net_pnl` for every trade closed so far this
    backtest - see this module's header docstring for why this is the
    cost-inclusive (net) figure, not a gross one, and why that is
    incidental rather than a deliberate new semantic choice."""
    current_open_positions_count: int
    """0 or 1 in the current single-position engine."""
    current_position_size_for_instrument: Decimal
    estimated_order_notional: Decimal
    max_concurrent_positions: int
    max_total_exposure: Decimal
    current_total_exposure: Decimal


def build_backtest_risk_context(inputs: BacktestRiskGateInputs) -> RiskEvaluationContext:
    """Constructs a REAL `RiskEvaluationContext` - the exact same
    dataclass `PaperTradingService`'s own order-submission method builds - never a
    backtest-specific copy. Safety gates that have no backtest-side
    analogue today (kill switch, market-session-open, strategy-active,
    stale-data, idempotency/duplicate-order tracking) are given
    deliberately permissive, honestly-labeled defaults (never fabricated
    as "the strategy really is active" - a backtest has no runtime kill
    switch or session clock to consult, so the honest default is "not
    blocked by a control this engine does not model")."""
    return RiskEvaluationContext(
        risk_limits=inputs.risk_limits,
        risk_configuration_version=inputs.risk_configuration_version,
        now=inputs.now,
        current_daily_realized_pnl=inputs.cumulative_closed_trade_net_pnl,
        current_total_exposure=inputs.current_total_exposure,
        current_open_positions_count=inputs.current_open_positions_count,
        current_position_size_for_instrument=inputs.current_position_size_for_instrument,
        estimated_order_notional=inputs.estimated_order_notional,
        max_concurrent_positions=inputs.max_concurrent_positions,
        max_total_exposure=inputs.max_total_exposure,
        # No kill switch exists in a backtest - honestly modeled as
        # always ACTIVE (never HALTED), not a fabricated "the operator
        # checked and it's fine."
        kill_switch_status=TradingHaltStatus.ACTIVE,
        # A backtest only ever iterates bars that already exist within
        # the configured session/data range - there is no independent
        # "is the market open right now" fact to consult beyond that.
        market_session_is_open=True,
        # A backtest's strategy is definitionally "active" for the whole
        # run - there is no separate activation toggle in this engine.
        strategy_is_active=True,
        # `DataQualityDisclosure` already exists as a SEPARATE, real
        # data-quality signal on `BacktestResult` - this adapter does
        # not duplicate that decision; a future integration could wire
        # it through, but doing so is out of scope for this standalone
        # proof.
        data_quality_is_stale=False,
        # A backtest has no idempotency-key-bearing order submission
        # pipeline - the empty set is honest, not a placeholder.
        already_submitted_idempotency_keys=frozenset(),
        instruments_with_pending_or_open_orders=frozenset(),
    )


def evaluate_backtest_entry_risk(
    order: OrderIntent, inputs: BacktestRiskGateInputs
) -> OrderRiskDecision:
    """Calls the REAL, unmodified `evaluate_order_risk()` - proves the
    adapter is wired correctly end-to-end, in isolation from
    `run_backtest()`'s own control flow. Returns the same
    `OrderRiskDecision` a real Paper Trading submission would get."""
    context = build_backtest_risk_context(inputs)
    return evaluate_order_risk(order, context)
