# File: src/intraday/research/backtesting/portfolio.py
#
# Checkpoint 28 Part 7/8/9: multi-instrument portfolio backtesting -
# built ON TOP OF the single-instrument primitives (`execution.py`,
# `cost_model.py`, `metrics.py`), never a re-implementation. The
# single-instrument `engine.run_backtest()` is completely unchanged and
# still the correct choice when `max_concurrent_positions == 1` (Part 7:
# "must preserve the current behavior").
#
# SCOPE (explicit, not hidden): every instrument in one portfolio run
# must share the SAME bar timestamps (same timeframe, same aligned
# session) - the engine validates this and raises rather than silently
# guessing an alignment. This is a documented POC simplification, not a
# general multi-timeframe/multi-session portfolio engine.
#
# CAPITAL ACCOUNTING (Part 8, explicit invariants, enforced not assumed):
#   - `available_cash` only ever decreases by an entry's own notional
#     value and increases by an exit's own (notional - costs).
#   - An entry is REJECTED (never partially filled, never allowed to
#     drive cash negative) if its notional exceeds `available_cash`.
#   - An entry is REJECTED if `max_concurrent_positions` open positions
#     already exist, regardless of available cash.
#   - No instrument may hold two simultaneous open positions (Part 8:
#     "no duplicate position for the same instrument").
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.research.backtesting import (
    Strategy,
    StrategyConfigurationValues,
    StrategyDirection,
    StrategySignal,
)
from intraday.research.backtesting.contracts import (
    BacktestMetrics,
    BacktestTrustLevel,
    DataQualityDisclosure,
    MarkToMarketPoint,
    PositionSizingMode,
    SimulatedTrade,
)
from intraday.research.backtesting.cost_model import CostModel, FlatPercentageCostModel
from intraday.research.backtesting.errors import InvalidBacktestConfigurationError
from intraday.research.backtesting.execution import (
    FeatureSeriesComputer,
    OpenPosition,
    compute_signals,
    mfe_mae,
    quantity_for,
    signed_gross_pnl,
)
from intraday.research.backtesting.metrics import compute_metrics


@dataclass(frozen=True, slots=True)
class InstrumentAssignment:
    """One instrument -> strategy pairing within a portfolio (Part 9:
    "Strategy A -> RELIANCE, Strategy B -> TCS" and "same strategy ->
    multiple instruments" are both expressed as a list of these)."""

    instrument_id: InstrumentId
    strategy_id: str
    specification_version: str
    code_version: str
    configuration_version: str
    strategy_values: dict[str, object]


@dataclass(frozen=True, slots=True)
class PortfolioBacktestConfiguration:
    assignments: tuple[InstrumentAssignment, ...]
    timeframe: Timeframe
    start: datetime
    end: datetime
    initial_capital: Decimal
    position_sizing_mode: PositionSizingMode
    position_size_value: Decimal
    max_concurrent_positions: int
    brokerage_percent: Decimal = Decimal("0")
    slippage_percent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.assignments:
            raise InvalidBacktestConfigurationError("portfolio requires at least one assignment")
        instrument_ids = [a.instrument_id for a in self.assignments]
        if len(instrument_ids) != len(set(instrument_ids)):
            raise InvalidBacktestConfigurationError(
                "duplicate instrument_id in portfolio assignments - one position per "
                "instrument is supported, not multiple simultaneous strategies on the "
                "same instrument"
            )
        if self.initial_capital <= 0:
            raise InvalidBacktestConfigurationError("initial_capital must be positive")
        if self.position_size_value <= 0:
            raise InvalidBacktestConfigurationError("position_size_value must be positive")
        if self.max_concurrent_positions < 1:
            raise InvalidBacktestConfigurationError("max_concurrent_positions must be at least 1")
        if self.max_concurrent_positions > len(self.assignments):
            raise InvalidBacktestConfigurationError(
                "max_concurrent_positions cannot exceed the number of instruments assigned"
            )
        if self.brokerage_percent < 0 or self.slippage_percent < 0:
            raise InvalidBacktestConfigurationError("costs must not be negative")


@dataclass(frozen=True, slots=True)
class PortfolioBacktestResult:
    portfolio_id: str
    configuration: PortfolioBacktestConfiguration
    trades: tuple[SimulatedTrade, ...]
    """Every trade carries its own strategy/instrument attribution
    (`SimulatedTrade` is reused unchanged - no second trade type)."""
    mark_to_market_curve: tuple[MarkToMarketPoint, ...]
    """Portfolio-level aggregate - realized/unrealized summed across
    every instrument's open/closed positions."""
    metrics: BacktestMetrics
    """The SAME `BacktestMetrics` shape single-instrument results use -
    no second metrics type for the portfolio case."""
    per_instrument_trade_counts: dict[str, int]
    rejected_entries: int
    """Entries rejected by either the max_concurrent_positions cap or
    insufficient available cash (Part 8's own invariant)."""
    data_quality: DataQualityDisclosure
    generated_at: datetime
    trust_level: BacktestTrustLevel = BacktestTrustLevel.POC


def _deterministic_portfolio_id(
    config: PortfolioBacktestConfiguration, bar_counts: tuple[int, ...]
) -> str:
    payload = "|".join(
        [
            "|".join(
                f"{a.instrument_id}:{a.strategy_id}:{a.specification_version}:"
                f"{a.code_version}:{a.configuration_version}"
                for a in config.assignments
            ),
            config.timeframe.value,
            config.start.isoformat(),
            config.end.isoformat(),
            str(config.initial_capital),
            config.position_sizing_mode.value,
            str(config.position_size_value),
            str(config.max_concurrent_positions),
            str(config.brokerage_percent),
            str(config.slippage_percent),
            ",".join(str(c) for c in bar_counts),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def run_portfolio_backtest(
    bars_by_instrument: dict[InstrumentId, tuple[Bar, ...]],
    strategies_by_instrument: dict[InstrumentId, Strategy],
    config: PortfolioBacktestConfiguration,
    compute_feature_series: FeatureSeriesComputer,
    *,
    data_quality: DataQualityDisclosure,
    generated_at: datetime,
    cost_model: CostModel | None = None,
) -> PortfolioBacktestResult:
    assignments = config.assignments
    for assignment in assignments:
        if assignment.instrument_id not in bars_by_instrument:
            raise InvalidBacktestConfigurationError(
                f"no bars supplied for assigned instrument {assignment.instrument_id!r}"
            )
        if assignment.instrument_id not in strategies_by_instrument:
            raise InvalidBacktestConfigurationError(
                f"no strategy supplied for assigned instrument {assignment.instrument_id!r}"
            )

    bar_series = [bars_by_instrument[a.instrument_id] for a in assignments]
    bar_counts = tuple(len(b) for b in bar_series)
    if len(set(bar_counts)) != 1 or bar_counts[0] == 0:
        raise InvalidBacktestConfigurationError(
            "portfolio backtesting requires every assigned instrument to supply the same "
            "non-zero number of bars, aligned by timestamp (documented POC scope)"
        )
    timestamps_by_index = list(
        zip(*[[b.timestamp for b in series] for series in bar_series], strict=True)
    )
    for index, group in enumerate(timestamps_by_index):
        if len(set(group)) != 1:
            raise InvalidBacktestConfigurationError(
                f"bar timestamps diverge across instruments at index {index} - portfolio "
                "backtesting requires bar-for-bar aligned timestamps"
            )

    costs = cost_model or FlatPercentageCostModel(config.brokerage_percent, config.slippage_percent)
    n_bars = bar_counts[0]

    signals_by_instrument: dict[InstrumentId, list[StrategySignal | None]] = {}
    for assignment in assignments:
        bars = bars_by_instrument[assignment.instrument_id]
        strategy = strategies_by_instrument[assignment.instrument_id]
        strategy_config = StrategyConfigurationValues(
            strategy_id=assignment.strategy_id,
            specification_version=assignment.specification_version,
            code_version=assignment.code_version,
            configuration_version=assignment.configuration_version,
            values=assignment.strategy_values,
        )
        signals, _warmup, _count = compute_signals(
            bars, strategy, strategy_config, compute_feature_series
        )
        signals_by_instrument[assignment.instrument_id] = signals

    available_cash = config.initial_capital
    open_positions: dict[InstrumentId, OpenPosition] = {}
    trade_intervals_by_instrument: dict[InstrumentId, list[tuple[int, int]]] = {
        a.instrument_id: [] for a in assignments
    }
    trades: list[SimulatedTrade] = []
    trade_counter = 0
    rejected_entries = 0

    def _close(
        instrument_id: InstrumentId,
        assignment: InstrumentAssignment,
        exit_index: int,
        exit_timestamp: datetime,
        exit_price: Decimal,
        reason: str,
    ) -> None:
        nonlocal available_cash, trade_counter
        position = open_positions[instrument_id]
        quantity = position.quantity
        filled_exit = costs.slippage_adjusted_price(position.direction, exit_price, entering=False)
        gross_pnl = signed_gross_pnl(
            position.direction, position.entry_price, filled_exit, quantity
        )
        entry_notional = position.entry_price * quantity
        exit_notional = filled_exit * quantity
        trade_costs = costs.brokerage(entry_notional) + costs.brokerage(exit_notional)
        net_pnl = gross_pnl - trade_costs
        bars = bars_by_instrument[instrument_id]
        holding_bars = bars[position.entry_index : exit_index + 1]
        mfe, mae = mfe_mae(position.direction, position.entry_price, holding_bars)
        trade_counter += 1
        trades.append(
            SimulatedTrade(
                trade_id=f"{assignment.strategy_id}-{instrument_id}-{trade_counter}",
                strategy_id=assignment.strategy_id,
                specification_version=assignment.specification_version,
                code_version=assignment.code_version,
                configuration_version=assignment.configuration_version,
                instrument_id=instrument_id,
                timeframe=config.timeframe,
                direction=position.direction,
                entry_timestamp=position.entry_timestamp,
                entry_price=position.entry_price,
                exit_timestamp=exit_timestamp,
                exit_price=filled_exit,
                quantity=quantity,
                gross_pnl=gross_pnl,
                costs=trade_costs,
                net_pnl=net_pnl,
                reason=reason,
                mfe=mfe,
                mae=mae,
            )
        )
        trade_intervals_by_instrument[instrument_id].append((position.entry_index, exit_index))
        # Capital accounting (Part 8): release the committed notional and
        # apply realized net P&L - cash was reduced by entry_notional at
        # entry, so this restores it plus/minus the trade's own outcome.
        available_cash += entry_notional + net_pnl
        del open_positions[instrument_id]

    for i in range(n_bars):
        is_last_bar = i == n_bars - 1
        for assignment in assignments:
            instrument_id = assignment.instrument_id
            bars = bars_by_instrument[instrument_id]
            signal = signals_by_instrument[instrument_id][i]

            if instrument_id not in open_positions:
                if (
                    signal is not None
                    and signal.direction != StrategyDirection.NEUTRAL
                    and not is_last_bar
                ):
                    if len(open_positions) >= config.max_concurrent_positions:
                        rejected_entries += 1
                        continue
                    entry_bar = bars[i + 1]
                    filled_entry = costs.slippage_adjusted_price(
                        signal.direction, entry_bar.open, entering=True
                    )
                    quantity = quantity_for(
                        config.position_sizing_mode,
                        config.position_size_value,
                        available_cash,
                        filled_entry,
                    )
                    notional = filled_entry * quantity
                    if quantity <= 0 or notional > available_cash:
                        rejected_entries += 1
                        continue
                    available_cash -= notional
                    open_positions[instrument_id] = OpenPosition(
                        instrument_id=instrument_id,
                        direction=signal.direction,
                        entry_index=i + 1,
                        entry_timestamp=entry_bar.timestamp,
                        entry_price=filled_entry,
                        quantity=quantity,
                    )
            else:
                position = open_positions[instrument_id]
                should_exit = (
                    signal is not None
                    and signal.direction != position.direction
                    and not is_last_bar
                )
                if should_exit:
                    exit_bar = bars[i + 1]
                    _close(
                        instrument_id,
                        assignment,
                        i + 1,
                        exit_bar.timestamp,
                        exit_bar.open,
                        "signal_reversal",
                    )
                elif is_last_bar:
                    _close(
                        instrument_id,
                        assignment,
                        i,
                        bars[i].timestamp,
                        bars[i].close,
                        "end_of_data",
                    )

    reference_bars = bar_series[0]
    mtm_curve = _build_portfolio_mtm_curve(
        config.initial_capital,
        reference_bars,
        bars_by_instrument,
        trades,
        trade_intervals_by_instrument,
    )
    metrics = compute_metrics(config.initial_capital, trades, mtm_curve)

    per_instrument_trade_counts: dict[str, int] = {a.instrument_id: 0 for a in assignments}
    for trade in trades:
        per_instrument_trade_counts[trade.instrument_id] += 1

    return PortfolioBacktestResult(
        portfolio_id=_deterministic_portfolio_id(config, bar_counts),
        configuration=config,
        trades=tuple(trades),
        mark_to_market_curve=mtm_curve,
        metrics=metrics,
        per_instrument_trade_counts=per_instrument_trade_counts,
        rejected_entries=rejected_entries,
        data_quality=data_quality,
        generated_at=generated_at,
        trust_level=BacktestTrustLevel.POC,
    )


def _build_portfolio_mtm_curve(
    initial_capital: Decimal,
    reference_bars: tuple[Bar, ...],
    bars_by_instrument: dict[InstrumentId, tuple[Bar, ...]],
    trades: list[SimulatedTrade],
    trade_intervals_by_instrument: dict[InstrumentId, list[tuple[int, int]]],
) -> tuple[MarkToMarketPoint, ...]:
    points: list[MarkToMarketPoint] = []
    realized = Decimal("0")
    peak = initial_capital

    trades_by_instrument: dict[InstrumentId, list[SimulatedTrade]] = {}
    for trade in trades:
        trades_by_instrument.setdefault(trade.instrument_id, []).append(trade)

    trade_pointer: dict[InstrumentId, int] = dict.fromkeys(bars_by_instrument, 0)

    for i, ref_bar in enumerate(reference_bars):
        unrealized = Decimal("0")
        for instrument_id, intervals in trade_intervals_by_instrument.items():
            instrument_trades = trades_by_instrument.get(instrument_id, [])
            pointer = trade_pointer[instrument_id]
            while pointer < len(intervals) and intervals[pointer][1] <= i:
                realized += instrument_trades[pointer].net_pnl
                pointer += 1
            trade_pointer[instrument_id] = pointer
            if pointer < len(intervals):
                entry_index, exit_index = intervals[pointer]
                if entry_index <= i < exit_index:
                    trade = instrument_trades[pointer]
                    mark_bar = bars_by_instrument[instrument_id][i]
                    unrealized += signed_gross_pnl(
                        trade.direction, trade.entry_price, mark_bar.close, trade.quantity
                    )

        total_equity = initial_capital + realized + unrealized
        peak = max(peak, total_equity)
        drawdown = peak - total_equity
        drawdown_percent = (drawdown / peak * 100) if peak > 0 else Decimal("0")
        points.append(
            MarkToMarketPoint(
                timestamp=ref_bar.timestamp,
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                total_equity=total_equity,
                peak_equity=peak,
                drawdown=drawdown,
                drawdown_percent=drawdown_percent,
            )
        )
    return tuple(points)
