# File: src/intraday/signal_intelligence/signal_verification/errors.py
#
# Checkpoint 19: signal-verification input-validation error types. Kept
# in the bounded context (not `domain/`), mirroring
# `signal_intelligence/signal_generation/errors.py`'s own precedent.
from __future__ import annotations


class InvalidHorizonError(ValueError):
    """Raised when `horizon_bars` is not a positive integer."""


class MismatchedInstrumentError(ValueError):
    """Raised when a future bar's instrument does not match the
    `DirectionalIndication` being verified."""


class MismatchedTimeframeError(ValueError):
    """Raised when a future bar's timeframe does not match the
    `DirectionalIndication` being verified."""


class NonFutureObservationError(ValueError):
    """Raised when a "future" bar's timestamp is not strictly after the
    `DirectionalIndication`'s own timestamp (Checkpoint 19 §10) - a bar
    at the same instant as the signal, or before it, is never a
    legitimate verification observation. Rejected, never silently
    dropped or reordered, matching this project's established
    `ensure_chronological()` policy."""
