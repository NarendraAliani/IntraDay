# File: src/intraday/signal_intelligence/feature_engine/rsi.py
#
# Checkpoint 64.49: Relative Strength Index - a PLATFORM/CANONICAL
# feature, not a Gainz-specific one. Built because 64.48 discovered the
# canonical feature registry had no RSI, ADX/+DI/-DI, Relative Volume,
# MACD Histogram, or Candle Body Ratio - not because a real Gainz
# reference implementation was ported (none exists in this repository;
# re-verified this checkpoint - see field_registry.py's module docstring
# and taskReport.md).
#
# ---------------------------------------------------------------------------
# FORMULA SOURCE - CRITICAL (Checkpoint 64.49 directive Part 5/6)
# ---------------------------------------------------------------------------
#
# Convention used: Wilder's ORIGINAL RSI (J. Welles Wilder Jr., "New
# Concepts in Technical Trading Systems", 1978) - the same smoothing
# family this project's own `atr.py` already documents as "the
# convention universally meant by ATR". Wilder's RSI is likewise the
# convention universally meant by "RSI" (period 14 by market default)
# across charting platforms and quant literature, and it composes
# naturally with this project's existing Wilder-ATR precedent (same
# smoothing shape: seed = simple mean of first N, then
# `avg_t = (avg_(t-1) * (N-1) + new_t) / N`).
#
# THIS IS A STANDARD, WELL-KNOWN TECHNICAL-ANALYSIS CONVENTION. It is
# NOT verified against any Gainz reference implementation, because no
# such file exists anywhere in this repository (Checkpoint 64.48's own
# honest finding, independently re-confirmed this checkpoint). If a real
# Gainz reference source is ever supplied, THIS implementation must be
# re-verified numerically against it before any strategy is allowed to
# assume identical RSI values.
#
#     diff_t   = close_t - close_(t-1)               (t >= 2)
#     gain_t   = max(diff_t, 0)
#     loss_t   = max(-diff_t, 0)
#     avg_gain_N = mean(gain_2 .. gain_(N+1))          (the seed)
#     avg_loss_N = mean(loss_2 .. loss_(N+1))          (the seed)
#     avg_gain_t = (avg_gain_(t-1) * (N-1) + gain_t) / N   for t > seed
#     avg_loss_t = (avg_loss_(t-1) * (N-1) + loss_t) / N   for t > seed
#     RS_t   = avg_gain_t / avg_loss_t
#     RSI_t  = 100 - (100 / (1 + RS_t))
#
# Edge cases (explicit, not guessed):
#     avg_loss_t == 0 and avg_gain_t == 0  -> RSI_t = 50 (flat/no-move
#         market - RS is mathematically 0/0; 50 is the conventional
#         "neutral" value used by every mainstream RSI implementation for
#         this degenerate case, not a Gainz-specific choice).
#     avg_loss_t == 0 and avg_gain_t  > 0  -> RSI_t = 100 (no losses in
#         the smoothing window at all - RS -> infinity).
#
# ---------------------------------------------------------------------------
# Warm-up (Checkpoint 64.49 Part 6/15)
# ---------------------------------------------------------------------------
#
# The first bar supplies no `diff` (needs a previous close - identical
# first-bar policy to `atr.py`'s True Range). `lookback = N` diffs are
# required to seed the Wilder average, so `N + 1` bars total are required
# before the FIRST RSI value is produced - exactly mirroring
# `compute_average_true_range`'s own warm-up shape (`N + 1` bars in,
# first output at `bars[N]`). Fewer than `N + 1` bars -> empty tuple, NOT
# a fabricated/partial-window value (Checkpoint 64.49 Part 15's "must not
# receive fabricated values").
#
# ---------------------------------------------------------------------------
# Threshold policy (Checkpoint 64.49 Part 6, explicit instruction)
# ---------------------------------------------------------------------------
#
# This feature returns ONLY the raw RSI value (range [0, 100]). No
# overbought/oversold threshold (e.g. 70/30) is hard-coded here - that is
# strategy CONFIGURATION, decided by whatever future strategy consumes
# this field, never baked into the feature itself.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    RelativeStrengthIndexDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)

_FIFTY = Decimal(50)
_HUNDRED = Decimal(100)


def compute_relative_strength_index(
    definition: RelativeStrengthIndexDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """Wilder RSI (see module docstring for the full formula, seed,
    edge-case, and warm-up documentation). No look-ahead is possible by
    construction: both the gain/loss series and the Wilder recurrence
    only ever consume the current bar and already-iterated history, in
    the chronological order `ensure_chronological()` below already
    guarantees.

    Precision: full `Decimal` arithmetic throughout, no `float`
    conversion, no explicit rounding.
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
    if len(bars) < lookback + 1:
        return ()

    # gains_losses[i] corresponds to bars[i + 1] (first-bar policy).
    gains_losses: list[tuple[Bar, Decimal, Decimal]] = []
    for previous, current in zip(bars, bars[1:], strict=False):
        diff = current.close - previous.close
        gain = diff if diff > 0 else Decimal(0)
        loss = -diff if diff < 0 else Decimal(0)
        gains_losses.append((current, gain, loss))

    seed_window = gains_losses[:lookback]
    seed_gain = sum((g for _, g, _ in seed_window), Decimal(0)) / lookback
    seed_loss = sum((loss for _, _, loss in seed_window), Decimal(0)) / lookback
    seed_bar = seed_window[-1][0]

    def _rsi(avg_gain: Decimal, avg_loss: Decimal) -> Decimal:
        if avg_loss == 0 and avg_gain == 0:
            return _FIFTY
        if avg_loss == 0:
            return _HUNDRED
        rs = avg_gain / avg_loss
        return _HUNDRED - (_HUNDRED / (Decimal(1) + rs))

    values: list[FeatureValue] = [
        FeatureValue(
            feature_name=definition.feature_name,
            feature_version=definition.feature_version,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=seed_bar.timestamp,
            value=_rsi(seed_gain, seed_loss),
        )
    ]

    n = Decimal(lookback)
    n_minus_1 = Decimal(lookback - 1)
    avg_gain = seed_gain
    avg_loss = seed_loss
    for bar, gain, loss in gains_losses[lookback:]:
        avg_gain = ((avg_gain * n_minus_1) + gain) / n
        avg_loss = ((avg_loss * n_minus_1) + loss) / n
        values.append(
            FeatureValue(
                feature_name=definition.feature_name,
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                value=_rsi(avg_gain, avg_loss),
            )
        )

    return tuple(values)
