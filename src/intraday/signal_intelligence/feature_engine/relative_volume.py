# File: src/intraday/signal_intelligence/feature_engine/relative_volume.py
#
# Checkpoint 64.49: Relative Volume (RVOL) - a canonical PLATFORM
# feature. No Gainz reference source exists in this repository (see
# `field_registry.py` module docstring and taskReport.md) - this is a
# standard, well-known convention, NOT verified against Gainz.
#
# ---------------------------------------------------------------------------
# FORMULA - explicit, per Checkpoint 64.49 Part 8's instruction
# ---------------------------------------------------------------------------
#
#     baseline_t = mean(volume_(t-N) .. volume_(t-1))   (previous N bars,
#                                                          EXCLUDING the
#                                                          current bar)
#     RVOL_t = volume_t / baseline_t
#
# Baseline choice: a trailing N-bar SIMPLE average of PRIOR volume,
# explicitly excluding the current bar - the single most common
# "relative volume" convention (current activity vs. its own recent
# history) and the one that avoids the current bar trivially dominating
# its own baseline. No Gainz-specific baseline (e.g. same-time-of-day
# N-session average) is assumed - that is a different, plausible-but-
# unverified convention this checkpoint does NOT implement (per Part 8's
# "do not choose a Gainz-specific formula unless supported").
#
# ---------------------------------------------------------------------------
# Missing-data behavior
# ---------------------------------------------------------------------------
#
# If `baseline_t == 0` (all-zero volume in the trailing window - the
# EXPECTED case for SAMPLE_BAR-sourced fixtures, which always carry
# `volume == 0`, per `field_registry.py`'s own existing "volume" field
# docstring), that bar is SKIPPED entirely - no `FeatureValue` is
# emitted, never a fabricated `inf`/`0`/`None`-as-Decimal value.
#
# ---------------------------------------------------------------------------
# Warm-up
# ---------------------------------------------------------------------------
#
# The first `lookback` bars produce no output (no complete trailing
# baseline window yet exists) - first possible output at `bars[lookback]`
# (0-indexed), identical warm-up SHAPE to SMA (`lookback` bars needed
# before any output, though here they are strictly PRIOR bars, not an
# inclusive window).
from __future__ import annotations

from collections import deque
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    RelativeVolumeDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)


def compute_relative_volume(
    definition: RelativeVolumeDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """`RVOL_t = volume_t / mean(volume_(t-N)..volume_(t-1))` (see module
    docstring for baseline rationale and missing-data behavior).

    No look-ahead: the baseline window only ever contains bars strictly
    BEFORE the current bar (a fixed-size trailing `deque`, never
    including `bar` itself before it is appended to the window for the
    NEXT iteration) - in the chronological order `ensure_chronological()`
    below already guarantees.
    """
    if not bars:
        return ()

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

    lookback = definition.lookback
    window: deque[Decimal] = deque(maxlen=lookback)
    values: list[FeatureValue] = []

    for bar in bars:
        if len(window) == lookback:
            baseline = sum(window, Decimal(0)) / lookback
            if baseline != 0:
                values.append(
                    FeatureValue(
                        feature_name=definition.feature_name,
                        feature_version=definition.feature_version,
                        instrument_id=instrument_id,
                        timeframe=timeframe,
                        timestamp=bar.timestamp,
                        value=bar.volume / baseline,
                    )
                )
        window.append(bar.volume)

    return tuple(values)
