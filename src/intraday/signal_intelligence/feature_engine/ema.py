# File: src/intraday/signal_intelligence/feature_engine/ema.py
#
# Checkpoint 16: Exponential Moving Average - the Feature Engine's first
# RECURSIVE/STATEFUL calculation, proving the architecture established at
# Checkpoint 15 generalizes beyond a fixed-window average. Depends only on
# `domain/feature` and `domain/market_data`, exactly like `sma.py` - no
# application, no infrastructure, no Django, no Dhan.
#
# ---------------------------------------------------------------------------
# EMA seed / initialization decision (Checkpoint 16 §2 - the most important
# design question of this checkpoint, so it is documented at length here,
# not only in the architecture docs)
# ---------------------------------------------------------------------------
#
# Chosen convention: SEED WITH THE SMA OF THE FIRST N CLOSES (Option B).
#
#     EMA_N = mean(close_1 .. close_N)                    (the seed)
#     EMA_t = alpha * close_t + (1 - alpha) * EMA_(t-1)    for t > N
#
# where `alpha = 2 / (N + 1)`.
#
# Why, not just what:
#
# 1. Reproducibility across independent implementations. "Seed with the
#    first close" (Option A) makes the *entire* infinite recursive series
#    permanently sensitive to a single, comparatively noisy observation -
#    two otherwise-identical EMA(20) series computed from the same closes
#    but starting the recursion one bar apart converge only slowly (the
#    influence of a bad seed decays but never structurally vanishes).
#    Seeding with SMA(N) is the convention used by the overwhelming
#    majority of charting platforms and quant libraries precisely because
#    it gives a stable, well-known, cross-checkable starting point -
#    directly satisfying Checkpoint 16 §2's own instruction to "strongly
#    prefer the convention that gives stable and widely reproducible
#    quantitative results."
# 2. It aligns naturally with the existing SMA foundation (Checkpoint 16
#    §2's second instruction) - this project already has a correct,
#    tested definition of "the mean of the first N closes" one checkpoint
#    old. Reusing that *concept* (not the `compute_simple_moving_average`
#    function itself - see the coupling note below) is the natural choice
#    rather than inventing a second, unrelated seeding idea.
# 3. It gives EMA the identical warm-up length as SMA of the same period -
#    "the first N-1 bars produce no output, the Nth bar's output is your
#    first valid value" - so a caller who has already internalized SMA's
#    warm-up semantics (Checkpoint 15 §11) does not need to learn a second,
#    different warm-up rule for EMA. (Option A would emit a first value
#    immediately at bar 1, which is a materially different, and less
#    useful, guarantee.)
#
# Explicitly rejected: Option A (seed = first close) - produces a
# permanently-biased early series and a first output at bar 1 that is not
# actually a "period-N" value in any meaningful sense (it is just the raw
# close, mislabeled as `ema_N`).
#
# ---------------------------------------------------------------------------
# Coupling note (Checkpoint 16 §12)
# ---------------------------------------------------------------------------
#
# The seed (mean of the first N closes) is computed LOCALLY in this module
# (`_seed_mean`), NOT by calling `sma.compute_simple_moving_average`. Two
# reasons, both architectural rather than convenience-driven:
#
# 1. `compute_simple_moving_average` returns a `tuple[FeatureValue, ...]`
#    identified as `sma_{N}` - reusing it to derive the EMA seed would mean
#    EMA's own internal seed seam is expressed in terms of a *different
#    feature's public output type*, an inappropriate coupling between two
#    otherwise-independent, separately-versioned features (a future change
#    to SMA's own semantics - e.g. a rounding policy - would silently
#    change EMA's seed too, an action-at-a-distance bug this module
#    refuses to introduce).
# 2. It avoids a dependency edge between `sma.py` and `ema.py` altogether -
#    each computation file depends only on `domain/feature`+
#    `domain/market_data`, never on a sibling computation. This keeps a
#    future removal or rewrite of SMA from being able to break EMA, and
#    vice versa.
#
# The *value* computed (mean of N closes) is conceptually identical to SMA
# by design (see point 2 above) - only the code path computing it is kept
# separate.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.feature_engine.definitions import (
    ExponentialMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)


def compute_exponential_moving_average(
    definition: ExponentialMovingAverageDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """`EMA_N = mean(close_1 .. close_N)` (the seed, at the Nth bar), then
    `EMA_t = alpha * close_t + (1 - alpha) * EMA_(t-1)` for every bar after
    the seed, where `alpha = Decimal(2) / Decimal(N + 1)` (see module
    docstring for the full seed-convention rationale).

    No look-ahead is possible by construction: the recursive accumulator
    (`previous_ema`) only ever carries forward a value computed from bars
    already iterated, in the chronological order `ensure_chronological()`
    below already guarantees - there is no code path through which a bar
    later in the sequence could influence an earlier output. This is also
    tested explicitly, not merely assumed (Checkpoint 16 §6).

    Warm-up (Checkpoint 16 §7, §11): the first `lookback - 1` bars produce
    NO output - not `None`, not a partial-window average. Exactly
    `lookback` observations are required before the first (seed) value is
    emitted. After the seed, one output exists per subsequent input bar,
    chronologically ordered (`N` bars in -> `N - lookback + 1` values out -
    identical output-count shape to `compute_simple_moving_average`).

    Output alignment: `FeatureValue.timestamp` equals its source bar's own
    `timestamp` (the bar's CLOSE time), identical to SMA's convention - no
    second timestamp rule is introduced.

    Precision: full `Decimal` arithmetic throughout - `alpha`, the seed
    mean, and every recursive step - no `float` conversion anywhere, no
    explicit rounding applied (a consumer needing display precision rounds
    explicitly at its own boundary).

    Stateful computation model (Checkpoint 16 §13): a single scalar
    accumulator (`previous_ema: Decimal | None`) is the entire calculation
    state - O(1) additional state beyond the output collection, O(n) time
    in the number of input bars. This function remains pure: the
    accumulator is local to this single call, never a global, never
    persisted between invocations - repeated calls with identical input
    produce identical output (Checkpoint 16 §14).

    Raises `MixedInstrumentSeriesError`/`MixedTimeframeSeriesError` if
    `bars` mixes instruments/timeframes (same rule as SMA, Checkpoint 15
    §11/§12) and whatever `ensure_chronological()` raises
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
    if len(bars) < lookback:
        return ()

    alpha = Decimal(2) / Decimal(lookback + 1)
    one_minus_alpha = Decimal(1) - alpha

    values: list[FeatureValue] = []

    # Seed: mean of the first `lookback` closes, computed locally (not via
    # `sma.compute_simple_moving_average` - see module docstring's
    # coupling note).
    seed_window = bars[:lookback]
    previous_ema = sum((bar.close for bar in seed_window), Decimal(0)) / lookback
    values.append(
        FeatureValue(
            feature_name=definition.feature_name,
            feature_version=definition.feature_version,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=seed_window[-1].timestamp,
            value=previous_ema,
        )
    )

    # Recurrence: every bar after the seed.
    for bar in bars[lookback:]:
        current_ema = alpha * bar.close + one_minus_alpha * previous_ema
        values.append(
            FeatureValue(
                feature_name=definition.feature_name,
                feature_version=definition.feature_version,
                instrument_id=instrument_id,
                timeframe=timeframe,
                timestamp=bar.timestamp,
                value=current_ema,
            )
        )
        previous_ema = current_ema

    return tuple(values)
