# File: src/intraday/signal_intelligence/signal_lifecycle/lifecycle.py
#
# Checkpoint 20: the first Signal Lifecycle rule - deterministic,
# time-bounded validity for a `DirectionalIndication`. Depends only on
# `signal_intelligence.signal_generation.contracts.DirectionalIndication`
# (documented intra-bounded-context reuse, same precedent as Checkpoint
# 19's `signal_verification`) and `domain/market_data`/`domain/shared_kernel`
# - never `signal_verification`, never `trading_engine`, never
# infrastructure.
#
# ---------------------------------------------------------------------------
# Expiry policy: explicit, never a magic default (Checkpoint 20 §6-7)
# ---------------------------------------------------------------------------
#
# `create_lifecycle()` requires `expires_at: datetime` as an explicit
# argument - no `DEFAULT_EXPIRY`/`DEFAULT_EXPIRY_MINUTES` constant exists
# anywhere in this module. Nothing in this project's existing
# architecture establishes a universal expiry policy (no strategy has
# been built yet to define "how long should a directional read stay
# meaningful" - that is a strategy-level/research decision, not this
# checkpoint's to invent). `compute_expiry_from_bars()` below is an
# OPTIONAL convenience helper for the common "N bars from signal time"
# case, built on the already-existing `timeframe_to_timedelta()`
# (Checkpoint 14) - it is never called implicitly; a caller must
# explicitly choose to use it (or compute `expires_at` any other way).
#
# ---------------------------------------------------------------------------
# Expiry boundary (Checkpoint 20 §12, explicit decision)
# ---------------------------------------------------------------------------
#
#     as_of <  expires_at  -> ACTIVE
#     as_of >= expires_at  -> EXPIRED
#
# A half-open validity interval `[signal_timestamp, expires_at)` - the
# exact instant `expires_at` itself already counts as expired, not the
# last active instant. Tested at the exact boundary (one microsecond
# before, exactly at, one microsecond after).
#
# ---------------------------------------------------------------------------
# The one illegal transition: time moving backward (Checkpoint 20 §10-11)
# ---------------------------------------------------------------------------
#
# State is a pure function of `(expires_at, as_of)`. Once
# `as_of >= expires_at`, every later (larger) `as_of` remains
# `>= expires_at` too - so `EXPIRED -> ACTIVE` is structurally
# impossible through forward-moving time, without needing a transition
# table to forbid it explicitly. The one thing that CAN illegitimately
# produce it is a caller passing an earlier `as_of` than a lifecycle's
# own last-evaluated `as_of` (rewinding time) - `advance_lifecycle()`
# rejects this with `NonMonotonicTimeError`. `as_of == lifecycle.as_of`
# (no time has passed) is explicitly ALLOWED and idempotent - re-
# evaluating "now" again always returns an equal `SignalLifecycle`
# (Checkpoint 20 §11).
from __future__ import annotations

from datetime import datetime

from intraday.domain.market_data.quality import timeframe_to_timedelta
from intraday.domain.shared_kernel.contracts import ensure_utc
from intraday.signal_intelligence.signal_generation.contracts import DirectionalIndication
from intraday.signal_intelligence.signal_lifecycle.contracts import (
    LIFECYCLE_DEFINITION_NAME,
    LIFECYCLE_DEFINITION_VERSION,
    SignalLifecycle,
    SignalLifecycleState,
)
from intraday.signal_intelligence.signal_lifecycle.errors import (
    InvalidExpiryError,
    NonMonotonicTimeError,
)


def compute_expiry_from_bars(indication: DirectionalIndication, lifetime_bars: int) -> datetime:
    """Convenience helper (Checkpoint 20 §6): `expires_at` =
    `indication.timestamp + lifetime_bars * (indication.timeframe's own
    fixed duration)`, reusing `timeframe_to_timedelta()` (Checkpoint 14)
    - not a new time-normalization mechanism. Bar-count-relative expiry
    is deliberately preferred over an arbitrary wall-clock duration
    (e.g. "15 minutes") because it stays meaningful across every
    `Timeframe` this project supports without a second, timeframe-
    specific magic number - the same reasoning `horizon_bars`
    (Checkpoint 19) already established. Never called implicitly by
    `create_lifecycle()` - purely optional."""
    if isinstance(lifetime_bars, bool) or not isinstance(lifetime_bars, int) or lifetime_bars <= 0:
        raise ValueError(f"lifetime_bars must be a positive int, got {lifetime_bars!r}")
    duration = timeframe_to_timedelta(indication.timeframe)
    return indication.timestamp + (duration * lifetime_bars)


def _state_at(expires_at: datetime, as_of: datetime) -> SignalLifecycleState:
    return SignalLifecycleState.EXPIRED if as_of >= expires_at else SignalLifecycleState.ACTIVE


def create_lifecycle(
    indication: DirectionalIndication, expires_at: datetime, as_of: datetime
) -> SignalLifecycle:
    """Begins a `SignalLifecycle` for `indication`, evaluated at `as_of`.

    `expires_at` must be strictly after `indication.timestamp`
    (`InvalidExpiryError` otherwise) - a validity window that ends
    before it begins is not legitimate. `as_of` may be at, before, or
    after `expires_at` - creating a lifecycle for an already-expired
    indication (e.g. replaying historical data) is a legitimate, honest
    outcome, not an error; it simply begins life already `EXPIRED`.

    Pure and deterministic: identical arguments always produce an
    identical `SignalLifecycle`. Never mutates `indication`.
    """
    ensure_utc(expires_at, field_name="expires_at")
    ensure_utc(as_of, field_name="as_of")
    if expires_at <= indication.timestamp:
        raise InvalidExpiryError(
            f"expires_at ({expires_at.isoformat()}) must be strictly after the indication's "
            f"own timestamp ({indication.timestamp.isoformat()})"
        )

    return SignalLifecycle(
        lifecycle_definition_name=LIFECYCLE_DEFINITION_NAME,
        lifecycle_definition_version=LIFECYCLE_DEFINITION_VERSION,
        instrument_id=indication.instrument_id,
        timeframe=indication.timeframe,
        signal_timestamp=indication.timestamp,
        expires_at=expires_at,
        as_of=as_of,
        state=_state_at(expires_at, as_of),
        indication=indication,
    )


def advance_lifecycle(lifecycle: SignalLifecycle, as_of: datetime) -> SignalLifecycle:
    """Re-evaluates `lifecycle` at a later (or equal) instant `as_of`,
    returning a NEW `SignalLifecycle` - never mutates `lifecycle` itself.

    Raises `NonMonotonicTimeError` if `as_of` is earlier than
    `lifecycle.as_of` - lifecycle time may only move forward (Checkpoint
    20 §10-11's "the one illegal transition" - see module docstring).
    `as_of == lifecycle.as_of` is explicitly allowed and idempotent.
    """
    ensure_utc(as_of, field_name="as_of")
    if as_of < lifecycle.as_of:
        raise NonMonotonicTimeError(
            f"as_of ({as_of.isoformat()}) is earlier than this lifecycle's own last-evaluated "
            f"as_of ({lifecycle.as_of.isoformat()}) - lifecycle time may only move forward"
        )

    return SignalLifecycle(
        lifecycle_definition_name=lifecycle.lifecycle_definition_name,
        lifecycle_definition_version=lifecycle.lifecycle_definition_version,
        instrument_id=lifecycle.instrument_id,
        timeframe=lifecycle.timeframe,
        signal_timestamp=lifecycle.signal_timestamp,
        expires_at=lifecycle.expires_at,
        as_of=as_of,
        state=_state_at(lifecycle.expires_at, as_of),
        indication=lifecycle.indication,
    )


def advance_lifecycles(
    lifecycles: tuple[SignalLifecycle, ...], as_of: datetime
) -> tuple[SignalLifecycle, ...]:
    """Advances multiple `SignalLifecycle`s to the same `as_of` in one
    call (Checkpoint 20 §23) - the minimal collection-level operation:
    preserves input order, evaluates each lifecycle independently (one
    lifecycle's state can never influence another's), and never mixes
    instruments/timeframes together implicitly (each lifecycle carries
    its own identity; nothing here aggregates across them)."""
    return tuple(advance_lifecycle(lifecycle, as_of) for lifecycle in lifecycles)


__all__ = [
    "advance_lifecycle",
    "advance_lifecycles",
    "compute_expiry_from_bars",
    "create_lifecycle",
]
