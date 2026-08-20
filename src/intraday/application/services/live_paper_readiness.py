# File: src/intraday/application/services/live_paper_readiness.py
#
# Checkpoint 64.12: the ONE canonical "can we safely start a LIVE PAPER
# SESSION" decision - composes three ALREADY-REAL, ALREADY-TESTED
# signals this project has independently had since Checkpoint 22/34/64:
#
#   1. `token_lifecycle.evaluate_dhan_token_lifecycle()` (Checkpoint 64
#      Part 1) - the credential's own claimed expiry, no network call.
#   2. `WorkerRuntimeStatusRecord` (Checkpoint 64.3) - the live worker's
#      own reported `watchdog_state`, whether it has EVER run.
#   3. Kill-switch engagement (Checkpoint 34) - the existing, real
#      trading-halt mechanism.
#
# NEVER a fourth, competing credential/health check - this module reads
# the outputs of the three above and answers ONE new question none of
# them answers alone: "is it safe to press START on a live paper
# session right now?" The answer to "can real orders be placed?" is
# NOT one of this module's inputs or outputs - that answer is
# structural (`PaperBroker` is the only concrete broker implementation
# anywhere in this codebase, verified Checkpoint 64.11) and permanent,
# independent of credential/worker/kill-switch state; `real_trading_state`
# below is therefore always the same literal value, never computed.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from intraday.application.services.token_lifecycle import (
    TokenLifecycleState,
    TokenLifecycleStatus,
)
from intraday.domain.session.contracts import SessionStatus


class LivePaperReadinessState(enum.Enum):
    """The gate's own decision - distinct from, and composed FROM,
    `TokenLifecycleState` (which only knows about the credential)."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    """No usable Dhan credential is configured - covers BOTH "nothing
    configured at all" and "only a client ID or only an access token is
    configured." A dedicated `CREDENTIAL_MISSING` state distinct from
    this was considered and deliberately NOT added: this project's own
    `DhanSettingsService.effective_credentials()` (Checkpoint 22)
    already treats "client ID present, token missing" and "neither
    present" identically (both return `None`) - inventing a state this
    module could never actually distinguish, given its real input, would
    be exactly the "state name with no real logic behind it"
    `token_lifecycle.py`'s own docstring already warned against."""
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED"
    CREDENTIAL_INVALID = "CREDENTIAL_INVALID"
    """The configured token does not decode as a usable JWT with a
    readable expiry claim (`TokenLifecycleState.MALFORMED`)."""
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    """The credential itself is fine, but the live worker has never
    reported a healthy state (never run, or its own watchdog reports
    DISCONNECTED/FAILED) - a real distinction from a credential
    problem, since a valid token with no running worker is a
    different remediation (start the worker) than an expired one
    (renew the credential)."""
    BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"
    """The kill switch is engaged - trading is deliberately halted;
    this takes priority over every other state since it is an
    explicit human safety action."""
    READY_FOR_PAPER = "READY_FOR_PAPER"


_SAFE_REASONS: dict[LivePaperReadinessState, str] = {
    LivePaperReadinessState.NOT_CONFIGURED: "No usable Dhan credential is configured.",
    LivePaperReadinessState.CREDENTIAL_EXPIRED: "Dhan access token has expired.",
    LivePaperReadinessState.CREDENTIAL_INVALID: "Dhan access token is malformed and could not "
    "be read.",
    LivePaperReadinessState.PROVIDER_UNAVAILABLE: "The live market-data worker has not "
    "reported a healthy connection.",
    LivePaperReadinessState.BLOCKED_BY_SAFETY: "The kill switch is engaged - trading is halted.",
    LivePaperReadinessState.READY_FOR_PAPER: "All readiness checks passed.",
}

_REMEDIATIONS: dict[LivePaperReadinessState, str] = {
    LivePaperReadinessState.NOT_CONFIGURED: "Configure a Dhan client ID and access token on "
    "the Settings page.",
    LivePaperReadinessState.CREDENTIAL_EXPIRED: "Renew the Dhan access token and revalidate "
    "configuration. Dhan's own Renew Token API only extends an ACTIVE token - an already-"
    "expired one must be replaced via Dhan's Generate Token flow.",
    LivePaperReadinessState.CREDENTIAL_INVALID: "Re-enter a valid Dhan access token on the "
    "Settings page.",
    LivePaperReadinessState.PROVIDER_UNAVAILABLE: "Start the live market-data worker "
    "(manage.py run_market_data_worker --provider dhan) and wait for it to report a healthy "
    "watchdog state.",
    LivePaperReadinessState.BLOCKED_BY_SAFETY: "Reset the kill switch on the Kill Switch page "
    "once it is safe to resume.",
    LivePaperReadinessState.READY_FOR_PAPER: "Start the Live Paper Session explicitly - this "
    "gate reporting READY never starts it automatically.",
}

_HEALTHY_WATCHDOG_STATES = frozenset({"HEALTHY", "DEGRADED", "STALE"})
"""DEGRADED/STALE still mean the worker is genuinely running and has
reported real state at least once - only DISCONNECTED/FAILED (or no
report at all) block the gate; a stale feed is a `WARNING`-worthy
condition surfaced via `provider_state`, not a hard PROVIDER_UNAVAILABLE
block, since the operator may still want to observe a recovering worker."""


@dataclass(frozen=True, slots=True)
class LivePaperReadiness:
    state: LivePaperReadinessState
    provider: str
    credential_state: TokenLifecycleState
    credential_expires_at: datetime | None
    provider_state: str
    """The real worker's own `watchdog_state` string, or
    `"NEVER_REPORTED"` when no `WorkerRuntimeStatus` row exists yet -
    never fabricated as `"HEALTHY"`."""
    market_state: str
    """The real, computed `SessionStatus` for `now` - reused verbatim
    from `domain.session.calendar`, never a second market-hours
    computation."""
    paper_execution_state: str
    real_trading_state: str
    """ALWAYS `"DISABLED"` - structural and permanent (see module
    docstring), never derived from any input to this function."""
    can_start: bool
    safe_reason: str
    remediation: str


def evaluate_live_paper_readiness(
    *,
    provider: str,
    token_status: TokenLifecycleStatus,
    watchdog_state: str | None,
    market_session_status: SessionStatus,
    kill_switch_engaged: bool,
) -> LivePaperReadiness:
    """Pure, I/O-free - every input is already computed by an existing,
    real signal (see module docstring). `watchdog_state=None` means no
    `WorkerRuntimeStatus` row exists for this provider (the worker has
    never run in this environment) - reported honestly as
    `"NEVER_REPORTED"`, never guessed as healthy or unhealthy."""
    if kill_switch_engaged:
        state = LivePaperReadinessState.BLOCKED_BY_SAFETY
    elif token_status.state is TokenLifecycleState.UNCONFIGURED:
        state = LivePaperReadinessState.NOT_CONFIGURED
    elif token_status.state is TokenLifecycleState.MALFORMED:
        state = LivePaperReadinessState.CREDENTIAL_INVALID
    elif token_status.state is TokenLifecycleState.EXPIRED:
        state = LivePaperReadinessState.CREDENTIAL_EXPIRED
    elif watchdog_state is None or watchdog_state not in _HEALTHY_WATCHDOG_STATES:
        state = LivePaperReadinessState.PROVIDER_UNAVAILABLE
    else:
        # VALID or EXPIRING_SOON credential + a worker that has reported
        # a genuinely-running watchdog state at least once.
        state = LivePaperReadinessState.READY_FOR_PAPER

    return LivePaperReadiness(
        state=state,
        provider=provider,
        credential_state=token_status.state,
        credential_expires_at=token_status.expires_at,
        provider_state=watchdog_state or "NEVER_REPORTED",
        market_state=market_session_status.value,
        paper_execution_state="ENABLED",  # PaperBroker is always structurally available
        real_trading_state="DISABLED",
        can_start=state is LivePaperReadinessState.READY_FOR_PAPER,
        safe_reason=_SAFE_REASONS[state],
        remediation=_REMEDIATIONS[state],
    )


__all__ = [
    "LivePaperReadiness",
    "LivePaperReadinessState",
    "evaluate_live_paper_readiness",
]
