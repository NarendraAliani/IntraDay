# File: src/intraday/application/services/live_paper_readiness_checklist.py
#
# Checkpoint 64.14 §2/§3: the 10-item Pre-Session Readiness Workbench -
# a pure re-presentation of signals that ALREADY exist and are ALREADY
# read by `live_paper_readiness.py` (Checkpoint 64.12), plus the
# EXISTING `ScannerConfigurationRecord`/`WorkerRuntimeStatusRecord`
# fields already built for the scanner control plane (Checkpoint 64.4).
# NEVER a competing readiness engine - `LivePaperReadiness.can_start`
# (Checkpoint 64.12) remains the sole authoritative aggregate decision
# (§4's explicit instruction); this module only explains that decision
# item-by-item for the operator, and its own item states are pure
# functions of the SAME underlying facts `evaluate_live_paper_readiness()`
# already reads - never a second opinion that could disagree with it.
from __future__ import annotations

import enum
from dataclasses import dataclass

from intraday.application.repositories.scanner_configuration import ScannerConfigurationRecord
from intraday.application.repositories.worker_runtime_status import WorkerRuntimeStatusRecord
from intraday.application.services.live_paper_readiness import LivePaperReadiness
from intraday.application.services.token_lifecycle import TokenLifecycleState
from intraday.domain.session.contracts import SessionStatus


class ReadinessCheckState(enum.Enum):
    READY = "READY"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    """Reserved for "no real signal exists yet to evaluate this check" -
    e.g. the credential dimension when NOTHING has ever been
    configured at all is `BLOCKED` (a real, known-bad state), but a
    genuinely absent signal (no watchdog report yet AND no credential
    problem) uses `UNKNOWN` rather than guessing READY or BLOCKED."""


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    key: str
    label: str
    state: ReadinessCheckState
    explanation: str
    remediation: str | None


def _credential_check(readiness: LivePaperReadiness) -> ReadinessCheck:
    """§3 example, implemented exactly: VALID -> READY, EXPIRING_SOON ->
    WARNING, EXPIRED -> BLOCKED, MALFORMED -> BLOCKED, UNCONFIGURED ->
    BLOCKED (no usable credential is, definitionally, not workable)."""
    mapping = {
        TokenLifecycleState.VALID: (
            ReadinessCheckState.READY,
            "A usable Dhan credential is configured.",
        ),
        TokenLifecycleState.EXPIRING_SOON: (
            ReadinessCheckState.WARNING,
            "The Dhan access token is valid but expires soon.",
        ),
        TokenLifecycleState.EXPIRED: (
            ReadinessCheckState.BLOCKED,
            "The Dhan access token has expired.",
        ),
        TokenLifecycleState.MALFORMED: (
            ReadinessCheckState.BLOCKED,
            "The configured Dhan access token is malformed.",
        ),
        TokenLifecycleState.UNCONFIGURED: (
            ReadinessCheckState.BLOCKED,
            "No Dhan credential is configured.",
        ),
    }
    state, explanation = mapping[readiness.credential_state]
    return ReadinessCheck(
        key="dhan_credential",
        label="Dhan Credential",
        state=state,
        explanation=explanation,
        remediation=readiness.remediation if state is not ReadinessCheckState.READY else None,
    )


def _token_validity_check(readiness: LivePaperReadiness) -> ReadinessCheck:
    """Distinct from `_credential_check` above - that check answers "is
    a usable credential configured at all," this one answers
    specifically "what is the token's own expiry state" - `UNCONFIGURED`
    has no expiry to evaluate, so it is honestly `UNKNOWN` here, not
    `BLOCKED` twice for the same underlying fact."""
    if readiness.credential_state is TokenLifecycleState.UNCONFIGURED:
        return ReadinessCheck(
            key="token_validity",
            label="Token Validity",
            state=ReadinessCheckState.UNKNOWN,
            explanation="No token is configured to evaluate.",
            remediation="Configure a Dhan access token first.",
        )
    mapping = {
        TokenLifecycleState.VALID: ReadinessCheckState.READY,
        TokenLifecycleState.EXPIRING_SOON: ReadinessCheckState.WARNING,
        TokenLifecycleState.EXPIRED: ReadinessCheckState.BLOCKED,
        TokenLifecycleState.MALFORMED: ReadinessCheckState.BLOCKED,
    }
    state = mapping[readiness.credential_state]
    expiry = (
        f" (expires {readiness.credential_expires_at.isoformat()})"
        if readiness.credential_expires_at
        else ""
    )
    return ReadinessCheck(
        key="token_validity",
        label="Token Validity",
        state=state,
        explanation=f"Token state: {readiness.credential_state.value}{expiry}.",
        remediation=readiness.remediation if state is ReadinessCheckState.BLOCKED else None,
    )


_HEALTHY = frozenset({"HEALTHY"})
_DEGRADED = frozenset({"DEGRADED", "STALE"})
_UNHEALTHY = frozenset({"DISCONNECTED", "FAILED"})


def _provider_connectivity_check(readiness: LivePaperReadiness) -> ReadinessCheck:
    ps = readiness.provider_state
    if ps in _HEALTHY:
        return ReadinessCheck(
            "provider_connectivity",
            "Provider Connectivity",
            ReadinessCheckState.READY,
            "The live worker reports a healthy connection.",
            None,
        )
    if ps in _DEGRADED:
        return ReadinessCheck(
            "provider_connectivity",
            "Provider Connectivity",
            ReadinessCheckState.WARNING,
            f"The live worker connection is {ps.lower()}.",
            "Monitor the watchdog - it may recover on its own.",
        )
    if ps in _UNHEALTHY:
        return ReadinessCheck(
            "provider_connectivity",
            "Provider Connectivity",
            ReadinessCheckState.BLOCKED,
            f"The live worker reports {ps.lower()}.",
            "Restart the live market-data worker process.",
        )
    return ReadinessCheck(
        "provider_connectivity",
        "Provider Connectivity",
        ReadinessCheckState.UNKNOWN,
        "The live worker has never reported status in this environment.",
        "Start the live market-data worker (manage.py run_market_data_worker --provider dhan).",
    )


def _watchdog_check(readiness: LivePaperReadiness) -> ReadinessCheck:
    """Same underlying `provider_state` source as `_provider_connectivity_check`
    (Checkpoint 64.3's own watchdog) - distinct framing: "connectivity"
    answers "can we reach the provider," "watchdog" answers "is the
    watchdog's own health classification favorable" - the SAME value
    read twice, on purpose, per the brief's own 10-item list naming
    both separately."""
    ps = readiness.provider_state
    if ps in _HEALTHY:
        return ReadinessCheck(
            "watchdog", "Watchdog", ReadinessCheckState.READY, "Watchdog: HEALTHY.", None
        )
    if ps in _DEGRADED:
        return ReadinessCheck(
            "watchdog",
            "Watchdog",
            ReadinessCheckState.WARNING,
            f"Watchdog: {ps}.",
            "Feed may be stale - monitor before starting a new session.",
        )
    if ps in _UNHEALTHY:
        return ReadinessCheck(
            "watchdog",
            "Watchdog",
            ReadinessCheckState.BLOCKED,
            f"Watchdog: {ps}.",
            "Resolve the worker connection before starting.",
        )
    return ReadinessCheck(
        "watchdog",
        "Watchdog",
        ReadinessCheckState.UNKNOWN,
        "No watchdog report exists yet.",
        "Start the live market-data worker.",
    )


def _market_state_check(market_session_status: SessionStatus) -> ReadinessCheck:
    if market_session_status is SessionStatus.OPEN:
        return ReadinessCheck(
            "market_state", "Market State", ReadinessCheckState.READY, "Market is OPEN.", None
        )
    if market_session_status in (SessionStatus.PRE_OPEN, SessionStatus.CLOSING):
        return ReadinessCheck(
            "market_state",
            "Market State",
            ReadinessCheckState.WARNING,
            f"Market is {market_session_status.value} - some behavior (e.g. new entries) "
            "may differ from a fully open session.",
            None,
        )
    return ReadinessCheck(
        "market_state",
        "Market State",
        ReadinessCheckState.BLOCKED,
        f"Market is {market_session_status.value}.",
        "Wait for the next trading session.",
    )


def _universe_check(
    desired: ScannerConfigurationRecord, effective: WorkerRuntimeStatusRecord | None
) -> ReadinessCheck:
    if desired.universe_mode == "SELECTED" and not desired.selected_instrument_ids:
        return ReadinessCheck(
            "universe",
            "Universe",
            ReadinessCheckState.BLOCKED,
            "SELECTED universe mode has no stocks selected.",
            "Select at least one stock, or switch to ALL_CONFIGURED.",
        )
    if desired.universe_mode == "WATCHLIST" and not desired.selected_watchlist_name:
        return ReadinessCheck(
            "universe",
            "Universe",
            ReadinessCheckState.BLOCKED,
            "WATCHLIST universe mode has no watchlist selected.",
            "Select a watchlist.",
        )
    if (
        effective is not None
        and effective.effective_universe_requested_count > 0
        and effective.effective_universe_subscribed_count
        < effective.effective_universe_requested_count
    ):
        shortfall = (
            effective.effective_universe_requested_count
            - effective.effective_universe_subscribed_count
        )
        return ReadinessCheck(
            "universe",
            "Universe",
            ReadinessCheckState.WARNING,
            f"{shortfall} of {effective.effective_universe_requested_count} requested "
            "instrument(s) are not subscribed.",
            "Some symbols may be unresolvable - check the worker logs.",
        )
    return ReadinessCheck(
        "universe",
        "Universe",
        ReadinessCheckState.READY,
        f"Universe mode: {desired.universe_mode}.",
        None,
    )


def _timeframe_check(desired: ScannerConfigurationRecord) -> ReadinessCheck:
    if not desired.timeframe:
        return ReadinessCheck(
            "timeframe",
            "Timeframe",
            ReadinessCheckState.BLOCKED,
            "No timeframe is configured.",
            "Select a timeframe.",
        )
    return ReadinessCheck(
        "timeframe",
        "Timeframe",
        ReadinessCheckState.READY,
        f"Timeframe: {desired.timeframe}.",
        None,
    )


def _strategy_selection_check(desired: ScannerConfigurationRecord) -> ReadinessCheck:
    if not desired.selected_strategy_ids:
        return ReadinessCheck(
            "strategy_selection",
            "Strategy Selection",
            ReadinessCheckState.BLOCKED,
            "No strategies are selected.",
            "Select at least one strategy.",
        )
    return ReadinessCheck(
        "strategy_selection",
        "Strategy Selection",
        ReadinessCheckState.READY,
        f"{len(desired.selected_strategy_ids)} strategy(ies) selected.",
        None,
    )


def _paper_execution_check() -> ReadinessCheck:
    """Always READY - `PaperBroker` is structurally always available
    (Checkpoint 64.11's own verified finding), not derived from any
    input. A structural confirmation, not a computed possibility of
    failure."""
    return ReadinessCheck(
        "paper_execution",
        "Paper Execution",
        ReadinessCheckState.READY,
        "Paper execution is always available (PaperBroker).",
        None,
    )


def _real_trading_safety_check() -> ReadinessCheck:
    """Always READY, meaning "confirmed safely disabled" - not "ready
    to trade for real." No code path in this codebase can flip this."""
    return ReadinessCheck(
        "real_trading_safety",
        "Real Trading Safety",
        ReadinessCheckState.READY,
        "Real order submission is structurally disabled - no broker implementation exists "
        "beyond PaperBroker.",
        None,
    )


def build_readiness_checklist(
    *,
    readiness: LivePaperReadiness,
    market_session_status: SessionStatus,
    desired: ScannerConfigurationRecord,
    effective: WorkerRuntimeStatusRecord | None,
) -> tuple[ReadinessCheck, ...]:
    """The 10 items, in the exact order the brief lists them. Pure -
    every check is derived from an input already computed elsewhere."""
    return (
        _credential_check(readiness),
        _provider_connectivity_check(readiness),
        _token_validity_check(readiness),
        _watchdog_check(readiness),
        _market_state_check(market_session_status),
        _universe_check(desired, effective),
        _timeframe_check(desired),
        _strategy_selection_check(desired),
        _paper_execution_check(),
        _real_trading_safety_check(),
    )


__all__ = [
    "ReadinessCheck",
    "ReadinessCheckState",
    "build_readiness_checklist",
]
