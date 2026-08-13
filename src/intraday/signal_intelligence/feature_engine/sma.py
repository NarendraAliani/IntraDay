# File: src/intraday/signal_intelligence/feature_engine/sma.py
#
# Checkpoint 15: Simple Moving Average - the first concrete feature
# computation. Depends only on `domain/feature` and `domain/market_data`
# (this bounded context's own README, written at Checkpoint 1, already
# named exactly this dependency set) - no application, no infrastructure,
# no Django, no Dhan. Pure, deterministic, O(n) rolling-sum calculation;
# no float conversion anywhere.
from __future__ import annotations

from collections import deque
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)


def compute_simple_moving_average(
    definition: SimpleMovingAverageDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """`SMA(t) = mean(close[t-N+1 .. t])` over `definition.lookback`
    closes, computed only from `Bar.close` (never high/low/volume, per
    Checkpoint 15 §6).

    No look-ahead is possible by construction: each output is derived
    from a rolling window that only ever accumulates bars already
    iterated, in the chronological order `ensure_chronological()` below
    already guarantees - there is no code path through which a bar later
    in the sequence could influence an earlier output.

    Output alignment (Checkpoint 15 §5, §8, §13): `FeatureValue.timestamp`
    equals its source bar's own `timestamp` (itself the bar's CLOSE time -
    see `domain.market_data.contracts.Bar`'s docstring - so no second
    timestamp convention is introduced). The first `lookback - 1` bars
    produce NO output at all - not `None`, not a shorter-period average -
    exactly `lookback` real observations are required before the first
    value is ever emitted. After warm-up, one output exists per input
    bar, preserving chronological order (never reordered).

    Precision: full `Decimal` division (`window_sum / definition.lookback`),
    using Python's default decimal context precision - no explicit
    rounding is applied here. A consumer needing a specific display
    precision rounds explicitly at its own boundary; this function does
    not invent a rounding policy nothing in this checkpoint's scope
    requires.

    Complexity: O(n) in the number of input bars - a fixed-size rolling
    window (`collections.deque(maxlen=lookback)`) with a running sum,
    never an O(n*lookback) re-summation per output.

    Raises `MixedInstrumentSeriesError`/`MixedTimeframeSeriesError` if
    `bars` contains more than one instrument/timeframe (Checkpoint 15
    §11, §12) and whatever `ensure_chronological()` raises
    (`DuplicateBarTimestampError`/`OutOfOrderBarError`, Checkpoint 14) if
    `bars` is not strictly chronological - reusing Checkpoint 14's
    canonical series validation rather than duplicating it.
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
    window_sum = Decimal(0)
    values: list[FeatureValue] = []

    for bar in bars:
        if len(window) == lookback:
            window_sum -= window[0]
        window.append(bar.close)
        window_sum += bar.close

        if len(window) == lookback:
            values.append(
                FeatureValue(
                    feature_name=definition.feature_name,
                    feature_version=definition.feature_version,
                    instrument_id=instrument_id,
                    timeframe=timeframe,
                    timestamp=bar.timestamp,
                    value=window_sum / lookback,
                )
            )

    return tuple(values)
