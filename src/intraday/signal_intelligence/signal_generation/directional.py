# File: src/intraday/signal_intelligence/signal_generation/directional.py
#
# Checkpoint 18: the first Signal Generation rule - a deterministic,
# pure interpretation of SMA/EMA/ATR feature state into a
# BULLISH/BEARISH/NEUTRAL `DirectionalIndication`. Depends only on
# `domain/feature` and `domain/market_data` (via `Bar`) - never on
# `signal_intelligence/feature_engine`'s compute functions themselves.
# This is the architectural boundary Checkpoint 18 §18 requires:
# "Signal Generation consumes FeatureValue/domain-level outputs. The
# feature engine owns computation. Signal Generation owns
# interpretation." - proven by imports, not just asserted.
#
# ---------------------------------------------------------------------------
# Signal semantics (Checkpoint 18 §5-6)
# ---------------------------------------------------------------------------
#
#     BULLISH  iff  EMA > SMA  AND  price > EMA  AND  ATR is valid
#     BEARISH  iff  EMA < SMA  AND  price < EMA  AND  ATR is valid
#     NEUTRAL  otherwise
#
# This is deliberately NOT a trading strategy - no stop-loss, target,
# position size, or execution instruction is produced or implied. It
# answers exactly one question: "does the current feature state indicate
# a bullish, bearish, or neutral directional condition?"
#
# Equality cases (EMA == SMA, price == EMA) fall through to NEUTRAL by
# construction - `>`/`<` are both false for equal Decimals, no special
# casing is needed, and none was added (Checkpoint 18 §16/§17's explicit
# test list confirms this is the intended behavior, not an oversight).
#
# ---------------------------------------------------------------------------
# ATR's role (Checkpoint 18 §7, explicit decision)
# ---------------------------------------------------------------------------
#
# ATR does NOT participate in the bullish/bearish direction test itself
# this checkpoint - no threshold (e.g. "ATR > 2%") is invented, because
# no existing architecture decision establishes one, and inventing an
# arbitrary magic number is explicitly forbidden by the checkpoint
# brief. ATR's role here is narrower and purely structural: it must
# EXIST and be VALID (non-negative - see `InvalidAtrValueError`) and
# aligned (same instrument/timeframe/timestamp as the other inputs) for
# an indication to be produced at all. This proves Signal Generation can
# consume a feature that is NOT close-only and NOT part of the
# directional comparison, without embedding ATR's own computation -
# exactly the same architectural point Checkpoint 17 proved for the
# Feature Engine itself, one layer up.
#
# ---------------------------------------------------------------------------
# Feature alignment rule (Checkpoint 18 §8, explicit decision)
# ---------------------------------------------------------------------------
#
# All four inputs (the price bar, SMA, EMA, ATR) must share the EXACT
# SAME `instrument_id`, `timeframe`, AND `timestamp` - not "the latest
# value we happen to have for each." A caller with genuinely misaligned
# inputs (e.g. SMA computed as of 10:15 but EMA as of 10:16) gets a
# raised, specific error (`MisalignedFeatureTimestampError` etc.) - never
# a silently-blended read across different market states. This mirrors
# `domain.market_data.quality.ensure_chronological()`'s own "reject,
# never silently paper over" policy (Checkpoint 14 §16).
from __future__ import annotations

from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.signal_intelligence.signal_generation.contracts import (
    DIRECTIONAL_INDICATION_DEFINITION_NAME,
    DIRECTIONAL_INDICATION_DEFINITION_VERSION,
    DirectionalIndication,
    SignalDirection,
)
from intraday.signal_intelligence.signal_generation.errors import (
    DuplicateFeatureObservationError,
    InvalidAtrValueError,
    MisalignedFeatureInstrumentError,
    MisalignedFeatureTimeframeError,
    MisalignedFeatureTimestampError,
    OutOfOrderFeatureObservationError,
    WrongFeatureTypeError,
)


def generate_directional_indication(
    bar: Bar, sma: FeatureValue, ema: FeatureValue, atr: FeatureValue
) -> DirectionalIndication:
    """Produces one `DirectionalIndication` from a single, fully-aligned
    observation. `bar.close` is the price compared against EMA/SMA - see
    module docstring for the full rule, ATR-role, and alignment
    rationale.

    All three feature values, and the bar itself, must share the same
    `instrument_id`/`timeframe`/`timestamp` - raises
    `MisalignedFeatureInstrumentError`/`MisalignedFeatureTimeframeError`/
    `MisalignedFeatureTimestampError` otherwise. Raises
    `WrongFeatureTypeError` if a value's `feature_name` does not match
    its parameter slot (defense in depth against a caller passing
    values in the wrong order) and `InvalidAtrValueError` if the ATR
    value is negative (mathematically impossible for a real True-Range
    average - Checkpoint 18 §17).

    Pure and side-effect-free: no database, no network, no Django, no
    mutation of any input. Deterministic - identical inputs always
    produce an identical `DirectionalIndication` (Checkpoint 18 §16).
    """
    if not (bar.instrument_id == sma.instrument_id == ema.instrument_id == atr.instrument_id):
        raise MisalignedFeatureInstrumentError(
            "price bar and SMA/EMA/ATR feature values must all belong to the same "
            f"instrument - got bar={bar.instrument_id!r}, sma={sma.instrument_id!r}, "
            f"ema={ema.instrument_id!r}, atr={atr.instrument_id!r}"
        )
    if not (bar.timeframe == sma.timeframe == ema.timeframe == atr.timeframe):
        raise MisalignedFeatureTimeframeError(
            "price bar and SMA/EMA/ATR feature values must all share the same "
            f"timeframe - got bar={bar.timeframe!r}, sma={sma.timeframe!r}, "
            f"ema={ema.timeframe!r}, atr={atr.timeframe!r}"
        )
    if not (bar.timestamp == sma.timestamp == ema.timestamp == atr.timestamp):
        raise MisalignedFeatureTimestampError(
            "price bar and SMA/EMA/ATR feature values must all share the same "
            f"observation timestamp - got bar={bar.timestamp.isoformat()}, "
            f"sma={sma.timestamp.isoformat()}, ema={ema.timestamp.isoformat()}, "
            f"atr={atr.timestamp.isoformat()}"
        )

    if not sma.feature_name.startswith("sma_"):
        raise WrongFeatureTypeError(f"expected an SMA feature value, got {sma.feature_name!r}")
    if not ema.feature_name.startswith("ema_"):
        raise WrongFeatureTypeError(f"expected an EMA feature value, got {ema.feature_name!r}")
    if not atr.feature_name.startswith("atr_"):
        raise WrongFeatureTypeError(f"expected an ATR feature value, got {atr.feature_name!r}")

    if atr.value < 0:
        raise InvalidAtrValueError(f"ATR value must not be negative, got {atr.value}")

    price: Decimal = bar.close
    if ema.value > sma.value and price > ema.value:
        direction = SignalDirection.BULLISH
    elif ema.value < sma.value and price < ema.value:
        direction = SignalDirection.BEARISH
    else:
        direction = SignalDirection.NEUTRAL

    return DirectionalIndication(
        definition_name=DIRECTIONAL_INDICATION_DEFINITION_NAME,
        definition_version=DIRECTIONAL_INDICATION_DEFINITION_VERSION,
        instrument_id=bar.instrument_id,
        timeframe=bar.timeframe,
        timestamp=bar.timestamp,
        direction=direction,
        price=price,
        sma=sma,
        ema=ema,
        atr=atr,
    )


def generate_directional_indications(
    bars: tuple[Bar, ...],
    sma_values: tuple[FeatureValue, ...],
    ema_values: tuple[FeatureValue, ...],
    atr_values: tuple[FeatureValue, ...],
) -> tuple[DirectionalIndication, ...]:
    """Aligns and generates a `DirectionalIndication` for every
    timestamp where a bar AND all three feature series have a value -
    the series-level counterpart to `generate_directional_indication`.

    Unlike the single-observation function (which RAISES on a mismatch
    once all three values are actually supplied), this aligner's policy
    for a timestamp missing one of SMA/EMA/ATR (e.g. during a shorter
    feature's warm-up period) is to SKIP that timestamp - no indication
    is produced for it, exactly as `compute_simple_moving_average` et al.
    produce no output during their own warm-up (Checkpoints 15-17). This
    is a deliberate, documented policy decision (Checkpoint 18 §17: a
    missing required input must never silently produce a misleading
    NEUTRAL indication conflating "no data" with "no directional edge") -
    not a silent NEUTRAL and not a raised exception for an ordinary,
    expected warm-up gap.

    No look-ahead (Checkpoint 18 §9): each indication is derived only
    from its own timestamp's bar/feature values - iterating the aligned
    timestamps in chronological order never lets a later timestamp's
    data influence an earlier indication, by construction (each call is
    independent - see `generate_directional_indication`'s own purity).

    Defensively validates that every bar/feature series is already
    internally consistent in instrument/timeframe before aligning
    (a caller passing series from different instruments entirely is a
    caller bug, not a legitimate partial-warm-up gap) - reuses the same
    error types `generate_directional_indication` raises.
    """
    if not bars or not sma_values or not ema_values or not atr_values:
        return ()

    instrument_id = bars[0].instrument_id
    timeframe = bars[0].timeframe
    for series in (bars, sma_values, ema_values, atr_values):
        for item in series:
            if item.instrument_id != instrument_id:
                raise MisalignedFeatureInstrumentError(
                    f"series mixes instruments {instrument_id!r} and {item.instrument_id!r}"
                )
            if item.timeframe != timeframe:
                raise MisalignedFeatureTimeframeError(
                    f"series mixes timeframes {timeframe!r} and {item.timeframe!r}"
                )

    for series, label in ((sma_values, "SMA"), (ema_values, "EMA"), (atr_values, "ATR")):
        for previous, current in zip(series, series[1:], strict=False):
            if current.timestamp == previous.timestamp:
                raise DuplicateFeatureObservationError(
                    f"duplicate {label} timestamp {current.timestamp.isoformat()}"
                )
            if current.timestamp < previous.timestamp:
                raise OutOfOrderFeatureObservationError(
                    f"{label} series out of order at {current.timestamp.isoformat()}"
                )

    sma_by_timestamp = {value.timestamp: value for value in sma_values}
    ema_by_timestamp = {value.timestamp: value for value in ema_values}
    atr_by_timestamp = {value.timestamp: value for value in atr_values}

    indications: list[DirectionalIndication] = []
    for bar in bars:
        sma = sma_by_timestamp.get(bar.timestamp)
        ema = ema_by_timestamp.get(bar.timestamp)
        atr = atr_by_timestamp.get(bar.timestamp)
        if sma is None or ema is None or atr is None:
            continue
        indications.append(generate_directional_indication(bar, sma, ema, atr))

    return tuple(indications)
