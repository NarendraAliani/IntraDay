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

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
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
from intraday.research.backtesting.tradeplan_execution import (
    ExitReason,
    TradePlanExitResult,
    compute_trade_plans,
    simulate_tradeplan_exit,
)

FeatureSeriesComputer = Callable[[str, "tuple[Bar, ...]"], "tuple[FeatureValue, ...]"]


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
        breakdown = costs.cost_breakdown(is_buy=entry_is_buy, notional=entry_notional).combine(
            costs.cost_breakdown(is_buy=exit_is_buy, notional=exit_notional)
        )
        trade_costs = breakdown.total
        net_pnl = gross_pnl - trade_costs
        holding_bars = bars[open_position.entry_index : exit_index + 1]
        mfe, mae = mfe_mae(open_position.direction, open_position.entry_price, holding_bars)
        trade_counter += 1
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
            )
        )
        trade_intervals.append((open_position.entry_index, exit_index))

    running_equity = backtest_config.initial_capital
    is_tradeplan_position = False

    for i, signal in enumerate(signals):
        is_last_bar = i == len(bars) - 1

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
                    open_position = OpenPosition(
                        instrument_id=backtest_config.instrument_id,
                        direction=signal.direction,
                        entry_index=i + 1,
                        entry_timestamp=entry_bar.timestamp,
                        entry_price=filled_entry,
                        quantity=quantity,
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
