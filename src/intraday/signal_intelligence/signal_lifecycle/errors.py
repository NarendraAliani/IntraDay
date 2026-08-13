# File: src/intraday/signal_intelligence/signal_lifecycle/errors.py
#
# Checkpoint 20: signal-lifecycle input-validation error types. Kept in
# the bounded context (not `domain/`), mirroring
# `signal_intelligence/signal_generation/errors.py` and
# `signal_intelligence/signal_verification/errors.py`'s own precedent.
from __future__ import annotations


class InvalidExpiryError(ValueError):
    """Raised when `expires_at` is not strictly after the source
    `DirectionalIndication`'s own `timestamp` - a lifecycle that expires
    before (or at) the instant it begins is not a legitimate validity
    window."""


class NonMonotonicTimeError(ValueError):
    """Raised when `advance_lifecycle()` is asked to evaluate a lifecycle
    at an `as_of` instant EARLIER than the lifecycle's own last-evaluated
    `as_of` - the one illegal transition this model has (Checkpoint 20
    §10): lifecycle time may only move forward, never backward. This is
    what makes `EXPIRED -> ACTIVE` structurally impossible through
    legitimate use - state is a pure function of `(expires_at, as_of)`,
    and once `as_of >= expires_at`, every later, forward-moving `as_of`
    remains `>= expires_at` too."""
