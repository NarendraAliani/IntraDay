# tests/unit/research/test_mark_to_market_accounting.py
#
# Checkpoint 64.26: proof-in-isolation test suite for the new, standalone
# `intraday.research.backtesting.mark_to_market` accounting model.
# `run_backtest()`/`run_stateful_backtest()`/`engine.py`/
# `historical_execution.py` are used here ONLY as read-only oracles for
# the regression comparison (never modified).
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.strategy_execution import (
    compute_feature_series as _compute_feature_series,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.position_exit.contracts import (
    ExitPlan,
    ExitReason,
    ManagedPosition,
    PositionLifecycleStatus,
)
from intraday.domain.position_exit.policy import evaluate_position_exit
from intraday.domain.shared_kernel.contracts import Exchange, OrderId, PositionId, Side, Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, StrategyDirection
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.cost_model import (
    CostModel,
    FlatPercentageCostModel,
    verified_nse_cash_equity_intraday_cost_model,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.mark_to_market import (
    EntryFill,
    ExitFill,
    MarkToMarketError,
    MarkToMarketLedger,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyParameterSchema
from intraday.trading_engine.strategy_execution.registry import build_default_registry

INSTRUMENT = "NSE:TESTCO"
RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


# --- A minimal, deterministic direction-flip strategy stub for the
# engine.py regression oracle. Signals exactly what the test tells it to,
# at the bar index the test wants, and nothing else - no
# `build_trade_plan` hook, so `engine.py` uses its direction-flip
# exit model (signal reversal / EOD), never the TradePlan/SL/T path.
@dataclass
class _StubSignal:
    direction: StrategyDirection


class _ScriptedStrategy:
    strategy_id = "scripted_stub"
    display_name = "Scripted Stub"
    specification_version = "v1"
    code_version = "v1"

    def __init__(self, signals_by_index: dict[int, StrategyDirection]) -> None:
        self._signals_by_index = signals_by_index
        self._index = -1

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(strategy_id=self.strategy_id, parameters=())

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        return ()

    def evaluate(self, bar: Bar, feature_values: dict, config: StrategyConfigurationValues):
        self._index += 1
        direction = self._signals_by_index.get(self._index)
        if direction is None:
            return None
        from intraday.trading_engine.strategy_execution.contracts import StrategySignal

        return StrategySignal(
            strategy_id=self.strategy_id,
            specification_version=self.specification_version,
            code_version=self.code_version,
            configuration_version="v1",
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            direction=direction,
            price=bar.close,
        )


def _bars_from_closes(closes: list[str]) -> tuple[Bar, ...]:
    """Flat-range bars: open=close of this bar (so entries/exits fill at
    an exact, test-controlled price), high/low padded so no stop/target
    machinery is ever implicated (this stub strategy has none anyway)."""
    bars = []
    for i, c in enumerate(closes):
        price = Decimal(c)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=BASE + timedelta(minutes=i),
                open=price,
                high=price + Decimal("5"),
                low=price - Decimal("5"),
                close=price,
                volume=Decimal("0"),
            )
        )
    return tuple(bars)


def _dq(bar_count: int) -> DataQualityDisclosure:
    return DataQualityDisclosure(
        data_source="fixture",
        data_quality=DataQualityLabel.FIXTURE_OR_HISTORICAL,
        bar_count=bar_count,
        missing_bar_note="none",
        transaction_cost_assumption="flat pct",
        slippage_assumption="flat pct",
        survivorship_bias_note="n/a",
    )


def _config(**overrides: object) -> BacktestConfiguration:
    defaults: dict[str, object] = {
        "instrument_id": INSTRUMENT,
        "timeframe": Timeframe.ONE_MINUTE,
        "start": BASE,
        "end": BASE + timedelta(minutes=40),
        "strategy_id": "scripted_stub",
        "specification_version": "v1",
        "code_version": "v1",
        "configuration_version": "v1",
        "initial_capital": Decimal("100000"),
        "position_sizing_mode": PositionSizingMode.FIXED_QUANTITY,
        "position_size_value": Decimal("10"),
        "brokerage_percent": Decimal("0"),
        "slippage_percent": Decimal("0"),
    }
    defaults.update(overrides)
    return BacktestConfiguration(**defaults)  # type: ignore[arg-type]


def _run_engine(
    closes: list[str],
    signals_by_index: dict[int, StrategyDirection],
    *,
    cost_model: CostModel | None = None,
) -> object:
    bars = _bars_from_closes(closes)
    strategy = _ScriptedStrategy(signals_by_index)
    result = run_backtest(
        bars,
        strategy,  # type: ignore[arg-type]
        StrategyConfigurationValues("scripted_stub", "v1", "v1", "v1", {}),
        _config(end=BASE + timedelta(minutes=len(closes) + 5)),
        lambda field_id, bars_: (),
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
        cost_model=cost_model,
    )
    return result


# =====================================================================
# Item 6: single-exit regression against engine.py (THE most important
# category). Same bars, same entry/exit prices/quantities, direct
# replication of the ledger's fills from the same fills the engine
# itself computed for its ONE trade, then compared field-for-field.
# =====================================================================


def _replicate_single_trade(result, *, cost_model: CostModel) -> tuple[Decimal, Decimal]:
    """Feeds the ledger the SAME entry/exit fill the engine's own single
    trade used, and returns (ledger_realized_pnl, ledger_equity_after_exit)."""
    assert len(result.trades) == 1
    trade = result.trades[0]
    entry_is_buy = trade.direction == StrategyDirection.BULLISH
    entry_notional = trade.entry_price * trade.quantity
    exit_notional = trade.exit_price * trade.quantity
    entry_cost = cost_model.cost_breakdown(is_buy=entry_is_buy, notional=entry_notional).total
    exit_cost = cost_model.cost_breakdown(is_buy=not entry_is_buy, notional=exit_notional).total

    ledger = MarkToMarketLedger(starting_cash=Decimal("100000"))
    pid = PositionId("regr-1")
    direction = Side.BUY if entry_is_buy else Side.SELL
    ledger.apply_entry_fill(
        EntryFill(
            pid, direction, trade.quantity, trade.entry_price, entry_cost, trade.entry_timestamp
        )
    )
    ledger.apply_exit_fill(
        ExitFill(pid, trade.quantity, trade.exit_price, exit_cost, trade.exit_timestamp)
    )
    state = ledger.position_state(pid)
    return state.realized_pnl, ledger.cash


@pytest.mark.parametrize(
    "scenario,closes,signals",
    [
        (
            "profit_signal_reversal",
            ["100", "100", "105", "105", "110"],
            {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH},
        ),
        (
            "loss_signal_reversal",
            ["100", "100", "95", "95", "90"],
            {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH},
        ),
        (
            "flat_signal_reversal",
            ["100", "100", "100", "100", "100"],
            {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH},
        ),
        (
            "profit_eod",
            ["100", "100", "105", "110", "115"],
            {0: StrategyDirection.BULLISH},
        ),
        (
            "loss_eod",
            ["100", "100", "95", "90", "85"],
            {0: StrategyDirection.BULLISH},
        ),
        (
            "short_profit_signal_reversal",
            ["100", "100", "95", "95", "90"],
            {0: StrategyDirection.BEARISH, 2: StrategyDirection.BULLISH},
        ),
        (
            "short_loss_eod",
            ["100", "100", "105", "110", "115"],
            {0: StrategyDirection.BEARISH},
        ),
    ],
)
def test_single_exit_regression_against_engine_zero_cost(scenario, closes, signals) -> None:
    cost_model = FlatPercentageCostModel(Decimal("0"), Decimal("0"))
    result = _run_engine(closes, signals, cost_model=cost_model)
    trade = result.trades[0]
    ledger_realized, ledger_cash_after_exit = _replicate_single_trade(result, cost_model=cost_model)

    assert ledger_realized == trade.net_pnl, f"{scenario}: realized_pnl mismatch"
    assert (
        ledger_cash_after_exit == Decimal("100000") + trade.net_pnl
    ), f"{scenario}: equity mismatch"
    assert result.metrics.net_pnl == trade.net_pnl


@pytest.mark.parametrize(
    "scenario,closes,signals",
    [
        (
            "profit_with_real_costs",
            ["100", "100", "105", "105", "110"],
            {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH},
        ),
        (
            "loss_with_real_costs",
            ["100", "100", "95", "95", "90"],
            {0: StrategyDirection.BULLISH, 2: StrategyDirection.BEARISH},
        ),
        (
            "eod_with_real_costs",
            ["100", "100", "105", "110", "115"],
            {0: StrategyDirection.BULLISH},
        ),
    ],
)
def test_single_exit_regression_against_engine_real_costs(scenario, closes, signals) -> None:
    cost_model = verified_nse_cash_equity_intraday_cost_model()
    result = _run_engine(closes, signals, cost_model=cost_model)
    trade = result.trades[0]
    ledger_realized, ledger_cash_after_exit = _replicate_single_trade(result, cost_model=cost_model)

    assert ledger_realized == trade.net_pnl, f"{scenario}: realized_pnl mismatch"
    assert (
        ledger_cash_after_exit == Decimal("100000") + trade.net_pnl
    ), f"{scenario}: equity mismatch"
    assert result.metrics.net_pnl == trade.net_pnl
    # Drawdown contribution: at the exit bar (position fully closed),
    # engine's own mtm total_equity must equal our ledger's equity too.
    exit_bar_index = None
    for i, bar in enumerate(_bars_from_closes(closes)):
        if bar.timestamp == trade.exit_timestamp:
            exit_bar_index = i
            break
    assert exit_bar_index is not None
    mtm_point = result.mark_to_market_curve[exit_bar_index]
    assert mtm_point.total_equity == ledger_cash_after_exit


# =====================================================================
# Checkpoint 64.27: ATR TradePlan single-exit regression against
# engine.py's own, unmodified TradePlan-exit path (`atr_volatility_
# breakout` via `tradeplan_execution.simulate_tradeplan_exit()`).
# 64.26 left this case unregressed - only direction-flip strategies were
# proven. This closes that gap: a real, deterministic ATR breakout
# (8 flat warm-up bars, a breakout bar, an entry bar, then a bar whose
# low drops far enough to touch the ATR stop-loss level and nothing
# else) drives `run_backtest()`'s real TradePlan branch to a single,
# full-close STOP_LOSS exit - confirmed by direct inspection of
# `engine.py` (§140-300) that the TradePlan branch ALWAYS closes the
# FULL position on the first level touched (`quantity =
# open_position.quantity` inside `_close_trade`, called once) - there
# is NO partial T1/T2/T3 exit support in `run_backtest()` today, only
# in the pure `MarkToMarketLedger`/hand-worked test above. That itself
# is an important, disclosed fact for future engine-integration
# planning, not merely incidental to this test's construction.
# =====================================================================

_ATR_INSTRUMENT = "NSE:TESTCO"


def _atr_bar(i: int, o: str, h: str, low: str, c: str) -> Bar:
    return Bar(
        instrument_id=_ATR_INSTRUMENT,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=BASE + timedelta(minutes=i + 1),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=Decimal("0"),
    )


def _atr_stop_loss_bars() -> tuple[Bar, ...]:
    """8 flat bars (ATR warm-up, lookback=5) -> a breakout bar (triggers
    a BULLISH signal) -> an entry bar (fills the entry at its OPEN,
    engine's own no-look-ahead rule) -> a bar whose LOW (100) drops well
    below the ATR-derived stop-loss (~109) and touches no target ->
    3 trailing flat bars so the sequence has a clean tail. Empirically
    verified (not hand-derived) to produce EXACTLY ONE trade, reason
    STOP_LOSS, entry=111, exit=106.80, quantity=10."""
    flat = [_atr_bar(i, "100", "101", "99", "100") for i in range(8)]
    breakout = _atr_bar(8, "100", "112", "99", "111")
    entry_bar = _atr_bar(9, "111", "113", "110", "112")
    stop_bar = _atr_bar(10, "110", "111", "100", "101")
    tail = [_atr_bar(11 + k, "101", "102", "100", "101") for k in range(3)]
    return (*flat, breakout, entry_bar, stop_bar, *tail)


def _atr_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "atr_volatility_breakout",
        "v1",
        "v1",
        "v1",
        {
            "lookback": 5,
            "atr_multiplier": Decimal("0.1"),
            "stop_loss_atr_multiplier": Decimal("1.0"),
            "target_1_atr_multiplier": Decimal("1.5"),
            "target_2_atr_multiplier": Decimal("2.5"),
            "target_3_atr_multiplier": Decimal("4.0"),
            "trailing_stop_atr_multiplier": Decimal("1.0"),
        },
    )


def _run_atr_engine(*, cost_model: CostModel) -> object:
    bars = _atr_stop_loss_bars()
    registry = build_default_registry()
    strategy = registry.get("atr_volatility_breakout")
    strategy_config = _atr_config()
    bt_config = _config(
        strategy_id="atr_volatility_breakout",
        end=BASE + timedelta(minutes=len(bars) + 5),
    )
    return run_backtest(
        bars,
        strategy,
        strategy_config,
        bt_config,
        _compute_feature_series,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
        cost_model=cost_model,
    )


def _replicate_atr_trade(trade, *, cost_model: CostModel) -> tuple[Decimal, Decimal]:
    entry_notional = trade.entry_price * trade.quantity
    exit_notional = trade.exit_price * trade.quantity
    entry_cost = cost_model.cost_breakdown(is_buy=True, notional=entry_notional).total
    exit_cost = cost_model.cost_breakdown(is_buy=False, notional=exit_notional).total

    ledger = MarkToMarketLedger(starting_cash=Decimal("100000"))
    pid = PositionId("atr-regr-1")
    ledger.apply_entry_fill(
        EntryFill(
            pid, Side.BUY, trade.quantity, trade.entry_price, entry_cost, trade.entry_timestamp
        )
    )
    ledger.apply_exit_fill(
        ExitFill(pid, trade.quantity, trade.exit_price, exit_cost, trade.exit_timestamp)
    )
    state = ledger.position_state(pid)
    return state.realized_pnl, ledger.cash


def test_atr_tradeplan_single_stop_loss_exit_regression_against_engine_zero_cost() -> None:
    cost_model = FlatPercentageCostModel(Decimal("0"), Decimal("0"))
    result = _run_atr_engine(cost_model=cost_model)

    assert len(result.trades) == 1, "bar sequence must produce exactly one ATR TradePlan trade"
    trade = result.trades[0]
    assert trade.reason == "STOP_LOSS"
    # engine's TradePlan path is FULL-CLOSE-ONLY today - confirmed by
    # direct code reading (see comment block above) - so this single
    # exit fill accounts for the ENTIRE quantity, no partial T1/T2/T3.
    assert trade.quantity == Decimal("10")

    ledger_realized, ledger_cash_after_exit = _replicate_atr_trade(trade, cost_model=cost_model)

    assert ledger_realized == trade.net_pnl, "ATR stop-loss realized_pnl mismatch"
    assert ledger_cash_after_exit == Decimal("100000") + trade.net_pnl
    assert result.metrics.net_pnl == trade.net_pnl


def test_atr_tradeplan_single_stop_loss_exit_regression_against_engine_real_costs() -> None:
    cost_model = verified_nse_cash_equity_intraday_cost_model()
    result = _run_atr_engine(cost_model=cost_model)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.reason == "STOP_LOSS"
    assert trade.quantity == Decimal("10")

    ledger_realized, ledger_cash_after_exit = _replicate_atr_trade(trade, cost_model=cost_model)

    # No discrepancy found: the ATR TradePlan single-exit (full-close)
    # case matches engine.py's net_pnl exactly, empirically verified -
    # same as the 10 direction-flip scenarios 64.26 already proved.
    assert ledger_realized == trade.net_pnl, "ATR stop-loss realized_pnl mismatch (real costs)"
    assert ledger_cash_after_exit == Decimal("100000") + trade.net_pnl
    assert result.metrics.net_pnl == trade.net_pnl

    exit_bar_index = None
    for i, bar in enumerate(_atr_stop_loss_bars()):
        if bar.timestamp == trade.exit_timestamp:
            exit_bar_index = i
            break
    assert exit_bar_index is not None
    mtm_point = result.mark_to_market_curve[exit_bar_index]
    assert mtm_point.total_equity == ledger_cash_after_exit


# =====================================================================
# Item 7: hand-worked 12-share T1/T2/T3 example with REAL costs.
# =====================================================================


def test_hand_worked_12_share_t1_t2_t3_example() -> None:
    """12 shares entry @ 100. T1 sells 4 @ 110 (1/3 of 12). T2 sells 2 @
    115 (1/3 of remaining 8). T3 sells 6 @ 120 (all remaining). Real
    costs from `IndianCashEquityIntradayCostModel` (verified schedule).

    Hand-computed cost breakdown (via the actual cost model, computed
    once and pinned here - see this checkpoint's report for how these
    numbers were derived):
        entry (buy,  12@100=1200): total cost = 0.51
        T1    (sell,  4@110= 440): total cost = 0.28
        T2    (sell,  2@115= 230): total cost = 0.15
        T3    (sell,  6@120= 720): total cost = 0.46
        sum of all four legs' costs = 0.51+0.28+0.15+0.46 = 1.40
    """
    cm = verified_nse_cash_equity_intraday_cost_model()
    entry_notional = Decimal("12") * Decimal("100")
    entry_cost = cm.cost_breakdown(is_buy=True, notional=entry_notional).total
    t1_notional = Decimal("4") * Decimal("110")
    t1_cost = cm.cost_breakdown(is_buy=False, notional=t1_notional).total
    t2_notional = Decimal("2") * Decimal("115")
    t2_cost = cm.cost_breakdown(is_buy=False, notional=t2_notional).total
    t3_notional = Decimal("6") * Decimal("120")
    t3_cost = cm.cost_breakdown(is_buy=False, notional=t3_notional).total

    assert entry_cost == Decimal("0.51")
    assert t1_cost == Decimal("0.28")
    assert t2_cost == Decimal("0.15")
    assert t3_cost == Decimal("0.46")

    starting_cash = Decimal("100000")
    ledger = MarkToMarketLedger(starting_cash)
    pid = PositionId("hand-worked-1")
    t0 = BASE

    ledger.apply_entry_fill(EntryFill(pid, Side.BUY, Decimal("12"), Decimal("100"), entry_cost, t0))
    # cash = 100000 - (1200 + 0.51) = 98799.49
    assert ledger.cash == starting_cash - Decimal("1200.51")

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("4"), Decimal("110"), t1_cost, t0 + timedelta(minutes=1))
    )
    # T1 price P&L = 4 * (110-100) = 40
    # T1 allocated entry cost = 0.51 * 4/12 = 0.17
    # T1 realized = 40 - 0.28 - 0.17 = 39.55
    # cash += (4*110 - 0.28) = += 439.72 -> cash = 98799.49 + 439.72 = 99239.21
    state = ledger.position_state(pid)
    assert state.realized_pnl == Decimal("39.55")
    assert state.remaining_quantity == Decimal("8")
    assert state.entry_cost_allocated == Decimal("0.17")
    assert ledger.cash == Decimal("99239.21")

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("2"), Decimal("115"), t2_cost, t0 + timedelta(minutes=2))
    )
    # T2 price P&L = 2 * (115-100) = 30
    # T2 allocated entry cost = 0.51 * 2/12 = 0.085
    # T2 realized = 30 - 0.15 - 0.085 = 29.765
    # cumulative realized = 39.55 + 29.765 = 69.315
    # cash += (2*115 - 0.15) = += 229.85 -> cash = 99239.21 + 229.85 = 99469.06
    state = ledger.position_state(pid)
    assert state.realized_pnl == Decimal("39.55") + Decimal("29.765")
    assert state.remaining_quantity == Decimal("6")
    assert state.entry_cost_allocated == Decimal("0.17") + Decimal("0.085")
    assert ledger.cash == Decimal("99469.06")

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("6"), Decimal("120"), t3_cost, t0 + timedelta(minutes=3))
    )
    # T3 price P&L = 6 * (120-100) = 120
    # T3 allocated entry cost = 0.51 * 6/12 = 0.255
    # T3 realized = 120 - 0.46 - 0.255 = 119.285
    # cumulative realized = 69.315 + 119.285 = 188.6
    # cash += (6*120 - 0.46) = += 719.54 -> cash = 99469.06 + 719.54 = 100188.6
    state = ledger.position_state(pid)
    expected_total_realized = Decimal("39.55") + Decimal("29.765") + Decimal("119.285")
    assert expected_total_realized == Decimal("188.6")
    assert state.realized_pnl == expected_total_realized
    assert state.remaining_quantity == Decimal("0")
    assert state.is_closed
    assert state.entry_cost_allocated == entry_cost  # 0.17+0.085+0.255 == 0.51 exactly
    assert ledger.cash == starting_cash + Decimal("188.6")
    assert ledger.realized_pnl == Decimal("188.6")

    # Item 11: cost applied exactly once per fill, sums to total exactly.
    total_cost = entry_cost + t1_cost + t2_cost + t3_cost
    assert total_cost == Decimal("1.40")
    result = ledger.finalize()
    assert result.final_cash == starting_cash + Decimal("188.6")
    assert result.realized_pnl == Decimal("188.6")
    assert result.unrealized_pnl == Decimal("0")
    assert result.total_pnl == Decimal("188.6")


# =====================================================================
# Item 8: partial exit with open remainder across several bars.
# =====================================================================


def test_partial_exit_with_open_remainder_only_exited_qty_realizes() -> None:
    starting_cash = Decimal("100000")
    ledger = MarkToMarketLedger(starting_cash)
    pid = PositionId("remainder-1")
    t0 = BASE
    zero_cost = Decimal("0")

    ledger.apply_entry_fill(EntryFill(pid, Side.BUY, Decimal("12"), Decimal("100"), zero_cost, t0))
    ledger.mark_bar(t0, {pid: Decimal("100")})

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("4"), Decimal("110"), zero_cost, t0 + timedelta(minutes=1))
    )
    # Only the 4 exited shares are realized: 4*(110-100) = 40
    assert ledger.realized_pnl == Decimal("40")
    snap1 = ledger.mark_bar(t0 + timedelta(minutes=1), {pid: Decimal("110")})
    # remainder = 8 shares, marked at 110: unrealized = 8*(110-100) = 80
    assert snap1.unrealized_pnl == Decimal("80")
    assert snap1.realized_pnl == Decimal("40")

    for minute, price in ((2, "112"), (3, "108"), (4, "111")):
        snap = ledger.mark_bar(t0 + timedelta(minutes=minute), {pid: Decimal(price)})
        assert snap.realized_pnl == Decimal("40")  # never moves without a fill
        expected_unrealized = Decimal("8") * (Decimal(price) - Decimal("100"))
        assert snap.unrealized_pnl == expected_unrealized
        assert ledger.realized_pnl == Decimal("40")  # never realizes the whole position early

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("2"), Decimal("115"), zero_cost, t0 + timedelta(minutes=5))
    )
    assert ledger.realized_pnl == Decimal("40") + Decimal("2") * (Decimal("115") - Decimal("100"))

    for minute, price in ((6, "120"), (7, "119")):
        snap = ledger.mark_bar(t0 + timedelta(minutes=minute), {pid: Decimal(price)})
        expected_unrealized = Decimal("6") * (Decimal(price) - Decimal("100"))
        assert snap.unrealized_pnl == expected_unrealized

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("6"), Decimal("120"), zero_cost, t0 + timedelta(minutes=8))
    )
    final_snap = ledger.mark_bar(t0 + timedelta(minutes=8), {})
    assert final_snap.unrealized_pnl == Decimal("0")
    state = ledger.position_state(pid)
    assert state.is_closed
    assert state.remaining_quantity == Decimal("0")


# =====================================================================
# Item 9: trailing stop (long and short) - REAL evaluate_position_exit()
# drives the accounting ledger; no hand-constructed ExitDecision.
# =====================================================================


def _managed_position(
    *,
    direction: Side,
    quantity: Decimal,
    remaining_quantity: Decimal,
    highest_favorable_price: Decimal,
    exit_plan: ExitPlan,
    lifecycle_status: PositionLifecycleStatus = PositionLifecycleStatus.OPEN,
) -> ManagedPosition:
    position = Position(
        position_id=PositionId("trail-1"),
        instrument_id=RELIANCE,
        direction=direction,
        quantity=quantity,
        average_entry_price=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        opened_at=BASE,
        status=PositionStatus.OPEN,
    )
    return ManagedPosition(
        position=position,
        strategy_id="atr_volatility_breakout",  # type: ignore[arg-type]
        strategy_version="v1",
        entry_order_id=OrderId("ord-1"),
        exit_plan=exit_plan,
        lifecycle_status=lifecycle_status,
        remaining_quantity=remaining_quantity,
        highest_favorable_price=highest_favorable_price,
    )


def test_trailing_stop_long_drives_ledger_via_real_policy() -> None:
    """Long trailing stop, distance=5. Price path proves
    `highest_favorable_price` never moves backward and the trail does
    not fire on a pullback that does not reach the trailing level."""
    plan = ExitPlan(stop_loss=None, trailing_stop_distance=Decimal("5"))
    ledger = MarkToMarketLedger(Decimal("100000"))
    pid = PositionId("trail-1")
    t0 = BASE
    entry_cost = Decimal("0")
    ledger.apply_entry_fill(EntryFill(pid, Side.BUY, Decimal("10"), Decimal("100"), entry_cost, t0))

    highest = Decimal("100")
    # price path: 102 (new high) -> 106 (new high) -> 104 (pullback, no
    # hit: trail = 106-5=101, 104>101) -> 101 (hits trail: 101<=101)
    path = [
        (t0 + timedelta(minutes=1), Decimal("102")),
        (t0 + timedelta(minutes=2), Decimal("106")),
        (t0 + timedelta(minutes=3), Decimal("104")),
        (t0 + timedelta(minutes=4), Decimal("101")),
    ]
    for ts, price in path:
        highest = max(highest, price)
        managed = _managed_position(
            direction=Side.BUY,
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            highest_favorable_price=highest,
            exit_plan=plan,
        )
        decision = evaluate_position_exit(managed=managed, current_price=price, now=ts)
        ledger.mark_bar(ts, {pid: price})
        if decision is not None:
            assert decision.reason == ExitReason.TRAILING_STOP
            ledger.apply_exit_fill(
                ExitFill(pid, decision.exit_quantity, decision.exit_price, entry_cost, ts)
            )
            break
    else:
        pytest.fail("trailing stop never fired")

    assert highest == Decimal("106")  # ratcheted, never moved backward on the 104 pullback
    state = ledger.position_state(pid)
    assert state.is_closed
    # realized = 10*(101-100) - 0 - 0 = 10
    assert state.realized_pnl == Decimal("10")


def test_trailing_stop_short_drives_ledger_via_real_policy() -> None:
    """Short (mirrored): `lowest_favorable_price` semantics are
    represented by `highest_favorable_price` holding the position's own
    best-seen price, which for a short is the LOWEST price reached -
    same field, direction-aware comparison inside the policy."""
    plan = ExitPlan(stop_loss=None, trailing_stop_distance=Decimal("5"))
    ledger = MarkToMarketLedger(Decimal("100000"))
    pid = PositionId("trail-2")
    t0 = BASE
    entry_cost = Decimal("0")
    ledger.apply_entry_fill(
        EntryFill(pid, Side.SELL, Decimal("10"), Decimal("100"), entry_cost, t0)
    )

    lowest = Decimal("100")
    # price path: 98 (new low) -> 94 (new low) -> 96 (pullback, no hit:
    # trail = 94+5=99, 96<99) -> 99 (hits trail: 99>=99)
    path = [
        (t0 + timedelta(minutes=1), Decimal("98")),
        (t0 + timedelta(minutes=2), Decimal("94")),
        (t0 + timedelta(minutes=3), Decimal("96")),
        (t0 + timedelta(minutes=4), Decimal("99")),
    ]
    for ts, price in path:
        lowest = min(lowest, price)
        managed = _managed_position(
            direction=Side.SELL,
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            highest_favorable_price=lowest,
            exit_plan=plan,
        )
        decision = evaluate_position_exit(managed=managed, current_price=price, now=ts)
        ledger.mark_bar(ts, {pid: price})
        if decision is not None:
            assert decision.reason == ExitReason.TRAILING_STOP
            ledger.apply_exit_fill(
                ExitFill(pid, decision.exit_quantity, decision.exit_price, entry_cost, ts)
            )
            break
    else:
        pytest.fail("trailing stop never fired")

    assert lowest == Decimal("94")  # ratcheted, never moved backward on the 96 pullback
    state = ledger.position_state(pid)
    assert state.is_closed
    # realized = 10 * (-1) * (99-100) - 0 - 0 = 10
    assert state.realized_pnl == Decimal("10")


# =====================================================================
# Item 10: same-bar intrabar ambiguity - whatever the REAL policy
# decides (stop checked before targets), the ledger just accounts for it.
# =====================================================================


def test_same_bar_stop_and_target_ambiguity_ledger_just_accounts() -> None:
    """Stop-loss and target both technically reachable at the same price
    point; `evaluate_position_exit()` checks stop-loss FIRST (see its own
    docstring: "stop-loss first (risk always wins)"). The ledger must
    account for exactly whichever `ExitDecision` the real policy hands
    it - it does not re-decide priority itself."""
    plan = ExitPlan(stop_loss=Decimal("95"), target_1=Decimal("95"))
    managed = _managed_position(
        direction=Side.BUY,
        quantity=Decimal("10"),
        remaining_quantity=Decimal("10"),
        highest_favorable_price=Decimal("100"),
        exit_plan=plan,
    )
    decision = evaluate_position_exit(managed=managed, current_price=Decimal("95"), now=BASE)
    assert decision is not None
    assert decision.reason == ExitReason.STOP_LOSS  # the real policy's own priority, not ours

    ledger = MarkToMarketLedger(Decimal("100000"))
    pid = PositionId("ambig-1")
    ledger.apply_entry_fill(
        EntryFill(pid, Side.BUY, Decimal("10"), Decimal("100"), Decimal("0"), BASE)
    )
    ledger.apply_exit_fill(
        ExitFill(pid, decision.exit_quantity, decision.exit_price, Decimal("0"), BASE)
    )
    state = ledger.position_state(pid)
    assert state.is_closed
    assert state.realized_pnl == Decimal("10") * (Decimal("95") - Decimal("100"))


# =====================================================================
# Item 11/12: cost allocation exactness and cash-flow proofs.
# =====================================================================


def test_cost_allocation_sums_exactly() -> None:
    cm = verified_nse_cash_equity_intraday_cost_model()
    entry_cost = cm.cost_breakdown(is_buy=True, notional=Decimal("1200")).total
    t1_cost = cm.cost_breakdown(is_buy=False, notional=Decimal("440")).total
    t2_cost = cm.cost_breakdown(is_buy=False, notional=Decimal("230")).total
    t3_cost = cm.cost_breakdown(is_buy=False, notional=Decimal("720")).total

    ledger = MarkToMarketLedger(Decimal("100000"))
    pid = PositionId("costs-1")
    t0 = BASE
    ledger.apply_entry_fill(EntryFill(pid, Side.BUY, Decimal("12"), Decimal("100"), entry_cost, t0))
    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("4"), Decimal("110"), t1_cost, t0 + timedelta(minutes=1))
    )
    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("2"), Decimal("115"), t2_cost, t0 + timedelta(minutes=2))
    )
    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("6"), Decimal("120"), t3_cost, t0 + timedelta(minutes=3))
    )

    state = ledger.position_state(pid)
    assert state.entry_cost_allocated == entry_cost
    assert entry_cost + t1_cost + t2_cost + t3_cost == Decimal("1.40")


def test_cash_flow_entry_and_exit() -> None:
    ledger = MarkToMarketLedger(Decimal("100000"))
    pid = PositionId("cash-1")
    ledger.apply_entry_fill(
        EntryFill(pid, Side.BUY, Decimal("10"), Decimal("100"), Decimal("5"), BASE)
    )
    assert ledger.cash == Decimal("100000") - (Decimal("1000") + Decimal("5"))

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("4"), Decimal("110"), Decimal("2"), BASE + timedelta(minutes=1))
    )
    # partial exit only moves cash for the exited 4 shares: += (4*110 - 2)
    assert ledger.cash == (Decimal("100000") - Decimal("1005")) + (Decimal("440") - Decimal("2"))


def test_unrealized_pnl_never_touches_cash() -> None:
    ledger = MarkToMarketLedger(Decimal("100000"))
    pid = PositionId("cash-2")
    ledger.apply_entry_fill(
        EntryFill(pid, Side.BUY, Decimal("10"), Decimal("100"), Decimal("0"), BASE)
    )
    cash_before = ledger.cash
    ledger.mark_bar(BASE, {pid: Decimal("150")})  # large unrealized move, no fill
    assert ledger.cash == cash_before  # cash is untouched by any mark


# =====================================================================
# Item 13: bar-level equity curve / drawdown reflects real equity
# movement (rises, T1 realizes profit, remainder falls, final exit).
# =====================================================================


def test_drawdown_reflects_real_equity_movement() -> None:
    starting_cash = Decimal("100000")
    ledger = MarkToMarketLedger(starting_cash)
    pid = PositionId("dd-1")
    t0 = BASE
    zero = Decimal("0")

    ledger.apply_entry_fill(EntryFill(pid, Side.BUY, Decimal("10"), Decimal("100"), zero, t0))
    snap0 = ledger.mark_bar(t0, {pid: Decimal("100")})
    assert snap0.equity == starting_cash
    assert snap0.drawdown == Decimal("0")

    snap1 = ledger.mark_bar(t0 + timedelta(minutes=1), {pid: Decimal("120")})
    # equity rises: unrealized = 10*20=200
    assert snap1.equity == starting_cash + Decimal("200")
    assert snap1.drawdown == Decimal("0")
    peak_after_rise = snap1.peak_equity
    assert peak_after_rise == starting_cash + Decimal("200")

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("5"), Decimal("120"), zero, t0 + timedelta(minutes=2))
    )
    # T1 realizes 5*(120-100)=100 profit on half; remainder 5 shares open
    snap2 = ledger.mark_bar(t0 + timedelta(minutes=2), {pid: Decimal("120")})
    assert snap2.realized_pnl == Decimal("100")
    assert snap2.unrealized_pnl == Decimal("100")  # remaining 5 * 20
    assert snap2.equity == starting_cash + Decimal("200")  # unchanged total, just re-split

    snap3 = ledger.mark_bar(t0 + timedelta(minutes=3), {pid: Decimal("90")})
    # remainder falls hard: unrealized = 5*(90-100) = -50
    assert snap3.realized_pnl == Decimal("100")
    assert snap3.unrealized_pnl == Decimal("-50")
    assert snap3.equity == starting_cash + Decimal("100") + Decimal("-50")
    assert snap3.equity < peak_after_rise
    assert snap3.drawdown == peak_after_rise - snap3.equity
    assert snap3.drawdown > Decimal("0")

    ledger.apply_exit_fill(
        ExitFill(pid, Decimal("5"), Decimal("90"), zero, t0 + timedelta(minutes=4))
    )
    snap4 = ledger.mark_bar(t0 + timedelta(minutes=4), {})
    assert snap4.unrealized_pnl == Decimal("0")
    total_realized = Decimal("100") + Decimal("5") * (Decimal("90") - Decimal("100"))
    assert total_realized == Decimal("50")
    assert snap4.realized_pnl == Decimal("50")
    assert snap4.equity == starting_cash + Decimal("50")
    assert snap4.drawdown == peak_after_rise - snap4.equity


# =====================================================================
# Item 14: multiple simultaneous positions - isolation proof.
# =====================================================================


def test_multiple_positions_isolated_and_summed_correctly() -> None:
    starting_cash = Decimal("100000")
    ledger = MarkToMarketLedger(starting_cash)
    pid_a = PositionId("multi-a")
    pid_b = PositionId("multi-b")
    t0 = BASE
    zero = Decimal("0")

    ledger.apply_entry_fill(EntryFill(pid_a, Side.BUY, Decimal("10"), Decimal("100"), zero, t0))
    ledger.apply_entry_fill(EntryFill(pid_b, Side.SELL, Decimal("20"), Decimal("50"), zero, t0))

    # Long A pays notional; short B RECEIVES notional (direction-aware
    # cash convention, see module docstring).
    expected_cash = starting_cash - Decimal("1000") + Decimal("1000")
    assert ledger.cash == expected_cash

    snap = ledger.mark_bar(t0, {pid_a: Decimal("105"), pid_b: Decimal("48")})
    market_value_a = Decimal("10") * Decimal("105")
    market_value_b = -Decimal("20") * Decimal("48")  # short = negative (liability)
    assert snap.market_value == market_value_a + market_value_b
    unrealized_a = Decimal("10") * (Decimal("105") - Decimal("100"))
    unrealized_b = Decimal("20") * -Decimal("1") * (Decimal("48") - Decimal("50"))
    assert snap.unrealized_pnl == unrealized_a + unrealized_b
    assert snap.equity == ledger.cash + snap.market_value

    # T1/T2/T3-style partial exit of position A must not touch B at all.
    ledger.apply_exit_fill(
        ExitFill(pid_a, Decimal("4"), Decimal("108"), zero, t0 + timedelta(minutes=1))
    )
    state_a = ledger.position_state(pid_a)
    state_b = ledger.position_state(pid_b)
    assert state_a.remaining_quantity == Decimal("6")
    assert state_b.remaining_quantity == Decimal("20")  # untouched
    assert state_b.entry_cost_allocated == Decimal("0")  # untouched
    assert state_a.realized_pnl == Decimal("4") * (Decimal("108") - Decimal("100"))
    assert state_b.realized_pnl == Decimal("0")

    # Both positions share their own logical identity across fills
    # (reused PositionId, no parallel ID scheme invented).
    ledger.apply_exit_fill(
        ExitFill(pid_a, Decimal("6"), Decimal("110"), zero, t0 + timedelta(minutes=2))
    )
    ledger.apply_exit_fill(
        ExitFill(pid_b, Decimal("20"), Decimal("45"), zero, t0 + timedelta(minutes=2))
    )
    final_snap = ledger.mark_bar(t0 + timedelta(minutes=2), {})
    assert final_snap.market_value == Decimal("0")
    assert final_snap.unrealized_pnl == Decimal("0")
    result = ledger.finalize()
    expected_realized_a = Decimal("4") * 8 + Decimal("6") * 10  # 32 + 60 = 92
    expected_realized_b = Decimal("20") * (Decimal("50") - Decimal("45"))  # 100
    assert result.realized_pnl == expected_realized_a + expected_realized_b


# =====================================================================
# Item 5: invariants (quantity conservation, cost-basis conservation,
# equity identity, total_pnl identity, non-negative quantities, terminal
# state equivalence).
# =====================================================================


@pytest.mark.parametrize(
    "original_qty,fills",
    [
        (Decimal("12"), [Decimal("4"), Decimal("2"), Decimal("6")]),
        (Decimal("9"), [Decimal("3"), Decimal("3"), Decimal("3")]),
        (Decimal("7"), [Decimal("7")]),
        (Decimal("100"), [Decimal("1")] * 100),
        (Decimal("13"), [Decimal("5"), Decimal("5"), Decimal("3")]),
    ],
)
def test_quantity_and_cost_basis_conservation_invariants(original_qty, fills) -> None:
    assert sum(fills) == original_qty
    cm = verified_nse_cash_equity_intraday_cost_model()
    entry_notional = original_qty * Decimal("100")
    entry_cost = cm.cost_breakdown(is_buy=True, notional=entry_notional).total

    ledger = MarkToMarketLedger(Decimal("1000000"))
    pid = PositionId("inv-1")
    t0 = BASE
    ledger.apply_entry_fill(EntryFill(pid, Side.BUY, original_qty, Decimal("100"), entry_cost, t0))

    cumulative_exited = Decimal("0")
    for i, qty in enumerate(fills):
        price = Decimal("100") + Decimal(i + 1) * Decimal("2")
        exit_cost = cm.cost_breakdown(is_buy=False, notional=qty * price).total
        ledger.apply_exit_fill(ExitFill(pid, qty, price, exit_cost, t0 + timedelta(minutes=i + 1)))
        cumulative_exited += qty
        state = ledger.position_state(pid)

        # Quantity conservation.
        assert original_qty == state.cumulative_exited_quantity + state.remaining_quantity
        assert state.cumulative_exited_quantity == cumulative_exited
        assert state.remaining_quantity >= 0
        assert state.cumulative_exited_quantity >= 0

        # Cost-basis conservation: original_entry_value ==
        # allocated_realized_entry_basis + remaining_entry_basis.
        original_entry_value = original_qty * Decimal("100") + entry_cost
        allocated_realized_entry_basis = (
            state.cumulative_exited_quantity * Decimal("100") + state.entry_cost_allocated
        )
        assert original_entry_value == allocated_realized_entry_basis + state.remaining_entry_basis

        # Terminal-state equivalence: remaining_quantity == 0 iff closed
        # (CLOSED is the only genuine terminal state per
        # `PositionLifecycleStatus.is_terminal()`).
        assert (state.remaining_quantity == 0) == state.is_closed

    final_state = ledger.position_state(pid)
    assert final_state.remaining_quantity == 0
    assert final_state.is_closed
    # total_pnl == realized_pnl + unrealized_pnl (unrealized is 0 - fully closed)
    result = ledger.finalize()
    assert result.total_pnl == result.realized_pnl + result.unrealized_pnl
    assert result.unrealized_pnl == Decimal("0")


def test_equity_equals_cash_plus_market_value_always(monkeypatch=None) -> None:
    ledger = MarkToMarketLedger(Decimal("50000"))
    pid = PositionId("eq-1")
    t0 = BASE
    ledger.apply_entry_fill(
        EntryFill(pid, Side.SELL, Decimal("5"), Decimal("200"), Decimal("1"), t0)
    )
    for minute, price in enumerate(["205", "195", "210", "190"], start=1):
        snap = ledger.mark_bar(t0 + timedelta(minutes=minute), {pid: Decimal(price)})
        assert snap.equity == snap.cash + snap.market_value
        assert snap.total_pnl == snap.realized_pnl + snap.unrealized_pnl


def test_exit_exceeding_remaining_quantity_rejected() -> None:
    ledger = MarkToMarketLedger(Decimal("100000"))
    pid = PositionId("bad-1")
    ledger.apply_entry_fill(
        EntryFill(pid, Side.BUY, Decimal("5"), Decimal("100"), Decimal("0"), BASE)
    )
    with pytest.raises(MarkToMarketError):
        ledger.apply_exit_fill(ExitFill(pid, Decimal("6"), Decimal("110"), Decimal("0"), BASE))


def test_exit_for_unknown_position_rejected() -> None:
    ledger = MarkToMarketLedger(Decimal("100000"))
    with pytest.raises(MarkToMarketError):
        ledger.apply_exit_fill(
            ExitFill(PositionId("nope"), Decimal("1"), Decimal("1"), Decimal("0"), BASE)
        )


def test_duplicate_entry_fill_for_same_position_rejected() -> None:
    ledger = MarkToMarketLedger(Decimal("100000"))
    pid = PositionId("dup-1")
    ledger.apply_entry_fill(
        EntryFill(pid, Side.BUY, Decimal("5"), Decimal("100"), Decimal("0"), BASE)
    )
    with pytest.raises(MarkToMarketError):
        ledger.apply_entry_fill(
            EntryFill(pid, Side.BUY, Decimal("5"), Decimal("100"), Decimal("0"), BASE)
        )


# =====================================================================
# Item 16: performance benchmark - >=100,000 bars, several positions,
# partial exits. Zero ORM/DB/network calls (confirmed by code reading -
# this module imports nothing beyond domain contracts + stdlib).
# =====================================================================


def test_performance_100k_bars_multiple_positions() -> None:
    import time

    bar_count = 100_000
    ledger = MarkToMarketLedger(Decimal("10000000"))
    position_ids = [PositionId(f"perf-{i}") for i in range(5)]
    t0 = BASE
    for i, pid in enumerate(position_ids):
        ledger.apply_entry_fill(
            EntryFill(
                pid,
                Side.BUY,
                Decimal("100"),
                Decimal("100"),
                Decimal("1"),
                t0 + timedelta(seconds=i),
            )
        )

    start = time.perf_counter()
    for bar_index in range(bar_count):
        ts = t0 + timedelta(minutes=bar_index + 1)
        price = Decimal("100") + Decimal(bar_index % 50)
        marks = {pid: price for pid in position_ids}
        ledger.mark_bar(ts, marks)
        if bar_index in (10_000, 40_000, 70_000):
            # a partial exit sprinkled in to exercise the fill path too
            pid = position_ids[bar_index % len(position_ids)]
            state = ledger.position_state(pid)
            if state.remaining_quantity >= 10:
                ledger.apply_exit_fill(ExitFill(pid, Decimal("10"), price, Decimal("0.5"), ts))
    elapsed = time.perf_counter() - start

    bars_per_sec = bar_count / elapsed if elapsed > 0 else float("inf")
    print(
        f"\nmark_to_market performance: {bar_count} bars in {elapsed:.3f}s "
        f"({bars_per_sec:.0f} bars/sec)"
    )
    result = ledger.finalize()
    assert len(result.equity_curve) == bar_count
    # Sanity: this ran fast enough to be a real proof, not a fluke -
    # generous bound, not a tight performance assertion.
    assert elapsed < 60
