# File: src/intraday/research/backtesting/engine.py
#
# Checkpoint 27/28: the single-instrument backtest simulation engine.
# Provider-neutral - no Dhan, no Django ORM, no broker call anywhere in
# this module (proven by
# `tests/unit/architecture/test_backtesting_sample_bar_boundary.py`).
#
# STRATEGY REUSE: this module never defines a strategy rule of its own.
# It calls the SAME `Strategy.evaluate()` the live diagnostic coordinator
# (Checkpoint 26) calls, with the SAME `StrategyConfigurationValues`.
#
# EXECUTION MODEL (Checkpoint 27 Part 5, unchanged for direction-flip
# strategies; extended by Checkpoint 64.22 for TradePlan strategies):
#   - Entry always fills at the NEXT bar's OPEN, for every strategy.
#   - For a strategy with NO `build_trade_plan()` hook (`ema_crossover`,
#     `sma_trend_filter`): unchanged direction-flip exits, also at the
#     NEXT bar's OPEN.
#   - For a strategy that DOES produce a `TradePlan` (currently only
#     `atr_volatility_breakout`): the position is exited by the SAME
#     conservative SL/T1/T2/T3/Trailing-Stop intrabar simulator
#     `tradeplan_execution.simulate_tradeplan_exit()` already proves
#     (Checkpoint 64.21), reusing it unmodified - never a second
#     implementation. Signal reversals are NOT used to exit a
#     TradePlan-managed position.
#   - End-of-series force-close (both models) at the FINAL bar's own
#     CLOSE - recorded as `ExitReason.EOD` for TradePlan positions.
#   - Feature series are computed ONCE over the full bar history via the
#     injected `compute_feature_series` (non-look-ahead-by-construction).
#
# MARK-TO-MARKET (Checkpoint 28 Part 4/5/6): in addition to the
# Checkpoint 27 realized-only `EquityPoint` curve (kept, never removed),
# this engine now also produces a `MarkToMarketPoint` per bar,
# separating realized from unrealized P&L, so drawdown can be computed
# from the true intrabar equity path rather than only from trade-close
# points. See `contracts.MarkToMarketPoint`'s own docstring for the
# mark-price convention.
from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from intraday.domain.execution.contracts import Fill, FillSource
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderStatus
from intraday.domain.risk.contracts import RiskDecisionOutcome
from intraday.domain.shared_kernel.contracts import Side
from intraday.research.backtesting import (
    Strategy,
    StrategyConfigurationValues,
    StrategyDirection,
)
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    BacktestResult,
    BacktestTrustLevel,
    CostModelIdentity,
    DataQualityDisclosure,
    EquityPoint,
    MarkToMarketPoint,
    ResultValidationSummary,
    SimulatedTrade,
)
from intraday.research.backtesting.cost_model import (
    CostModel,
    FlatPercentageCostModel,
    IndianCashEquityIntradayCostModel,
)
from intraday.research.backtesting.errors import InsufficientHistoricalDataError
from intraday.research.backtesting.execution import (
    OpenPosition,
    compute_signals,
    mfe_mae,
    quantity_for_config,
    signed_gross_pnl,
)
from intraday.research.backtesting.metrics import compute_metrics
from intraday.research.backtesting.order_intent_adapter import build_backtest_entry_order_intent
from intraday.research.backtesting.position_lifecycle import (
    BacktestPositionLifecycleStatus,
    close_backtest_position,
    hold_backtest_position,
    open_backtest_position,
)
from intraday.research.backtesting.risk_gate_adapter import (
    BacktestRiskGateInputs,
    evaluate_backtest_entry_risk,
)
from intraday.research.backtesting.tradeplan_execution import (
    ExitReason,
    TradePlanExitResult,
    compute_trade_plans,
    simulate_tradeplan_exit,
)

FeatureSeriesComputer = Callable[[str, "tuple[Bar, ...]"], "tuple[FeatureValue, ...]"]

# Checkpoint 64.30: `RiskEvaluationContext.max_total_exposure` is a
# MANDATORY field (no `None` = "unconfigured" option exists on that
# dataclass, unlike `max_daily_trades`) but `BacktestConfiguration` has
# no dedicated total-exposure-limit field of its own yet (out of this
# checkpoint's strict scope - see `BacktestConfiguration.risk_limits`'s
# own docstring). Rather than fabricate a numeric limit that was never
# configured, this is honestly modeled as "no total-exposure
# restriction exists in a backtest today" - the same "not blocked by a
# control this engine does not model" discipline
# `risk_gate_adapter.build_backtest_risk_context()` already uses for the
# kill switch/market-session/strategy-active gates. A future checkpoint
# that adds a real `BacktestConfiguration.max_total_exposure` field
# would replace this constant with that field's value.
_UNCONSTRAINED_TOTAL_EXPOSURE = Decimal("Infinity")


def _deterministic_backtest_id(
    config: BacktestConfiguration, bars: tuple[Bar, ...], cost_model: CostModel
) -> str:
    """Derived from configuration identity + data identity + COST MODEL
    identity (Checkpoint 29 Part 9/19) - never a random UUID. Same
    strategy, same bars, different cost model must never collide."""
    first_ts = bars[0].timestamp.isoformat() if bars else "none"
    last_ts = bars[-1].timestamp.isoformat() if bars else "none"
    payload = "|".join(
        [
            config.strategy_id,
            config.specification_version,
            config.code_version,
            config.configuration_version,
            config.instrument_id,
            config.timeframe.value,
            config.start.isoformat(),
            config.end.isoformat(),
            config.position_sizing_mode.value,
            str(config.position_size_value),
            str(config.brokerage_percent),
            str(config.slippage_percent),
            first_ts,
            last_ts,
            str(len(bars)),
            cost_model.name,
            cost_model.version,
            cost_model.effective_from.isoformat(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def run_backtest(
    bars: tuple[Bar, ...],
    strategy: Strategy,
    strategy_config: StrategyConfigurationValues,
    backtest_config: BacktestConfiguration,
    compute_feature_series: FeatureSeriesComputer,
    *,
    data_quality: DataQualityDisclosure,
    generated_at: datetime,
    cost_model: CostModel | None = None,
) -> BacktestResult:
    if not bars:
        raise InsufficientHistoricalDataError(
            f"no bars available for {backtest_config.instrument_id!r} "
            f"{backtest_config.timeframe.value} in the requested range"
        )

    costs: CostModel
    if cost_model is not None:
        costs = cost_model
    else:
        costs = FlatPercentageCostModel(
            backtest_config.brokerage_percent, backtest_config.slippage_percent
        )

    signals, warmup_bars, signal_count = compute_signals(
        bars, strategy, strategy_config, compute_feature_series
    )
    # Checkpoint 64.22 §5: parallel to `signals` - `None` for every bar
    # unless the strategy itself produces a real TradePlan (currently
    # only `atr_volatility_breakout`). Reuses `compute_trade_plans()`
    # unmodified from Checkpoint 64.21 - never a second TradePlan
    # construction path.
    trade_plans = compute_trade_plans(
        bars, strategy, strategy_config, compute_feature_series, signals
    )

    trades: list[SimulatedTrade] = []
    # Parallel to `trades`: (entry_index, exit_index_inclusive) - used to
    # build the mark-to-market curve without re-deriving position
    # intervals from timestamps.
    trade_intervals: list[tuple[int, int]] = []
    # Checkpoint 64.43: the canonical `domain.execution.contracts.Fill`
    # producer list for THIS engine. One `Fill` per ACTUAL simulated
    # execution event (never one per completed `SimulatedTrade`) -
    # appended in execution order, never re-sorted. Purely additive
    # OBSERVATION alongside the pre-existing `trades`/`trade_intervals`/
    # equity-curve/metrics machinery below - nothing here reads from or
    # writes back into `fills`, so its presence cannot change any
    # existing numerical result.
    fills: list[Fill] = []
    open_position: OpenPosition | None = None
    # Checkpoint 64.22 §5/§6: set only for a TradePlan-based open
    # position - `None` while a direction-flip position (or no position)
    # is open. Precomputed AT ENTRY TIME via `simulate_tradeplan_exit()`
    # (deterministic given entry_index + bars, no look-ahead - matches
    # `tradeplan_execution.py`'s own no-look-ahead proof), then acted on
    # only once the loop actually reaches that bar index.
    pending_tradeplan_exit: TradePlanExitResult | None = None
    tradeplan_trade_count = 0
    trade_counter = 0
    skipped_signals = 0
    rejected_trades = 0
    # Checkpoint 64.30: distinct from `rejected_trades` above (which
    # counts a zero-quantity/insufficient-capital rejection, unrelated
    # to risk limits). Always stay 0 / empty when `backtest_config.
    # risk_limits is None` - the entry branch below never touches these
    # in that case.
    risk_rejected_trades = 0
    risk_rejection_reason_breakdown: dict[str, int] = {}

    def _close_trade(
        exit_index: int, exit_timestamp: datetime, exit_price: Decimal, reason: str
    ) -> None:
        nonlocal trade_counter
        assert open_position is not None  # noqa: S101 - internal invariant, narrows for mypy
        quantity = open_position.quantity
        filled_exit = costs.slippage_adjusted_price(
            open_position.direction, exit_price, entering=False
        )
        gross_pnl = signed_gross_pnl(
            open_position.direction, open_position.entry_price, filled_exit, quantity
        )
        entry_notional = open_position.entry_price * quantity
        exit_notional = filled_exit * quantity
        entry_is_buy = open_position.direction == StrategyDirection.BULLISH
        exit_is_buy = not entry_is_buy
        # Checkpoint 64.43: these two per-leg breakdowns were already
        # being computed inline (chained straight into `.combine()`)
        # before this checkpoint - captured as named locals here so the
        # EXIT-leg breakdown can also be reused, unchanged, as the exit
        # `Fill.transaction_cost` below. `breakdown`/`trade_costs` below
        # are numerically IDENTICAL to before this checkpoint (same two
        # calls, same combine, only now assigned to a name first).
        entry_leg_breakdown = costs.cost_breakdown(is_buy=entry_is_buy, notional=entry_notional)
        exit_leg_breakdown = costs.cost_breakdown(is_buy=exit_is_buy, notional=exit_notional)
        breakdown = entry_leg_breakdown.combine(exit_leg_breakdown)
        trade_costs = breakdown.total
        net_pnl = gross_pnl - trade_costs
        holding_bars = bars[open_position.entry_index : exit_index + 1]
        mfe, mae = mfe_mae(open_position.direction, open_position.entry_price, holding_bars)
        trade_counter += 1
        # Checkpoint 64.32: the SAME `BacktestPosition` carried on
        # `open_position.position_lifecycle` throughout the position's
        # life, advanced to its terminal CLOSED state here - never a
        # second, independently-constructed lifecycle object. `None`
        # only in the theoretical direct-construction case described on
        # `OpenPosition.position_lifecycle`'s own docstring.
        closed_lifecycle = (
            close_backtest_position(open_position.position_lifecycle)
            if open_position.position_lifecycle is not None
            else None
        )
        trades.append(
            SimulatedTrade(
                trade_id=f"{backtest_config.strategy_id}-{trade_counter}",
                strategy_id=backtest_config.strategy_id,
                specification_version=backtest_config.specification_version,
                code_version=backtest_config.code_version,
                configuration_version=backtest_config.configuration_version,
                instrument_id=backtest_config.instrument_id,
                timeframe=backtest_config.timeframe,
                direction=open_position.direction,
                entry_timestamp=open_position.entry_timestamp,
                entry_price=open_position.entry_price,
                exit_timestamp=exit_timestamp,
                exit_price=filled_exit,
                quantity=quantity,
                gross_pnl=gross_pnl,
                costs=trade_costs,
                net_pnl=net_pnl,
                reason=reason,
                mfe=mfe,
                mae=mae,
                cost_breakdown=breakdown,
                # Checkpoint 64.31: carried verbatim from the
                # `OpenPosition` this trade closes out - the SAME
                # `OrderIntent` constructed at entry time (and, when a
                # risk gate was configured, the SAME object evaluated by
                # `evaluate_order_risk()`) - never a second construction.
                order_intent=open_position.order_intent,
                # Checkpoint 64.32: the terminal CLOSED lifecycle
                # derived above from this same trade's own
                # `open_position.position_lifecycle`.
                position_lifecycle=closed_lifecycle,
            )
        )
        trade_intervals.append((open_position.entry_index, exit_index))

        # Checkpoint 64.43: the EXIT Fill - one canonical `Fill` for
        # THIS actual exit execution event, constructed from the exact
        # already-computed local values above (`filled_exit`,
        # `quantity`, `exit_leg_breakdown.total`), never independently
        # recomputed. `order_id`: this engine's exit path (signal
        # reversal / TradePlan SL-T1-T2-T3-Trailing / EOD force-close)
        # constructs NO independent exit `OrderIntent` anywhere in this
        # module - the only real order identity that ever exists for a
        # round trip is the single entry `OrderIntent` built once at
        # entry time (`build_backtest_entry_order_intent()`, carried on
        # `open_position.order_intent`). Per the 64.43 directive's own
        # explicit instruction NOT to fabricate a new exit order
        # identity merely to satisfy this field, the exit Fill reuses
        # that SAME entry `order_id` - the identical, pre-existing
        # precedent Checkpoint 64.32 already established for
        # `BacktestPosition.position_id=entry_order.order_id`. This is a
        # documented architectural limitation (see taskReport.md "Order
        # ID Relationship" and the architecture doc), not a silent
        # invention: a genuine, separately-identified exit order does
        # not exist in this engine today.
        if open_position.order_intent is not None:
            exit_side = Side.BUY if exit_is_buy else Side.SELL
            fills.append(
                Fill(
                    fill_id=f"{open_position.order_intent.order_id}-fill-exit-{trade_counter}",
                    order_id=open_position.order_intent.order_id,
                    instrument_id=backtest_config.instrument_id,
                    side=exit_side,
                    quantity=quantity,
                    price=filled_exit,
                    timestamp=exit_timestamp,
                    transaction_cost=exit_leg_breakdown.total,
                    slippage_applied=filled_exit - exit_price,
                    status_at_fill=OrderStatus.FILLED,
                    source=FillSource.BACKTEST,
                )
            )

    running_equity = backtest_config.initial_capital
    is_tradeplan_position = False

    for i, signal in enumerate(signals):
        is_last_bar = i == len(bars) - 1

        # Checkpoint 64.32: purely a REFLECTION of the engine's own
        # existing state - a position that is still open on any bar
        # strictly after its own entry bar has, by definition, already
        # survived at least one full bar with no exit, so its canonical
        # lifecycle is advanced OPEN -> HELD here. This is O(1) and
        # runs only when the status is still OPEN (never repeated once
        # HELD - `hold_backtest_position()` is itself idempotent, but
        # the `is` guard below additionally avoids doing the work at
        # all on every subsequent bar). No exit decision is made or
        # influenced by this - `should_exit_on_reversal`,
        # `pending_tradeplan_exit`, and the EOD checks below are
        # entirely unchanged and still solely authoritative.
        if (
            open_position is not None
            and open_position.position_lifecycle is not None
            and i > open_position.entry_index
            and open_position.position_lifecycle.lifecycle_status
            is BacktestPositionLifecycleStatus.OPEN
        ):
            open_position.position_lifecycle = hold_backtest_position(
                open_position.position_lifecycle
            )

        if open_position is None:
            if (
                signal is not None
                and signal.direction != StrategyDirection.NEUTRAL
                and not is_last_bar
            ):
                entry_bar = bars[i + 1]
                filled_entry = costs.slippage_adjusted_price(
                    signal.direction, entry_bar.open, entering=True
                )
                quantity = quantity_for_config(backtest_config, running_equity, filled_entry)
                if quantity > 0:
                    # Checkpoint 64.31: the REAL canonical `OrderIntent`
                    # is now constructed for EVERY accepted entry
                    # attempt (quantity > 0), not only when a risk gate
                    # is configured - it is the canonical representation
                    # of "what order the strategy wanted to submit",
                    # independent of whether a risk policy is consulted.
                    # Built ONCE here (never per-bar, never rebuilt) and
                    # reused verbatim below: as the SAME object fed to
                    # the risk gate (when configured) AND as the SAME
                    # object retained on `OpenPosition`/`SimulatedTrade`
                    # for the accepted entry - never a second,
                    # separately-constructed `OrderIntent`. Direction is
                    # already guaranteed non-NEUTRAL here (this branch's
                    # own `signal.direction != StrategyDirection.NEUTRAL`
                    # guard above).
                    entry_order = build_backtest_entry_order_intent(
                        strategy_id=backtest_config.strategy_id,
                        instrument_id=backtest_config.instrument_id,
                        direction=signal.direction,
                        quantity=quantity,
                        entry_timestamp=entry_bar.timestamp,
                        entry_index=i + 1,
                    )
                    # Checkpoint 64.30: OPT-IN risk gate. When
                    # `risk_limits is None` (the default, and every
                    # pre-64.30 test's configuration), this entire block
                    # is skipped - `entry_risk_approved` stays `True`
                    # and NOTHING below differs from pre-64.30 code:
                    # same `OpenPosition`, same TradePlan precomputation,
                    # same branch taken. `entry_order` above is still
                    # constructed in this path (Checkpoint 64.31), but
                    # `evaluate_order_risk()` itself is NOT called - see
                    # `test_i_no_risk_evaluation_occurs_when_risk_limits_
                    # is_none` in test_checkpoint_64_30_risk_gate_wiring.py,
                    # still passing unmodified.
                    entry_risk_approved = True
                    if backtest_config.risk_limits is not None:
                        risk_inputs = BacktestRiskGateInputs(
                            risk_limits=backtest_config.risk_limits,
                            risk_configuration_version=backtest_config.configuration_version,
                            now=entry_bar.timestamp,
                            # Cost-inclusive, matching `SimulatedTrade.
                            # net_pnl`'s own convention - see
                            # `risk_gate_adapter.py`'s header docstring.
                            cumulative_closed_trade_net_pnl=(
                                running_equity - backtest_config.initial_capital
                            ),
                            # Honest: this branch only runs when
                            # `open_position is None` (no position open
                            # right now, single-instrument/single-
                            # position POC engine).
                            current_open_positions_count=0,
                            current_position_size_for_instrument=Decimal("0"),
                            estimated_order_notional=filled_entry * quantity,
                            max_concurrent_positions=backtest_config.max_concurrent_positions,
                            max_total_exposure=_UNCONSTRAINED_TOTAL_EXPOSURE,
                            current_total_exposure=Decimal("0"),
                        )
                        risk_decision = evaluate_backtest_entry_risk(entry_order, risk_inputs)
                        if risk_decision.outcome is RiskDecisionOutcome.REJECTED:
                            entry_risk_approved = False
                            risk_rejected_trades += 1
                            reason = (
                                risk_decision.reason_code.value
                                if risk_decision.reason_code is not None
                                else "UNKNOWN"
                            )
                            risk_rejection_reason_breakdown[reason] = (
                                risk_rejection_reason_breakdown.get(reason, 0) + 1
                            )
                    if entry_risk_approved:
                        open_position = OpenPosition(
                            instrument_id=backtest_config.instrument_id,
                            direction=signal.direction,
                            entry_index=i + 1,
                            entry_timestamp=entry_bar.timestamp,
                            entry_price=filled_entry,
                            quantity=quantity,
                            # Checkpoint 64.31: the SAME `OrderIntent`
                            # constructed above - the same object fed to
                            # the risk gate when configured, never a
                            # second construction.
                            order_intent=entry_order,
                            # Checkpoint 64.32: the real canonical
                            # position lifecycle - always starts OPEN,
                            # per `open_backtest_position()`'s own
                            # contract. `position_id` reuses the SAME
                            # `entry_order.order_id` already constructed
                            # above (never a second, independent ID).
                            position_lifecycle=open_backtest_position(
                                position_id=entry_order.order_id,
                                direction=signal.direction,
                                quantity=quantity,
                                entry_price=filled_entry,
                                entry_timestamp=entry_bar.timestamp,
                            ),
                        )
                        # Checkpoint 64.43: the ENTRY Fill - one
                        # canonical `Fill` for THIS actual entry
                        # execution event, built from the exact same
                        # already-computed local values used for
                        # `OpenPosition`/`entry_order` above
                        # (`filled_entry`, `quantity`, `entry_bar.
                        # timestamp`, `entry_order.order_id`/`.side`) -
                        # never independently recomputed.
                        # `transaction_cost` below is the entry-leg-only
                        # `CostBreakdown.total`, computed via the SAME
                        # `costs.cost_breakdown()` call `_close_trade`
                        # makes for its own entry leg (pure/deterministic
                        # given identical `is_buy`/`notional` inputs) -
                        # this is an ADDITIONAL call for Fill
                        # observability only; it does not replace, feed
                        # into, or alter `_close_trade`'s own entry-leg
                        # computation or `trade_costs`/`net_pnl` in any
                        # way (that computation still happens exactly
                        # once, at exit time, exactly as before this
                        # checkpoint).
                        entry_leg_cost = costs.cost_breakdown(
                            is_buy=entry_order.side == Side.BUY,
                            notional=filled_entry * quantity,
                        ).total
                        fills.append(
                            Fill(
                                fill_id=f"{entry_order.order_id}-fill-entry",
                                order_id=entry_order.order_id,
                                instrument_id=backtest_config.instrument_id,
                                side=entry_order.side,
                                quantity=quantity,
                                price=filled_entry,
                                timestamp=entry_bar.timestamp,
                                transaction_cost=entry_leg_cost,
                                slippage_applied=filled_entry - entry_bar.open,
                                status_at_fill=OrderStatus.FILLED,
                                source=FillSource.BACKTEST,
                            )
                        )
                        plan = trade_plans[i]
                        if plan is not None:
                            # Checkpoint 64.22 §5/§6: TradePlan-managed
                            # position - exit is precomputed here
                            # (deterministic given entry_index + bars, no
                            # look-ahead) and only ACTED ON once the loop
                            # reaches that bar, exactly like every other
                            # fill in this engine.
                            is_tradeplan_position = True
                            tradeplan_trade_count += 1
                            pending_tradeplan_exit = simulate_tradeplan_exit(
                                trade_plan=plan,
                                direction=open_position.direction,
                                entry_index=open_position.entry_index,
                                bars=bars,
                            )
                        else:
                            is_tradeplan_position = False
                            pending_tradeplan_exit = None
                else:
                    rejected_trades += 1
        elif is_tradeplan_position:
            # Checkpoint 64.22 §5/§6: TradePlan-managed exits ONLY - the
            # SL/T1/T2/T3/Trailing simulation from `tradeplan_execution.
            # py` governs the exit, never a signal-reversal flip (the
            # strategy's own TradePlan already encodes its exit
            # discipline, matching the live coordinator's own
            # risk-managed-exit semantics).
            if pending_tradeplan_exit is not None and i == pending_tradeplan_exit.exit_index:
                _close_trade(
                    i,
                    bars[i].timestamp,
                    pending_tradeplan_exit.exit_price,
                    pending_tradeplan_exit.exit_reason.value,
                )
                running_equity += trades[-1].net_pnl
                open_position = None
                pending_tradeplan_exit = None
                is_tradeplan_position = False
            elif is_last_bar:
                # Checkpoint 64.22 §6: never touched any level before the
                # series ended - same EOD force-close policy as the
                # direction-flip model (final bar's own close), recorded
                # honestly as `ExitReason.EOD`.
                _close_trade(i, bars[i].timestamp, bars[i].close, ExitReason.EOD.value)
                running_equity += trades[-1].net_pnl
                open_position = None
                pending_tradeplan_exit = None
                is_tradeplan_position = False
        else:
            if signal is not None and signal.direction == open_position.direction:
                skipped_signals += 1
            should_exit_on_reversal = (
                signal is not None
                and signal.direction != open_position.direction
                and not is_last_bar
            )
            if should_exit_on_reversal:
                exit_bar = bars[i + 1]
                _close_trade(i + 1, exit_bar.timestamp, exit_bar.open, "signal_reversal")
                running_equity += trades[-1].net_pnl
                open_position = None
            elif is_last_bar:
                _close_trade(i, bars[i].timestamp, bars[i].close, "end_of_data")
                running_equity += trades[-1].net_pnl
                open_position = None

    equity_curve = _build_equity_curve(backtest_config.initial_capital, trades, bars[0].timestamp)
    mtm_curve = _build_mark_to_market_curve(
        backtest_config.initial_capital, bars, trades, trade_intervals
    )
    metrics = compute_metrics(backtest_config.initial_capital, trades, mtm_curve)
    exit_reason_breakdown: dict[str, int] = {}
    for trade in trades:
        exit_reason_breakdown[trade.reason] = exit_reason_breakdown.get(trade.reason, 0) + 1
    validation = ResultValidationSummary(
        bar_count=len(bars),
        signal_count=signal_count,
        trade_count=len(trades),
        warmup_bars=warmup_bars,
        skipped_signals=skipped_signals,
        rejected_trades=rejected_trades,
        data_gaps_note=(
            "Gap detection requires an explicit session-calendar cross-check, "
            "not performed by this engine - not computed, not assumed zero."
        ),
        tradeplan_trades=tradeplan_trade_count,
        exit_reason_breakdown=exit_reason_breakdown,
        risk_rejected_trades=risk_rejected_trades,
        risk_rejection_reason_breakdown=risk_rejection_reason_breakdown,
    )

    cost_model_identity = CostModelIdentity(
        name=costs.name,
        version=costs.version,
        effective_from=costs.effective_from,
        is_verified=isinstance(costs, IndianCashEquityIntradayCostModel),
    )

    return BacktestResult(
        backtest_id=_deterministic_backtest_id(backtest_config, bars, costs),
        configuration=backtest_config,
        trades=tuple(trades),
        equity_curve=equity_curve,
        mark_to_market_curve=mtm_curve,
        metrics=metrics,
        data_quality=data_quality,
        validation=validation,
        cost_model_identity=cost_model_identity,
        generated_at=generated_at,
        trust_level=BacktestTrustLevel.POC,
        # Checkpoint 64.43: the canonical Fill list, in execution order
        # (entry Fill immediately before its own trade's exit Fill,
        # trades themselves in chronological close order) - purely
        # additive observability, never read by anything above this
        # line.
        fills=tuple(fills),
    )


def _build_equity_curve(
    initial_capital: Decimal, trades: list[SimulatedTrade], start_timestamp: datetime
) -> tuple[EquityPoint, ...]:
    """Checkpoint 27's original realized-only curve - kept unchanged
    (Checkpoint 28 Part 4 explicitly forbids removing it)."""
    points: list[EquityPoint] = [
        EquityPoint(
            timestamp=start_timestamp,
            balance=initial_capital,
            cumulative_pnl=Decimal("0"),
            drawdown=Decimal("0"),
            drawdown_percent=Decimal("0"),
        )
    ]
    balance = initial_capital
    peak = initial_capital
    for trade in trades:
        balance += trade.net_pnl
        peak = max(peak, balance)
        drawdown = peak - balance
        drawdown_percent = (drawdown / peak * 100) if peak > 0 else Decimal("0")
        points.append(
            EquityPoint(
                timestamp=trade.exit_timestamp,
                balance=balance,
                cumulative_pnl=balance - initial_capital,
                drawdown=drawdown,
                drawdown_percent=drawdown_percent,
            )
        )
    return tuple(points)


def _build_mark_to_market_curve(
    initial_capital: Decimal,
    bars: tuple[Bar, ...],
    trades: list[SimulatedTrade],
    trade_intervals: list[tuple[int, int]],
) -> tuple[MarkToMarketPoint, ...]:
    """One point per bar (Part 4). Mark price = that bar's own close
    (Part 6, documented in `MarkToMarketPoint`'s own docstring)."""
    points: list[MarkToMarketPoint] = []
    realized = Decimal("0")
    peak = initial_capital
    trade_index = 0  # next trade whose exit we haven't yet folded into `realized`

    for i, bar in enumerate(bars):
        # Fold in any trade that closed AT OR BEFORE this bar index.
        while trade_index < len(trades) and trade_intervals[trade_index][1] <= i:
            realized += trades[trade_index].net_pnl
            trade_index += 1

        unrealized = Decimal("0")
        for trade, (entry_index, exit_index) in zip(trades, trade_intervals, strict=True):
            if entry_index <= i < exit_index:
                # Position genuinely open AT this bar (not yet closed) -
                # value it at this bar's close, excluding exit costs
                # (Part 6: those are only realized at actual exit). The
                # exit bar itself (i == exit_index) is intentionally
                # excluded here - its P&L was already folded into
                # `realized` above.
                unrealized = signed_gross_pnl(
                    trade.direction, trade.entry_price, bar.close, trade.quantity
                )
                break

        total_equity = initial_capital + realized + unrealized
        peak = max(peak, total_equity)
        drawdown = peak - total_equity
        drawdown_percent = (drawdown / peak * 100) if peak > 0 else Decimal("0")
        points.append(
            MarkToMarketPoint(
                timestamp=bar.timestamp,
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                total_equity=total_equity,
                peak_equity=peak,
                drawdown=drawdown,
                drawdown_percent=drawdown_percent,
            )
        )
    return tuple(points)
