# File: src/intraday/signal_intelligence/feature_engine/price_delta.py
#
# Checkpoint 64.97: Price Delta - a generic, reusable, parameterized
# N-bar close-to-close delta feature.
#
#     price_delta_N(t) = close[t] - close[t-N]
#
# Representation choice (directive Phase 4 - inspect convention first):
# no existing canonical feature returns a boolean-condition value (every
# `FeatureValue.value` in this platform is a numeric `Decimal` -
# RSI/ADX/+DI/-DI/Relative Volume/MACD Histogram/Candle Body Ratio are
# all plain magnitudes). The reference research file
# (`docs/research/gainz_signal_engine_reference.py`, read-only) itself
# expresses this as TWO boolean columns, `price_up_delta`/
# `price_down_delta` = `close > close.shift(N)` / `close < close.shift(N)`.
# Rather than duplicate that ambiguous multi-field shape, this checkpoint
# implements the SMALLEST canonical representation that still supports
# it: a single SIGNED numeric delta. `price_up_delta` is recoverable as
# `price_delta_N > 0`, `price_down_delta` as `price_delta_N < 0` - any
# future strategy (Gainz-derived or otherwise) can threshold this one
# field either way, without this checkpoint fabricating two separate
# derived boolean fields ahead of an actual consumer needing them.
#
# Parameterization: `PriceDeltaDefinition(lookback=N)` lives in
# `definitions.py`, following the exact same one-off-dataclass-per-
# identity pattern as `SimpleMovingAverageDefinition`/
# `ExponentialMovingAverageDefinition`/etc. - `feature_name` bakes N in,
# e.g. `"price_delta_10"`. N=10 below is used ONLY as the reference
# file's default (`GainzConfig.candle_delta_length = 10`) - explicitly a
# REFERENCE-ARTIFACT DEFAULT, never a "verified Gainz parameter" (no
# Gainz source exists to verify it against - see
# `docs/research/GAINZ_SIGNAL_ENGINE_AUDIT.md`). No strategy in this
# checkpoint uses this default; it exists purely as a documented,
# available convenience for a future caller.
#
# Look-ahead safety: `price_delta_N(t)` depends ONLY on `close[t]` and
# `close[t-N]` - both already-observed bars at or before t. No future
# bar can ever participate.
#
# Warm-up: the first N bars of any series cannot be evaluated (no
# `close[t-N]` exists yet) - SKIPPED entirely, matching every other
# lookback-based feature's "no output, not a fabricated value"
# convention.
from __future__ import annotations

from collections import deque
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    PriceDeltaDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)

# REFERENCE-ARTIFACT DEFAULT - taken from the user-supplied reference
# file's `GainzConfig.candle_delta_length` field only, NOT a verified
# Gainz parameter (no authentic Gainz source exists to verify against).
# Not used as a default anywhere production code constructs a
# `PriceDeltaDefinition` - purely documentation of provenance for a
# caller who chooses to opt into it explicitly.
REFERENCE_ARTIFACT_DEFAULT_LOOKBACK = 10


def compute_price_delta(
    definition: PriceDeltaDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """`price_delta_N(t) = close[t] - close[t-N]`, signed. See module
    docstring for the full representation/warm-up/look-ahead rationale."""
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
    window: deque[Decimal] = deque(maxlen=lookback + 1)
    values: list[FeatureValue] = []

    for bar in bars:
        window.append(bar.close)
        if len(window) == lookback + 1:
            values.append(
                FeatureValue(
                    feature_name=definition.feature_name,
                    feature_version=definition.feature_version,
                    instrument_id=instrument_id,
                    timeframe=timeframe,
                    timestamp=bar.timestamp,
                    value=window[-1] - window[0],
                )
            )

    return tuple(values)
