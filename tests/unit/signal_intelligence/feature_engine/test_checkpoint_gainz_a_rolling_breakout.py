# File: tests/unit/signal_intelligence/feature_engine/
#   test_checkpoint_gainz_a_rolling_breakout.py
#
# CHECKPOINT-GAINZ-A: Rolling N-Bar Breakout/Breakdown - unit tests,
# matching the fixture/assertion style established by
# `test_checkpoint_64_97_engulfing_and_price_delta.py` (`_bar()` helper,
# explicit arithmetic in comments, no magic-number assertions).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import DuplicateBarTimestampError, OutOfOrderBarError
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import RollingBreakoutDefinition
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
from intraday.signal_intelligence.feature_engine.rolling_breakout import compute_rolling_breakout

IID = InstrumentId("TEST")
TF = Timeframe.ONE_MINUTE
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(i: int, o: str, h: str, lo: str, c: str, v: str = "100") -> Bar:
    open_d, high_d, low_d, close_d = Decimal(o), Decimal(h), Decimal(lo), Decimal(c)
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
# A. Correctness - breakout / breakdown / range / warm-up.
# ---------------------------------------------------------------------------


def test_a1_clear_breakout() -> None:
    # 5 prior bars, high/low fixed at [95, 105] -> prior_high = 105,
    # prior_low = 95. 6th bar's close = 110 > prior_high 105 -> breakout.
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(5))
    breakout_bar = _bar(5, "106", "112", "106", "110")
    values = compute_rolling_breakout(RollingBreakoutDefinition(5), bars + (breakout_bar,))
    assert len(values) == 1
    assert values[0].value == Decimal(1)
    assert values[0].timestamp == breakout_bar.timestamp


def test_a2_clear_breakdown() -> None:
    # Same prior window (prior_high=105, prior_low=95). 6th bar's close =
    # 90 < prior_low 95 -> breakdown.
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(5))
    breakdown_bar = _bar(5, "94", "94", "88", "90")
    values = compute_rolling_breakout(RollingBreakoutDefinition(5), bars + (breakdown_bar,))
    assert len(values) == 1
    assert values[0].value == Decimal(-1)


def test_a3_no_breakout_stays_within_range() -> None:
    # 6th bar's close = 102, strictly inside (95, 105) -> neither.
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(5))
    range_bar = _bar(5, "101", "103", "99", "102")
    values = compute_rolling_breakout(RollingBreakoutDefinition(5), bars + (range_bar,))
    assert len(values) == 1
    assert values[0].value == Decimal(0)


def test_a4_close_exactly_equal_to_prior_high_is_not_a_breakout() -> None:
    # Strict `>` required - close == prior_high (105) is NOT a breakout.
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(5))
    boundary_bar = _bar(5, "100", "105", "99", "105")
    values = compute_rolling_breakout(RollingBreakoutDefinition(5), bars + (boundary_bar,))
    assert values[0].value == Decimal(0)


def test_a5_close_exactly_equal_to_prior_low_is_not_a_breakdown() -> None:
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(5))
    boundary_bar = _bar(5, "100", "101", "95", "95")
    values = compute_rolling_breakout(RollingBreakoutDefinition(5), bars + (boundary_bar,))
    assert values[0].value == Decimal(0)


def test_a6_insufficient_warmup_fewer_than_n_prior_bars() -> None:
    # Only 4 prior bars exist for an N=5 window -> no output at all.
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(4))
    values = compute_rolling_breakout(RollingBreakoutDefinition(5), bars)
    assert values == ()


def test_a7_empty_series() -> None:
    assert compute_rolling_breakout(RollingBreakoutDefinition(5), ()) == ()


def test_a8_first_output_is_exactly_at_bars_lookback_index() -> None:
    # N=3: bars[0..2] fill the window, bars[3] is the first bar that can
    # produce an output (matching relative_volume.py's warm-up shape).
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(6))
    values = compute_rolling_breakout(RollingBreakoutDefinition(3), bars)
    assert len(values) == 6 - 3
    assert values[0].timestamp == bars[3].timestamp


def test_a9_current_bar_high_low_never_included_in_own_window() -> None:
    # The breakout bar's OWN extreme high (200) must not leak into the
    # window used to test itself - only PRIOR bars' highs matter.
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(5))
    self_referential_bar = _bar(5, "100", "200", "95", "104")  # close 104 < prior_high 105
    values = compute_rolling_breakout(RollingBreakoutDefinition(5), bars + (self_referential_bar,))
    assert values[0].value == Decimal(0)  # NOT a breakout despite its own high=200


# ---------------------------------------------------------------------------
# B. Default parameter (N=20, not hardcoded elsewhere).
# ---------------------------------------------------------------------------


def test_b1_default_lookback_is_20() -> None:
    assert RollingBreakoutDefinition().lookback == 20
    assert RollingBreakoutDefinition().feature_name == "rolling_breakout_20"


def test_b2_lookback_is_configurable() -> None:
    assert RollingBreakoutDefinition(10).lookback == 10
    assert RollingBreakoutDefinition(10).feature_name == "rolling_breakout_10"


def test_b3_rejects_non_positive_lookback() -> None:
    with pytest.raises(InvalidLookbackError):
        RollingBreakoutDefinition(0)
    with pytest.raises(InvalidLookbackError):
        RollingBreakoutDefinition(-5)


# ---------------------------------------------------------------------------
# C. No-lookahead safety.
# ---------------------------------------------------------------------------


def test_c1_future_bar_does_not_influence_earlier_output() -> None:
    short_series = tuple(_bar(i, "100", "105", "95", "100") for i in range(6))
    longer_series = short_series + (_bar(6, "100", "500", "1", "500"),)
    definition = RollingBreakoutDefinition(5)
    short_values = compute_rolling_breakout(definition, short_series)
    longer_values = compute_rolling_breakout(definition, longer_series)
    assert short_values[0] == longer_values[0]


def test_c2_mutating_a_later_bar_leaves_earlier_output_unchanged() -> None:
    bars = [_bar(i, "100", "105", "95", "100") for i in range(8)]
    original = compute_rolling_breakout(RollingBreakoutDefinition(5), tuple(bars))
    victim = bars[7]
    bars[7] = Bar(
        instrument_id=victim.instrument_id,
        timeframe=victim.timeframe,
        timestamp=victim.timestamp,
        open=victim.open,
        high=Decimal("999"),
        low=victim.low,
        close=Decimal("999"),
        volume=victim.volume,
    )
    mutated = compute_rolling_breakout(RollingBreakoutDefinition(5), tuple(bars))
    assert original[:-1] == mutated[:-1]
    assert original[-1] != mutated[-1]


# ---------------------------------------------------------------------------
# D. Determinism.
# ---------------------------------------------------------------------------


def test_d1_determinism() -> None:
    bars = tuple(_bar(i, "100", "105", "95", str(100 + (i % 4) - 2)) for i in range(12))
    definition = RollingBreakoutDefinition(5)
    assert compute_rolling_breakout(definition, bars) == compute_rolling_breakout(
        definition, bars
    )


# ---------------------------------------------------------------------------
# E. Series integrity (reused domain rules, not reimplemented).
# ---------------------------------------------------------------------------


def test_e1_mixed_instrument_rejected() -> None:
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
        compute_rolling_breakout(RollingBreakoutDefinition(1), (prev, curr))


def test_e2_mixed_timeframe_rejected() -> None:
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
        compute_rolling_breakout(RollingBreakoutDefinition(1), (prev, curr))


def test_e3_duplicate_timestamps_rejected() -> None:
    bar = _bar(0, "100", "101", "99", "100")
    with pytest.raises(DuplicateBarTimestampError):
        compute_rolling_breakout(RollingBreakoutDefinition(1), (bar, bar))


def test_e4_out_of_order_rejected() -> None:
    bars = (_bar(1, "100", "101", "99", "100"), _bar(0, "100", "101", "99", "101"))
    with pytest.raises(OutOfOrderBarError):
        compute_rolling_breakout(RollingBreakoutDefinition(1), bars)


# ---------------------------------------------------------------------------
# F. Registry integration.
# ---------------------------------------------------------------------------


def test_f1_new_field_registered() -> None:
    ids = {f.field_id for f in list_fields()}
    assert "rolling_breakout" in ids


def test_f2_get_field_returns_definition() -> None:
    field = get_field("rolling_breakout")
    assert field is not None
    assert is_parameterized_feature("rolling_breakout") is True


def test_f3_existing_fields_unaffected() -> None:
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
        "ma_divergence_sma",
        "ma_divergence_ema",
        "market_regime",
    ):
        assert original in ids


def test_f4_dispatcher_computes_new_field() -> None:
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(8))
    values = compute_feature_series("rolling_breakout_5", bars)
    assert values == compute_rolling_breakout(RollingBreakoutDefinition(5), bars)


def test_f5_dispatcher_uses_default_lookback_when_no_param_given() -> None:
    # "rolling_breakout" with no trailing integer resolves to zero
    # params, so RollingBreakoutDefinition(*()) uses its default (20).
    bars = tuple(_bar(i, "100", "105", "95", "100") for i in range(25))
    values = compute_feature_series("rolling_breakout", bars)
    assert values == compute_rolling_breakout(RollingBreakoutDefinition(), bars)


def test_f6_dispatcher_unrecognized_field_still_raises() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        compute_feature_series("not_a_real_field", (_bar(0, "100", "101", "99", "100"),))
