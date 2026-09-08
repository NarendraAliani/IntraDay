# File: tests/unit/signal_intelligence/feature_engine/
#   test_checkpoint_orb_a_opening_range.py
#
# CHECKPOINT-ORB-A: Opening Range - unit tests, matching the fixture/
# assertion style established by
# `test_checkpoint_vwap_a_session_vwap.py` (`_bar()` helper, explicit
# arithmetic in comments, no magic-number assertions). Phase A of
# `ORB_STRATEGY_ROADMAP.md` - a new strategy thread, unrelated to
# Gainz (paused) and VWAP (Phase D complete, also paused for tuning).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import OpeningRangeDefinition
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)
from intraday.signal_intelligence.feature_engine.field_registry import (
    get_field,
    list_fields,
)
from intraday.signal_intelligence.feature_engine.opening_range import (
    compute_opening_range_high,
    compute_opening_range_low,
)

IID = InstrumentId("TEST")
TF = Timeframe.FIVE_MINUTE
# 2026-01-05 is a real Monday trading day, already used successfully as
# a fixture date in test_checkpoint_vwap_a_session_vwap.py.
DAY_1_OPEN = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)  # 09:15 IST - market_open
DAY_2_OPEN = datetime(2026, 1, 6, 3, 45, tzinfo=UTC)  # next trading day, 09:15 IST


def _bar(ts: datetime, o: str, h: str, lo: str, c: str) -> Bar:
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
        volume=Decimal("1000"),
    )


def _session_bars(open_ts: datetime, closes: list[tuple[str, str, str, str]]) -> tuple[Bar, ...]:
    """`closes[i]` = (open, high, low, close) for the bar whose
    timestamp is `open_ts + 5*(i+1)` minutes - i.e. the FIRST bar's
    timestamp is the session's first canonical 5m close (09:20 IST for
    a 09:15 IST open), matching this project's own close-anchored
    `Bar.timestamp` convention."""
    return tuple(
        _bar(open_ts + timedelta(minutes=5 * (i + 1)), *ohlc) for i, ohlc in enumerate(closes)
    )


# ---------------------------------------------------------------------------
# A. Hand-computed arithmetic - the 3-bar window (default 15 minutes).
# ---------------------------------------------------------------------------


def test_a1_first_3_bars_produce_no_output_window_incomplete() -> None:
    # Bars at 09:20/09:25/09:30 IST - all WITHIN [09:15, 09:30] - no
    # output for any of them.
    bars = _session_bars(
        DAY_1_OPEN,
        [
            ("100", "105", "98", "102"),
            ("102", "108", "101", "104"),
            ("104", "106", "100", "103"),
        ],
    )
    high_values = compute_opening_range_high(OpeningRangeDefinition(15), bars)
    low_values = compute_opening_range_low(OpeningRangeDefinition(15), bars)
    assert high_values == ()
    assert low_values == ()


def test_a2_4th_bar_emits_the_frozen_range_hand_computed() -> None:
    # Window bars (09:20/09:25/09:30 IST): highs [105,108,106] -> max=108;
    # lows [98,101,100] -> min=98. 4th bar (09:35 IST) is the FIRST bar
    # strictly after window_end (09:30 IST) - emits the frozen (108, 98).
    window = [
        ("100", "105", "98", "102"),
        ("102", "108", "101", "104"),
        ("104", "106", "100", "103"),
    ]
    post_window = ("103", "110", "103", "109")
    bars = _session_bars(DAY_1_OPEN, [*window, post_window])

    high_values = compute_opening_range_high(OpeningRangeDefinition(15), bars)
    low_values = compute_opening_range_low(OpeningRangeDefinition(15), bars)

    assert len(high_values) == 1
    assert len(low_values) == 1
    assert high_values[0].value == Decimal(108)
    assert low_values[0].value == Decimal(98)
    assert high_values[0].timestamp == bars[3].timestamp


def test_a3_range_stays_frozen_for_every_subsequent_bar_that_session() -> None:
    window = [
        ("100", "105", "98", "102"),
        ("102", "108", "101", "104"),
        ("104", "106", "100", "103"),
    ]
    # Two post-window bars, both with WILDLY different highs/lows -
    # neither should change the already-frozen (108, 98).
    post = [("103", "999", "1", "500"), ("500", "999", "1", "500")]
    bars = _session_bars(DAY_1_OPEN, [*window, *post])

    high_values = compute_opening_range_high(OpeningRangeDefinition(15), bars)
    low_values = compute_opening_range_low(OpeningRangeDefinition(15), bars)

    assert len(high_values) == 2
    assert len(low_values) == 2
    assert all(v.value == Decimal(108) for v in high_values)
    assert all(v.value == Decimal(98) for v in low_values)


# ---------------------------------------------------------------------------
# B. Session-reset - the most important test class for this feature,
#    same standard CHECKPOINT-VWAP-A's own test_b1 set.
# ---------------------------------------------------------------------------


def test_b1_day_2_gets_its_own_independent_opening_range() -> None:
    day1_window = [
        ("100", "105", "98", "102"),
        ("102", "108", "101", "104"),
        ("104", "106", "100", "103"),
    ]
    day1_post = ("103", "110", "103", "109")
    # Day 2 at a WILDLY different price level and a DIFFERENT range
    # shape - if day 2 incorrectly inherited day 1's window state, its
    # own range would be wrong.
    day2_window = [
        ("2000", "2010", "1995", "2005"),
        ("2005", "2020", "2000", "2010"),
        ("2010", "2015", "1990", "2000"),
    ]
    day2_post = ("2000", "2030", "1980", "2025")

    bars = _session_bars(DAY_1_OPEN, [*day1_window, day1_post]) + _session_bars(
        DAY_2_OPEN, [*day2_window, day2_post]
    )

    high_values = compute_opening_range_high(OpeningRangeDefinition(15), bars)
    low_values = compute_opening_range_low(OpeningRangeDefinition(15), bars)

    # Day 1: exactly 1 emission (its own 4th bar).
    # Day 2: exactly 1 emission (its own 4th bar) - day 2's window bars
    # produce no output either, freshly, just like day 1's did.
    assert len(high_values) == 2
    assert len(low_values) == 2
    assert high_values[0].value == Decimal(108)  # day 1's own range
    assert low_values[0].value == Decimal(98)
    # day 2 highs [2010,2020,2015] -> max=2020; lows [1995,2000,1990] -> min=1990
    assert high_values[1].value == Decimal(2020)
    assert low_values[1].value == Decimal(1990)
    assert high_values[1].timestamp.date() == DAY_2_OPEN.date()


def test_b2_a_day_whose_bars_never_cover_a_complete_window_produces_no_output() -> None:
    # Only 2 bars this "session" - the window (3 bars) never completes,
    # so NOTHING should be emitted for this day at all - never a
    # fabricated partial-window value.
    bars = _session_bars(
        DAY_1_OPEN,
        [("100", "105", "98", "102"), ("102", "108", "101", "104")],
    )
    high_values = compute_opening_range_high(OpeningRangeDefinition(15), bars)
    low_values = compute_opening_range_low(OpeningRangeDefinition(15), bars)
    assert high_values == ()
    assert low_values == ()


# ---------------------------------------------------------------------------
# C. Market-open resolution - the one genuinely new piece beyond VWAP's
#    own pattern. Confirms `build_session_for()`'s REAL market_open is
#    used, not a hardcoded clock assumption.
# ---------------------------------------------------------------------------


def test_c1_window_boundary_is_relative_to_the_sessions_real_market_open() -> None:
    """A bar at exactly `market_open + opening_range_minutes` (09:30
    IST for the default 15-minute window) must be INCLUDED in the
    window (boundary inclusive - the 3rd bar itself, per §1.3's own
    3-bar finding), and the very next bar (09:35 IST) must be the
    first to receive the frozen value - proving the window boundary is
    computed from the session's real, resolved `market_open`
    (03:45 UTC / 09:15 IST for this project's real calendar), not a
    guessed or hardcoded instant."""
    window = [
        ("100", "105", "98", "102"),  # 09:20 IST
        ("102", "108", "101", "104"),  # 09:25 IST
        ("104", "106", "100", "103"),  # 09:30 IST - exactly market_open + 15min
    ]
    post = ("103", "110", "103", "109")  # 09:35 IST - first bar strictly after
    bars = _session_bars(DAY_1_OPEN, [*window, post])

    high_values = compute_opening_range_high(OpeningRangeDefinition(15), bars)

    # Exactly 1 emission (the 4th bar) - the 3rd (boundary) bar itself
    # produced no output, confirming the boundary comparison is
    # inclusive against the REAL resolved market_open + duration, not
    # off by one bar in either direction.
    assert len(high_values) == 1
    assert high_values[0].timestamp == bars[3].timestamp


def test_c2_a_different_window_duration_moves_the_boundary_correctly() -> None:
    """A 10-minute window covers only 2 bars (09:20/09:25 IST), not 3 -
    proving the boundary genuinely derives from `opening_range_minutes`
    against the real `market_open`, not a hardcoded "always 3 bars"
    assumption."""
    bars = _session_bars(
        DAY_1_OPEN,
        [
            ("100", "105", "98", "102"),  # 09:20 IST - within [09:15, 09:25]
            ("102", "108", "101", "104"),  # 09:25 IST - exactly the boundary, included
            ("104", "106", "100", "103"),  # 09:30 IST - first bar strictly after
        ],
    )
    high_values = compute_opening_range_high(OpeningRangeDefinition(10), bars)
    low_values = compute_opening_range_low(OpeningRangeDefinition(10), bars)

    assert len(high_values) == 1
    assert len(low_values) == 1
    assert high_values[0].timestamp == bars[2].timestamp
    # Window = bars 0,1 only: highs [105,108] -> max=108; lows [98,101] -> min=98.
    assert high_values[0].value == Decimal(108)
    assert low_values[0].value == Decimal(98)


# ---------------------------------------------------------------------------
# D. No look-ahead.
# ---------------------------------------------------------------------------


def test_d1_earlier_values_unaffected_by_a_later_bar() -> None:
    window = [
        ("100", "105", "98", "102"),
        ("102", "108", "101", "104"),
        ("104", "106", "100", "103"),
    ]
    post_1 = ("103", "110", "103", "109")
    bars_4 = _session_bars(DAY_1_OPEN, [*window, post_1])
    values_4 = compute_opening_range_high(OpeningRangeDefinition(15), bars_4)

    post_2 = ("109", "9999", "9999", "9999")  # a huge, later 5th bar
    bars_5 = _session_bars(DAY_1_OPEN, [*window, post_1, post_2])
    values_5 = compute_opening_range_high(OpeningRangeDefinition(15), bars_5)

    # The 4th bar's own value must be byte-for-byte identical whether
    # or not a huge later 5th bar is appended.
    assert values_4[0].value == values_5[0].value == Decimal(108)


# ---------------------------------------------------------------------------
# E. Mixed-instrument / mixed-timeframe guard (existing precedent).
# ---------------------------------------------------------------------------


def test_e1_mixed_instrument_series_rejected() -> None:
    bar1 = _bar(DAY_1_OPEN + timedelta(minutes=5), "100", "105", "98", "102")
    other = Bar(
        instrument_id=InstrumentId("OTHER"),
        timeframe=TF,
        timestamp=DAY_1_OPEN + timedelta(minutes=10),
        open=Decimal(100),
        high=Decimal(105),
        low=Decimal(98),
        close=Decimal(102),
        volume=Decimal(1000),
    )
    try:
        compute_opening_range_high(OpeningRangeDefinition(15), (bar1, other))
        raise AssertionError("expected MixedInstrumentSeriesError")
    except MixedInstrumentSeriesError:
        pass


def test_e2_mixed_timeframe_series_rejected() -> None:
    bar1 = _bar(DAY_1_OPEN + timedelta(minutes=5), "100", "105", "98", "102")
    other = Bar(
        instrument_id=IID,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=DAY_1_OPEN + timedelta(minutes=10),
        open=Decimal(100),
        high=Decimal(105),
        low=Decimal(98),
        close=Decimal(102),
        volume=Decimal(1000),
    )
    try:
        compute_opening_range_low(OpeningRangeDefinition(15), (bar1, other))
        raise AssertionError("expected MixedTimeframeSeriesError")
    except MixedTimeframeSeriesError:
        pass


def test_e3_empty_bars_returns_empty() -> None:
    assert compute_opening_range_high(OpeningRangeDefinition(15), ()) == ()
    assert compute_opening_range_low(OpeningRangeDefinition(15), ()) == ()


# ---------------------------------------------------------------------------
# F. Definition identity.
# ---------------------------------------------------------------------------


def test_f1_definition_feature_name_is_parameterized() -> None:
    d15 = OpeningRangeDefinition(15)
    d30 = OpeningRangeDefinition(30)
    assert d15.feature_name == "opening_range_15"
    assert d30.feature_name == "opening_range_30"
    assert OpeningRangeDefinition().opening_range_minutes == 15  # documented default


# ---------------------------------------------------------------------------
# G. Registry + dispatcher integration.
# ---------------------------------------------------------------------------


def test_g1_both_fields_registered() -> None:
    high_field = get_field("opening_range_high")
    low_field = get_field("opening_range_low")
    assert high_field is not None
    assert low_field is not None
    assert "high" in high_field.required_inputs
    assert "low" in low_field.required_inputs


def test_g2_both_fields_listed() -> None:
    fields = list_fields()
    ids = {f.field_id for f in fields}
    assert "opening_range_high" in ids
    assert "opening_range_low" in ids


def test_g3_compute_feature_series_dispatches_both_fields() -> None:
    window = [
        ("100", "105", "98", "102"),
        ("102", "108", "101", "104"),
        ("104", "106", "100", "103"),
    ]
    post = ("103", "110", "103", "109")
    bars = _session_bars(DAY_1_OPEN, [*window, post])

    high_values = compute_feature_series("opening_range_high_15", bars)
    low_values = compute_feature_series("opening_range_low_15", bars)

    assert len(high_values) == 1
    assert len(low_values) == 1
    assert high_values[0].value == Decimal(108)
    assert low_values[0].value == Decimal(98)


def test_g4_a_non_default_window_duration_dispatches_correctly() -> None:
    bars = _session_bars(
        DAY_1_OPEN,
        [
            ("100", "105", "98", "102"),
            ("102", "108", "101", "104"),
            ("104", "106", "100", "103"),
        ],
    )
    values = compute_feature_series("opening_range_high_10", bars)
    assert len(values) == 1
    assert values[0].value == Decimal(108)  # window = first 2 bars only
