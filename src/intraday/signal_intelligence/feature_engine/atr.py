# File: src/intraday/signal_intelligence/feature_engine/atr.py
#
# Checkpoint 17: Average True Range - the Feature Engine's third
# computation and its first that is NOT close-only. Proves the
# architecture established at Checkpoints 15/16 already generalizes to a
# calculation needing multiple OHLC fields plus one prior bar's close,
# without requiring a new domain contract (`Bar` already carries
# high/low/close) or a new function-signature shape (still
# `compute_*(definition, bars) -> tuple[FeatureValue, ...]`). Depends
# only on `domain/feature` and `domain/market_data`, exactly like
# `sma.py`/`ema.py` - no application, no infrastructure, no Django, no
# Dhan.
#
# ---------------------------------------------------------------------------
# True Range definition (Checkpoint 17 §3)
# ---------------------------------------------------------------------------
#
#     TR_t = max(
#         High_t - Low_t,
#         abs(High_t - Close_(t-1)),
#         abs(Low_t - Close_(t-1)),
#     )
#
# ---------------------------------------------------------------------------
# First-bar policy (Checkpoint 17 §3, explicit decision)
# ---------------------------------------------------------------------------
#
# The FIRST bar in any input series has no previous close, so it CANNOT
# produce a True Range value - not a degraded one, not one computed
# against itself. `bars[0]` is used ONLY as the "previous bar" supplying
# `Close_(t-1)` for `bars[1]`'s True Range; it never contributes a TR (or
# ATR) value of its own. This is the "first bar cannot produce a true
# range" policy the checkpoint brief prefers, chosen over the rejected
# alternative of silently treating the first bar's own high/low/close as
# both "current" and "previous" (which would produce a TR of
# `High_1 - Low_1` that is mathematically dishonest - not a real true
# range, since there is no real previous close to compare against).
#
# ---------------------------------------------------------------------------
# ATR convention (Checkpoint 17 §4, explicit decision)
# ---------------------------------------------------------------------------
#
# Chosen: canonical WILDER ATR - not an EMA-based ATR.
#
#     ATR_N = mean(TR_1 .. TR_N)                          (the seed)
#     ATR_t = ((ATR_(t-1) * (N - 1)) + TR_t) / N            for t > N
#
# Why: Wilder's own original formulation (J. Welles Wilder Jr., "New
# Concepts in Technical Trading Systems", 1978) is the definition
# universally meant by "ATR" across charting platforms and quant
# literature - an EMA-based variant (`alpha = 2/(N+1)`, this project's
# own EMA convention) is a different, less-conventional indicator that
# happens to share the name "ATR" in some libraries, but is not what
# "ATR" means by default. The checkpoint brief explicitly names Wilder
# ATR as "the preferred convention unless existing architecture evidence
# contradicts it" - no such evidence exists in this codebase (no ATR
# convention was decided anywhere before this checkpoint), so the
# canonical convention is used.
#
# Note Wilder smoothing's own internal weighting (`(N-1)/N` and `1/N`) is
# NOT the same formula as this project's EMA (`alpha=2/(N+1)`) - the two
# recurrences are structurally similar (both a weighted blend of the
# previous value and a new observation) but numerically distinct. This is
# expected: they are different indicators that happen to share a
# "recursive smoothing" shape, not the same calculation reused. No code
# is shared between `ema.py` and `atr.py`'s recurrence for the same
# reason `ema.py` does not call `sma.py` (Checkpoint 16 decision #73) -
# keeping each computation's own formula self-contained and
# unambiguous, with no dependency edge between sibling computations.
#
# ---------------------------------------------------------------------------
# Warm-up semantics (Checkpoint 17 §12, explicit decision)
# ---------------------------------------------------------------------------
#
# `lookback = N` TR observations are required to seed ATR. Since TR
# itself only exists from the SECOND bar onward (first-bar policy above),
# producing the first (seed) ATR value requires `N + 1` bars total:
# bars[0] (supplies only the initial previous-close), plus bars[1..N]
# (produce TR_1..TR_N). The seed ATR's timestamp is `bars[N]`'s own
# timestamp - the bar whose TR completes the seed window, exactly
# mirroring how SMA/EMA's seed timestamp is the bar completing their own
# seed windows. After the seed, one ATR value exists per subsequent bar:
# `M` bars in -> `M - N` ATR values out (one fewer than SMA/EMA's
# `M - N + 1`, because ATR "loses" one bar to the first-bar policy that
# SMA/EMA do not need to lose).
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)


def _true_range(current: Bar, previous: Bar) -> Decimal:
    high_low = current.high - current.low
    high_prev_close = abs(current.high - previous.close)
    low_prev_close = abs(current.low - previous.close)
    return max(high_low, high_prev_close, low_prev_close)


def compute_average_true_range(
    definition: AverageTrueRangeDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """Wilder Average True Range (see module docstring for the full
    convention, first-bar policy, seed, recurrence and warm-up rationale).

    Uses `bar.high`, `bar.low`, `bar.close`, and the PREVIOUS bar's
    `close` - never `open`, `volume`, or any quote/LTP field. `bars[0]`
    supplies only a previous close for `bars[1]`'s True Range and never
    produces a TR/ATR value of its own (the first-bar policy).

    No look-ahead is possible by construction: both the True Range series
    and the Wilder recurrence only ever consume the current bar and
    already-iterated history, in the chronological order
    `ensure_chronological()` below already guarantees.

    Precision: full `Decimal` arithmetic throughout (every True Range,
    the seed mean, and every recursive step) - no `float` conversion
    anywhere, no explicit rounding.

    Complexity: O(n) in the number of input bars, O(1) additional
    calculation state (one running `previous_atr` accumulator, plus one
    single-pass True Range computation per bar) - identical complexity
    shape to `compute_exponential_moving_average`.

    Raises `MixedInstrumentSeriesError`/`MixedTimeframeSeriesError` if
    `bars` mixes instruments/timeframes (same rule as SMA/EMA) and
    whatever `ensure_chronological()` raises
    (`DuplicateBarTimestampError`/`OutOfOrderBarError`) if `bars` is not
    strictly chronological - reusing Checkpoint 14's canonical series
    validation rather than duplicating it.
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

    # True Range exists only from the second bar onward (first-bar
    # policy) - `true_ranges[i]` corresponds to `bars[i + 1]`.
    true_ranges: list[tuple[Bar, Decimal]] = [
        (current, _true_range(current, previous))
        for previous, current in zip(bars, bars[1:], strict=False)
    ]

    seed_window = true_ranges[:lookback]
    seed_atr = sum((tr for _, tr in seed_window), Decimal(0)) / lookback
    seed_bar = seed_window[-1][0]

    values: list[FeatureValue] = [
        FeatureValue(
            feature_name=definition.feature_name,
            feature_version=definition.feature_version,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=seed_bar.timestamp,
            value=seed_atr,
        )
    ]

    n = Decimal(lookback)
    n_minus_1 = Decimal(lookback - 1)
    previous_atr = seed_atr
    for bar, tr in true_ranges[lookback:]:
        current_atr = ((previous_atr * n_minus_1) + tr) / n
        values.append(
            FeatureValue(
                feature_name=definition.feature_name,
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                value=current_atr,
            )
        )
        previous_atr = current_atr

    return tuple(values)
