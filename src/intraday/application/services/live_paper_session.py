# File: src/intraday/application/services/live_paper_session.py
#
# Checkpoint 64.13: the explicit, human-triggered START/STOP workflow
# for a Live Paper Session - sitting IN FRONT of the EXISTING scanner
# control plane (`ScannerConfigurationRepository.save()`, Checkpoint
# 64.4), never a new worker-state model or a second desired/effective
# reconciliation engine. "Starting a session" means: re-check
# `LivePaperReadiness` (Checkpoint 64.12) and, only if `can_start`,
# write `ScannerConfiguration.enabled=True` with the CURRENT desired
# universe/timeframe/strategy selection captured as-is - the same
# real, audited write path Checkpoint 64.4 already built. This module
# adds NOTHING to what happens after that write: the already-running
# worker process (a separate OS process, started manually - see
# Checkpoint 64.4's own disclosed limitation, unchanged here) picks up
# the change on its own next reconciliation cycle, exactly as it
# already does for any other configuration change.
#
# Session STATE (`LivePaperSessionState`) is a pure re-interpretation
# of the SAME two rows `scanner_configuration_views.py`'s own
# `_compose_response()` already reads (`ScannerConfigurationRecord` +
# `WorkerRuntimeStatusRecord`) - never a third status model. The two
# functions intentionally use slightly different vocabularies for
# different audiences: `_compose_response()`'s EFFECTIVE/APPLYING/
# DEGRADED/STOPPED answers "what is the scanner's config-reconciliation
# state" (an existing, general-purpose question); this module's
# NOT_READY/READY/STARTING/RUNNING/STOPPING/STOPPED/FAILED answers the
# narrower "what state is THIS operator-initiated session in" -
# Checkpoint 64.13's own explicit vocabulary.
from __future__ import annotations

import enum
from dataclasses import dataclass

from intraday.application.repositories.scanner_configuration import (
    ScannerConfigurationRecord,
    ScannerConfigurationRepository,
)
from intraday.application.repositories.worker_runtime_status import WorkerRuntimeStatusRecord
from intraday.application.services.live_paper_readiness import LivePaperReadiness


class LivePaperSessionState(enum.Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class LivePaperSessionResult:
    accepted: bool
    """`False` means the requested START/STOP was REFUSED (readiness
    blocked a start, or an idempotent no-op for an already-matching
    state) - the caller (the view) uses this to choose the HTTP status,
    never a raised exception for an expected, safe refusal."""
    state: LivePaperSessionState
    desired: ScannerConfigurationRecord
    message: str
    remediation: str | None


_FAILED_WORKER_STATES = frozenset({"FAILED", "AUTH_FAILED", "TOKEN_EXPIRED"})
"""Checkpoint 64.14 §8: the REAL, ALREADY-EXISTING `WorkerState` values
(`infrastructure/market_data_providers/dhan/worker_state.py`, Checkpoint
53) `run_market_data_worker.py` itself sets as `final_state` on a
genuine, unrecoverable startup/runtime failure - persisted verbatim
into `WorkerRuntimeStatus.worker_state` (confirmed by reading
`worker_runtime_status_repository.py`'s own `save()`). This is NOT a
fabricated condition invented for test coverage - it is the SAME field
the worker command already writes on: bad/expired credentials at
startup (`AUTH_FAILED`/`TOKEN_EXPIRED`, `run_market_data_worker.py`'s
own `_run_dhan()` guard clauses) or no instruments resolved / an
unrecoverable connection failure (`FAILED`)."""


def derive_live_paper_session_state(
    *,
    desired: ScannerConfigurationRecord,
    effective: WorkerRuntimeStatusRecord | None,
    readiness: LivePaperReadiness,
) -> LivePaperSessionState:
    """Pure - the SAME two rows the existing scanner-config GET
    endpoint already reads, re-interpreted for this narrower question.
    `DEGRADED` (Checkpoint 64.4's own vocabulary - some, not all,
    requested instruments subscribed) is folded into `RUNNING` here:
    a partially-subscribed session is still genuinely RUNNING, not a
    distinct session-lifecycle state - the shortfall itself remains
    visible via `effective_universe_subscribed_count` on the existing
    scanner-config GET response, never hidden, just not re-modeled as
    a session state of its own.

    §9's explicit instruction is honored precisely: `desired.enabled`
    ALONE is never treated as RUNNING - `RUNNING` requires the
    `effective_configuration_version` to actually MATCH `desired`'s,
    i.e. real evidence the worker reconciled. The same discipline
    applies in the stop direction: `STOPPING` (not `STOPPED`) is
    returned while `desired.enabled is False` but the worker's last
    reported `configuration_version` has not yet caught up."""
    if effective is not None and effective.worker_state in _FAILED_WORKER_STATES:
        return LivePaperSessionState.FAILED

    version_reconciled = (
        effective is not None
        and effective.effective_configuration_version == desired.configuration_version
    )

    if not desired.enabled:
        if effective is None:
            return (
                LivePaperSessionState.READY
                if readiness.can_start
                else LivePaperSessionState.NOT_READY
            )
        return (
            LivePaperSessionState.STOPPED if version_reconciled else LivePaperSessionState.STOPPING
        )

    return LivePaperSessionState.RUNNING if version_reconciled else LivePaperSessionState.STARTING


def start_live_paper_session(
    *,
    readiness: LivePaperReadiness,
    repository: ScannerConfigurationRepository,
    provider: str,
    requested_by: str,
    requested_by_user_id: int,
    request_id: str,
) -> LivePaperSessionResult:
    """The backend's OWN, independent re-check - NEVER trusts a
    frontend-supplied `can_start` value (Checkpoint 64.13 §8's explicit
    instruction). Idempotent: an already-`enabled` desired configuration
    is left untouched and reported as already RUNNING/STARTING, never
    re-saved (which would otherwise bump `configuration_version` for no
    real change and could look like spurious reconciliation churn to
    the worker)."""
    current = repository.get(provider)
    if not readiness.can_start:
        return LivePaperSessionResult(
            accepted=False,
            state=LivePaperSessionState.NOT_READY,
            desired=current,
            message="Live Paper Session cannot start.",
            remediation=readiness.remediation,
        )
    if current.enabled:
        return LivePaperSessionResult(
            accepted=False,
            state=LivePaperSessionState.STARTING,
            desired=current,
            message="Live Paper Session is already running - START is idempotent, no duplicate "
            "worker action was taken.",
            remediation=None,
        )

    updated = repository.save(
        provider,
        enabled=True,
        timeframe=current.timeframe,
        universe_mode=current.universe_mode,
        selected_instrument_ids=list(current.selected_instrument_ids),
        selected_watchlist_name=current.selected_watchlist_name,
        selected_strategy_ids=list(current.selected_strategy_ids),
        requested_by=requested_by,
        requested_by_user_id=requested_by_user_id,
        request_id=request_id,
        action="live_paper_session.start",
    )
    return LivePaperSessionResult(
        accepted=True,
        state=LivePaperSessionState.STARTING,
        desired=updated,
        message="Live Paper Session start requested - the already-running worker process will "
        "apply this on its next reconciliation cycle.",
        remediation=None,
    )


def stop_live_paper_session(
    *,
    repository: ScannerConfigurationRepository,
    provider: str,
    requested_by: str,
    requested_by_user_id: int,
    request_id: str,
) -> LivePaperSessionResult:
    """Idempotent in the other direction - stopping an already-stopped
    session is a safe no-op, never an error. Stopping NEVER touches
    historical/research data (`SignalRecord`/`PaperOrderRecord`/report
    tables) - it only flips the SAME `ScannerConfiguration.enabled`
    flag `start_live_paper_session()` sets, which Checkpoint 64.4's
    own worker-side logic already treats as "skip the signal pipeline,
    keep persisting bars" rather than a destructive action."""
    current = repository.get(provider)
    if not current.enabled:
        return LivePaperSessionResult(
            accepted=False,
            state=LivePaperSessionState.STOPPED,
            desired=current,
            message="Live Paper Session is already stopped.",
            remediation=None,
        )

    updated = repository.save(
        provider,
        enabled=False,
        timeframe=current.timeframe,
        universe_mode=current.universe_mode,
        selected_instrument_ids=list(current.selected_instrument_ids),
        selected_watchlist_name=current.selected_watchlist_name,
        selected_strategy_ids=list(current.selected_strategy_ids),
        requested_by=requested_by,
        requested_by_user_id=requested_by_user_id,
        request_id=request_id,
        action="live_paper_session.stop",
    )
    return LivePaperSessionResult(
        accepted=True,
        state=LivePaperSessionState.STOPPING,
        desired=updated,
        message="Live Paper Session stop requested - the worker will skip the signal pipeline "
        "from its next reconciliation cycle (bars keep being recorded).",
        remediation=None,
    )


__all__ = [
    "LivePaperSessionResult",
    "LivePaperSessionState",
    "derive_live_paper_session_state",
    "start_live_paper_session",
    "stop_live_paper_session",
]
