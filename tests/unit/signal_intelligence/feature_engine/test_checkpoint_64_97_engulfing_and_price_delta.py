# File: tests/unit/signal_intelligence/feature_engine/
#   test_checkpoint_64_97_engulfing_and_price_delta.py
#
# Checkpoint 64.97: CANONICAL FEATURE ENGINE EXTENSION - Bullish
# Engulfing, Bearish Engulfing, Price Delta.
#
# HONESTY NOTICE: these are GENERIC, standard candlestick/price features.
# They are structurally similar to columns in the user-supplied
# research/rebuild reference file
# (docs/research/gainz_signal_engine_reference.py, read-only, never
# modified) but are NOT claimed to be verified authentic GainzAlgo
# mathematics - see docs/research/GAINZ_SIGNAL_ENGINE_AUDIT.md.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import DuplicateBarTimestampError, OutOfOrderBarError
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.bearish_engulfing import (
    BEARISH_ENGULFING_FIELD_ID,
    compute_bearish_engulfing,
)
from intraday.signal_intelligence.feature_engine.bullish_engulfing import (
    BULLISH_ENGULFING_FIELD_ID,
    compute_bullish_engulfing,
)
from intraday.signal_intelligence.feature_engine.definitions import PriceDeltaDefinition
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
from intraday.signal_intelligence.feature_engine.price_delta import (
    REFERENCE_ARTIFACT_DEFAULT_LOOKBACK,
    compute_price_delta,
)

IID = InstrumentId("TEST")
TF = Timeframe.ONE_MINUTE
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(i: int, o: str, h: str, lo: str, c: str, v: str = "100") -> Bar:
    open_d, high_d, low_d, close_d = Decimal(o), Decimal(h), Decimal(lo), Decimal(c)
    # Widen high/low if needed so open/close always lie within [low, high]
    # (Bar.__post_init__'s own invariant) - callers below pick simple
    # round-number OHLC without hand-checking every close against a fixed
    # high/low.
    high_d = max(high_d, open_d, close_d)
    low_d = min(low_d, open_d, close_d)
    return Bar(
        instrument_id=IID,
        timeframe=TF,
        timestamp=BASE_TS + timedelta(minutes=i),
        open=open_d,
        high=high_d,
        low=low_d,
        close=close_d,
        volume=Decimal(v),
    )


# ---------------------------------------------------------------------------
# A. Bullish Engulfing correctness.
# ---------------------------------------------------------------------------


def test_a1_bullish_engulfing_true() -> None:
    # prev bearish (open 110 -> close 100), curr bullish and engulfs it
    # (open 99 <= prev close 100, close 112 > prev open 110).
    prev = _bar(0, "110", "111", "99", "100")
    curr = _bar(1, "99", "113", "98", "112")
    values = compute_bullish_engulfing((prev, curr))
    assert len(values) == 1
    assert values[0].value == Decimal(1)
    assert values[0].feature_name == BULLISH_ENGULFING_FIELD_ID
    assert values[0].timestamp == curr.timestamp


def test_a2_bullish_engulfing_false_when_not_engulfing() -> None:
    # curr is bullish but does NOT engulf (close only 105, prev open 110).
    prev = _bar(0, "110", "111", "99", "100")
    curr = _bar(1, "101", "106", "100", "105")
    values = compute_bullish_engulfing((prev, curr))
    assert len(values) == 1
    assert values[0].value == Decimal(0)


def test_a3_bullish_engulfing_false_when_prev_not_bearish() -> None:
    prev = _bar(0, "100", "111", "99", "110")  # prev bullish
    curr = _bar(1, "99", "120", "98", "115")
    values = compute_bullish_engulfing((prev, curr))
    assert values[0].value == Decimal(0)


def test_a4_bullish_engulfing_boundary_equal_open_and_prev_close() -> None:
    # curr.open == prev.close exactly (the <= boundary) - must count.
    prev = _bar(0, "110", "111", "99", "100")
    curr = _bar(1, "100", "113", "99", "112")
    values = compute_bullish_engulfing((prev, curr))
    assert values[0].value == Decimal(1)


def test_a5_bullish_engulfing_first_bar_warmup_no_value() -> None:
    values = compute_bullish_engulfing((_bar(0, "100", "101", "99", "100"),))
    assert values == ()


def test_a6_bullish_engulfing_empty_series() -> None:
    assert compute_bullish_engulfing(()) == ()


# ---------------------------------------------------------------------------
# B. Bearish Engulfing correctness.
# ---------------------------------------------------------------------------


def test_b1_bearish_engulfing_true() -> None:
    prev = _bar(0, "100", "111", "99", "110")  # prev bullish
    curr = _bar(1, "111", "112", "97", "98")  # curr bearish, engulfs
    values = compute_bearish_engulfing((prev, curr))
    assert len(values) == 1
    assert values[0].value == Decimal(1)
    assert values[0].feature_name == BEARISH_ENGULFING_FIELD_ID


def test_b2_bearish_engulfing_false_when_not_engulfing() -> None:
    prev = _bar(0, "100", "111", "99", "110")
    curr = _bar(1, "109", "110", "105", "106")  # bearish but not engulfing
    values = compute_bearish_engulfing((prev, curr))
    assert values[0].value == Decimal(0)


def test_b3_bearish_engulfing_false_when_prev_not_bullish() -> None:
    prev = _bar(0, "110", "111", "99", "100")  # prev bearish
    curr = _bar(1, "111", "112", "80", "90")
    values = compute_bearish_engulfing((prev, curr))
    assert values[0].value == Decimal(0)


def test_b4_bearish_engulfing_boundary_equal_open_and_prev_close() -> None:
    prev = _bar(0, "100", "111", "99", "110")
    curr = _bar(1, "110", "112", "97", "98")  # curr.open == prev.close exactly
    values = compute_bearish_engulfing((prev, curr))
    assert values[0].value == Decimal(1)


def test_b5_bearish_engulfing_first_bar_warmup_no_value() -> None:
    assert compute_bearish_engulfing((_bar(0, "100", "101", "99", "100"),)) == ()


def test_b6_flat_candles_never_engulf() -> None:
    # equal opens/closes on both bars - neither candle is bullish nor
    # bearish, so neither pattern can fire.
    prev = _bar(0, "100", "101", "99", "100")
    curr = _bar(1, "100", "101", "99", "100")
    assert compute_bullish_engulfing((prev, curr))[0].value == Decimal(0)
    assert compute_bearish_engulfing((prev, curr))[0].value == Decimal(0)


def test_b7_gap_up_open_breaks_bullish_engulfing_condition() -> None:
    # curr opens ABOVE prev close (gap up) -> open <= prev.close fails.
    prev = _bar(0, "110", "111", "99", "100")
    curr = _bar(1, "105", "120", "104", "119")
    values = compute_bullish_engulfing((prev, curr))
    assert values[0].value == Decimal(0)


def test_b8_gap_down_open_breaks_bearish_engulfing_condition() -> None:
    prev = _bar(0, "100", "111", "99", "110")
    curr = _bar(1, "105", "106", "80", "90")  # opens BELOW prev close (gap down)
    values = compute_bearish_engulfing((prev, curr))
    assert values[0].value == Decimal(0)


# ---------------------------------------------------------------------------
# C. Price Delta correctness.
# ---------------------------------------------------------------------------


def test_c1_price_delta_positive() -> None:
    bars = tuple(_bar(i, "100", "101", "99", str(100 + i)) for i in range(5))
    values = compute_price_delta(PriceDeltaDefinition(2), bars)
    # close[2]-close[0]=102-100=2 ; close[3]-close[1]=103-101=2 ; close[4]-close[2]=104-102=2
    assert [v.value for v in values] == [Decimal(2), Decimal(2), Decimal(2)]


def test_c2_price_delta_negative() -> None:
    bars = tuple(_bar(i, "100", "101", "99", str(110 - i)) for i in range(5))
    values = compute_price_delta(PriceDeltaDefinition(2), bars)
    assert all(v.value == Decimal(-2) for v in values)


def test_c3_price_delta_zero() -> None:
    bars = tuple(_bar(i, "100", "101", "99", "100") for i in range(5))
    values = compute_price_delta(PriceDeltaDefinition(2), bars)
    assert all(v.value == Decimal(0) for v in values)


def test_c4_price_delta_insufficient_history() -> None:
    bars = tuple(_bar(i, "100", "101", "99", "100") for i in range(3))
    assert compute_price_delta(PriceDeltaDefinition(10), bars) == ()


def test_c5_price_delta_configurable_lookback() -> None:
    bars = tuple(_bar(i, "100", "101", "99", str(100 + i)) for i in range(20))
    d5 = compute_price_delta(PriceDeltaDefinition(5), bars)
    d10 = compute_price_delta(PriceDeltaDefinition(10), bars)
    assert len(d5) == 20 - 5
    assert len(d10) == 20 - 10
    assert d5[0].value == Decimal(5)
    assert d10[0].value == Decimal(10)


def test_c6_price_delta_empty_series() -> None:
    assert compute_price_delta(PriceDeltaDefinition(10), ()) == ()


def test_c7_price_delta_reference_default_is_documented_not_hardcoded() -> None:
    # REFERENCE-ARTIFACT DEFAULT only - not baked into any Definition
    # default, must be supplied explicitly by a caller.
    assert REFERENCE_ARTIFACT_DEFAULT_LOOKBACK == 10
    with pytest.raises(TypeError):
        PriceDeltaDefinition()  # type: ignore[call-arg]


def test_c8_price_delta_rejects_non_positive_lookback() -> None:
    with pytest.raises(InvalidLookbackError):
        PriceDeltaDefinition(0)
    with pytest.raises(InvalidLookbackError):
        PriceDeltaDefinition(-3)


# ---------------------------------------------------------------------------
# D. No-lookahead safety (mandatory).
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


def test_d1_bullish_engulfing_no_lookahead() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + (i % 3) - 1)) for i in range(10))
    mutated_bars = _mutate_last_bar(bars)
    original = compute_bullish_engulfing(bars)
    mutated = compute_bullish_engulfing(mutated_bars)
    assert original[:-1] == mutated[:-1]


def test_d2_bearish_engulfing_no_lookahead() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + (i % 3) - 1)) for i in range(10))
    mutated_bars = _mutate_last_bar(bars)
    original = compute_bearish_engulfing(bars)
    mutated = compute_bearish_engulfing(mutated_bars)
    assert original[:-1] == mutated[:-1]


def test_d3_price_delta_no_lookahead() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + i)) for i in range(15))
    mutated_bars = _mutate_last_bar(bars)
    original = compute_price_delta(PriceDeltaDefinition(5), bars)
    mutated = compute_price_delta(PriceDeltaDefinition(5), mutated_bars)
    assert original[:-1] == mutated[:-1]
    assert original[-1] != mutated[-1]  # sanity: mutation DID matter for the last value


def test_d4_mutating_middle_future_bar_leaves_earlier_engulfing_unchanged() -> None:
    bars = [_bar(i, "100", "105", "95", str(100 + (i % 3) - 1)) for i in range(20)]
    mutate_index = 12
    original = compute_bullish_engulfing(tuple(bars))
    victim = bars[mutate_index]
    bars[mutate_index] = Bar(
        instrument_id=victim.instrument_id,
        timeframe=victim.timeframe,
        timestamp=victim.timestamp,
        open=victim.open + Decimal("30"),
        high=victim.high + Decimal("40"),
        low=max(victim.low - Decimal("5"), Decimal("1")),
        close=victim.close + Decimal("35"),
        volume=victim.volume,
    )
    mutated = compute_bullish_engulfing(tuple(bars))
    victim_ts = victim.timestamp
    original_before = [fv for fv in original if fv.timestamp < victim_ts]
    mutated_before = [fv for fv in mutated if fv.timestamp < victim_ts]
    assert original_before == mutated_before
    assert original_before  # sanity: there IS history before the mutation point


def test_d5_price_delta_future_bar_does_not_influence_earlier_output() -> None:
    short_series = tuple(_bar(i, "100", "101", "99", str(100 + i)) for i in range(5))
    longer_series = short_series + (_bar(5, "100", "101", "99", "999"),)
    definition = PriceDeltaDefinition(3)
    short_values = compute_price_delta(definition, short_series)
    longer_values = compute_price_delta(definition, longer_series)
    assert short_values[0] == longer_values[0]


# ---------------------------------------------------------------------------
# E. Determinism.
# ---------------------------------------------------------------------------


def test_e1_determinism() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + (i % 4) - 2)) for i in range(12))
    assert compute_bullish_engulfing(bars) == compute_bullish_engulfing(bars)
    assert compute_bearish_engulfing(bars) == compute_bearish_engulfing(bars)
    assert compute_price_delta(PriceDeltaDefinition(3), bars) == compute_price_delta(
        PriceDeltaDefinition(3), bars
    )


# ---------------------------------------------------------------------------
# F. Edge cases / series integrity (reused domain rules, not reimplemented).
# ---------------------------------------------------------------------------


def test_f1_mixed_instrument_rejected() -> None:
    other = InstrumentId("OTHER")
    prev = _bar(0, "100", "101", "99", "100")
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
        compute_bullish_engulfing((prev, curr))
    with pytest.raises(MixedInstrumentSeriesError):
        compute_price_delta(PriceDeltaDefinition(1), (prev, curr))


def test_f2_mixed_timeframe_rejected() -> None:
    prev = _bar(0, "100", "101", "99", "100")
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
        compute_bearish_engulfing((prev, curr))
    with pytest.raises(MixedTimeframeSeriesError):
        compute_price_delta(PriceDeltaDefinition(1), (prev, curr))


def test_f3_duplicate_timestamps_rejected() -> None:
    bar = _bar(0, "100", "101", "99", "100")
    with pytest.raises(DuplicateBarTimestampError):
        compute_bullish_engulfing((bar, bar))
    with pytest.raises(DuplicateBarTimestampError):
        compute_price_delta(PriceDeltaDefinition(1), (bar, bar))


def test_f4_out_of_order_rejected() -> None:
    bars = (_bar(1, "100", "101", "99", "100"), _bar(0, "100", "101", "99", "101"))
    with pytest.raises(OutOfOrderBarError):
        compute_bearish_engulfing(bars)
    with pytest.raises(OutOfOrderBarError):
        compute_price_delta(PriceDeltaDefinition(1), bars)


def test_f5_two_row_dataset_produces_exactly_one_engulfing_value() -> None:
    bars = (_bar(0, "110", "111", "99", "100"), _bar(1, "99", "113", "98", "112"))
    assert len(compute_bullish_engulfing(bars)) == 1
    assert len(compute_bearish_engulfing(bars)) == 1


# ---------------------------------------------------------------------------
# G. Registry integration.
# ---------------------------------------------------------------------------


def test_g1_new_fields_registered() -> None:
    ids = {f.field_id for f in list_fields()}
    for expected in ("bullish_engulfing", "bearish_engulfing", "price_delta"):
        assert expected in ids


def test_g2_get_field_returns_definitions() -> None:
    for field_id in ("bullish_engulfing", "bearish_engulfing", "price_delta"):
        field = get_field(field_id)
        assert field is not None
        assert is_parameterized_feature(field_id) is True


def test_g3_existing_fields_unaffected() -> None:
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
    ):
        assert original in ids


def test_g4_dispatcher_computes_new_fields() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + (i % 3) - 1)) for i in range(15))
    bullish = compute_feature_series("bullish_engulfing", bars)
    bearish = compute_feature_series("bearish_engulfing", bars)
    delta = compute_feature_series("price_delta_5", bars)
    assert bullish
    assert bearish
    assert delta
    assert bullish == compute_bullish_engulfing(bars)
    assert bearish == compute_bearish_engulfing(bars)
    assert delta == compute_price_delta(PriceDeltaDefinition(5), bars)


def test_g5_dispatcher_unrecognized_field_still_raises() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        compute_feature_series("not_a_real_field", (_bar(0, "100", "101", "99", "100"),))


# ---------------------------------------------------------------------------
# H. Reference comparison - canonical vs reference-file logic, on
# identical clean inputs. NOT a test of authentic Gainz behaviour - a
# divergence-detection fixture only.
# ---------------------------------------------------------------------------


def _reference_bullish_engulfing(prev: Bar, curr: Bar) -> bool:
    """Hand-transcribed from `gainz_signal_engine_reference.py`'s own
    `x["bullish_engulfing"]` pandas expression (read-only source, never
    executed/imported - transcribed only for this comparison)."""
    return bool(
        prev.close < prev.open
        and curr.close > curr.open
        and curr.close > prev.open
        and curr.open <= prev.close
    )


def _reference_bearish_engulfing(prev: Bar, curr: Bar) -> bool:
    return bool(
        prev.close > prev.open
        and curr.close < curr.open
        and curr.close < prev.open
        and curr.open >= prev.close
    )


def _reference_price_delta_signals(closes: list[Decimal], n: int, index: int) -> tuple[bool, bool]:
    """`price_up_delta`/`price_down_delta` from the reference file - two
    booleans, recoverable from this checkpoint's signed delta via
    `> 0`/`< 0`."""
    if index < n:
        raise IndexError("insufficient history for reference comparison")
    up = closes[index] > closes[index - n]
    down = closes[index] < closes[index - n]
    return up, down


def test_h1_bullish_engulfing_matches_reference_logic_on_clean_inputs() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + (i % 3) - 1)) for i in range(20))
    canonical = compute_bullish_engulfing(bars)
    for i in range(1, len(bars)):
        expected = _reference_bullish_engulfing(bars[i - 1], bars[i])
        actual = canonical[i - 1].value == Decimal(1)
        assert actual == expected, f"MISMATCH at index {i}: canonical={actual} reference={expected}"


def test_h2_bearish_engulfing_matches_reference_logic_on_clean_inputs() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + (i % 3) - 1)) for i in range(20))
    canonical = compute_bearish_engulfing(bars)
    for i in range(1, len(bars)):
        expected = _reference_bearish_engulfing(bars[i - 1], bars[i])
        actual = canonical[i - 1].value == Decimal(1)
        assert actual == expected, f"MISMATCH at index {i}: canonical={actual} reference={expected}"


def test_h3_price_delta_sign_matches_reference_up_down_booleans() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + i - (i % 5))) for i in range(25))
    closes = [b.close for b in bars]
    n = 5
    canonical = compute_price_delta(PriceDeltaDefinition(n), bars)
    for offset, fv in enumerate(canonical):
        index = n + offset
        up, down = _reference_price_delta_signals(closes, n, index)
        if fv.value > 0:
            assert up and not down
        elif fv.value < 0:
            assert down and not up
        else:
            assert not up and not down
