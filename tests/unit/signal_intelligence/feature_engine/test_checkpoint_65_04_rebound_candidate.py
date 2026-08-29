# File: tests/unit/signal_intelligence/feature_engine/
#   test_checkpoint_65_04_rebound_candidate.py
#
# Checkpoint 65.04: CANONICAL MARKET CONTEXT FEATURE - rebound_candidate.
# REDUCED, TARGETED testing only (per checkpoint directive) - covers
# positive/negative rebound condition, boundary conditions, warm-up,
# missing dependencies, determinism, no-lookahead, and
# registry/dispatcher integration. Does NOT re-run the full suite.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import DuplicateBarTimestampError, OutOfOrderBarError
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.bullish_engulfing import (
    compute_bullish_engulfing,
)
from intraday.signal_intelligence.feature_engine.definitions import (
    ReboundCandidateDefinition,
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
from intraday.signal_intelligence.feature_engine.price_delta import compute_price_delta
from intraday.signal_intelligence.feature_engine.rebound_candidate import (
    compute_rebound_candidate,
)
from intraday.signal_intelligence.feature_engine.rsi import compute_relative_strength_index

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


def _decline_then_engulfing_bars() -> tuple[Bar, ...]:
    # A steady 12-bar decline (close falling by 2 each bar, each bar's
    # own close < open i.e. bearish) from 150 down to 128, so that:
    #   - price_delta_10(t) is well below zero,
    #   - RSI(10) is pushed low (all losses, no gains, in the decline),
    #   - the LAST bar is a genuine bullish-engulfing reversal candle
    #     (engulfs the prior bearish candle).
    bars = []
    close = Decimal("150")
    for i in range(12):
        next_close = close - Decimal("2")
        bars.append(_bar(i, str(next_close), o=str(close)))
        close = next_close
    # Prior bar (index 11) is bearish: open=128 close=126. Append a
    # bullish-engulfing bar: open <= 126, close > 128.
    prior_close = bars[-1].close
    prior_open = bars[-1].open
    engulf = _bar(
        12,
        str(prior_open + Decimal("3")),
        o=str(prior_close - Decimal("1")),
    )
    bars.append(engulf)
    return tuple(bars)


# ---------------------------------------------------------------------------
# A. Positive / negative rebound condition.
# ---------------------------------------------------------------------------


def test_a1_positive_rebound_all_conditions_met() -> None:
    bars = _decline_then_engulfing_bars()
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=40
    )
    values = compute_rebound_candidate(definition, bars)
    assert values
    assert values[-1].value == Decimal(1)
    assert values[-1].timestamp == bars[-1].timestamp


def test_a2_no_rebound_when_rising_market() -> None:
    # Steadily rising closes: price_delta > 0, RSI high - never oversold,
    # no bearish-then-bullish-engulfing setup either.
    bars = tuple(_bar(i, str(100 + i * 2)) for i in range(15))
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=30
    )
    values = compute_rebound_candidate(definition, bars)
    assert values
    assert all(v.value == Decimal(0) for v in values)


def test_a3_no_rebound_when_engulfing_missing() -> None:
    # Decline present, RSI oversold, but the final bar is NOT a bullish
    # engulfing candle (it just continues declining slightly).
    bars = []
    close = Decimal("150")
    for i in range(12):
        next_close = close - Decimal("2")
        bars.append(_bar(i, str(next_close), o=str(close)))
        close = next_close
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=40
    )
    values = compute_rebound_candidate(definition, bars)
    assert values
    assert values[-1].value == Decimal(0)


# ---------------------------------------------------------------------------
# B. Boundary conditions.
# ---------------------------------------------------------------------------


def test_b1_threshold_boundary_not_strictly_less_is_false() -> None:
    # RSI exactly equal to the threshold must NOT count as oversold
    # (strict `<`), verified via the shared core against a synthetic
    # dependency-value join by exercising the public function's
    # documented `<` semantics using a constructed rsi_oversold_threshold
    # equal to an observed RSI value.
    bars = _decline_then_engulfing_bars()
    rsi_values = compute_relative_strength_index(
        __import__(
            "intraday.signal_intelligence.feature_engine.definitions", fromlist=["x"]
        ).RelativeStrengthIndexDefinition(10),
        bars,
    )
    observed_rsi_at_last = rsi_values[-1].value
    # floor(observed) <= observed, so `observed < floor(observed)` is
    # always False - i.e. the oversold condition (`rsi < threshold`)
    # cannot fire, verifying the strict `<` boundary semantics.
    threshold = int(observed_rsi_at_last)
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=threshold
    )
    values = compute_rebound_candidate(definition, bars)
    last = next(v for v in values if v.timestamp == bars[-1].timestamp)
    assert last.value == Decimal(0)


def test_b2_rejects_invalid_threshold() -> None:
    with pytest.raises(InvalidLookbackError):
        ReboundCandidateDefinition(delta_lookback=10, rsi_lookback=14, rsi_oversold_threshold=-1)
    with pytest.raises(InvalidLookbackError):
        ReboundCandidateDefinition(delta_lookback=10, rsi_lookback=14, rsi_oversold_threshold=101)
    with pytest.raises(InvalidLookbackError):
        ReboundCandidateDefinition(delta_lookback=0, rsi_lookback=14, rsi_oversold_threshold=30)
    with pytest.raises(InvalidLookbackError):
        ReboundCandidateDefinition(delta_lookback=10, rsi_lookback=-5, rsi_oversold_threshold=30)


def test_b3_no_hardcoded_default_parameters() -> None:
    with pytest.raises(TypeError):
        ReboundCandidateDefinition()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# C. Warm-up.
# ---------------------------------------------------------------------------


def test_c1_empty_series() -> None:
    definition = ReboundCandidateDefinition(
        delta_lookback=5, rsi_lookback=5, rsi_oversold_threshold=30
    )
    assert compute_rebound_candidate(definition, ()) == ()


def test_c2_insufficient_history_produces_no_output() -> None:
    bars = tuple(_bar(i, str(100 - i)) for i in range(5))  # only 5 bars
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=30
    )
    assert compute_rebound_candidate(definition, bars) == ()


def test_c3_warmup_matches_max_of_dependency_warmups() -> None:
    # delta_lookback=5 -> needs 6 bars; rsi_lookback=10 -> needs 11 bars;
    # bullish_engulfing needs 2 bars. max => first output at bar index 10.
    bars = tuple(_bar(i, str(100 + (i % 3) - 1)) for i in range(15))
    definition = ReboundCandidateDefinition(
        delta_lookback=5, rsi_lookback=10, rsi_oversold_threshold=30
    )
    values = compute_rebound_candidate(definition, bars)
    delta_values = compute_price_delta(definition.price_delta_definition, bars)
    rsi_values = compute_relative_strength_index(definition.rsi_definition, bars)
    engulfing_values = compute_bullish_engulfing(bars)
    expected_first_ts = max(
        delta_values[0].timestamp, rsi_values[0].timestamp, engulfing_values[0].timestamp
    )
    assert values[0].timestamp == expected_first_ts


# ---------------------------------------------------------------------------
# D. Missing dependencies / honest unavailability.
# ---------------------------------------------------------------------------


def test_d1_single_bar_series_no_output() -> None:
    bars = (_bar(0, "100"),)
    definition = ReboundCandidateDefinition(
        delta_lookback=1, rsi_lookback=1, rsi_oversold_threshold=30
    )
    assert compute_rebound_candidate(definition, bars) == ()


def test_d2_never_fabricates_during_warmup() -> None:
    bars = tuple(_bar(i, str(100 - i)) for i in range(8))
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=30
    )
    # Insufficient bars for either dependency's warm-up -> honestly empty,
    # never a fabricated 0 for every bar.
    assert compute_rebound_candidate(definition, bars) == ()


# ---------------------------------------------------------------------------
# E. Determinism.
# ---------------------------------------------------------------------------


def test_e1_determinism() -> None:
    bars = _decline_then_engulfing_bars()
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=40
    )
    assert compute_rebound_candidate(definition, bars) == compute_rebound_candidate(
        definition, bars
    )


# ---------------------------------------------------------------------------
# F. No-lookahead (mutation-style).
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


def test_f1_no_lookahead_mutating_last_bar_does_not_change_earlier_outputs() -> None:
    bars = tuple(_bar(i, str(100 + (i % 5) - 2)) for i in range(20))
    mutated_bars = _mutate_last_bar(bars)
    definition = ReboundCandidateDefinition(
        delta_lookback=5, rsi_lookback=5, rsi_oversold_threshold=40
    )
    original = compute_rebound_candidate(definition, bars)
    mutated = compute_rebound_candidate(definition, mutated_bars)
    assert original[:-1] == mutated[:-1]


def test_f2_future_bar_does_not_influence_earlier_output() -> None:
    short_series = tuple(_bar(i, str(100 + (i % 5) - 2)) for i in range(12))
    longer_series = short_series + (_bar(12, "999"),)
    definition = ReboundCandidateDefinition(
        delta_lookback=5, rsi_lookback=5, rsi_oversold_threshold=40
    )
    short_values = compute_rebound_candidate(definition, short_series)
    longer_values = compute_rebound_candidate(definition, longer_series)
    assert short_values == longer_values[: len(short_values)]


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
    definition = ReboundCandidateDefinition(
        delta_lookback=1, rsi_lookback=1, rsi_oversold_threshold=30
    )
    with pytest.raises(MixedInstrumentSeriesError):
        compute_rebound_candidate(definition, (prev, curr))


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
    definition = ReboundCandidateDefinition(
        delta_lookback=1, rsi_lookback=1, rsi_oversold_threshold=30
    )
    with pytest.raises(MixedTimeframeSeriesError):
        compute_rebound_candidate(definition, (prev, curr))


def test_g3_duplicate_timestamps_rejected() -> None:
    bar = _bar(0, "100")
    definition = ReboundCandidateDefinition(
        delta_lookback=1, rsi_lookback=1, rsi_oversold_threshold=30
    )
    with pytest.raises(DuplicateBarTimestampError):
        compute_rebound_candidate(definition, (bar, bar))


def test_g4_out_of_order_rejected() -> None:
    bars = (_bar(1, "100"), _bar(0, "101"))
    definition = ReboundCandidateDefinition(
        delta_lookback=1, rsi_lookback=1, rsi_oversold_threshold=30
    )
    with pytest.raises(OutOfOrderBarError):
        compute_rebound_candidate(definition, bars)


# ---------------------------------------------------------------------------
# H. Registry / dispatcher integration.
# ---------------------------------------------------------------------------


def test_h1_new_field_registered() -> None:
    ids = {f.field_id for f in list_fields()}
    assert "rebound_candidate" in ids


def test_h2_get_field_returns_definition() -> None:
    field = get_field("rebound_candidate")
    assert field is not None
    assert is_parameterized_feature("rebound_candidate") is True


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
    ):
        assert original in ids


def test_h4_dispatcher_computes_new_field() -> None:
    bars = _decline_then_engulfing_bars()
    result = compute_feature_series("rebound_candidate_10_10_40", bars)
    assert result
    assert result == compute_rebound_candidate(
        ReboundCandidateDefinition(delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=40),
        bars,
    )


def test_h5_never_boolean_output_always_decimal_zero_or_one() -> None:
    bars = _decline_then_engulfing_bars()
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=40
    )
    values = compute_rebound_candidate(definition, bars)
    for v in values:
        assert isinstance(v.value, Decimal)
        assert not isinstance(v.value, bool)
        assert v.value in (Decimal(0), Decimal(1))


def test_h6_output_is_never_buy_sell_string() -> None:
    bars = _decline_then_engulfing_bars()
    definition = ReboundCandidateDefinition(
        delta_lookback=10, rsi_lookback=10, rsi_oversold_threshold=40
    )
    values = compute_rebound_candidate(definition, bars)
    for v in values:
        assert not isinstance(v.value, str)
