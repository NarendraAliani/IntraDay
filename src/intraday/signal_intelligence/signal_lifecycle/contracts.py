# File: src/intraday/signal_intelligence/signal_lifecycle/contracts.py
#
# Checkpoint 20: the state model for a `DirectionalIndication`'s
# (Checkpoint 18) temporal validity as time progresses.
#
# ---------------------------------------------------------------------------
# Why the state model is ACTIVE/EXPIRED, not CREATED/ACTIVE/EXPIRED
# (Checkpoint 20 §3-4, a real architectural finding)
# ---------------------------------------------------------------------------
#
# `CREATED` was considered and rejected. A `DirectionalIndication`
# already carries its own creation instant (`timestamp`, Checkpoint 18) -
# introducing a separate lifecycle `CREATED` state would either (a)
# duplicate that same instant under a second name, or (b) imply a
# distinct real-world condition ("created but not yet active") that
# nothing in this system's current scope produces. Unlike an `Order`
# (which genuinely has a PENDING-then-risk-approved gate,
# `domain/order`, a later checkpoint), no approval or staging step
# exists between an indication being generated and its lifecycle
# beginning - a lifecycle begins directly in `ACTIVE`, computed purely
# from the indication's own `timestamp`, an explicit `expires_at`, and
# the instant being evaluated (`as_of`). This is the smallest honest
# model, not an arbitrary simplification - see
# docs/architecture/SIGNAL_LIFECYCLE_ARCHITECTURE.md for the full
# reasoning.
#
# ---------------------------------------------------------------------------
# Why VERIFIED is not a lifecycle state (Checkpoint 20 §5, §20)
# ---------------------------------------------------------------------------
#
# `VerificationResult` (Checkpoint 19) answers "was the directional call
# subsequently supported by price movement?" - a fact about outcome.
# `SignalLifecycle` answers "is this indication still temporally valid
# right now?" - a fact about validity/staleness. These are genuinely
# orthogonal questions with independent answers: an indication can be
# `EXPIRED` and never verified at all (nobody asked); `ACTIVE` and
# already `SUPPORTED` (verification can complete before expiry, since
# verification's own horizon and lifecycle's own expiry are two
# independently-chosen parameters); or any other combination. Collapsing
# them into one enum would force every consumer of lifecycle state to
# also depend on verification even when it has no reason to (a caller
# that only needs "is this still fresh?" would be forced to also
# retrieve/compute a `VerificationResult` it doesn't need). This module
# has NO import of `signal_intelligence.signal_verification` - verified
# by `tests/unit/architecture/test_signal_lifecycle_boundaries.py`.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version, ensure_utc
from intraday.signal_intelligence.signal_generation.contracts import DirectionalIndication

# The lifecycle RULE's own name/version - identifies which lifecycle
# policy produced a `SignalLifecycle`, distinct from
# `DirectionalIndication.definition_name`/`definition_version` (which
# identifies the rule that produced the indication itself) and from
# `VerificationResult`'s own definition fields (Checkpoint 19). Same flat
# name+`Version` convention as every other contract in this codebase.
LIFECYCLE_DEFINITION_NAME = "time_bounded_validity"
LIFECYCLE_DEFINITION_VERSION = Version(value="v1")


class SignalLifecycleState(enum.Enum):
    """The temporal-validity state of a `DirectionalIndication` -
    deliberately two states, not three (no `CREATED`) and not four (no
    `VERIFIED`) - see module docstring for both decisions."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class SignalLifecycle:
    """The lifecycle state of one `DirectionalIndication`, evaluated as
    of a specific instant (`as_of`).

    Identity (Checkpoint 20 §17) is structural - `(lifecycle_definition_name,
    lifecycle_definition_version, instrument_id, timeframe, signal_timestamp,
    expires_at)` - reusing the source indication's own identity
    components plus the expiry policy's own chosen instant, mirroring
    `FeatureValue`/`DirectionalIndication`/`VerificationResult`'s
    identical convention. No random UUID.

    Immutable (Checkpoint 20 §15): a transition never mutates an
    existing `SignalLifecycle` - `create_lifecycle()`/`advance_lifecycle()`
    (lifecycle.py) always return a NEW instance. The embedded `indication`
    is itself already immutable (Checkpoint 18) and is never modified
    here either.
    """

    lifecycle_definition_name: str
    lifecycle_definition_version: Version
    instrument_id: InstrumentId
    timeframe: Timeframe
    signal_timestamp: datetime
    expires_at: datetime
    as_of: datetime
    state: SignalLifecycleState
    indication: DirectionalIndication

    def __post_init__(self) -> None:
        ensure_utc(self.signal_timestamp, field_name="SignalLifecycle.signal_timestamp")
        ensure_utc(self.expires_at, field_name="SignalLifecycle.expires_at")
        ensure_utc(self.as_of, field_name="SignalLifecycle.as_of")
        if not self.lifecycle_definition_name.strip():
            raise ValueError("SignalLifecycle.lifecycle_definition_name must be non-empty")
        if self.instrument_id != self.indication.instrument_id:
            raise ValueError("SignalLifecycle.instrument_id must match indication.instrument_id")
        if self.timeframe != self.indication.timeframe:
            raise ValueError("SignalLifecycle.timeframe must match indication.timeframe")
        if self.signal_timestamp != self.indication.timestamp:
            raise ValueError("SignalLifecycle.signal_timestamp must match indication.timestamp")
