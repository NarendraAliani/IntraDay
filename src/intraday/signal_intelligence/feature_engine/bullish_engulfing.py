# File: src/intraday/signal_intelligence/feature_engine/bullish_engulfing.py
#
# Checkpoint 64.97: Bullish Engulfing - a canonical, GENERIC candlestick
# feature. This is NOT an authentic-GainzAlgo implementation and is NOT
# claimed to be numerically/behaviorally verified against GainzAlgo. It
# is the STANDARD, well-established two-candle "bullish engulfing"
# pattern definition, which happens to be structurally identical to the
# rule visible in the user-supplied research/rebuild reference file
# (`docs/research/gainz_signal_engine_reference.py`, read-only, never
# modified this checkpoint - see that file's own `bullish_engulfing`
# column for comparison, and
# `docs/research/GAINZ_SIGNAL_ENGINE_AUDIT.md` for the
# GENERIC/REBUILT/UNVERIFIED-GAINZ classification of this feature).
#
#     bullish_engulfing_t = (close[t-1] < open[t-1])   # prior candle bearish
#                        AND (close[t] > open[t])       # current candle bullish
#                        AND (close[t] > open[t-1])     # current close > prior open
#                        AND (open[t] <= close[t-1])    # current open <= prior close
#
# Look-ahead safety: uses ONLY bars t and t-1 - never t+1 or later. Valid
# at the CLOSE of candle t (Bar.timestamp is already the bar's close
# time - see `domain.market_data.contracts.Bar`'s own docstring), so no
# additional alignment decision is needed here.
#
# Representation: `FeatureValue.value` must be a `Decimal`
# (`domain.feature.contracts.FeatureValue.__post_init__`) - there is no
# boolean variant of that contract anywhere in this platform. The
# boolean condition above is therefore encoded as `Decimal("1")` (true)
# / `Decimal("0")` (false), the smallest representation that fits the
# existing contract without inventing a second `FeatureValue`-like type.
#
# Warm-up: the FIRST bar in any series cannot be evaluated (there is no
# t-1) - it is SKIPPED entirely, following the same "no output, not a
# fabricated value" convention `sma.py`/`rsi.py`/etc. already use for
# their own warm-up windows. A single-bar series therefore produces NO
# values at all.
from __future__ import annotations

from decimal import Decimal

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

BULLISH_ENGULFING_FIELD_ID = "bullish_engulfing"


def compute_bullish_engulfing(bars: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
    """Generic two-candle bullish-engulfing detector - see module
    docstring for the exact rule and its explicit t/t-1-only,
    no-future-data guarantee."""
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
    for i in range(1, len(bars)):
        prev = bars[i - 1]
        curr = bars[i]
        is_bullish_engulfing = (
            prev.close < prev.open
            and curr.close > curr.open
            and curr.close > prev.open
            and curr.open <= prev.close
        )
        values.append(
            FeatureValue(
                feature_name=BULLISH_ENGULFING_FIELD_ID,
                feature_version=FEATURE_ENGINE_VERSION,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=curr.timestamp,
                value=Decimal(1) if is_bullish_engulfing else Decimal(0),
            )
        )

    return tuple(values)
