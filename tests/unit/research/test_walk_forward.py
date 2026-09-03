# tests/unit/research/test_walk_forward.py
#
# Checkpoint 68.2: tests for the new, isolated walk-forward splitting/
# aggregation logic (src/intraday/research/backtesting/walk_forward.py)
# against SYNTHETIC FIXTURE BARS ONLY - real research-eligible
# HistoricalBar data is still zero rows (RECON_BACKTEST_SUMMARY.md,
# re-confirmed CHECKPOINT_67.13-C_SUMMARY.md), and this checkpoint's
# own scope explicitly excludes testing against real data.
#
# Bar-fixture construction reuses the SAME pattern already established
# in test_backtesting_engine.py's own `_bars()` helper (one Bar() call
# per synthetic price, INSTRUMENT/Timeframe.ONE_MINUTE fixed, only the
# inter-bar time delta is parameterized here so bars can span multiple
# distinct calendar days - required for walk-forward's day-based fold
# boundaries, unlike the engine's own minute-spaced tests) - no second,
# independently-invented synthetic-bar helper is created.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, build_default_registry
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.errors import InsufficientHistoricalDataError
from intraday.research.backtesting.walk_forward import (
    InsufficientDataForWalkForwardError,
    WalkForwardFold,
    compute_walk_forward_folds,
    run_walk_forward_backtest,
)
from intraday.signal_intelligence.feature_engine.definitions import (
    ExponentialMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average

INSTRUMENT = "NSE:TESTCO"
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def _compute(field_id: str, bars: tuple[Bar, ...]):
    kind, _, raw = field_id.partition("_")
    lookback = int(raw)
    if kind == "ema":
        return compute_exponential_moving_average(
            ExponentialMovingAverageDefinition(lookback), bars
        )
    raise ValueError(field_id)


def _daily_bars(prices: list[str], bars_per_day: int = 10) -> tuple[Bar, ...]:
    """Same construction as test_backtesting_engine.py's `_bars()` -
    one synthetic OHLCV Bar per price, fixed instrument/timeframe -
    except bars are grouped `bars_per_day` at a time onto successive
    CALENDAR DAYS (still 1-minute-spaced within a day) so the fixture
    spans multiple distinct dates, which walk-forward's fold boundaries
    require."""
    bars = []
    for i, price_str in enumerate(prices):
        day_index, minute_in_day = divmod(i, bars_per_day)
        price = Decimal(price_str)
        timestamp = BASE + timedelta(days=day_index) + timedelta(minutes=minute_in_day)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=timestamp,
                open=price - Decimal("1"),
                high=price + Decimal("2"),
                low=price - Decimal("2"),
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
        "end": BASE + timedelta(days=30),
        "strategy_id": "ema_crossover",
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


def _ema_strategy():
    registry = build_default_registry()
    return registry.get("ema_crossover")


def _ema_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )


# --- 1. Fold-boundary correctness (no overlap / no look-ahead) ------------


def test_folds_have_no_overlap_and_no_look_ahead() -> None:
    """No bar timestamp in a fold's out-of-sample window may also
    appear in that SAME fold's in-sample window - the defining
    no-look-ahead property for walk-forward splitting."""
    prices = [str(100 + i) for i in range(100)]
    bars = _daily_bars(prices, bars_per_day=10)  # 10 distinct calendar days

    folds = compute_walk_forward_folds(bars, min_oos_days=2, min_folds=3)
    assert len(folds) == 3

    bars_by_ts = {b.timestamp: b for b in bars}
    for fold in folds:
        in_sample_ts = {
            ts for ts in bars_by_ts if fold.in_sample_start <= ts <= fold.in_sample_end
        }
        oos_ts = {
            ts
            for ts in bars_by_ts
            if fold.out_of_sample_start <= ts <= fold.out_of_sample_end
        }
        assert in_sample_ts & oos_ts == set(), "in-sample/out-of-sample windows overlap"
        assert fold.out_of_sample_start > fold.in_sample_end
        assert fold.in_sample_bar_count == len(in_sample_ts)
        assert fold.out_of_sample_bar_count == len(oos_ts)


def test_folds_are_anchored_expanding_in_sample() -> None:
    """Anchored/expanding design (68.1 §B1): fold N's in-sample window
    must be a strict superset of fold N-1's in-sample window, and must
    include fold N-1's out-of-sample dates too."""
    prices = [str(100 + i) for i in range(100)]
    bars = _daily_bars(prices, bars_per_day=10)

    folds = compute_walk_forward_folds(bars, min_oos_days=2, min_folds=3)
    for earlier, later in zip(folds, folds[1:], strict=False):
        assert later.in_sample_start == earlier.in_sample_start  # anchored, never slides
        assert later.in_sample_end >= earlier.out_of_sample_end
        assert later.in_sample_bar_count > earlier.in_sample_bar_count  # expanding


# --- 2. Insufficient-data refusal path -------------------------------------


def test_insufficient_data_raises_dedicated_error_not_a_tiny_fold() -> None:
    """Too few distinct calendar days to build even one requested fold
    must raise InsufficientDataForWalkForwardError, never silently
    produce a misleading near-empty fold."""
    prices = [str(100 + i) for i in range(20)]
    bars = _daily_bars(prices, bars_per_day=10)  # only 2 distinct days

    with pytest.raises(InsufficientDataForWalkForwardError):
        compute_walk_forward_folds(bars, min_oos_days=5, min_folds=1)


def test_insufficient_data_error_is_not_the_engines_own_error_type() -> None:
    """Confirms the NEW dedicated error type is used (mirroring, not
    reusing, engine.errors.InsufficientHistoricalDataError - see that
    class's own distinction documented on
    InsufficientDataForWalkForwardError)."""
    prices = [str(100 + i) for i in range(10)]
    bars = _daily_bars(prices, bars_per_day=10)  # only 1 distinct day

    with pytest.raises(InsufficientDataForWalkForwardError) as excinfo:
        compute_walk_forward_folds(bars, min_oos_days=1, min_folds=1)
    assert not isinstance(excinfo.value, InsufficientHistoricalDataError)


def test_zero_bars_raises_insufficient_data_for_walk_forward() -> None:
    with pytest.raises(InsufficientDataForWalkForwardError):
        compute_walk_forward_folds((), min_oos_days=1, min_folds=1)


# --- 3. End-to-end run: aggregate metrics computed correctly ---------------


def test_end_to_end_walk_forward_aggregates_known_per_fold_results() -> None:
    """Runs the real orchestration function against small synthetic
    fixture bars and proves the aggregate fields are actually derived
    from the per-fold BacktestResult objects the SAME run produced -
    not merely that the call completes without raising."""
    prices = [str(100 + i) for i in range(120)]
    bars = _daily_bars(prices, bars_per_day=12)  # 10 distinct days

    result = run_walk_forward_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
        min_oos_days=2,
        min_folds=2,
    )

    assert len(result.folds) == 2
    assert len(result.in_sample_results) == 2
    assert len(result.out_of_sample_results) == 2

    expected_oos_return = sum(
        (r.metrics.return_percent for r in result.out_of_sample_results), Decimal("0")
    ) / Decimal(2)
    assert result.aggregate_oos_return == expected_oos_return

    expected_oos_win_rate = sum(
        (r.metrics.win_rate_percent for r in result.out_of_sample_results), Decimal("0")
    ) / Decimal(2)
    assert result.aggregate_oos_win_rate == expected_oos_win_rate

    expected_ratios = [
        oos.metrics.return_percent / is_.metrics.return_percent
        for is_, oos in zip(result.in_sample_results, result.out_of_sample_results, strict=True)
        if is_.metrics.return_percent != 0
    ]
    if expected_ratios:
        expected_mean_ratio = sum(expected_ratios, Decimal("0")) / Decimal(len(expected_ratios))
        assert result.mean_degradation_ratio == expected_mean_ratio
    else:
        assert result.mean_degradation_ratio is None

    assert "2 walk-forward fold(s)" in result.data_sufficiency_note
    assert str(len(result.folds)) in result.data_sufficiency_note


def test_data_sufficiency_note_flags_small_fold_counts() -> None:
    prices = [str(100 + i) for i in range(60)]
    bars = _daily_bars(prices, bars_per_day=10)

    result = run_walk_forward_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=datetime.now(tz=UTC),
        min_oos_days=2,
        min_folds=1,
    )
    assert len(result.folds) == 1
    assert "must not be presented with the same confidence" in result.data_sufficiency_note


# --- 4. run_backtest() itself is never modified or monkeypatched -----------


def test_run_backtest_used_by_walk_forward_is_the_real_unmodified_function() -> None:
    """Proves the module-level `run_backtest` walk_forward.py calls is
    IDENTICAL (by `is` identity) to the real function imported directly
    from engine.py in this test - i.e. walk_forward.py neither wraps,
    monkeypatches, nor reimplements it."""
    from intraday.research.backtesting import walk_forward as wf_module

    assert wf_module.run_backtest is run_backtest


def test_walk_forward_and_direct_engine_call_produce_identical_result_for_one_fold() -> None:
    """Runs the real engine.run_backtest() directly on a fold's own
    in-sample bar slice/config, then confirms run_walk_forward_backtest
    produced the BIT-IDENTICAL BacktestResult for that same fold's
    in-sample side - proving the orchestration calls the real function
    with the real inputs, not a stand-in."""
    prices = [str(100 + i) for i in range(80)]
    bars = _daily_bars(prices, bars_per_day=10)

    folds = compute_walk_forward_folds(bars, min_oos_days=2, min_folds=1)
    fold = folds[0]
    is_bars = tuple(b for b in bars if fold.in_sample_start <= b.timestamp <= fold.in_sample_end)
    is_config = _config(start=fold.in_sample_start, end=fold.in_sample_end)
    generated_at = datetime(2026, 6, 1, tzinfo=UTC)

    direct_result = run_backtest(
        is_bars,
        _ema_strategy(),
        _ema_config(),
        is_config,
        _compute,
        data_quality=_dq(len(is_bars)),
        generated_at=generated_at,
    )

    wf_result = run_walk_forward_backtest(
        bars,
        _ema_strategy(),
        _ema_config(),
        _config(),
        _compute,
        data_quality=_dq(len(bars)),
        generated_at=generated_at,
        min_oos_days=2,
        min_folds=1,
    )

    assert wf_result.in_sample_results[0].backtest_id == direct_result.backtest_id
    assert wf_result.in_sample_results[0].trades == direct_result.trades
    assert wf_result.in_sample_results[0].metrics == direct_result.metrics


# --- WalkForwardFold dataclass shape ----------------------------------------


def test_walk_forward_fold_has_the_documented_fields() -> None:
    fold = WalkForwardFold(
        in_sample_start=BASE,
        in_sample_end=BASE + timedelta(days=1),
        out_of_sample_start=BASE + timedelta(days=2),
        out_of_sample_end=BASE + timedelta(days=3),
        in_sample_bar_count=10,
        out_of_sample_bar_count=5,
    )
    assert fold.in_sample_bar_count == 10
    assert fold.out_of_sample_bar_count == 5
