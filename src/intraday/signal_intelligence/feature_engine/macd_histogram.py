# File: src/intraday/signal_intelligence/feature_engine/macd_histogram.py
#
# Checkpoint 64.49: MACD Histogram - a canonical PLATFORM feature. No
# Gainz reference source exists in this repository (see
# `field_registry.py` module docstring and taskReport.md) - the standard
# 12/26/9 convention below is NOT verified against Gainz.
#
# ---------------------------------------------------------------------------
# FORMULA SOURCE - CRITICAL
# ---------------------------------------------------------------------------
#
# Convention: the standard MACD (Gerald Appel), universally parameterized
# 12/26/9 by market default:
#
#     MACD_line_t   = EMA_fast_t - EMA_slow_t     (fast=12, slow=26 by
#                                                    default)
#     signal_line_t = EMA_signal(MACD_line)_t      (signal period = 9 by
#                                                    default)
#     histogram_t   = MACD_line_t - signal_line_t
#
# `fast_lookback`/`slow_lookback`/`signal_lookback` are explicit
# parameters (default 12/26/9) - not hard-coded - per Checkpoint 64.49
# Part 9's own instruction to determine fast/slow/signal EMA periods
# explicitly.
#
# ---------------------------------------------------------------------------
# EMA REUSE (Checkpoint 64.49 Part 2/9: "do not create another EMA
# implementation")
# ---------------------------------------------------------------------------
#
# `EMA_fast`/`EMA_slow` are computed by calling the EXISTING canonical
# `signal_intelligence.feature_engine.ema.compute_exponential_moving_average`
# directly on the real input `bars` - zero duplicated EMA math, literal
# reuse.
#
# The SIGNAL line is different: it is the EMA of the *MACD line series*
# (a derived scalar), not of a bar series - and `Bar.__post_init__`
# requires every OHLC field to be a STRICTLY POSITIVE `Decimal`
# (`domain/market_data/contracts.py`), while a MACD line value can
# legitimately be negative or zero. It is therefore IMPOSSIBLE to wrap
# MACD-line values in synthetic `Bar` objects and pass them through the
# real Bar-taking EMA function without violating that domain invariant.
# `_ema_of_series` below applies the EXACT SAME seed+recurrence
# CONVENTION `ema.py` documents (seed = simple mean of the first N
# values; then `EMA_t = alpha * value_t + (1 - alpha) * EMA_(t-1)`,
# `alpha = 2 / (N + 1)`) to a plain `Decimal` sequence - this is the same
# non-duplication precedent `ema.py` itself sets for its OWN seed (it
# reimplements "mean of first N" locally rather than calling `sma.py`,
# to avoid an inappropriate cross-feature coupling - see `ema.py`'s
# "Coupling note"). No second EMA FRAMEWORK is created; this is a single
# private helper applying one already-canonical formula to a value shape
# `Bar` cannot represent.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    ExponentialMovingAverageDefinition,
    MacdHistogramDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import (
    compute_exponential_moving_average,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)


def _ema_of_series(values: list[Decimal], period: int) -> list[Decimal | None]:
    """Same seed+recurrence convention as `ema.py` (see module
    docstring), applied to a plain Decimal sequence. Returns one entry
    per input value: `None` before the seed is reached, the EMA value
    from the seed onward."""
    if len(values) < period:
        return [None] * len(values)
    out: list[Decimal | None] = [None] * (period - 1)
    alpha = Decimal(2) / Decimal(period + 1)
    one_minus_alpha = Decimal(1) - alpha
    seed = sum(values[:period], Decimal(0)) / period
    out.append(seed)
    previous = seed
    for value in values[period:]:
        current = alpha * value + one_minus_alpha * previous
        out.append(current)
        previous = current
    return out


def compute_macd_histogram(
    definition: MacdHistogramDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """MACD Histogram (see module docstring for the full formula, EMA-
    reuse rationale, and parameterization). No look-ahead: `EMA_fast`/
    `EMA_slow` are the existing forward-only canonical EMA function; the
    signal-line helper is the identical forward-only seed+recurrence
    shape applied to the (already forward-only) MACD line."""
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

    ema_fast = compute_exponential_moving_average(
        ExponentialMovingAverageDefinition(definition.fast_lookback), bars
    )
    ema_slow = compute_exponential_moving_average(
        ExponentialMovingAverageDefinition(definition.slow_lookback), bars
    )
    if not ema_fast or not ema_slow:
        return ()

    fast_by_ts = {fv.timestamp: fv.value for fv in ema_fast}
    # MACD line exists only where BOTH fast and slow EMA exist - slow's
    # own timestamps are always a subset of fast's (slow_lookback >
    # fast_lookback by convention), so iterate slow's series.
    macd_bars = list(ema_slow)
    macd_line: list[Decimal] = [fast_by_ts[fv.timestamp] - fv.value for fv in macd_bars]

    signal = _ema_of_series(macd_line, definition.signal_lookback)

    values: list[FeatureValue] = []
    for fv, macd_value, signal_value in zip(macd_bars, macd_line, signal, strict=True):
        if signal_value is None:
            continue
        values.append(
            FeatureValue(
                feature_name=definition.feature_name,
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=fv.timestamp,
                value=macd_value - signal_value,
            )
        )

    return tuple(values)
