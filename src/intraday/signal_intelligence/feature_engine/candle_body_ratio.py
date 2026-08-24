# File: src/intraday/signal_intelligence/feature_engine/candle_body_ratio.py
#
# Checkpoint 64.49: Candle Body Ratio - a canonical PLATFORM feature.
# No Gainz reference source exists in this repository (see
# `field_registry.py` module docstring and taskReport.md) - this is the
# standard, most common technical-analysis definition, NOT verified
# against Gainz.
#
#     body_ratio_t = |close_t - open_t| / (high_t - low_t)
#
# Safe by construction: `Bar.__post_init__` already guarantees
# `low <= open <= high` and `low <= close <= high`, so the numerator can
# never exceed the denominator when the denominator is positive - the
# ratio is always in `[0, 1]`. When `high_t == low_t` (a zero-range bar -
# only possible when open == high == low == close, per that same Bar
# invariant), the ratio is mathematically undefined (0/0) - that bar is
# SKIPPED entirely, never a fabricated `0`/`1`/division-by-zero crash
# (Checkpoint 64.49 Part 10's explicit "handle high == low safely").
#
# Per-bar, stateless: unlike SMA/EMA/ATR/RSI/ADX/RVOL, this feature needs
# no prior bars and has NO warm-up requirement - the first bar in any
# series can produce a value immediately (unless it is itself zero-
# range).
from __future__ import annotations

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    FEATURE_ENGINE_VERSION,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)

CANDLE_BODY_RATIO_FIELD_ID = "candle_body_ratio"


def compute_candle_body_ratio(bars: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
    """`body_ratio_t = |close_t - open_t| / (high_t - low_t)`, skipping
    zero-range bars (see module docstring). No look-ahead is possible:
    each output depends only on its OWN bar's OHLC - there is no
    recurrence, so a later bar cannot influence an earlier output even in
    principle."""
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

    values: list[FeatureValue] = []
    for bar in bars:
        candle_range = bar.high - bar.low
        if candle_range == 0:
            continue
        values.append(
            FeatureValue(
                feature_name=CANDLE_BODY_RATIO_FIELD_ID,
                feature_version=FEATURE_ENGINE_VERSION,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                value=abs(bar.close - bar.open) / candle_range,
            )
        )

    return tuple(values)
