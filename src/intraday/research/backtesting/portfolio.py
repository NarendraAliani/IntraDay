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
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits
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
    CostModelIdentity,
    DataQualityDisclosure,
    MarkToMarketPoint,
    PositionSizingMode,
    SimulatedTrade,
)
from intraday.research.backtesting.cost_model import (
    CostModel,
    FlatPercentageCostModel,
    IndianCashEquityIntradayCostModel,
)
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
from intraday.research.backtesting.order_intent_adapter import (
    build_backtest_entry_order_intent,
)
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

# Checkpoint 64.34: same honest "no configured cap" sentinel `engine.py`
# uses for `max_total_exposure` (Checkpoint 64.30) - `RiskEvaluationContext`
# requires A value, and neither engine tracks a configured total-exposure
# limit today, so `Decimal("Infinity")` means "never reject on this
# dimension," not a fabricated number.
_UNCONSTRAINED_TOTAL_EXPOSURE = Decimal("Infinity")


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
    risk_limits: RiskLimits | None = None
    """Checkpoint 64.34: OPT-IN canonical risk gate, mirroring
    `BacktestConfiguration.risk_limits` (Checkpoint 64.30) exactly - same
    type, same default. `None` (the default, and every pre-64.34 caller's
    configuration) means the risk gate is never invoked and this
    checkpoint's entire block is skipped: numerically byte-identical to
    64.33 behavior. When set, the SAME canonical `evaluate_order_risk()`
    (via `risk_gate_adapter.evaluate_backtest_entry_risk()`) that
    `run_backtest()` already uses evaluates every accepted-so-far entry
    candidate, for every instrument - never a portfolio-specific risk
    policy or a second `RiskLimits`-shaped type."""

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
    insufficient available cash (Part 8's own invariant) - UNCHANGED by
    Checkpoint 64.34: a canonical-risk-gate rejection is counted
    separately below, never folded into this pre-existing counter, so
    every pre-64.34 caller reading this field sees byte-identical
    numbers when `risk_limits` stays `None`."""
    data_quality: DataQualityDisclosure
    cost_model_identity: CostModelIdentity
    generated_at: datetime
    trust_level: BacktestTrustLevel = BacktestTrustLevel.POC
    risk_rejected_entries: int = 0
    """Checkpoint 64.34: entry candidates that passed BOTH the
    `max_concurrent_positions` cap AND the capital/notional check above
    (i.e. would otherwise have opened a position) but were rejected by
    the canonical `evaluate_order_risk()` because `PortfolioBacktest
    Configuration.risk_limits` was configured. Always `0` when
    `risk_limits` is `None` - mirrors `BacktestResult.risk_rejected_
    trades` (Checkpoint 64.30) exactly, just named for portfolio
    "entries" rather than single-instrument "trades"."""
    risk_rejection_reason_breakdown: dict[str, int] = field(default_factory=dict)
    """Checkpoint 64.34: count of risk-rejected entries per
    `RiskRejectionReason.value`, across every instrument - counted from
    the real `OrderRiskDecision`, never estimated. Empty when
    `risk_limits` is `None`. Mirrors `BacktestResult.risk_rejection_
    reason_breakdown` (Checkpoint 64.30)."""


def _deterministic_portfolio_id(
    config: PortfolioBacktestConfiguration, bar_counts: tuple[int, ...], cost_model: CostModel
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
            cost_model.name,
            cost_model.version,
            cost_model.effective_from.isoformat(),
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

    costs: CostModel
    if cost_model is not None:
        costs = cost_model
    else:
        costs = FlatPercentageCostModel(config.brokerage_percent, config.slippage_percent)
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
    # Checkpoint 64.34: distinct from `rejected_entries` above (unrelated
    # pre-existing cause: max_concurrent_positions cap or insufficient
    # cash). Always stay 0/empty when `config.risk_limits is None` - the
    # entry branch below never touches these in that case, mirroring
    # `engine.py`'s `risk_rejected_trades`/`risk_rejection_reason_
    # breakdown` (Checkpoint 64.30) exactly.
    risk_rejected_entries = 0
    risk_rejection_reason_breakdown: dict[str, int] = {}
    # Checkpoint 64.34: running total of `SimulatedTrade.net_pnl` for
    # every trade CLOSED so far across ALL instruments - the portfolio-
    # level equivalent of `engine.py`'s `running_equity -
    # initial_capital`. Updated only in `_close()`, alongside
    # `available_cash`, so it is always the honest sum of realized P&L at
    # the moment any entry decision is evaluated.
    cumulative_realized_net_pnl = Decimal("0")

    def _close(
        instrument_id: InstrumentId,
        assignment: InstrumentAssignment,
        exit_index: int,
        exit_timestamp: datetime,
        exit_price: Decimal,
        reason: str,
    ) -> None:
        nonlocal available_cash, trade_counter, cumulative_realized_net_pnl
        position = open_positions[instrument_id]
        quantity = position.quantity
        filled_exit = costs.slippage_adjusted_price(position.direction, exit_price, entering=False)
        gross_pnl = signed_gross_pnl(
            position.direction, position.entry_price, filled_exit, quantity
        )
        entry_notional = position.entry_price * quantity
        exit_notional = filled_exit * quantity
        entry_is_buy = position.direction == StrategyDirection.BULLISH
        exit_is_buy = not entry_is_buy
        breakdown = costs.cost_breakdown(is_buy=entry_is_buy, notional=entry_notional).combine(
            costs.cost_breakdown(is_buy=exit_is_buy, notional=exit_notional)
        )
        trade_costs = breakdown.total
        net_pnl = gross_pnl - trade_costs
        bars = bars_by_instrument[instrument_id]
        holding_bars = bars[position.entry_index : exit_index + 1]
        mfe, mae = mfe_mae(position.direction, position.entry_price, holding_bars)
        trade_counter += 1
        # Checkpoint 64.33: the SAME `BacktestPosition` carried on
        # `position.position_lifecycle` throughout this instrument's own
        # position life, advanced to its terminal CLOSED state here -
        # never a second, independently-constructed lifecycle object,
        # exactly mirroring `engine.py`'s own `_close_trade()` pattern
        # from 64.32. `None` only in the theoretical direct-construction
        # case described on `OpenPosition.position_lifecycle`'s docstring.
        closed_lifecycle = (
            close_backtest_position(position.position_lifecycle)
            if position.position_lifecycle is not None
            else None
        )
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
                cost_breakdown=breakdown,
                # Checkpoint 64.33: carried verbatim from the
                # `OpenPosition` this trade closes out - the SAME
                # `OrderIntent` constructed at this instrument's own
                # entry time, never a second construction.
                order_intent=position.order_intent,
                # Checkpoint 64.33: the terminal CLOSED lifecycle derived
                # above from this same trade's own
                # `position.position_lifecycle`.
                position_lifecycle=closed_lifecycle,
            )
        )
        trade_intervals_by_instrument[instrument_id].append((position.entry_index, exit_index))
        # Capital accounting (Part 8): release the committed notional and
        # apply realized net P&L - cash was reduced by entry_notional at
        # entry, so this restores it plus/minus the trade's own outcome.
        available_cash += entry_notional + net_pnl
        cumulative_realized_net_pnl += net_pnl
        del open_positions[instrument_id]

    for i in range(n_bars):
        is_last_bar = i == n_bars - 1
        for assignment in assignments:
            instrument_id = assignment.instrument_id
            bars = bars_by_instrument[instrument_id]
            signal = signals_by_instrument[instrument_id][i]

            # Checkpoint 64.33: purely a REFLECTION of this instrument's
            # own already-open position state - mirrors `engine.py`'s
            # 64.32 HELD guard exactly, just evaluated per-instrument
            # instead of for one global position. A position still open
            # strictly past its own entry bar has, by definition,
            # survived at least one full bar with no exit, so its own
            # canonical lifecycle (never shared with any other
            # instrument's lifecycle object) is advanced OPEN -> HELD
            # here. O(1), runs only while still OPEN. No exit decision is
            # made or influenced by this - the existing `should_exit`/
            # `is_last_bar` logic below is entirely unchanged and still
            # solely authoritative.
            existing_position = open_positions.get(instrument_id)
            if (
                existing_position is not None
                and existing_position.position_lifecycle is not None
                and i > existing_position.entry_index
                and existing_position.position_lifecycle.lifecycle_status
                is BacktestPositionLifecycleStatus.OPEN
            ):
                existing_position.position_lifecycle = hold_backtest_position(
                    existing_position.position_lifecycle
                )

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
                    # Checkpoint 64.33: the REAL canonical `OrderIntent`
                    # (the SAME `order_intent_adapter.
                    # build_backtest_entry_order_intent()` used by
                    # `run_backtest()` since 64.31 - never a
                    # "portfolio_order_intent" or parallel construction),
                    # built once here per accepted entry and reused
                    # verbatim below on both `OpenPosition` and (via
                    # `_close`) `SimulatedTrade`. Checkpoint 64.34: also
                    # the SAME `OrderIntent` object fed to the risk gate
                    # below when `config.risk_limits` is configured -
                    # `entry_order` is constructed exactly once here,
                    # before the cash is committed, so a risk rejection
                    # never needs to "undo" a capital deduction.
                    entry_order = build_backtest_entry_order_intent(
                        strategy_id=assignment.strategy_id,
                        instrument_id=instrument_id,
                        direction=signal.direction,
                        quantity=quantity,
                        entry_timestamp=entry_bar.timestamp,
                        entry_index=i + 1,
                    )
                    # Checkpoint 64.34: OPT-IN canonical risk gate,
                    # evaluated AFTER the pre-existing portfolio-level
                    # constraints above (max_concurrent_positions cap,
                    # capital/notional check) have already passed - those
                    # remain portfolio execution constraints, not part of
                    # the canonical risk policy, and their ordering/
                    # semantics are entirely unchanged from 64.33. When
                    # `config.risk_limits is None` (the default, and every
                    # pre-64.34 caller's configuration), this whole block
                    # is skipped: `entry_risk_approved` stays `True` and
                    # nothing below differs from 64.33 - same
                    # `OpenPosition`, same cash deduction, same branch
                    # taken. Mirrors `engine.py`'s 64.30 wiring exactly,
                    # with two portfolio-specific, honestly-computed
                    # inputs `engine.py`'s single-position engine could
                    # only ever hardcode to 0: `current_open_positions_
                    # count` (this instrument's own entry does not yet
                    # count) and `current_total_exposure` (the real sum of
                    # every OTHER instrument's currently open notional).
                    entry_risk_approved = True
                    if config.risk_limits is not None:
                        current_total_exposure = sum(
                            (p.entry_price * p.quantity for p in open_positions.values()),
                            start=Decimal("0"),
                        )
                        risk_inputs = BacktestRiskGateInputs(
                            risk_limits=config.risk_limits,
                            risk_configuration_version=assignment.configuration_version,
                            now=entry_bar.timestamp,
                            # Cost-inclusive, matching `SimulatedTrade.
                            # net_pnl`'s own convention - see
                            # `risk_gate_adapter.py`'s header docstring.
                            # Portfolio-level: summed across ALL
                            # instruments' closed trades, the honest
                            # multi-instrument equivalent of `engine.py`'s
                            # single-instrument `running_equity -
                            # initial_capital`.
                            cumulative_closed_trade_net_pnl=cumulative_realized_net_pnl,
                            # Honest and genuinely multi-instrument-aware:
                            # how many OTHER instruments already have an
                            # open position right now (this instrument's
                            # own entry, evaluated here, is not yet
                            # counted - it is not open until approved).
                            current_open_positions_count=len(open_positions),
                            current_position_size_for_instrument=Decimal("0"),
                            estimated_order_notional=notional,
                            max_concurrent_positions=config.max_concurrent_positions,
                            max_total_exposure=_UNCONSTRAINED_TOTAL_EXPOSURE,
                            current_total_exposure=current_total_exposure,
                        )
                        risk_decision = evaluate_backtest_entry_risk(entry_order, risk_inputs)
                        if risk_decision.outcome is RiskDecisionOutcome.REJECTED:
                            entry_risk_approved = False
                            risk_rejected_entries += 1
                            reason = (
                                risk_decision.reason_code.value
                                if risk_decision.reason_code is not None
                                else "UNKNOWN"
                            )
                            risk_rejection_reason_breakdown[reason] = (
                                risk_rejection_reason_breakdown.get(reason, 0) + 1
                            )
                    if not entry_risk_approved:
                        continue
                    # Capital is committed only for an entry that has
                    # passed BOTH the pre-existing portfolio constraints
                    # AND (when configured) the canonical risk gate -
                    # never deducted for a risk-rejected candidate.
                    available_cash -= notional
                    open_positions[instrument_id] = OpenPosition(
                        instrument_id=instrument_id,
                        direction=signal.direction,
                        entry_index=i + 1,
                        entry_timestamp=entry_bar.timestamp,
                        entry_price=filled_entry,
                        quantity=quantity,
                        # Checkpoint 64.33: the SAME `OrderIntent`
                        # constructed immediately above - never a second
                        # construction.
                        order_intent=entry_order,
                        # Checkpoint 64.33: the real canonical position
                        # lifecycle for THIS instrument's position - always
                        # starts OPEN, per `open_backtest_position()`'s own
                        # contract. `position_id` reuses the SAME
                        # `entry_order.order_id` already constructed above
                        # (never a second, independent ID) - and, because
                        # 64.33 additionally qualified `order_id` with
                        # `instrument_id` (see `order_intent_adapter.py`),
                        # this `position_id` is guaranteed distinct across
                        # every other instrument's own position, even
                        # under "same strategy -> multiple instruments".
                        position_lifecycle=open_backtest_position(
                            position_id=entry_order.order_id,
                            direction=signal.direction,
                            quantity=quantity,
                            entry_price=filled_entry,
                            entry_timestamp=entry_bar.timestamp,
                        ),
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
        portfolio_id=_deterministic_portfolio_id(config, bar_counts, costs),
        configuration=config,
        trades=tuple(trades),
        mark_to_market_curve=mtm_curve,
        metrics=metrics,
        per_instrument_trade_counts=per_instrument_trade_counts,
        rejected_entries=rejected_entries,
        data_quality=data_quality,
        cost_model_identity=CostModelIdentity(
            name=costs.name,
            version=costs.version,
            effective_from=costs.effective_from,
            is_verified=isinstance(costs, IndianCashEquityIntradayCostModel),
        ),
        generated_at=generated_at,
        trust_level=BacktestTrustLevel.POC,
        risk_rejected_entries=risk_rejected_entries,
        risk_rejection_reason_breakdown=risk_rejection_reason_breakdown,
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
