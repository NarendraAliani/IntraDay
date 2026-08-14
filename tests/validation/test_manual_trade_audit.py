# tests/validation/test_manual_trade_audit.py
#
# Checkpoint 30 Part 15: manual audit of at least 3 trades, with explicit
# hand arithmetic shown in this file's comments, pinned as permanent
# regression fixtures. Each trade below was independently recomputed by
# hand (signal -> next-bar execution -> quantity -> entry costs -> exit
# costs -> gross P&L -> net P&L) using the documented cost schedule from
# Checkpoint 29 (docs/research or BACKTESTING_ARCHITECTURE.md):
#   brokerage: min(0.03% * notional, Rs 20), rounded to 2dp
#   exchange:  0.00307% * notional, rounded to 2dp
#   sebi:      0.0001% * notional, rounded to 2dp
#   gst:       18% * (unrounded brokerage + unrounded exchange + unrounded sebi), rounded to 2dp
#   stt:       0.025% * notional, SELL leg only, rounded to 2dp
#   stamp:     0.003% * notional, BUY leg only, rounded to 2dp
# Rounding: Decimal("0.01"), ROUND_HALF_UP, applied once per component.
#
# These three trades were chosen to cover three distinct outcome shapes:
# a long win, a short win closed by end-of-data, and a short loss - so
# the audit is not cherry-picking only the "easy" (profitable) case.
from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intraday.domain.market_data.contracts import Bar  # noqa: E402
from intraday.domain.shared_kernel.contracts import Timeframe  # noqa: E402
from intraday.research.backtesting import (  # noqa: E402
    StrategyConfigurationValues,
    build_default_registry,
)
from intraday.research.backtesting.contracts import (  # noqa: E402
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.cost_model import (  # noqa: E402
    verified_nse_cash_equity_intraday_cost_model,
)
from intraday.research.backtesting.engine import run_backtest  # noqa: E402
from intraday.signal_intelligence.feature_engine.atr import (  # noqa: E402
    compute_average_true_range,
)
from intraday.signal_intelligence.feature_engine.definitions import (  # noqa: E402
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import (  # noqa: E402
    compute_exponential_moving_average,
)
from intraday.signal_intelligence.feature_engine.sma import (  # noqa: E402
    compute_simple_moving_average,
)
from tests.validation.fixtures import extended_fixture, micro_fixture  # noqa: E402

FAST_LOOKBACK = 3
SLOW_LOOKBACK = 6
QUANTITY = Decimal("10")
INITIAL_CAPITAL = Decimal("100000")


def _compute(field_id, bars):
    kind, _, raw = field_id.partition("_")
    lookback = int(raw)
    if kind == "sma":
        return compute_simple_moving_average(SimpleMovingAverageDefinition(lookback), bars)
    if kind == "ema":
        return compute_exponential_moving_average(
            ExponentialMovingAverageDefinition(lookback), bars
        )
    if kind == "atr":
        return compute_average_true_range(AverageTrueRangeDefinition(lookback), bars)
    raise ValueError(field_id)


def _run(fixture):
    domain_bars = tuple(
        Bar(
            instrument_id=fixture.instrument_id,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=datetime.fromisoformat(rb.timestamp),
            open=rb.open,
            high=rb.high,
            low=rb.low,
            close=rb.close,
            volume=Decimal("0"),
        )
        for rb in fixture.bars
    )
    registry = build_default_registry()
    config = BacktestConfiguration(
        instrument_id=fixture.instrument_id,
        timeframe=Timeframe.ONE_MINUTE,
        start=domain_bars[0].timestamp,
        end=domain_bars[-1].timestamp,
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        initial_capital=INITIAL_CAPITAL,
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=QUANTITY,
        brokerage_percent=Decimal("0"),
        slippage_percent=Decimal("0"),
    )
    strategy_config = StrategyConfigurationValues(
        "ema_crossover",
        "v1",
        "v1",
        "v1",
        {"fast_lookback": FAST_LOOKBACK, "slow_lookback": SLOW_LOOKBACK},
    )
    dq = DataQualityDisclosure(
        data_source="frozen validation fixture (synthetic)",
        data_quality=DataQualityLabel.FIXTURE_OR_HISTORICAL,
        bar_count=len(domain_bars),
        missing_bar_note="none - contiguous synthetic fixture",
        transaction_cost_assumption="verified_nse_cash_equity_intraday_cost_model",
        slippage_assumption="none (zero slippage, isolates execution/cost logic)",
        survivorship_bias_note="n/a - single frozen instrument",
    )
    return run_backtest(
        domain_bars,
        registry.get("ema_crossover"),
        strategy_config,
        config,
        _compute,
        data_quality=dq,
        generated_at=datetime.now(UTC),
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )


def test_manual_audit_trade_1_long_win_micro_fixture() -> None:
    """Trade ema_crossover-1 on MICRO-EMA-CROSSOVER-V1: BULLISH, entry
    101 -> exit 108, qty 10, closed by signal_reversal.

    Hand arithmetic:
      gross = (108 - 101) * 10 = 70
      entry (BUY, notional 1010): brokerage 0.303->0.30, exchange
        0.031007->0.03, sebi 0.00101->0.00, gst 18%*0.335117=0.0603->0.06,
        stt 0 (buy), stamp 0.003%*1010=0.0303->0.03 => entry total 0.42
      exit (SELL, notional 1080): brokerage 0.324->0.32, exchange
        0.033156->0.03, sebi 0.00108->0.00, gst 18%*0.358236=0.0645->0.06,
        stt 0.025%*1080=0.27, stamp 0 (sell) => exit total 0.68
      total costs = 0.42 + 0.68 = 1.10
      net = 70 - 1.10 = 68.90
    """
    result = _run(micro_fixture())
    trade = result.trades[0]
    assert trade.entry_price == Decimal("101")
    assert trade.exit_price == Decimal("108")
    assert trade.quantity == Decimal("10")
    assert trade.reason == "signal_reversal"
    assert trade.gross_pnl == Decimal("70")
    cb = trade.cost_breakdown
    assert cb.brokerage == Decimal("0.62")
    assert cb.exchange_transaction_charges == Decimal("0.06")
    assert cb.sebi_charges == Decimal("0.00")
    assert cb.gst == Decimal("0.12")
    assert cb.stt == Decimal("0.27")
    assert cb.stamp_duty == Decimal("0.03")
    assert trade.costs == Decimal("1.10")
    assert trade.net_pnl == Decimal("68.90")


def test_manual_audit_trade_2_short_win_end_of_data_micro_fixture() -> None:
    """Trade ema_crossover-2 on MICRO-EMA-CROSSOVER-V1: BEARISH, entry
    106 -> exit 102, qty 10, closed by end_of_data (forced close at the
    final bar's own close).

    Hand arithmetic:
      gross = (106 - 102) * 10 = 40
      entry (SELL, notional 1060): brokerage 0.318->0.32, exchange
        0.032542->0.03, sebi 0.00106->0.00, gst 18%*0.351602=0.0633->0.06,
        stt 0.025%*1060=0.265->0.27, stamp 0 (sell) => entry total 0.68
      exit (BUY, notional 1020): brokerage 0.306->0.31, exchange
        0.031314->0.03, sebi 0.00102->0.00, gst 18%*0.338334=0.0609->0.06,
        stt 0 (buy), stamp 0.003%*1020=0.0306->0.03 => exit total 0.43
      total costs = 0.68 + 0.43 = 1.11
      net = 40 - 1.11 = 38.89
    """
    result = _run(micro_fixture())
    trade = result.trades[1]
    assert trade.entry_price == Decimal("106")
    assert trade.exit_price == Decimal("102")
    assert trade.quantity == Decimal("10")
    assert trade.reason == "end_of_data"
    assert trade.gross_pnl == Decimal("40")
    cb = trade.cost_breakdown
    assert cb.brokerage == Decimal("0.63")
    assert cb.exchange_transaction_charges == Decimal("0.06")
    assert cb.sebi_charges == Decimal("0.00")
    assert cb.gst == Decimal("0.12")
    assert cb.stt == Decimal("0.27")
    assert cb.stamp_duty == Decimal("0.03")
    assert trade.costs == Decimal("1.11")
    assert trade.net_pnl == Decimal("38.89")


def test_manual_audit_trade_3_short_loss_extended_fixture() -> None:
    """Trade ema_crossover-2 on EXTENDED-EMA-CROSSOVER-V1: BEARISH, entry
    234 -> exit 235, qty 10, closed by signal_reversal - a losing trade,
    deliberately included so the audit is not cherry-picked to only
    profitable outcomes.

    Hand arithmetic:
      gross = (234 - 235) * 10 = -10
      entry (SELL, notional 2340): brokerage 0.702->0.70, exchange
        0.071838->0.07, sebi 0.00234->0.00, gst 18%*0.776178=0.1397->0.14,
        stt 0.025%*2340=0.585->0.59, stamp 0 (sell) => entry total 1.50
      exit (BUY, notional 2350): brokerage 0.705->0.71, exchange
        0.072145->0.07, sebi 0.00235->0.00, gst 18%*0.779495=0.1403->0.14,
        stt 0 (buy), stamp 0.003%*2350=0.0705->0.07 => exit total 0.99
      total costs = 1.50 + 0.99 = 2.49
      net = -10 - 2.49 = -12.49
    """
    result = _run(extended_fixture())
    trade = result.trades[1]
    assert trade.direction.name == "BEARISH"
    assert trade.entry_price == Decimal("234")
    assert trade.exit_price == Decimal("235")
    assert trade.quantity == Decimal("10")
    assert trade.reason == "signal_reversal"
    assert trade.gross_pnl == Decimal("-10")
    cb = trade.cost_breakdown
    assert cb.brokerage == Decimal("1.41")
    assert cb.exchange_transaction_charges == Decimal("0.14")
    assert cb.sebi_charges == Decimal("0.00")
    assert cb.gst == Decimal("0.28")
    assert cb.stt == Decimal("0.59")
    assert cb.stamp_duty == Decimal("0.07")
    assert trade.costs == Decimal("2.49")
    assert trade.net_pnl == Decimal("-12.49")
