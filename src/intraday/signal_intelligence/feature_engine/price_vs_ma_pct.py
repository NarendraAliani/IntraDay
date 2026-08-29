# File: src/intraday/signal_intelligence/feature_engine/price_vs_ma_pct.py
#
# Checkpoint 65.03: Price vs Moving Average Percentage - a generic,
# reusable, parameterized "how far is price from its moving average"
# feature. First implementation candidate carried forward from
# Checkpoint 65.02's Market Context Intelligence audit
# (docs/research/MARKET_CONTEXT_INTELLIGENCE.md) - the ONLY concept
# implemented this checkpoint (rebound_candidate, market_regime, sector
# deviation, sectorwise DMA, sentiment, index correlation, unwinding,
# Firecell are all explicitly OUT OF SCOPE - see that doc and
# taskReport.md).
#
#     price_vs_ma_pct(t) = (close[t] - moving_average(t)) / moving_average(t)
#
# Output is a SIGNED Decimal percentage (as a fraction, e.g. 0.02 = price
# 2% above the MA; NOT pre-multiplied by 100 - identical convention to
# every other ratio-shaped canonical feature in this engine, e.g.
# `relative_volume`, which is also a bare ratio, not a "x100 percent"
# value). >0 means price is above the MA, <0 means price is below the
# MA, =0 means price exactly equals the MA. NEVER a boolean - a future
# strategy/context layer thresholds this numeric value itself.
#
# ---------------------------------------------------------------------------
# Design decision: ONE shared formula, TWO field identities (SMA/EMA)
# ---------------------------------------------------------------------------
#
# The directive asks whether MA type ("sma"/"ema") can be represented as
# a parameter of ONE feature contract, or whether the architecture
# requires two separate identities. Inspecting the existing
# `field_registry.parse_feature_name()` algorithm (used by BOTH the
# registry resolver and `application.services.strategy_execution.
# compute_feature_series()`'s dispatcher) shows it strips only a
# TRAILING RUN OF INTEGER SEGMENTS off a feature name to recover its
# parameters (`"macd_hist_12_26_9"` -> kind `"macd_hist"`, params
# `(12, 26, 9)`) - every existing parameter is numeric. MA type
# ("sma"/"ema") is categorical, not numeric, so it cannot be smuggled
# into that same trailing-integer-suffix slot without either (a)
# breaking the existing parser for every other feature, or (b) inventing
# a second, incompatible parsing convention - both rejected.
#
# The smallest correct fix that reuses the EXISTING convention exactly
# (multi-word kinds are already supported - "plus_di", "minus_di",
# "relative_volume", "macd_hist" are all multi-word kinds followed by
# purely-numeric params) is to fold the MA type into the KIND itself:
# two field identities, `price_vs_ma_pct_sma` and `price_vs_ma_pct_ema`,
# each taking a single numeric `lookback` parameter
# (`"price_vs_ma_pct_sma_20"` -> kind `"price_vs_ma_pct_sma"`, params
# `(20,)`). This is NOT a duplicate implementation: both identities
# delegate to the SAME core formula function below
# (`_price_vs_ma_pct_from_ma_series`) and to the SAME canonical SMA/EMA
# compute functions (`sma.compute_simple_moving_average`/
# `ema.compute_exponential_moving_average`) already used everywhere
# else in this engine - no second moving-average engine is created, only
# two thin, symmetric public wrappers plus two `Definition` identities
# in `definitions.py`, following the exact one-off-dataclass-per-identity
# pattern every other feature identity already uses.
#
# No new registry, no new namespace architecture - two more entries in
# the SAME `field_registry._FIELDS` tuple.
#
# ---------------------------------------------------------------------------
# Warm-up
# ---------------------------------------------------------------------------
#
# Identical to the underlying MA's own warm-up (Checkpoint 15/16): SMA
# needs `lookback` closes before its first value, EMA needs `lookback`
# closes before its seed. `price_vs_ma_pct` can therefore only ever be
# emitted starting at the underlying MA's own first valid index - no new
# warm-up policy is invented here. The first `lookback - 1` bars produce
# NO output at all (not `None`, not a partial value).
#
# ---------------------------------------------------------------------------
# Look-ahead safety
# ---------------------------------------------------------------------------
#
# `price_vs_ma_pct(t)` depends only on `close[t]` and `moving_average(t)`
# - and `moving_average(t)` is itself computed by the existing SMA/EMA
# functions, which are already proven (Checkpoints 15/16) to depend only
# on bars at or before `t`. No future bar can ever participate in any
# output at index `t`.
#
# ---------------------------------------------------------------------------
# Divide-by-zero / invalid MA handling
# ---------------------------------------------------------------------------
#
# `Bar.__post_init__` (domain/market_data/contracts.py) already forbids
# non-positive `close`, so a raw close can never be zero/negative -
# but an SMA/EMA VALUE could still mathematically reach exactly zero
# (e.g. a lookback window whose closes happen to sum to a value the
# recursive EMA formula could, in principle, drive to zero over many
# bars, or - defensively - if a future MA source ever legitimately
# produces zero). This module treats `moving_average(t) == 0` as "the
# ratio is undefined at t" and SKIPS that output entirely (same "skip,
# never fabricate" discipline `candle_body_ratio.py` already uses for
# zero-range bars, and `relative_volume.py` for a zero baseline) -
# NEVER a raw `ZeroDivisionError`, NEVER a silently wrong value.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    PriceVsMaPctEmaDefinition,
    PriceVsMaPctSmaDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average


def _price_vs_ma_pct_from_ma_series(
    feature_name: str,
    feature_version,
    bars: tuple[Bar, ...],
    ma_values: tuple[FeatureValue, ...],
) -> tuple[FeatureValue, ...]:
    """Shared core: combines an already-computed MA `FeatureValue` series
    (SMA or EMA - this function does not know or care which) with the
    same bars' closes, by timestamp, into signed `price_vs_ma_pct`
    values. A zero MA value is skipped (see module docstring's
    divide-by-zero section), never dividing by zero."""
    close_by_timestamp = {bar.timestamp: bar.close for bar in bars}
    values: list[FeatureValue] = []
    for ma in ma_values:
        close = close_by_timestamp.get(ma.timestamp)
        if close is None:
            # Cannot happen given both series derive from the same `bars`
            # input, but never silently mismatch timestamps if it did.
            continue
        if ma.value == 0:
            continue
        values.append(
            FeatureValue(
                feature_name=feature_name,
                feature_version=feature_version,
                instrument_id=ma.instrument_id,
                timeframe=ma.timeframe,
                timestamp=ma.timestamp,
                value=(close - ma.value) / ma.value,
            )
        )
    return tuple(values)


def _validate_series(bars: tuple[Bar, ...]) -> None:
    """Series-integrity checks identical to every other feature in this
    engine - reused via `ensure_chronological`, not reimplemented. Kept
    here too (in addition to the underlying SMA/EMA call already
    performing it) purely so the error is raised before any work is
    done, matching this engine's existing fail-fast convention."""
    if not bars:
        return
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


def compute_price_vs_ma_pct_sma(
    definition: PriceVsMaPctSmaDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """`price_vs_ma_pct` against the canonical SMA - see module docstring
    for the full formula/warm-up/look-ahead/zero-MA documentation."""
    if not bars:
        return ()
    _validate_series(bars)
    sma_values = compute_simple_moving_average(definition.sma_definition, bars)
    return _price_vs_ma_pct_from_ma_series(
        definition.feature_name, definition.feature_version, bars, sma_values
    )


def compute_price_vs_ma_pct_ema(
    definition: PriceVsMaPctEmaDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """`price_vs_ma_pct` against the canonical EMA - see module docstring
    for the full formula/warm-up/look-ahead/zero-MA documentation."""
    if not bars:
        return ()
    _validate_series(bars)
    ema_values = compute_exponential_moving_average(definition.ema_definition, bars)
    return _price_vs_ma_pct_from_ma_series(
        definition.feature_name, definition.feature_version, bars, ema_values
    )
