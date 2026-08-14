# File: src/intraday/research/backtesting/engine.py
#
# Checkpoint 27: the backtest simulation engine. Provider-neutral - no
# Dhan, no Django ORM, no broker call anywhere in this module (proven by
# `tests/unit/architecture/test_backtesting_sample_bar_boundary.py`,
# mirroring Checkpoint 26's own SAMPLE_BAR safety-gate test pattern).
#
# STRATEGY REUSE (Part 4): this module never defines a strategy rule of
# its own. It calls the SAME `Strategy.evaluate()` the live diagnostic
# coordinator (Checkpoint 26) calls, with the SAME
# `StrategyConfigurationValues`, imported directly from
# `trading_engine.strategy_execution` - the one legal cross-bounded-
# context import for `research.backtesting`
# (`.importlinter` contract 4's `ignore_imports` exception).
#
# EXECUTION MODEL (Part 5, chosen and documented, not left implicit):
#   - A strategy signal computed from bar[i]'s CLOSE (bar.timestamp is
#     always a bar's close time - domain.market_data.contracts.Bar's own
#     documented convention) is never executable at that same instant.
#   - Entry and every direction-flip exit fill at the NEXT bar's OPEN
#     (bar[i+1].open) - the first price actually observable after the
#     decision was made. This is the single deterministic rule chosen to
#     avoid look-ahead bias; no other execution timing is implemented.
#   - If the series ends while a position is open, it is force-closed at
#     the FINAL bar's own CLOSE (reason "end_of_data") - not future
#     information, since it is the last bar that exists.
#   - Feature series are computed ONCE over the full bar history via the
#     injected `compute_feature_series` (same non-look-ahead-by-
#     construction functions Checkpoint 15-17 already proved: each
#     output at index i depends only on bars[0..i]).
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.research.backtesting import Strategy, StrategyConfigurationValues, StrategyDirection
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    BacktestMetrics,
    BacktestResult,
    DataQualityDisclosure,
    EquityPoint,
    PositionSizingMode,
    SimulatedTrade,
)
from intraday.research.backtesting.errors import InsufficientHistoricalDataError

FeatureSeriesComputer = Callable[[str, "tuple[Bar, ...]"], "tuple[FeatureValue, ...]"]


def _deterministic_backtest_id(config: BacktestConfiguration, bars: tuple[Bar, ...]) -> str:
    """Derived from configuration identity + data identity - never a
    random UUID (Part 10/11 reproducibility: re-running the same
    configuration against the same data always yields the same id)."""
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
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class _OpenPosition:
    direction: StrategyDirection
    entry_index: int
    entry_timestamp: datetime
    entry_price: Decimal
    quantity: Decimal


def _signed_gross_pnl(
    direction: StrategyDirection, entry_price: Decimal, exit_price: Decimal, quantity: Decimal
) -> Decimal:
    if direction == StrategyDirection.BULLISH:
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def _apply_slippage(
    direction: StrategyDirection, price: Decimal, slippage_percent: Decimal, *, entering: bool
) -> Decimal:
    """Slippage always moves the fill price AGAINST the trader - a long
    entry/short exit pays more, a short entry/long exit receives less.
    Applied as a simple percentage of price (MODEL ASSUMPTION, not a
    verified microstructure model)."""
    factor = slippage_percent / Decimal("100")
    is_buy = (direction == StrategyDirection.BULLISH) == entering
    return price * (1 + factor) if is_buy else price * (1 - factor)


def _quantity_for(
    config: BacktestConfiguration, current_equity: Decimal, entry_price: Decimal
) -> Decimal:
    if config.position_sizing_mode == PositionSizingMode.FIXED_QUANTITY:
        return config.position_size_value.to_integral_value(rounding="ROUND_DOWN")
    notional = current_equity * config.position_size_value
    if entry_price <= 0:
        return Decimal("0")
    return (notional / entry_price).to_integral_value(rounding="ROUND_DOWN")


def _mfe_mae(
    direction: StrategyDirection, entry_price: Decimal, holding_bars: tuple[Bar, ...]
) -> tuple[Decimal, Decimal]:
    """Part 9: MFE/MAE computed directly from the trade's own holding-
    period bars (entry bar through exit bar, inclusive) - a different
    computation basis than `signal_intelligence.theoretical_outcome`
    (which measures a fixed future horizon from a `DirectionalIndication`,
    not a trade's actual holding period), so it is a new, small
    computation here rather than a reuse of that module."""
    if direction == StrategyDirection.BULLISH:
        favorable = max(bar.high - entry_price for bar in holding_bars)
        adverse = max(entry_price - bar.low for bar in holding_bars)
    else:
        favorable = max(entry_price - bar.low for bar in holding_bars)
        adverse = max(bar.high - entry_price for bar in holding_bars)
    return max(favorable, Decimal("0")), max(adverse, Decimal("0"))


def run_backtest(
    bars: tuple[Bar, ...],
    strategy: Strategy,
    strategy_config: StrategyConfigurationValues,
    backtest_config: BacktestConfiguration,
    compute_feature_series: FeatureSeriesComputer,
    *,
    data_quality: DataQualityDisclosure,
    generated_at: datetime,
) -> BacktestResult:
    if not bars:
        raise InsufficientHistoricalDataError(
            f"no bars available for {backtest_config.instrument_id!r} "
            f"{backtest_config.timeframe.value} in the requested range"
        )

    required_features = strategy.required_features(strategy_config)
    feature_lookup: dict[str, dict[datetime, FeatureValue]] = {}
    for field_id in required_features:
        series = compute_feature_series(field_id, bars)
        feature_lookup[field_id] = {fv.timestamp: fv for fv in series}

    signals = []
    for bar in bars:
        feature_values = {
            fid: feature_lookup[fid][bar.timestamp]
            for fid in required_features
            if bar.timestamp in feature_lookup[fid]
        }
        signals.append(strategy.evaluate(bar, feature_values, strategy_config))

    trades: list[SimulatedTrade] = []
    open_position: _OpenPosition | None = None
    trade_counter = 0

    def _close_trade(
        exit_index: int, exit_timestamp: datetime, exit_price: Decimal, reason: str
    ) -> None:
        nonlocal trade_counter
        assert open_position is not None  # noqa: S101 - internal invariant, narrows for mypy
        quantity = open_position.quantity
        filled_exit = _apply_slippage(
            open_position.direction, exit_price, backtest_config.slippage_percent, entering=False
        )
        gross_pnl = _signed_gross_pnl(
            open_position.direction, open_position.entry_price, filled_exit, quantity
        )
        entry_notional = open_position.entry_price * quantity
        exit_notional = filled_exit * quantity
        costs = (entry_notional + exit_notional) * (
            backtest_config.brokerage_percent / Decimal("100")
        )
        net_pnl = gross_pnl - costs
        holding_bars = bars[open_position.entry_index : exit_index + 1]
        mfe, mae = _mfe_mae(open_position.direction, open_position.entry_price, holding_bars)
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
                costs=costs,
                net_pnl=net_pnl,
                reason=reason,
                mfe=mfe,
                mae=mae,
            )
        )

    running_equity = backtest_config.initial_capital

    for i, signal in enumerate(signals):
        is_last_bar = i == len(bars) - 1

        if open_position is None:
            if (
                signal is not None
                and signal.direction != StrategyDirection.NEUTRAL
                and not is_last_bar
            ):
                entry_bar = bars[i + 1]
                filled_entry = _apply_slippage(
                    signal.direction,
                    entry_bar.open,
                    backtest_config.slippage_percent,
                    entering=True,
                )
                quantity = _quantity_for(backtest_config, running_equity, filled_entry)
                if quantity > 0:
                    open_position = _OpenPosition(
                        direction=signal.direction,
                        entry_index=i + 1,
                        entry_timestamp=entry_bar.timestamp,
                        entry_price=filled_entry,
                        quantity=quantity,
                    )
        else:
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
    metrics = _compute_metrics(backtest_config, trades, equity_curve)

    return BacktestResult(
        backtest_id=_deterministic_backtest_id(backtest_config, bars),
        configuration=backtest_config,
        trades=tuple(trades),
        equity_curve=equity_curve,
        metrics=metrics,
        data_quality=data_quality,
        generated_at=generated_at,
    )


def _build_equity_curve(
    initial_capital: Decimal, trades: list[SimulatedTrade], start_timestamp: datetime
) -> tuple[EquityPoint, ...]:
    """Part 7: derived from the trade ledger, never invented. Sampled at
    each trade-close event (realized P&L only) plus a starting point -
    this engine does NOT mark open positions to market between bars
    (documented POC limitation, `docs/architecture/BACKTESTING_ARCHITECTURE.md`)."""
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


def _compute_metrics(
    config: BacktestConfiguration,
    trades: list[SimulatedTrade],
    equity_curve: tuple[EquityPoint, ...],
) -> BacktestMetrics:
    total = len(trades)
    winners = [t for t in trades if t.net_pnl > 0]
    losers = [t for t in trades if t.net_pnl < 0]
    gross_profit = sum((t.net_pnl for t in winners), Decimal("0"))
    gross_loss = sum((t.net_pnl for t in losers), Decimal("0"))
    net_pnl = sum((t.net_pnl for t in trades), Decimal("0"))
    win_rate = (Decimal(len(winners)) / total * 100) if total else Decimal("0")
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss != 0 else None
    max_drawdown = max((p.drawdown for p in equity_curve), default=Decimal("0"))
    max_drawdown_percent = max((p.drawdown_percent for p in equity_curve), default=Decimal("0"))
    average_trade = (net_pnl / total) if total else Decimal("0")
    average_winner = (gross_profit / len(winners)) if winners else None
    average_loser = (gross_loss / len(losers)) if losers else None

    sharpe: Decimal | None = None
    sortino: Decimal | None = None
    if total >= 2:
        returns = [
            (t.net_pnl / (t.entry_price * t.quantity))
            if t.entry_price * t.quantity != 0
            else Decimal("0")
            for t in trades
        ]
        mean_return = sum(returns, Decimal("0")) / total
        variance = sum(((r - mean_return) ** 2 for r in returns), Decimal("0")) / (total - 1)
        std_dev = variance.sqrt() if variance > 0 else Decimal("0")
        if std_dev > 0:
            sharpe = mean_return / std_dev
        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_variance = sum((r**2 for r in downside_returns), Decimal("0")) / len(
                downside_returns
            )
            downside_dev = downside_variance.sqrt()
            if downside_dev > 0:
                sortino = mean_return / downside_dev

    final_capital = equity_curve[-1].balance if equity_curve else config.initial_capital
    return_percent = (
        (final_capital - config.initial_capital) / config.initial_capital * 100
        if config.initial_capital > 0
        else Decimal("0")
    )

    return BacktestMetrics(
        total_trades=total,
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate_percent=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        max_drawdown_percent=max_drawdown_percent,
        average_trade=average_trade,
        average_winner=average_winner,
        average_loser=average_loser,
        sharpe_ratio_trade_level=sharpe,
        sortino_ratio_trade_level=sortino,
        final_capital=final_capital,
        return_percent=return_percent,
    )
