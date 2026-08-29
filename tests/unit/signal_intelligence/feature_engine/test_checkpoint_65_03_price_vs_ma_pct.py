# File: tests/unit/signal_intelligence/feature_engine/
#   test_checkpoint_65_03_price_vs_ma_pct.py
#
# Checkpoint 65.03: CANONICAL MARKET CONTEXT FEATURE - price_vs_ma_pct.
# REDUCED, TARGETED testing only (per checkpoint directive) - covers
# positive/negative/zero divergence, warm-up, zero-MA handling, parameter
# handling, determinism, no-lookahead, and registry/dispatcher
# integration. Does NOT re-run the full suite.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import DuplicateBarTimestampError, OutOfOrderBarError
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import (
    PriceVsMaPctEmaDefinition,
    PriceVsMaPctSmaDefinition,
)
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
from intraday.signal_intelligence.feature_engine.price_vs_ma_pct import (
    compute_price_vs_ma_pct_ema,
    compute_price_vs_ma_pct_sma,
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


def test_a1_positive_divergence_price_above_sma() -> None:
    # Flat closes at 100 for 3 bars (SMA(3) seeds at bar index 2 = 100),
    # then a close well above the MA.
    bars = tuple(_bar(i, "100") for i in range(3)) + (_bar(3, "112"),)
    values = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars)
    # sma at bar3 = mean(100,100,112) = 104 ; (112-104)/104 > 0
    last = values[-1]
    assert last.value > 0


def test_a2_negative_divergence_price_below_sma() -> None:
    bars = tuple(_bar(i, "100") for i in range(3)) + (_bar(3, "88"),)
    values = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars)
    assert values[-1].value < 0


def test_a3_zero_divergence_price_equals_ma() -> None:
    bars = tuple(_bar(i, "100") for i in range(5))
    values = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars)
    assert all(v.value == Decimal(0) for v in values)


def test_a4_exact_formula_sma() -> None:
    bars = (
        _bar(0, "100"),
        _bar(1, "110"),
        _bar(2, "120"),
    )
    values = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars)
    assert len(values) == 1
    sma = (Decimal(100) + Decimal(110) + Decimal(120)) / 3
    expected = (Decimal(120) - sma) / sma
    assert values[0].value == expected


def test_a5_exact_formula_ema() -> None:
    bars = tuple(_bar(i, str(100 + i)) for i in range(6))
    values = compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(3), bars)
    from intraday.signal_intelligence.feature_engine.ema import (
        compute_exponential_moving_average,
    )
    from intraday.signal_intelligence.feature_engine.definitions import (
        ExponentialMovingAverageDefinition,
    )

    ema_values = compute_exponential_moving_average(ExponentialMovingAverageDefinition(3), bars)
    assert len(values) == len(ema_values)
    for fv, ema in zip(values, ema_values, strict=True):
        expected = (bars[[b.timestamp for b in bars].index(ema.timestamp)].close - ema.value) / (
            ema.value
        )
        assert fv.value == expected


# ---------------------------------------------------------------------------
# B. Warm-up.
# ---------------------------------------------------------------------------


def test_b1_sma_warmup_no_output_before_lookback() -> None:
    bars = tuple(_bar(i, "100") for i in range(2))  # only 2 bars, lookback 3
    assert compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars) == ()


def test_b2_sma_warmup_first_output_exactly_at_lookback() -> None:
    bars = tuple(_bar(i, "100") for i in range(3))
    values = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars)
    assert len(values) == 1
    assert values[0].timestamp == bars[2].timestamp


def test_b3_ema_warmup_matches_underlying_ema_seed_index() -> None:
    bars = tuple(_bar(i, str(100 + i)) for i in range(5))
    values = compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(3), bars)
    assert len(values) == 5 - 3 + 1
    assert values[0].timestamp == bars[2].timestamp


def test_b4_empty_series() -> None:
    assert compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(5), ()) == ()
    assert compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(5), ()) == ()


# ---------------------------------------------------------------------------
# C. Zero-MA handling (divide-by-zero safety).
# ---------------------------------------------------------------------------


def test_c1_zero_sma_output_is_skipped_not_raised() -> None:
    # SMA(3) of closes (10, -5, -5) = 0 exactly -> that output must be
    # skipped, never a ZeroDivisionError. (Bar's own invariant forbids
    # non-positive close, so we approximate the "MA reaches zero" edge
    # case by directly exercising the shared core helper against a
    # synthetic MA series rather than fabricating negative-close bars
    # domain rules disallow.)
    from intraday.signal_intelligence.feature_engine.price_vs_ma_pct import (
        _price_vs_ma_pct_from_ma_series,
    )
    from intraday.domain.feature.contracts import FeatureValue
    from intraday.domain.shared_kernel.contracts import Version

    bars = (_bar(0, "100"),)
    zero_ma = FeatureValue(
        feature_name="sma_1",
        feature_version=Version(value="v1"),
        instrument_id=IID,
        timeframe=TF,
        timestamp=bars[0].timestamp,
        value=Decimal(0),
    )
    result = _price_vs_ma_pct_from_ma_series("price_vs_ma_pct_sma_1", Version(value="v1"), bars, (zero_ma,))
    assert result == ()  # skipped, no exception


# ---------------------------------------------------------------------------
# D. Parameter handling.
# ---------------------------------------------------------------------------


def test_d1_configurable_lookback_sma() -> None:
    bars = tuple(_bar(i, str(100 + i)) for i in range(20))
    v5 = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(5), bars)
    v10 = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(10), bars)
    assert len(v5) == 20 - 5 + 1
    assert len(v10) == 20 - 10 + 1
    assert v5[0].feature_name == "price_vs_ma_pct_sma_5"
    assert v10[0].feature_name == "price_vs_ma_pct_sma_10"


def test_d2_rejects_non_positive_lookback() -> None:
    with pytest.raises(InvalidLookbackError):
        PriceVsMaPctSmaDefinition(0)
    with pytest.raises(InvalidLookbackError):
        PriceVsMaPctEmaDefinition(-1)


def test_d3_no_hardcoded_default_lookback() -> None:
    with pytest.raises(TypeError):
        PriceVsMaPctSmaDefinition()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        PriceVsMaPctEmaDefinition()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# E. Determinism.
# ---------------------------------------------------------------------------


def test_e1_determinism() -> None:
    bars = tuple(_bar(i, str(100 + (i % 4) - 2)) for i in range(12))
    assert compute_price_vs_ma_pct_sma(
        PriceVsMaPctSmaDefinition(3), bars
    ) == compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars)
    assert compute_price_vs_ma_pct_ema(
        PriceVsMaPctEmaDefinition(3), bars
    ) == compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(3), bars)


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


def test_f1_sma_no_lookahead() -> None:
    bars = tuple(_bar(i, str(100 + (i % 3) - 1)) for i in range(10))
    mutated_bars = _mutate_last_bar(bars)
    original = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars)
    mutated = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), mutated_bars)
    assert original[:-1] == mutated[:-1]


def test_f2_ema_no_lookahead() -> None:
    bars = tuple(_bar(i, str(100 + (i % 3) - 1)) for i in range(10))
    mutated_bars = _mutate_last_bar(bars)
    original = compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(3), bars)
    mutated = compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(3), mutated_bars)
    assert original[:-1] == mutated[:-1]


def test_f3_future_bar_does_not_influence_earlier_output() -> None:
    short_series = tuple(_bar(i, str(100 + i)) for i in range(5))
    longer_series = short_series + (_bar(5, "999"),)
    definition = PriceVsMaPctSmaDefinition(3)
    short_values = compute_price_vs_ma_pct_sma(definition, short_series)
    longer_values = compute_price_vs_ma_pct_sma(definition, longer_series)
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
        compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(1), (prev, curr))


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
        compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(1), (prev, curr))


def test_g3_duplicate_timestamps_rejected() -> None:
    bar = _bar(0, "100")
    with pytest.raises(DuplicateBarTimestampError):
        compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(1), (bar, bar))


def test_g4_out_of_order_rejected() -> None:
    bars = (_bar(1, "100"), _bar(0, "101"))
    with pytest.raises(OutOfOrderBarError):
        compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(1), bars)


# ---------------------------------------------------------------------------
# H. Registry / dispatcher integration.
# ---------------------------------------------------------------------------


def test_h1_new_fields_registered() -> None:
    ids = {f.field_id for f in list_fields()}
    assert "price_vs_ma_pct_sma" in ids
    assert "price_vs_ma_pct_ema" in ids


def test_h2_get_field_returns_definitions() -> None:
    for field_id in ("price_vs_ma_pct_sma", "price_vs_ma_pct_ema"):
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
    ):
        assert original in ids


def test_h4_dispatcher_computes_new_fields() -> None:
    bars = tuple(_bar(i, str(100 + (i % 3) - 1)) for i in range(15))
    sma_result = compute_feature_series("price_vs_ma_pct_sma_5", bars)
    ema_result = compute_feature_series("price_vs_ma_pct_ema_5", bars)
    assert sma_result
    assert ema_result
    assert sma_result == compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(5), bars)
    assert ema_result == compute_price_vs_ma_pct_ema(PriceVsMaPctEmaDefinition(5), bars)


def test_h5_never_boolean_output() -> None:
    bars = tuple(_bar(i, str(100 + i)) for i in range(10))
    values = compute_price_vs_ma_pct_sma(PriceVsMaPctSmaDefinition(3), bars)
    for v in values:
        assert isinstance(v.value, Decimal)
        assert not isinstance(v.value, bool)
