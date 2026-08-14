# File: src/intraday/signal_intelligence/theoretical_outcome/errors.py
#
# Checkpoint 21: theoretical-outcome input-validation error types. Kept
# in the bounded context (not `domain/`), mirroring
# `signal_intelligence/signal_verification/errors.py`'s own precedent.
# Deliberately NOT imported from `signal_verification` - see
# SIGNAL_THEORETICAL_OUTCOME_ARCHITECTURE.md's "Relationship with
# VerificationResult" for why the two bounded-context modules remain
# independent even though their error shapes look similar.
from __future__ import annotations


class InvalidHorizonError(ValueError):
    """Raised when `horizon_bars` is not a positive integer."""


class MismatchedInstrumentError(ValueError):
    """Raised when a future bar's instrument does not match the
    `DirectionalIndication` being measured."""


class MismatchedTimeframeError(ValueError):
    """Raised when a future bar's timeframe does not match the
    `DirectionalIndication` being measured."""


class NonFutureObservationError(ValueError):
    """Raised when a "future" bar's timestamp is not strictly after the
    `DirectionalIndication`'s own timestamp (Checkpoint 21 §7-8) - a bar
    at the same instant as the signal, or before it, is never a
    legitimate theoretical-outcome observation."""
