# File: src/intraday/application/services/token_lifecycle.py
#
# Checkpoint 64 Part 1: the token-lifecycle gap NewStatus.md named
# ("only a state NAME exists, no renewal logic") - and a REAL, live-
# verified bug this checkpoint's own readiness-gate connectivity test
# found: the Settings page's "Connected" badge (`ConnectionStatusBadge`,
# driven by `check_dhan_connectivity()`'s CACHED last-test result) can
# be stale relative to the access token's actual, real expiry - this
# environment's own configured Dhan access token was found EXPIRED
# (issued 2026-08-17 07:10 UTC, expired 2026-08-18 07:10 UTC per Dhan's
# documented ~24h token TTL, verified by decoding its own `exp` claim)
# while the last cached connection-test result still said "Connected."
# A live WebSocket handshake against Dhan's real `wss://api-feed.dhan.co`
# endpoint (Checkpoint 64's own readiness-gate verification) confirmed
# this concretely: the connection was accepted at the transport level
# then closed abnormally (code 1006) within seconds - the exact symptom
# an expired/invalid token produces, distinct from a network failure.
#
# This module answers ONE question, cheaply and locally, with NO
# network call: "based on the access token's OWN claims, what state is
# it in right now?" - never a substitute for a real connectivity check
# (only Dhan's server can confirm a token is ACTUALLY still accepted),
# but the one signal available instantly, on every Settings page load,
# without hitting Dhan's rate limits.
#
# Dhan's access token is a JWT (confirmed directly this checkpoint by
# decoding a real configured token) - the standard `exp`/`iat` claims
# are read here. This module NEVER verifies the JWT signature (that
# would require Dhan's own signing key, which this project does not
# have and should not need for a purely informational expiry read) and
# NEVER logs, returns, or exposes the token itself - only the derived
# state and the (non-secret) expiry instant.
from __future__ import annotations

import base64
import binascii
import enum
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

EXPIRING_SOON_THRESHOLD = timedelta(hours=1)
"""Dhan's own documented access-token lifetime is ~24 hours - warning an
operator inside the final hour gives them a real chance to renew before
a live session silently loses its connection mid-day."""


class TokenLifecycleState(enum.Enum):
    """The minimum safe vocabulary Checkpoint 64's own brief asked for.
    `RENEWING`/`RENEWED`/`AUTH_FAILURE` are NOT included here - those
    require an actual renewal attempt or a real connectivity check
    (Dhan's documented `RenewToken` API, or a live WebSocket/REST call
    rejecting the token), neither of which this pure, local, claims-only
    evaluator performs. This module's job is narrower and more honest:
    "what does the token's own expiry claim say," nothing more."""

    UNCONFIGURED = "UNCONFIGURED"
    """No access token is configured at all (DB row empty, no env var)."""
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    """Still valid, but within `EXPIRING_SOON_THRESHOLD` of its own
    documented expiry - the operator-facing "renew now" warning state."""
    EXPIRED = "EXPIRED"
    """Past its own `exp` claim - THE state this checkpoint's readiness
    gate found this environment's configured token actually in."""
    MALFORMED = "MALFORMED"
    """A non-empty value is configured but it does not decode as a JWT
    with a readable `exp` claim - never silently treated as VALID or
    EXPIRED, since neither claim can honestly be made about it."""

    # Checkpoint 64.1: reachable ONLY through `attempt_dhan_token_renewal()`
    # below, never through `evaluate_dhan_token_lifecycle()` alone -
    # these require an actual renewal ATTEMPT, not just reading claims.
    RENEWED = "RENEWED"
    """A renewal call to Dhan's `/v2/RenewToken` succeeded - the caller
    now holds a genuinely new access token."""
    AUTH_FAILURE = "AUTH_FAILURE"
    """A renewal attempt was made (token was `EXPIRING_SOON`) and Dhan
    rejected it - distinct from `EXPIRED`, which never even attempts
    renewal (Dhan's own documented rule: an expired token cannot be
    renewed via this endpoint at all)."""
    OPERATOR_ACTION_REQUIRED = "OPERATOR_ACTION_REQUIRED"
    """The token is `EXPIRED`/`MALFORMED`/`UNCONFIGURED` - Dhan's
    `RenewToken` endpoint is documented to reject an already-expired
    token outright, so no automatic recovery is possible; a human must
    obtain a fresh token. The worker must never pretend to be connected
    in this state (Checkpoint 64.1's own explicit requirement)."""

    # NOTE: no `RENEWING` member exists. That would be an in-flight
    # status for an asynchronous renewal job - this project has no such
    # job/queue for token renewal (renewal is a single synchronous
    # call, see `attempt_dhan_token_renewal()`) - adding a state this
    # code can never actually occupy would be exactly the "state name
    # with no real logic behind it" this checkpoint's own review
    # criticized about the PRE-Checkpoint-64 token handling.


@dataclass(frozen=True, slots=True)
class TokenLifecycleStatus:
    state: TokenLifecycleState
    expires_at: datetime | None
    """UTC. `None` for UNCONFIGURED/MALFORMED, where no expiry claim
    could be read at all."""


def _decode_jwt_payload(token: str) -> dict[str, object] | None:
    """Decodes ONLY the JWT payload segment (never the signature) -
    returns `None` for anything that doesn't parse as a 3-segment JWT
    with a JSON payload, rather than raising, since a malformed token
    is an expected, named `MALFORMED` outcome here, not a bug."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_segment = parts[1]
    padded = payload_segment + "=" * (-len(payload_segment) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(decoded_bytes)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def evaluate_dhan_token_lifecycle(
    access_token: str | None, *, now: datetime
) -> TokenLifecycleStatus:
    """Pure, I/O-free, no network call - see module docstring for the
    real bug this closes and the honest limits of what it can claim."""
    if not access_token:
        return TokenLifecycleStatus(state=TokenLifecycleState.UNCONFIGURED, expires_at=None)

    payload = _decode_jwt_payload(access_token)
    if payload is None:
        return TokenLifecycleStatus(state=TokenLifecycleState.MALFORMED, expires_at=None)

    raw_exp = payload.get("exp")
    if not isinstance(raw_exp, int | float):
        return TokenLifecycleStatus(state=TokenLifecycleState.MALFORMED, expires_at=None)

    expires_at = datetime.fromtimestamp(raw_exp, tz=UTC)
    if now >= expires_at:
        return TokenLifecycleStatus(state=TokenLifecycleState.EXPIRED, expires_at=expires_at)
    if expires_at - now <= EXPIRING_SOON_THRESHOLD:
        return TokenLifecycleStatus(state=TokenLifecycleState.EXPIRING_SOON, expires_at=expires_at)
    return TokenLifecycleStatus(state=TokenLifecycleState.VALID, expires_at=expires_at)


class TokenRenewalError(Exception):
    """The application layer's own boundary exception for a failed
    renewal attempt - NEVER a Dhan-specific exception type (application
    must not depend on infrastructure, Contract 6 of `.importlinter`).
    The infrastructure-layer adapter that implements `TokenRenewer`
    below is responsible for translating any real Dhan client error
    into this one generic type."""


@dataclass(frozen=True, slots=True)
class TokenRenewalResult:
    new_access_token: str


class TokenRenewer(Protocol):
    """The Protocol `attempt_dhan_token_renewal()` depends on - the
    real implementation (`token_renewal_client.py::renew_dhan_token`,
    infrastructure layer) is injected by the composition root, never
    imported here directly."""

    def __call__(self, *, client_id: str, current_access_token: str) -> TokenRenewalResult: ...


def attempt_dhan_token_renewal(
    *, client_id: str, access_token: str | None, now: datetime, renew: TokenRenewer
) -> tuple[TokenLifecycleState, str | None]:
    """Returns `(new_state, new_access_token)` - `new_access_token` is
    non-`None` ONLY when `new_state is RENEWED`.

    Renewal is attempted ONLY from `EXPIRING_SOON` - Dhan's own
    documented `/v2/RenewToken` behavior: "This only renews tokens
    which are active. If you try to renew an expired token, it will
    return an error." Calling it for an already-`EXPIRED` token would
    not be a bug-tolerant retry, it would be a call the endpoint is
    documented to always reject - so `EXPIRED`/`MALFORMED`/`UNCONFIGURED`
    go straight to `OPERATOR_ACTION_REQUIRED` without ever calling
    `renew`, and a `VALID` token needs no action at all."""
    current = evaluate_dhan_token_lifecycle(access_token, now=now)

    if current.state in (
        TokenLifecycleState.EXPIRED,
        TokenLifecycleState.MALFORMED,
        TokenLifecycleState.UNCONFIGURED,
    ):
        return TokenLifecycleState.OPERATOR_ACTION_REQUIRED, None
    if current.state is TokenLifecycleState.VALID:
        return TokenLifecycleState.VALID, None

    assert current.state is TokenLifecycleState.EXPIRING_SOON
    assert access_token is not None  # EXPIRING_SOON is unreachable without a configured token
    try:
        result = renew(client_id=client_id, current_access_token=access_token)
    except TokenRenewalError:
        return TokenLifecycleState.AUTH_FAILURE, None
    return TokenLifecycleState.RENEWED, result.new_access_token


__all__ = [
    "TokenLifecycleState",
    "TokenLifecycleStatus",
    "evaluate_dhan_token_lifecycle",
    "EXPIRING_SOON_THRESHOLD",
    "TokenRenewalError",
    "TokenRenewalResult",
    "TokenRenewer",
    "attempt_dhan_token_renewal",
]
