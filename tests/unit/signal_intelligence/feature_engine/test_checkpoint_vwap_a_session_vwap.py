# File: tests/unit/signal_intelligence/feature_engine/
#   test_checkpoint_vwap_a_session_vwap.py
#
# CHECKPOINT-VWAP-A: Session-Anchored VWAP - unit tests, matching the
# fixture/assertion style established by
# `test_checkpoint_gainz_a_rolling_breakout.py` (`_bar()` helper,
# explicit arithmetic in comments, no magic-number assertions). Phase A
# of `VWAP_STRATEGY_ROADMAP.md` - a new strategy thread, unrelated to
# Gainz (paused per `CHECKPOINT_75`).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import SessionVwapDefinition
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)
from intraday.signal_intelligence.feature_engine.field_registry import (
    get_field,
    is_parameterized_feature,
    list_fields,
)
from intraday.signal_intelligence.feature_engine.vwap import compute_session_vwap

IID = InstrumentId("TEST")
TF = Timeframe.ONE_MINUTE
DAY_1 = datetime(2026, 1, 5, 3, 50, tzinfo=UTC)  # 09:20 IST
DAY_2 = datetime(2026, 1, 6, 3, 50, tzinfo=UTC)  # next trading day, 09:20 IST


def _bar(ts: datetime, o: str, h: str, lo: str, c: str, v: str) -> Bar:
    open_d, high_d, low_d, close_d = Decimal(o), Decimal(h), Decimal(lo), Decimal(c)
    high_d = max(high_d, open_d, close_d)
    low_d = min(low_d, open_d, close_d)
    return Bar(
        instrument_id=IID,
        timeframe=TF,
        timestamp=ts,
        open=open_d,
        high=high_d,
        low=low_d,
        close=close_d,
        volume=Decimal(v),
    )


# ---------------------------------------------------------------------------
# A. Hand-computed arithmetic - single-day session.
# ---------------------------------------------------------------------------


def test_a1_first_bar_of_a_session_vwap_equals_its_own_typical_price() -> None:
    # typical_price = (h+l+c)/3 = (110+90+100)/3 = 100. VWAP with a
    # single bar is just that bar's own typical price - NO warm-up
    # required, unlike SMA/EMA/ATR/rolling_breakout.
    bar = _bar(DAY_1, "100", "110", "90", "100", "1000")
    values = compute_session_vwap(SessionVwapDefinition(), (bar,))
    assert len(values) == 1
    assert values[0].value == Decimal(100)
    assert values[0].timestamp == DAY_1


def test_a2_two_bars_same_session_hand_computed() -> None:
    # Bar 1: typical=(110+90+100)/3=100, volume=1000
    #   -> cumulative: price_vol=100*1000=100000, vol=1000, vwap=100
    # Bar 2: typical=(120+100+110)/3=110, volume=500
    #   -> cumulative: price_vol=100000+110*500=155000, vol=1500,
    #      vwap=155000/1500=103.333...
    bar1 = _bar(DAY_1, "100", "110", "90", "100", "1000")
    bar2 = _bar(DAY_1 + timedelta(minutes=1), "105", "120", "100", "110", "500")
    values = compute_session_vwap(SessionVwapDefinition(), (bar1, bar2))
    assert len(values) == 2
    assert values[0].value == Decimal(100)
    assert values[1].value == Decimal(155000) / Decimal(1500)


def test_a3_three_bars_hand_computed_running_average() -> None:
    # Bar 3: typical=(100+80+90)/3=90, volume=1500
    #   -> cumulative: price_vol=155000+90*1500=290000, vol=3000,
    #      vwap=290000/3000=96.666...
    bar1 = _bar(DAY_1, "100", "110", "90", "100", "1000")
    bar2 = _bar(DAY_1 + timedelta(minutes=1), "105", "120", "100", "110", "500")
    bar3 = _bar(DAY_1 + timedelta(minutes=2), "95", "100", "80", "90", "1500")
    values = compute_session_vwap(SessionVwapDefinition(), (bar1, bar2, bar3))
    assert len(values) == 3
    assert values[2].value == Decimal(290000) / Decimal(3000)


# ---------------------------------------------------------------------------
# B. Session-reset - THE most important test for this feature.
# ---------------------------------------------------------------------------


def test_b1_day_2_does_not_inherit_day_1_accumulators() -> None:
    """Two consecutive trading days in one `bars` tuple. Day 1's own
    hand-computed running VWAP must match test_a2/a3 exactly, and DAY
    2's first bar must equal ITS OWN typical price - proving day 2's
    accumulators started fresh at zero, not carried over from day 1's
    (very different) price level."""
    day1_bar1 = _bar(DAY_1, "100", "110", "90", "100", "1000")
    day1_bar2 = _bar(DAY_1 + timedelta(minutes=1), "105", "120", "100", "110", "500")
    # Day 2 at a WILDLY different price level (2000 vs ~100) - if day 2
    # incorrectly inherited day 1's cumulative sums, its VWAP would be
    # dragged far below 2000; if reset correctly, it equals exactly its
    # own typical price.
    day2_bar1 = _bar(DAY_2, "2000", "2010", "1990", "2000", "300")
    day2_bar2 = _bar(DAY_2 + timedelta(minutes=1), "2000", "2020", "2000", "2010", "700")

    values = compute_session_vwap(
        SessionVwapDefinition(), (day1_bar1, day1_bar2, day2_bar1, day2_bar2)
    )
    assert len(values) == 4

    # Day 1 unaffected by anything that comes after it.
    assert values[0].value == Decimal(100)
    assert values[1].value == Decimal(155000) / Decimal(1500)

    # Day 2 bar 1: RESET - equals its own typical price exactly, not
    # some blend with day 1's ~100-103 level.
    day2_bar1_typical = (Decimal("2010") + Decimal("1990") + Decimal("2000")) / Decimal(3)
    assert values[2].value == day2_bar1_typical
    assert values[2].timestamp == DAY_2

    # Day 2 bar 2: running average WITHIN day 2 only.
    day2_bar2_typical = (Decimal("2020") + Decimal("2000") + Decimal("2010")) / Decimal(3)
    expected_cum_pv = day2_bar1_typical * Decimal("300") + day2_bar2_typical * Decimal("700")
    expected_cum_vol = Decimal("300") + Decimal("700")
    assert values[3].value == expected_cum_pv / expected_cum_vol


def test_b2_three_consecutive_days_each_reset_independently() -> None:
    day1 = _bar(DAY_1, "100", "105", "95", "100", "1000")
    day2 = _bar(DAY_2, "500", "505", "495", "500", "1000")
    day3 = _bar(DAY_2 + timedelta(days=1), "50", "55", "45", "50", "1000")

    values = compute_session_vwap(SessionVwapDefinition(), (day1, day2, day3))
    assert len(values) == 3
    # Each is a single-bar session - VWAP is exactly that bar's own
    # typical price, proving no cross-day contamination in either
    # direction.
    assert values[0].value == Decimal(100)
    assert values[1].value == Decimal(500)
    assert values[2].value == Decimal(50)


def test_b3_session_boundary_detected_purely_from_bar_timestamp_date_utc() -> None:
    """Confirms the exact mechanism `VWAP_STRATEGY_ROADMAP.md` §1.2/1.3
    described: a boundary is detected the instant `.timestamp.date()`
    changes, with no gap in minutes required - even a session "boundary"
    one minute apart (impossible in real trading-hours data, but proving
    the mechanism is date-based, not gap-size-based) triggers a reset."""
    last_bar_of_day1 = _bar(
        datetime(2026, 1, 5, 23, 59, tzinfo=UTC), "100", "105", "95", "100", "1000"
    )
    first_bar_of_day2 = _bar(
        datetime(2026, 1, 6, 0, 1, tzinfo=UTC), "9000", "9010", "8990", "9000", "1000"
    )
    values = compute_session_vwap(
        SessionVwapDefinition(), (last_bar_of_day1, first_bar_of_day2)
    )
    assert len(values) == 2
    assert values[1].value == Decimal(9000)  # reset, not blended with day 1's ~100 level


# ---------------------------------------------------------------------------
# C. No look-ahead.
# ---------------------------------------------------------------------------


def test_c1_earlier_values_unaffected_by_later_bars() -> None:
    bar1 = _bar(DAY_1, "100", "110", "90", "100", "1000")
    bar2 = _bar(DAY_1 + timedelta(minutes=1), "105", "120", "100", "110", "500")

    values_two_bars = compute_session_vwap(SessionVwapDefinition(), (bar1, bar2))

    bar3 = _bar(DAY_1 + timedelta(minutes=2), "9999", "9999", "9999", "9999", "999999")
    values_three_bars = compute_session_vwap(SessionVwapDefinition(), (bar1, bar2, bar3))

    # bar1/bar2's own VWAP values must be byte-for-byte identical
    # whether or not a huge later bar3 is appended - a later bar can
    # never retroactively change an earlier output.
    assert values_two_bars[0].value == values_three_bars[0].value
    assert values_two_bars[1].value == values_three_bars[1].value


# ---------------------------------------------------------------------------
# D. Zero-volume edge case - skip, never fabricate/crash.
# ---------------------------------------------------------------------------


def test_d1_zero_volume_bar_at_session_start_is_skipped_not_a_crash() -> None:
    zero_vol_bar = _bar(DAY_1, "100", "105", "95", "100", "0")
    real_bar = _bar(DAY_1 + timedelta(minutes=1), "105", "110", "100", "108", "1000")
    values = compute_session_vwap(SessionVwapDefinition(), (zero_vol_bar, real_bar))
    # Only the second bar produces a value - the first is mathematically
    # undefined (0/0), skipped per candle_body_ratio.py's own precedent,
    # never a fabricated 0 and never a ZeroDivisionError.
    assert len(values) == 1
    assert values[0].timestamp == real_bar.timestamp
    typical = (Decimal("110") + Decimal("100") + Decimal("108")) / Decimal(3)
    assert values[0].value == typical  # cumulative vol is just this bar's own 1000


# ---------------------------------------------------------------------------
# E. Mixed-instrument / mixed-timeframe guard (existing precedent).
# ---------------------------------------------------------------------------


def test_e1_mixed_instrument_series_rejected() -> None:
    bar1 = _bar(DAY_1, "100", "105", "95", "100", "1000")
    other = Bar(
        instrument_id=InstrumentId("OTHER"),
        timeframe=TF,
        timestamp=DAY_1 + timedelta(minutes=1),
        open=Decimal(100),
        high=Decimal(105),
        low=Decimal(95),
        close=Decimal(100),
        volume=Decimal(1000),
    )
    try:
        compute_session_vwap(SessionVwapDefinition(), (bar1, other))
        raise AssertionError("expected MixedInstrumentSeriesError")
    except MixedInstrumentSeriesError:
        pass


def test_e2_mixed_timeframe_series_rejected() -> None:
    bar1 = _bar(DAY_1, "100", "105", "95", "100", "1000")
    other = Bar(
        instrument_id=IID,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=DAY_1 + timedelta(minutes=1),
        open=Decimal(100),
        high=Decimal(105),
        low=Decimal(95),
        close=Decimal(100),
        volume=Decimal(1000),
    )
    try:
        compute_session_vwap(SessionVwapDefinition(), (bar1, other))
        raise AssertionError("expected MixedTimeframeSeriesError")
    except MixedTimeframeSeriesError:
        pass


def test_e3_empty_bars_returns_empty() -> None:
    assert compute_session_vwap(SessionVwapDefinition(), ()) == ()


# ---------------------------------------------------------------------------
# F. Definition identity.
# ---------------------------------------------------------------------------


def test_f1_definition_feature_name_and_version() -> None:
    d = SessionVwapDefinition()
    assert d.feature_name == "vwap"
    bar = _bar(DAY_1, "100", "105", "95", "100", "1000")
    values = compute_session_vwap(d, (bar,))
    assert values[0].feature_name == "vwap"
    assert values[0].feature_version == d.feature_version


# ---------------------------------------------------------------------------
# G. Registry + dispatcher integration.
# ---------------------------------------------------------------------------


def test_g1_vwap_is_registered_in_field_registry() -> None:
    field = get_field("vwap")
    assert field is not None
    assert field.field_id == "vwap"
    assert "high" in field.required_inputs
    assert "low" in field.required_inputs
    assert "close" in field.required_inputs
    assert "volume" in field.required_inputs


def test_g2_vwap_is_listed_and_categorized_as_a_derived_feature() -> None:
    fields = list_fields()
    assert any(f.field_id == "vwap" for f in fields)
    # `is_parameterized_feature()` actually means "is this a DERIVED
    # field vs. a raw OHLCV one" (its own docstring/implementation,
    # `field.category == FieldCategory.DERIVED_FEATURE`) - NOT
    # literally "does this take a numeric lookback parameter".
    # `candle_body_ratio` (also parameter-free) returns True here too,
    # re-confirmed directly this test - vwap correctly matches that
    # same precedent, not a special case.
    assert is_parameterized_feature("vwap") is True
    assert is_parameterized_feature("candle_body_ratio") is True
    assert is_parameterized_feature("close") is False


def test_g3_compute_feature_series_dispatches_vwap() -> None:
    bar1 = _bar(DAY_1, "100", "110", "90", "100", "1000")
    bar2 = _bar(DAY_1 + timedelta(minutes=1), "105", "120", "100", "110", "500")
    values = compute_feature_series("vwap", (bar1, bar2))
    assert len(values) == 2
    assert values[0].value == Decimal(100)
    assert values[1].value == Decimal(155000) / Decimal(1500)


def test_g4_session_reset_reproducible_through_the_real_dispatcher_too() -> None:
    """Same as test_b1, but through `compute_feature_series()` - the
    real path a strategy's `required_features()` would actually use,
    not just the pure function directly."""
    day1_bar = _bar(DAY_1, "100", "110", "90", "100", "1000")
    day2_bar = _bar(DAY_2, "2000", "2010", "1990", "2000", "300")
    values = compute_feature_series("vwap", (day1_bar, day2_bar))
    assert len(values) == 2
    assert values[0].value == Decimal(100)
    day2_typical = (Decimal("2010") + Decimal("1990") + Decimal("2000")) / Decimal(3)
    assert values[1].value == day2_typical
