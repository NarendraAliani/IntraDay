# File: src/intraday/signal_intelligence/signal_verification/verification.py
#
# Checkpoint 19: the first Signal Verification rule - a deterministic,
# pure evaluation of whether actual subsequent price movement supported
# a `DirectionalIndication`'s (Checkpoint 18) directional call. Depends
# on `signal_intelligence.signal_generation.contracts.DirectionalIndication`
# (see that module and `contracts.py` here for why this is intra-bounded-
# context reuse, not a domain/ dependency) and `domain/market_data`
# (`Bar`) - never on `feature_engine`'s compute functions, never on
# `theoretical_outcome`/MFE/MAE (explicitly out of scope this checkpoint).
#
# ---------------------------------------------------------------------------
# Outcome semantics (Checkpoint 19 §4, §6)
# ---------------------------------------------------------------------------
#
#     BULLISH  + observed_price > reference_price  -> SUPPORTED
#     BULLISH  + observed_price <= reference_price -> NOT_SUPPORTED
#
#     BEARISH  + observed_price < reference_price  -> SUPPORTED
#     BEARISH  + observed_price >= reference_price -> NOT_SUPPORTED
#
#     NEUTRAL  (any observed_price)                -> INCONCLUSIVE
#
# `reference_price` is `indication.price` (Checkpoint 19 §7) - the
# signal-time close, already carried on `DirectionalIndication` from
# Checkpoint 18; never a future bar's close.
#
# Equal prices (`observed_price == reference_price`) are treated as
# NOT_SUPPORTED for BULLISH/BEARISH, not SUPPORTED and not INCONCLUSIVE
# - "no net movement" cannot honestly SUPPORT a directional call that
# specifically predicted movement in one direction (an explicit decision,
# not left ambiguous - mirrors `generate_directional_indication`'s own
# treatment of equality as "no directional condition met").
#
# NEUTRAL is never silently treated as NOT_SUPPORTED (Checkpoint 19
# §13): a NEUTRAL indication made no directional prediction to support
# or refute in the first place, so its only honest verification outcome
# is INCONCLUSIVE - regardless of what price does afterward.
#
# ---------------------------------------------------------------------------
# Evaluation horizon (Checkpoint 19 §5, §14)
# ---------------------------------------------------------------------------
#
# `horizon_bars: int` is an explicit, required parameter - no magic
# default. The verifier evaluates exactly ONE future observation: the
# bar `horizon_bars` bars after the signal (i.e. `future_bars[horizon_bars
# - 1]`, since `future_bars` contains only bars strictly after the
# signal, in chronological order) - the smallest deterministic
# implementation the brief itself recommends, explicitly NOT a
# path/MFE/MAE analysis across the whole horizon (Checkpoint 19 §14,
# deferred to `signal_intelligence/theoretical_outcome` in a later
# checkpoint). Any bars beyond `horizon_bars` in the supplied series are
# ignored - the caller may supply more than strictly needed without
# changing the result.
#
# ---------------------------------------------------------------------------
# Incomplete-horizon semantics (Checkpoint 19 §12, explicit decision)
# ---------------------------------------------------------------------------
#
# If fewer than `horizon_bars` future bars are available (end-of-day
# signal, holiday, missing data, interrupted feed), the outcome is
# INCONCLUSIVE - never silently treated as NOT_SUPPORTED. There is
# nothing dishonest about "we don't yet know" being a distinct state
# from "the market moved against the call."
from __future__ import annotations

from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.signal_intelligence.signal_generation.contracts import (
    DirectionalIndication,
    SignalDirection,
)
from intraday.signal_intelligence.signal_verification.contracts import (
    VERIFICATION_DEFINITION_NAME,
    VERIFICATION_DEFINITION_VERSION,
    VerificationOutcome,
    VerificationResult,
)
from intraday.signal_intelligence.signal_verification.errors import (
    InvalidHorizonError,
    MismatchedInstrumentError,
    MismatchedTimeframeError,
    NonFutureObservationError,
)


def _inconclusive(indication: DirectionalIndication, horizon_bars: int) -> VerificationResult:
    return VerificationResult(
        verification_definition_name=VERIFICATION_DEFINITION_NAME,
        verification_definition_version=VERIFICATION_DEFINITION_VERSION,
        instrument_id=indication.instrument_id,
        timeframe=indication.timeframe,
        signal_timestamp=indication.timestamp,
        horizon_bars=horizon_bars,
        direction=indication.direction,
        reference_price=indication.price,
        observed_price=None,
        evaluation_timestamp=None,
        outcome=VerificationOutcome.INCONCLUSIVE,
        indication=indication,
    )


def verify_directional_indication(
    indication: DirectionalIndication, future_bars: tuple[Bar, ...], horizon_bars: int
) -> VerificationResult:
    """Evaluates `indication` against `future_bars` (bars strictly after
    `indication.timestamp`, for the same instrument/timeframe, in
    chronological order) at exactly `horizon_bars` bars ahead. See module
    docstring for the full outcome/horizon/incomplete-horizon semantics.

    `future_bars` need not contain exactly `horizon_bars` entries - fewer
    produces `INCONCLUSIVE` (Checkpoint 19 §12); more is accepted and the
    extras beyond `horizon_bars` are simply not used (Checkpoint 19 §14
    - single-point evaluation, not path analysis).

    Raises `InvalidHorizonError` if `horizon_bars` is not a positive
    integer, `MismatchedInstrumentError`/`MismatchedTimeframeError` if
    any bar does not match `indication`'s instrument/timeframe, and
    `NonFutureObservationError` if any bar's timestamp is not strictly
    after `indication.timestamp` (Checkpoint 19 §10 - a bar at the same
    instant as the signal, or before it, is never a legitimate
    verification observation). Reuses `ensure_chronological()`
    (Checkpoint 14) for ordering/duplicate validation - not
    reimplemented.

    Pure and side-effect-free: no database, no network, no mutation of
    `indication` or any bar (all inputs are frozen dataclasses).
    Deterministic - identical inputs always produce an identical
    `VerificationResult`.
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

    if indication.direction is SignalDirection.NEUTRAL:
        return _inconclusive(indication, horizon_bars)

    if len(future_bars) < horizon_bars:
        return _inconclusive(indication, horizon_bars)

    evaluation_bar = future_bars[horizon_bars - 1]
    observed_price: Decimal = evaluation_bar.close
    reference_price = indication.price

    if indication.direction is SignalDirection.BULLISH:
        outcome = (
            VerificationOutcome.SUPPORTED
            if observed_price > reference_price
            else VerificationOutcome.NOT_SUPPORTED
        )
    else:  # BEARISH
        outcome = (
            VerificationOutcome.SUPPORTED
            if observed_price < reference_price
            else VerificationOutcome.NOT_SUPPORTED
        )

    return VerificationResult(
        verification_definition_name=VERIFICATION_DEFINITION_NAME,
        verification_definition_version=VERIFICATION_DEFINITION_VERSION,
        instrument_id=indication.instrument_id,
        timeframe=indication.timeframe,
        signal_timestamp=indication.timestamp,
        horizon_bars=horizon_bars,
        direction=indication.direction,
        reference_price=reference_price,
        observed_price=observed_price,
        evaluation_timestamp=evaluation_bar.timestamp,
        outcome=outcome,
        indication=indication,
    )


def verify_directional_indications(
    indications: tuple[DirectionalIndication, ...],
    bars: tuple[Bar, ...],
    horizon_bars: int,
) -> tuple[VerificationResult, ...]:
    """Verifies multiple `DirectionalIndication`s against one shared bar
    series (Checkpoint 19 §19) - the series-level counterpart to
    `verify_directional_indication`. `bars` is the FULL bar series (not
    pre-sliced per indication); for each indication, only bars strictly
    after its own `timestamp` are considered as its future observations
    - each indication is verified independently, using only its own
    future, never another indication's (Checkpoint 19 §9's "verification
    for T does not affect verification for another signal", tested
    explicitly).

    Preserves the input order of `indications`. Raises
    `MismatchedInstrumentError`/`MismatchedTimeframeError` up front if
    `bars` is not homogeneous with the indications' own instrument/
    timeframe (defense in depth, mirroring
    `generate_directional_indications`'s own upfront series check).
    """
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

    results: list[VerificationResult] = []
    for indication in indications:
        future_bars = tuple(bar for bar in bars if bar.timestamp > indication.timestamp)
        results.append(verify_directional_indication(indication, future_bars, horizon_bars))
    return tuple(results)
