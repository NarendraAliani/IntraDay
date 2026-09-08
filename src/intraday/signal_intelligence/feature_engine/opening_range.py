# File: src/intraday/signal_intelligence/feature_engine/opening_range.py
#
# CHECKPOINT-ORB-A: Opening Range - a canonical, reusable PLATFORM
# feature, Phase A of `ORB_STRATEGY_ROADMAP.md`. Standard, well-
# established technical-analysis convention (the high/low of a fixed
# window at the start of each trading session) - not a Gainz port, not
# verified against any external reference. A genuinely NEW strategy
# thread, unrelated to `gainz_compatible_research.py` (paused) and
# `vwap_mean_reversion.py` (Phase D complete, also paused for tuning) -
# neither is touched by this checkpoint.
#
# ---------------------------------------------------------------------------
# FORMULA - explicit
# ---------------------------------------------------------------------------
#
#     window = [market_open, market_open + opening_range_minutes]
#     opening_range_high = max(high_i) for every bar i whose
#                           timestamp falls within `window`
#     opening_range_low  = min(low_i)  for the same bars
#
# Once the window closes, EVERY subsequent bar in that same session
# emits the SAME FROZEN `(opening_range_high, opening_range_low)` pair
# - this is a single fixed fact about the day, not a moving window
# (unlike `rolling_breakout.py`'s own trailing N-bar shape, which is a
# genuinely different computation - re-confirmed directly,
# `ORB_STRATEGY_ROADMAP.md` §0/§1.1, not assumed from the name alone).
#
# ---------------------------------------------------------------------------
# Two parallel fields, not one signed value - representation choice,
# explicit
# ---------------------------------------------------------------------------
#
# `rolling_breakout.py`'s signed `1`/`-1`/`0` representation works
# because breakout and breakdown are MUTUALLY EXCLUSIVE for a given bar
# (a single close cannot be simultaneously above the prior high AND
# below the prior low). `opening_range_high`/`opening_range_low` are
# NOT mutually exclusive or derivable from one another - they are two
# genuinely independent numbers a downstream strategy needs
# separately (e.g. to test `close > high` for a bullish breakout and
# `close < low` for a bearish one, and to compute the range's own SIZE
# as `high - low`). Collapsing them into one field would lose real
# information, unlike the rolling-breakout case - so this module
# follows `directional_movement.py`'s own precedent instead (`+DI`/`-DI`
# as two independent compute functions sharing one `Definition` class
# and one parameter) rather than `rolling_breakout.py`'s signed-value
# shape: `compute_opening_range_high()`/`compute_opening_range_low()`
# below are two separate functions, dispatched as two separate
# field_ids (`opening_range_high_N`/`opening_range_low_N`), both
# constructed from the SAME `OpeningRangeDefinition(N)`.
#
# ---------------------------------------------------------------------------
# Session-anchoring: VWAP's proven "which day" pattern, PLUS the one
# genuinely new piece VWAP never needed - "where in the day"
# ---------------------------------------------------------------------------
#
# Reuses `CHECKPOINT-VWAP-A`'s own proven grouping key
# (`bar.timestamp.date()`, UTC) to detect session boundaries - the
# same mechanism, not a second implementation. UNLIKE VWAP (which never
# needed to know WHEN within a day a bar falls, only WHICH day), ORB
# genuinely needs each session's own `market_open` instant to know
# whether a given bar falls inside the opening window at all. This is
# supplied by `domain.session.calendar.build_session_for()` - an
# EXISTING function (already used by `historical_data_coverage.py`,
# `walk_forward.py`, and others this session), not new resolver logic:
# `TradingSession.market_open` is already the correctly-UTC-converted
# 09:15 IST instant for that exact calendar date. `as_of` is passed as
# the bar's own timestamp - per `historical_data_coverage.py`'s own
# established comment ("session status classification is irrelevant
# here; only the shape matters"), `market_open` itself does not depend
# on which instant is passed as `as_of`, only session STATUS
# classification does (irrelevant here - this module never reads
# `TradingSession.status`).
#
# ---------------------------------------------------------------------------
# Warm-up - no output for the first 3 bars of a session (5m grain), or
# for any session whose supplied bars never cover a complete window
# ---------------------------------------------------------------------------
#
# `ORB_STRATEGY_ROADMAP.md` §1.3: the classic 09:15-09:30 IST window,
# on this project's `5m`/CLOSE-anchored bar grain, covers exactly 3
# bars (closes 09:20/09:25/09:30 IST) - those 3 bars themselves produce
# NO output (the range isn't complete yet, matching `rolling_
# breakout.py`'s own "no fabricated value before the window is whole"
# convention). A session whose supplied bars never include one at or
# before `market_open + opening_range_minutes` also produces no output
# for that entire day - the range cannot be honestly computed from data
# that doesn't cover it, never fabricated from a partial window.
from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.domain.session.calendar import build_session_for
from intraday.signal_intelligence.feature_engine.definitions import (
    OpeningRangeDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)


def _compute_opening_range_bounds(
    definition: OpeningRangeDefinition, bars: tuple[Bar, ...]
) -> tuple[list[FeatureValue], list[FeatureValue]]:
    """Shared single-pass computation for both parallel fields (see
    module docstring for why two fields, not one) - kept private so
    `compute_opening_range_high()`/`compute_opening_range_low()` below
    each stay a simple, independently-callable `tuple[FeatureValue,
    ...]`-returning function (matching every other feature-engine
    module's own public shape), at the cost of each public call
    re-running this pass independently - the SAME trade-off `+DI`/`-DI`
    (`directional_movement.py`) already accepts, not a new
    inefficiency introduced here."""
    if not bars:
        return [], []

    ensure_chronological(bars)

    instrument_id = bars[0].instrument_id
    timeframe = bars[0].timeframe
    for bar in bars:
        if bar.instrument_id != instrument_id:
            raise MixedInstrumentSeriesError(
                f"bar series mixes instruments {instrument_id!r} and "
                f"{bar.instrument_id!r} - a feature series must come from one instrument"
            )
        if bar.timeframe != timeframe:
            raise MixedTimeframeSeriesError(
                f"bar series mixes timeframes {timeframe!r} and {bar.timeframe!r} "
                "- a feature calculation must never blend timeframes"
            )

    window_duration = timedelta(minutes=definition.opening_range_minutes)

    high_values: list[FeatureValue] = []
    low_values: list[FeatureValue] = []

    current_session_date: date_type | None = None
    window_end = None
    window_high: Decimal | None = None
    window_low: Decimal | None = None
    frozen_high: Decimal | None = None
    frozen_low: Decimal | None = None

    for bar in bars:
        bar_date = bar.timestamp.date()
        if bar_date != current_session_date:
            # New trading day (or the very first bar) - reset ALL
            # per-day state, including the frozen post-window values,
            # so day 2 never inherits day 1's opening range.
            current_session_date = bar_date
            session = build_session_for(bar_date, bar.timestamp)
            window_end = session.market_open + window_duration
            window_high = None
            window_low = None
            frozen_high = None
            frozen_low = None

        if bar.timestamp <= window_end:
            # Still inside the opening window - accumulate, emit NO
            # value for this bar (the range is not complete yet).
            window_high = bar.high if window_high is None else max(window_high, bar.high)
            window_low = bar.low if window_low is None else min(window_low, bar.low)
            continue

        if window_high is None or window_low is None:
            # The window closed but no bar ever fell inside it (a gap
            # in the supplied series) - the range cannot be honestly
            # computed for this day. Never fabricated.
            continue

        if frozen_high is None:
            # First bar strictly after the window closed - freeze the
            # range for the rest of this session. No look-ahead: this
            # freeze uses only bars at-or-before `window_end`, which
            # this current bar (strictly after it) can never influence.
            frozen_high = window_high
            frozen_low = window_low

        high_values.append(
            FeatureValue(
                feature_name=f"opening_range_high_{definition.opening_range_minutes}",
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                value=frozen_high,
            )
        )
        low_values.append(
            FeatureValue(
                feature_name=f"opening_range_low_{definition.opening_range_minutes}",
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                value=frozen_low,
            )
        )

    return high_values, low_values


def compute_opening_range_high(
    definition: OpeningRangeDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """The opening range's high boundary (see module docstring for the
    full formula, session-reset/market-open-resolution mechanism, and
    warm-up rationale)."""
    high_values, _ = _compute_opening_range_bounds(definition, bars)
    return tuple(high_values)


def compute_opening_range_low(
    definition: OpeningRangeDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """The opening range's low boundary - see `compute_opening_range_high()`
    and the module docstring."""
    _, low_values = _compute_opening_range_bounds(definition, bars)
    return tuple(low_values)
