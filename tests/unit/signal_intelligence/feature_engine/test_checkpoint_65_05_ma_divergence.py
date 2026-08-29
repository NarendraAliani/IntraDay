# File: tests/unit/signal_intelligence/feature_engine/
#   test_checkpoint_65_05_ma_divergence.py
#
# Checkpoint 65.05: CANONICAL MARKET CONTEXT FEATURE - ma_divergence.
# REDUCED, TARGETED testing only (per checkpoint directive) - covers
# positive/negative/zero divergence, fast/slow ordering validation,
# insufficient history, warm-up, zero-slow-MA handling, determinism,
# no-lookahead, Decimal output, and registry/dispatcher integration.
# Does NOT re-run the full suite.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import DuplicateBarTimestampError, OutOfOrderBarError
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import (
    ExponentialMovingAverageDefinition,
    MaDivergenceEmaDefinition,
    MaDivergenceSmaDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.errors import (
    InvalidLookbackError,
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)
from intraday.signal_intelligence.feature_engine.field_registry import (
    get_field,
    is_parameterized_feature,
    list_fields,
)
from intraday.signal_intelligence.feature_engine.ma_divergence import (
    compute_ma_divergence_ema,
    compute_ma_divergence_sma,
)
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

IID = InstrumentId("TEST")
TF = Timeframe.ONE_MINUTE
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(i: int, close: str, o: str | None = None) -> Bar:
    close_d = Decimal(close)
    open_d = Decimal(o) if o is not None else close_d
    high_d = max(open_d, close_d) + Decimal("1")
    low_d = min(open_d, close_d) - Decimal("1")
    return Bar(
        instrument_id=IID,
        timeframe=TF,
        timestamp=BASE_TS + timedelta(minutes=i),
        open=open_d,
        high=high_d,
        low=low_d,
        close=close_d,
        volume=Decimal("100"),
    )


# ---------------------------------------------------------------------------
# A. Positive / negative / zero divergence.
# ---------------------------------------------------------------------------


def test_a1_positive_divergence_fast_above_slow_sma() -> None:
    # Flat closes at 100 for 5 bars, then a sharp rise - the fast(2) SMA
    # reacts faster than the slow(5) SMA, so fast ends up above slow.
    bars = tuple(_bar(i, "100") for i in range(5)) + (_bar(5, "130"), _bar(6, "150"))
    values = compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars)
    assert values[-1].value > 0


def test_a2_negative_divergence_fast_below_slow_sma() -> None:
    bars = tuple(_bar(i, "100") for i in range(5)) + (_bar(5, "70"), _bar(6, "50"))
    values = compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars)
    assert values[-1].value < 0


def test_a3_zero_divergence_fast_equals_slow() -> None:
    bars = tuple(_bar(i, "100") for i in range(8))
    values = compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars)
    assert all(v.value == Decimal(0) for v in values)


def test_a4_exact_formula_sma() -> None:
    bars = tuple(_bar(i, str(100 + i)) for i in range(6))
    definition = MaDivergenceSmaDefinition(2, 4)
    values = compute_ma_divergence_sma(definition, bars)
    fast_values = compute_simple_moving_average(SimpleMovingAverageDefinition(2), bars)
    slow_values = compute_simple_moving_average(SimpleMovingAverageDefinition(4), bars)
    fast_by_ts = {v.timestamp: v.value for v in fast_values}
    slow_by_ts = {v.timestamp: v.value for v in slow_values}
    assert len(values) == len(slow_values)
    for v in values:
        fast = fast_by_ts[v.timestamp]
        slow = slow_by_ts[v.timestamp]
        assert v.value == (fast - slow) / slow


def test_a5_exact_formula_ema() -> None:
    bars = tuple(_bar(i, str(100 + i)) for i in range(8))
    definition = MaDivergenceEmaDefinition(2, 4)
    values = compute_ma_divergence_ema(definition, bars)
    fast_values = compute_exponential_moving_average(ExponentialMovingAverageDefinition(2), bars)
    slow_values = compute_exponential_moving_average(ExponentialMovingAverageDefinition(4), bars)
    fast_by_ts = {v.timestamp: v.value for v in fast_values}
    slow_by_ts = {v.timestamp: v.value for v in slow_values}
    assert len(values) == len(slow_values)
    for v in values:
        fast = fast_by_ts[v.timestamp]
        slow = slow_by_ts[v.timestamp]
        assert v.value == (fast - slow) / slow


# ---------------------------------------------------------------------------
# B. Fast/slow ordering, invalid parameters.
# ---------------------------------------------------------------------------


def test_b1_rejects_fast_greater_than_or_equal_slow() -> None:
    with pytest.raises(InvalidLookbackError):
        MaDivergenceSmaDefinition(5, 5)
    with pytest.raises(InvalidLookbackError):
        MaDivergenceSmaDefinition(10, 5)
    with pytest.raises(InvalidLookbackError):
        MaDivergenceEmaDefinition(20, 9)


def test_b2_never_silently_swaps_fast_slow() -> None:
    # fast=10 > slow=5 must raise, NOT silently become fast=5, slow=10.
    with pytest.raises(InvalidLookbackError):
        MaDivergenceSmaDefinition(10, 5)


def test_b3_rejects_non_positive_lookback() -> None:
    with pytest.raises(InvalidLookbackError):
        MaDivergenceSmaDefinition(0, 5)
    with pytest.raises(InvalidLookbackError):
        MaDivergenceEmaDefinition(-1, 5)


def test_b4_no_hardcoded_default_parameters() -> None:
    with pytest.raises(TypeError):
        MaDivergenceSmaDefinition()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        MaDivergenceEmaDefinition()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# C. Warm-up / insufficient history.
# ---------------------------------------------------------------------------


def test_c1_no_output_before_slow_warmup() -> None:
    bars = tuple(_bar(i, "100") for i in range(4))  # slow lookback 5, only 4 bars
    assert compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars) == ()


def test_c2_first_output_exactly_at_slow_warmup() -> None:
    bars = tuple(_bar(i, "100") for i in range(5))
    values = compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars)
    assert len(values) == 1
    assert values[0].timestamp == bars[4].timestamp


def test_c3_ema_warmup_matches_slow_ema_seed_index() -> None:
    bars = tuple(_bar(i, str(100 + i)) for i in range(8))
    values = compute_ma_divergence_ema(MaDivergenceEmaDefinition(2, 4), bars)
    assert values[0].timestamp == bars[3].timestamp


def test_c4_empty_series() -> None:
    assert compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), ()) == ()
    assert compute_ma_divergence_ema(MaDivergenceEmaDefinition(2, 5), ()) == ()


# ---------------------------------------------------------------------------
# D. Zero slow-MA handling.
# ---------------------------------------------------------------------------


def test_d1_zero_slow_ma_output_is_skipped_not_raised() -> None:
    from intraday.domain.feature.contracts import FeatureValue
    from intraday.domain.shared_kernel.contracts import Version
    from intraday.signal_intelligence.feature_engine.ma_divergence import (
        _ma_divergence_from_ma_series,
    )

    ts = BASE_TS
    fast = FeatureValue(
        feature_name="sma_2",
        feature_version=Version(value="v1"),
        instrument_id=IID,
        timeframe=TF,
        timestamp=ts,
        value=Decimal("10"),
    )
    slow_zero = FeatureValue(
        feature_name="sma_5",
        feature_version=Version(value="v1"),
        instrument_id=IID,
        timeframe=TF,
        timestamp=ts,
        value=Decimal(0),
    )
    result = _ma_divergence_from_ma_series(
        "ma_divergence_sma_2_5", Version(value="v1"), IID, TF, (fast,), (slow_zero,)
    )
    assert result == ()  # skipped, no exception, no fabricated inf/None


# ---------------------------------------------------------------------------
# E. Determinism.
# ---------------------------------------------------------------------------


def test_e1_determinism() -> None:
    bars = tuple(_bar(i, str(100 + (i % 4) - 2)) for i in range(15))
    assert compute_ma_divergence_sma(
        MaDivergenceSmaDefinition(2, 5), bars
    ) == compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars)
    assert compute_ma_divergence_ema(
        MaDivergenceEmaDefinition(2, 5), bars
    ) == compute_ma_divergence_ema(MaDivergenceEmaDefinition(2, 5), bars)


# ---------------------------------------------------------------------------
# F. No-lookahead.
# ---------------------------------------------------------------------------


def _mutate_last_bar(bars: tuple[Bar, ...]) -> tuple[Bar, ...]:
    last = bars[-1]
    mutated = Bar(
        instrument_id=last.instrument_id,
        timeframe=last.timeframe,
        timestamp=last.timestamp,
        open=last.open + Decimal("50"),
        high=last.high + Decimal("60"),
        low=max(last.low - Decimal("10"), Decimal("1")),
        close=last.close + Decimal("55"),
        volume=last.volume + Decimal("999"),
    )
    return bars[:-1] + (mutated,)


def test_f1_sma_no_lookahead_mutation() -> None:
    bars = tuple(_bar(i, str(100 + (i % 3) - 1)) for i in range(12))
    mutated_bars = _mutate_last_bar(bars)
    original = compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars)
    mutated = compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), mutated_bars)
    assert original[:-1] == mutated[:-1]


def test_f2_ema_no_lookahead_mutation() -> None:
    bars = tuple(_bar(i, str(100 + (i % 3) - 1)) for i in range(12))
    mutated_bars = _mutate_last_bar(bars)
    original = compute_ma_divergence_ema(MaDivergenceEmaDefinition(2, 5), bars)
    mutated = compute_ma_divergence_ema(MaDivergenceEmaDefinition(2, 5), mutated_bars)
    assert original[:-1] == mutated[:-1]


def test_f3_future_bar_does_not_influence_earlier_output() -> None:
    short_series = tuple(_bar(i, str(100 + i)) for i in range(7))
    longer_series = short_series + (_bar(7, "999"),)
    definition = MaDivergenceSmaDefinition(2, 5)
    short_values = compute_ma_divergence_sma(definition, short_series)
    longer_values = compute_ma_divergence_sma(definition, longer_series)
    assert short_values[0] == longer_values[0]


# ---------------------------------------------------------------------------
# G. Series-integrity edge cases (reused domain rules).
# ---------------------------------------------------------------------------


def test_g1_mixed_instrument_rejected() -> None:
    other = InstrumentId("OTHER")
    prev = _bar(0, "100")
    curr = Bar(
        instrument_id=other,
        timeframe=TF,
        timestamp=BASE_TS + timedelta(minutes=1),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("100"),
    )
    with pytest.raises(MixedInstrumentSeriesError):
        compute_ma_divergence_sma(MaDivergenceSmaDefinition(1, 2), (prev, curr))


def test_g2_mixed_timeframe_rejected() -> None:
    prev = _bar(0, "100")
    curr = Bar(
        instrument_id=IID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=BASE_TS + timedelta(minutes=1),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("100"),
    )
    with pytest.raises(MixedTimeframeSeriesError):
        compute_ma_divergence_ema(MaDivergenceEmaDefinition(1, 2), (prev, curr))


def test_g3_duplicate_timestamps_rejected() -> None:
    bar = _bar(0, "100")
    with pytest.raises(DuplicateBarTimestampError):
        compute_ma_divergence_sma(MaDivergenceSmaDefinition(1, 2), (bar, bar))


def test_g4_out_of_order_rejected() -> None:
    bars = (_bar(1, "100"), _bar(0, "101"))
    with pytest.raises(OutOfOrderBarError):
        compute_ma_divergence_ema(MaDivergenceEmaDefinition(1, 2), bars)


# ---------------------------------------------------------------------------
# H. Registry / dispatcher integration.
# ---------------------------------------------------------------------------


def test_h1_new_fields_registered() -> None:
    ids = {f.field_id for f in list_fields()}
    assert "ma_divergence_sma" in ids
    assert "ma_divergence_ema" in ids


def test_h2_get_field_returns_definitions() -> None:
    for field_id in ("ma_divergence_sma", "ma_divergence_ema"):
        field = get_field(field_id)
        assert field is not None
        assert is_parameterized_feature(field_id) is True


def test_h3_existing_fields_unaffected() -> None:
    ids = {f.field_id for f in list_fields()}
    for original in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "sma",
        "ema",
        "atr",
        "rsi",
        "adx",
        "plus_di",
        "minus_di",
        "relative_volume",
        "macd_hist",
        "candle_body_ratio",
        "bullish_engulfing",
        "bearish_engulfing",
        "price_delta",
        "price_vs_ma_pct_sma",
        "price_vs_ma_pct_ema",
        "rebound_candidate",
    ):
        assert original in ids


def test_h4_dispatcher_computes_new_fields() -> None:
    bars = tuple(_bar(i, str(100 + (i % 3) - 1)) for i in range(20))
    sma_result = compute_feature_series("ma_divergence_sma_2_5", bars)
    ema_result = compute_feature_series("ma_divergence_ema_2_5", bars)
    assert sma_result
    assert ema_result
    assert sma_result == compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars)
    assert ema_result == compute_ma_divergence_ema(MaDivergenceEmaDefinition(2, 5), bars)


def test_h5_never_boolean_output_and_is_decimal() -> None:
    bars = tuple(_bar(i, str(100 + i)) for i in range(10))
    values = compute_ma_divergence_sma(MaDivergenceSmaDefinition(2, 5), bars)
    for v in values:
        assert isinstance(v.value, Decimal)
        assert not isinstance(v.value, bool)


def test_h6_dispatcher_rejects_invalid_fast_slow_combination() -> None:
    bars = tuple(_bar(i, "100") for i in range(10))
    with pytest.raises(InvalidLookbackError):
        compute_feature_series("ma_divergence_sma_5_5", bars)
