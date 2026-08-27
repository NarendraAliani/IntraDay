# File: src/intraday/signal_intelligence/feature_engine/bearish_engulfing.py
#
# Checkpoint 64.97: Bearish Engulfing - the symmetric counterpart of
# `bullish_engulfing.py`. Same disclaimers apply verbatim (see that
# module's header) - GENERIC candlestick feature, NOT authentic-GainzAlgo
# verified, structurally identical to the reference file's own
# `bearish_engulfing` column (read-only comparison only).
#
#     bearish_engulfing_t = (close[t-1] > open[t-1])   # prior candle bullish
#                        AND (close[t] < open[t])       # current candle bearish
#                        AND (close[t] < open[t-1])     # current close < prior open
#                        AND (open[t] >= close[t-1])    # current open >= prior close
#
# Look-ahead safety, Decimal-boolean encoding, and warm-up semantics are
# all identical to `bullish_engulfing.py` - see that module's docstring
# for the full rationale, not repeated here.
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

BEARISH_ENGULFING_FIELD_ID = "bearish_engulfing"


def compute_bearish_engulfing(bars: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
    """Generic two-candle bearish-engulfing detector - see module
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
        is_bearish_engulfing = (
            prev.close > prev.open
            and curr.close < curr.open
            and curr.close < prev.open
            and curr.open >= prev.close
        )
        values.append(
            FeatureValue(
                feature_name=BEARISH_ENGULFING_FIELD_ID,
                feature_version=FEATURE_ENGINE_VERSION,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=curr.timestamp,
                value=Decimal(1) if is_bearish_engulfing else Decimal(0),
            )
        )

    return tuple(values)
