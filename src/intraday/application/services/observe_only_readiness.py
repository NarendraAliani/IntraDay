# File: src/intraday/application/services/observe_only_readiness.py
#
# Checkpoint 64.57: the "is it safe to attempt `--provider dhan --mode
# observe-only`" readiness contract - deliberately DISTINCT from
# `live_paper_readiness.py` (Checkpoint 64.12), which answers a
# stricter, different question ("can real trading be enabled," which
# additionally requires a worker that has ALREADY reported a healthy
# watchdog state at least once, plus kill-switch state). Observe-only
# is a strictly weaker, read-only mode - it places no order, constructs
# no `OrderIntent`, never touches `PaperBroker` (Checkpoint 64.56's own
# dynamically-proven gate) - so its readiness question is narrower and
# answerable from the credential's own claimed state alone, with no
# dependency on a worker having run before: "is a fresh valid token
# present, at all, right now?"
#
# This module does NOT duplicate `run_market_data_worker.py`'s own
# inline connect-time gate (lines evaluating
# `evaluate_dhan_token_lifecycle()` immediately before opening a
# websocket) - it EXTRACTS that same decision into an explicit, named,
# independently-testable contract, so the next live-session milestone
# (and this checkpoint's own tests) can assert the exact readiness
# state WITHOUT constructing a worker, opening a socket, or touching
# the network. The worker's own inline gate remains authoritative at
# connect time and is unchanged by this module (Checkpoint 64.57's own
# directive: "do not modify 64.56 safety behavior unless a genuine
# defect is found" - none was found here).
#
# Pure, I/O-free: `now` and the already-resolved `TokenLifecycleStatus`
# are the only inputs, never a raw token value and never a network
# call. Never returns, logs, or accepts the token itself - only the
# already-safe `TokenLifecycleState`/`expires_at` fields
# `token_lifecycle.py` itself already exposes.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from intraday.application.services.token_lifecycle import (
    TokenLifecycleState,
    TokenLifecycleStatus,
)


class ObserveOnlyReadinessState(enum.Enum):
    """The minimum vocabulary Checkpoint 64.57 §7 asked for. Every
    member maps to exactly one `TokenLifecycleState` - no member exists
    that this function can never actually produce (the same discipline
    `token_lifecycle.py`'s own docstring insists on for its own enum)."""

    READY_FOR_OBSERVE_ONLY = "READY_FOR_OBSERVE_ONLY"
    """Token is VALID or EXPIRING_SOON - sufficient to attempt
    `--provider dhan --mode observe-only`. `EXPIRING_SOON` is still
    included (identical precedent to the worker's own inline gate and
    to `attempt_dhan_token_renewal()`'s own VALID/EXPIRING_SOON
    grouping) - a token expiring in under an hour can still legitimately
    start an observe-only session; it is not yet EXPIRED."""
    BLOCKED_TOKEN_ABSENT = "BLOCKED_TOKEN_ABSENT"  # noqa: S105 - state name, not a secret
    """`TokenLifecycleState.UNCONFIGURED` - no credential configured at
    all (neither database nor environment source)."""
    BLOCKED_TOKEN_EXPIRED = "BLOCKED_TOKEN_EXPIRED"  # noqa: S105 - state name, not a secret
    """`TokenLifecycleState.EXPIRED` - a credential is present but its
    own `exp` claim has passed. This is this environment's own observed
    state across 64.55/64.56/Milestone 1."""
    BLOCKED_TOKEN_MALFORMED = "BLOCKED_TOKEN_MALFORMED"  # noqa: S105 - state name, not a secret
    """`TokenLifecycleState.MALFORMED` - a non-empty value is configured
    but does not decode as a JWT with a readable `exp` claim."""


_STATE_MAP: dict[TokenLifecycleState, ObserveOnlyReadinessState] = {
    TokenLifecycleState.UNCONFIGURED: ObserveOnlyReadinessState.BLOCKED_TOKEN_ABSENT,
    TokenLifecycleState.MALFORMED: ObserveOnlyReadinessState.BLOCKED_TOKEN_MALFORMED,
    TokenLifecycleState.EXPIRED: ObserveOnlyReadinessState.BLOCKED_TOKEN_EXPIRED,
    TokenLifecycleState.VALID: ObserveOnlyReadinessState.READY_FOR_OBSERVE_ONLY,
    TokenLifecycleState.EXPIRING_SOON: ObserveOnlyReadinessState.READY_FOR_OBSERVE_ONLY,
}
"""`RENEWED`/`AUTH_FAILURE`/`OPERATOR_ACTION_REQUIRED` are deliberately
absent - those `TokenLifecycleState` members are reachable ONLY through
`attempt_dhan_token_renewal()`, never through
`evaluate_dhan_token_lifecycle()` (the only evaluator this module's
caller is expected to use, per its own docstring) - so they can never
actually reach this map. If one somehow did, the `KeyError` below is
the correct, fail-closed behavior: this module must never guess a
readiness state for a token state it was not designed to classify."""


@dataclass(frozen=True, slots=True)
class ObserveOnlyReadiness:
    state: ObserveOnlyReadinessState
    provider: str
    credential_state: TokenLifecycleState
    credential_expires_at: datetime | None
    ready: bool
    """`True` exactly when `state is READY_FOR_OBSERVE_ONLY` - the sole
    boolean gate the next milestone's command should branch on. Never a
    second, independently-computed boolean."""


def evaluate_dhan_observe_only_readiness(
    *, provider: str, token_status: TokenLifecycleStatus
) -> ObserveOnlyReadiness:
    """Pure. Deterministic for a given `token_status`. Never performs a
    network call, never reads the token value, never logs anything."""
    state = _STATE_MAP[token_status.state]
    return ObserveOnlyReadiness(
        state=state,
        provider=provider,
        credential_state=token_status.state,
        credential_expires_at=token_status.expires_at,
        ready=state is ObserveOnlyReadinessState.READY_FOR_OBSERVE_ONLY,
    )


__all__ = [
    "ObserveOnlyReadiness",
    "ObserveOnlyReadinessState",
    "evaluate_dhan_observe_only_readiness",
]
