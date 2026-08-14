# File: src/intraday/signal_intelligence/theoretical_outcome/outcome.py
#
# Checkpoint 21: the first Theoretical Outcome rule - a deterministic,
# pure measurement of maximum favorable/adverse price excursion (MFE/
# MAE) a `DirectionalIndication` (Checkpoint 18) experienced over an
# explicit future observation window. Depends only on
# `signal_intelligence.signal_generation.contracts.DirectionalIndication`
# (documented intra-bounded-context reuse, same precedent as
# Checkpoints 19/20) and `domain/market_data` (`Bar`) - never
# `signal_verification`, `signal_lifecycle`, `trading_engine`, or
# infrastructure.
#
# ---------------------------------------------------------------------------
# Reference price (Checkpoint 21 §5, explicit decision)
# ---------------------------------------------------------------------------
#
# `indication.price` - the SAME reference price Checkpoint 19's
# `VerificationResult` already uses. Reusing it (rather than "first
# future bar close/open") keeps every signal-intelligence measurement
# anchored to the one canonical "what price was known at signal time"
# value `DirectionalIndication` already carries - introducing a second
# reference-price convention here would let the two measurements
# silently disagree about what "the signal price" even means.
#
# ---------------------------------------------------------------------------
# MFE / MAE definition (Checkpoint 21 §4, explicit decision - a
# deliberate refinement of the brief's own illustrative formula)
# ---------------------------------------------------------------------------
#
#     BULLISH:
#         MFE = max(0, max_i(high_i - reference_price))
#         MAE = min(0, min_i(low_i  - reference_price))
#
#     BEARISH:
#         MFE = max(0, max_i(reference_price - low_i))
#         MAE = min(0, min_i(reference_price - high_i))
#
# where i ranges over every future bar in the observation window.
#
# The brief's own illustrative formula (`MFE = max(future_high -
# reference)`, `MAE = min(future_low - reference)`) is used AS THE BASIS
# but explicitly CLAMPED at zero here - a deliberate refinement, not an
# oversight: MFE ("favorable excursion") can never legitimately be
# negative (a "negative favorable movement" is not favorable at all,
# it's simply the absence of one), and MAE ("adverse excursion") can
# never legitimately be positive (a "positive adverse movement" is not
# adverse, it's the absence of one). Without clamping, a BULLISH
# indication whose price only ever rose would report a spuriously
# "positive" MAE (e.g. low never dropped below reference, so
# `min(low - reference)` > 0) - which would misleadingly suggest a
# FAVORABLE minimum instead of correctly reporting "no adverse movement
# occurred" (MAE = 0). This clamping is what makes `MFE >= 0` and
# `MAE <= 0` universal invariants, tested directly as Hypothesis
# properties.
#
# ---------------------------------------------------------------------------
# NEUTRAL semantics (Checkpoint 21 §13, explicit decision)
# ---------------------------------------------------------------------------
#
# A NEUTRAL indication has no favorable/adverse direction to measure -
# "favorable" and "adverse" are meaningless without a directional call
# to measure them against. `mfe`/`mae` are `None` for NEUTRAL, not `0`
# (which would be a real, different, dishonest measurement implying "no
# movement occurred" when movement may well have occurred - it simply
# isn't classifiable as favorable/adverse without a direction).
#
# ---------------------------------------------------------------------------
# Partial / missing horizon semantics (Checkpoint 21 §14-15)
# ---------------------------------------------------------------------------
#
# `ObservationCompleteness.NO_DATA` (zero future bars) - `mfe`/`mae` are
# `None`, never `0` - missing data must remain distinguishable from a
# genuine zero excursion (Checkpoint 21 §14's own explicit warning).
# `ObservationCompleteness.PARTIAL` (1..horizon_bars-1 bars available) -
# MFE/MAE ARE computed from the bars that exist (a real, honest
# measurement over a shorter-than-requested window - not silently
# treated as if the full horizon had been observed), but `completeness`
# explicitly flags this as PARTIAL so a consumer never mistakes it for
# a COMPLETE measurement. `ObservationCompleteness.COMPLETE` - at least
# `horizon_bars` future bars were available; only the first
# `horizon_bars` are used (extra bars beyond the horizon are accepted
# but ignored, mirroring Checkpoint 19's own single-point-verification
# policy for over-supplied series).
#
# ---------------------------------------------------------------------------
# Same-bar high/low ambiguity (Checkpoint 21 §19, explicit non-decision)
# ---------------------------------------------------------------------------
#
# A single future bar can legitimately contribute to BOTH the MFE and
# MAE calculation (its high driving MFE, its low driving MAE, or vice
# versa for BEARISH) - this function makes NO claim about which
# occurred first within that bar. OHLC data alone cannot answer that
# (it would require intrabar tick data, out of scope). No
# target-hit-before-stop/stop-before-target inference is made anywhere
# in this module.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.signal_generation.contracts import (
    DirectionalIndication,
    SignalDirection,
)
from intraday.signal_intelligence.theoretical_outcome.contracts import (
    OUTCOME_DEFINITION_NAME,
    OUTCOME_DEFINITION_VERSION,
    ObservationCompleteness,
    TheoreticalOutcome,
)
from intraday.signal_intelligence.theoretical_outcome.errors import (
    InvalidHorizonError,
    MismatchedInstrumentError,
    MismatchedTimeframeError,
    NonFutureObservationError,
)


def compute_theoretical_outcome(
    indication: DirectionalIndication, future_bars: tuple[Bar, ...], horizon_bars: int
) -> TheoreticalOutcome:
    """Measures MFE/MAE for `indication` over `future_bars` (bars
    strictly after `indication.timestamp`, for the same instrument/
    timeframe, in chronological order), using at most the first
    `horizon_bars` of them. See module docstring for the full
    reference-price/MFE-MAE/NEUTRAL/partial-horizon/same-bar-ambiguity
    semantics.

    Raises `InvalidHorizonError` if `horizon_bars` is not a positive
    integer, `MismatchedInstrumentError`/`MismatchedTimeframeError` if
    any bar does not match `indication`'s instrument/timeframe, and
    `NonFutureObservationError` if any bar's timestamp is not strictly
    after `indication.timestamp`. Reuses `ensure_chronological()`
    (Checkpoint 14) for ordering/duplicate validation - not
    reimplemented.

    Pure and side-effect-free: no database, no network, no mutation of
    `indication` or any bar. Deterministic - identical inputs always
    produce an identical `TheoreticalOutcome`.
    """
    if isinstance(horizon_bars, bool) or not isinstance(horizon_bars, int) or horizon_bars <= 0:
        raise InvalidHorizonError(f"horizon_bars must be a positive int, got {horizon_bars!r}")

    ensure_chronological(future_bars)

    for bar in future_bars:
        if bar.instrument_id != indication.instrument_id:
            raise MismatchedInstrumentError(
                f"future bar instrument {bar.instrument_id!r} does not match "
                f"indication instrument {indication.instrument_id!r}"
            )
        if bar.timeframe != indication.timeframe:
            raise MismatchedTimeframeError(
                f"future bar timeframe {bar.timeframe!r} does not match "
                f"indication timeframe {indication.timeframe!r}"
            )
        if bar.timestamp <= indication.timestamp:
            raise NonFutureObservationError(
                f"bar at {bar.timestamp.isoformat()} is not strictly after the signal "
                f"timestamp {indication.timestamp.isoformat()}"
            )

    window = future_bars[:horizon_bars]
    bars_observed = len(window)

    if bars_observed == 0:
        completeness = ObservationCompleteness.NO_DATA
    elif bars_observed < horizon_bars:
        completeness = ObservationCompleteness.PARTIAL
    else:
        completeness = ObservationCompleteness.COMPLETE

    reference_price = indication.price
    mfe: Decimal | None
    mae: Decimal | None

    if indication.direction is SignalDirection.NEUTRAL or bars_observed == 0:
        mfe = None
        mae = None
    elif indication.direction is SignalDirection.BULLISH:
        mfe = max(Decimal(0), max(bar.high - reference_price for bar in window))
        mae = min(Decimal(0), min(bar.low - reference_price for bar in window))
    else:  # BEARISH
        mfe = max(Decimal(0), max(reference_price - bar.low for bar in window))
        mae = min(Decimal(0), min(reference_price - bar.high for bar in window))

    return TheoreticalOutcome(
        outcome_definition_name=OUTCOME_DEFINITION_NAME,
        outcome_definition_version=OUTCOME_DEFINITION_VERSION,
        instrument_id=indication.instrument_id,
        timeframe=indication.timeframe,
        signal_timestamp=indication.timestamp,
        horizon_bars=horizon_bars,
        direction=indication.direction,
        reference_price=reference_price,
        mfe=mfe,
        mae=mae,
        bars_observed=bars_observed,
        completeness=completeness,
        indication=indication,
    )


def compute_theoretical_outcomes(
    indications: tuple[DirectionalIndication, ...],
    bars: tuple[Bar, ...],
    horizon_bars: int,
) -> tuple[TheoreticalOutcome, ...]:
    """Measures multiple `DirectionalIndication`s against one shared bar
    series - the series-level counterpart to `compute_theoretical_outcome`,
    mirroring `signal_verification.verify_directional_indications`'s
    exact shape. Preserves input order; each indication's outcome is
    computed independently, using only its own future bars, never
    another indication's."""
    if not indications:
        return ()

    instrument_id = indications[0].instrument_id
    timeframe = indications[0].timeframe
    for indication in indications:
        if indication.instrument_id != instrument_id:
            raise MismatchedInstrumentError(
                f"indications mix instruments {instrument_id!r} and {indication.instrument_id!r}"
            )
        if indication.timeframe != timeframe:
            raise MismatchedTimeframeError(
                f"indications mix timeframes {timeframe!r} and {indication.timeframe!r}"
            )
    for bar in bars:
        if bar.instrument_id != instrument_id:
            raise MismatchedInstrumentError(
                f"bars series mixes instrument {bar.instrument_id!r} with "
                f"indications' instrument {instrument_id!r}"
            )
        if bar.timeframe != timeframe:
            raise MismatchedTimeframeError(
                f"bars series mixes timeframe {bar.timeframe!r} with "
                f"indications' timeframe {timeframe!r}"
            )

    ensure_chronological(bars)

    results: list[TheoreticalOutcome] = []
    for indication in indications:
        future_bars = tuple(bar for bar in bars if bar.timestamp > indication.timestamp)
        results.append(compute_theoretical_outcome(indication, future_bars, horizon_bars))
    return tuple(results)
