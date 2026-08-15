# File: src/intraday/infrastructure/market_data_providers/dhan/worker_state.py
#
# Checkpoint 53: the persistent market-data worker's own state machine -
# pure, no I/O, no socket, no Django - exactly the same "pure
# classification/transition logic separated from I/O" discipline this
# project already uses throughout (e.g.
# `control_plane/market_data_health/evaluator.py`,
# `infrastructure/persistence/emergency_square_off_event_repository.py`'s
# claim logic). A REAL worker process (not built this checkpoint - see
# the gap register) would drive this state machine from its own
# asyncio/threading event loop; this module defines WHAT the legal
# transitions are, deterministically testable without ever opening a
# real connection.
#
# HONEST SCOPE LIMIT: this is the state machine ONLY. No process, no
# `manage.py` command, no actual WebSocket client exists yet - building
# those against a credential this environment cannot verify would risk
# shipping unverifiable "runtime" code and calling it live-capable,
# exactly what this checkpoint's own instructions forbid. This module
# is the correct, real, independently-testable foundation that future
# work plugs an actual transport into.
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkerState(Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    AUTHENTICATING = "AUTHENTICATING"
    CONNECTING = "CONNECTING"
    SUBSCRIBING = "SUBSCRIBING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    AUTH_FAILED = "AUTH_FAILED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105 - a state name, not a credential
    STOPPING = "STOPPING"
    FAILED = "FAILED"


class WorkerEvent(Enum):
    START_REQUESTED = "START_REQUESTED"
    AUTH_SUCCEEDED = "AUTH_SUCCEEDED"
    AUTH_FAILED_EVENT = "AUTH_FAILED_EVENT"
    CONNECTED = "CONNECTED"
    SUBSCRIBED = "SUBSCRIBED"
    HEARTBEAT_OK = "HEARTBEAT_OK"
    HEARTBEAT_TIMEOUT = "HEARTBEAT_TIMEOUT"
    CONNECTION_LOST = "CONNECTION_LOST"
    TOKEN_EXPIRED_EVENT = "TOKEN_EXPIRED_EVENT"  # noqa: S105 - an event name, not a credential
    RECONNECT_SUCCEEDED = "RECONNECT_SUCCEEDED"
    RECONNECT_EXHAUSTED = "RECONNECT_EXHAUSTED"
    STOP_REQUESTED = "STOP_REQUESTED"
    STOPPED_CLEANLY = "STOPPED_CLEANLY"


# The complete legal-transition table - every (state, event) pair not
# listed here is ILLEGAL and `apply_event()` refuses it (returns
# `None`, never silently guesses a "reasonable" next state). Building
# this as an explicit, exhaustively-testable table - not an if/elif
# chain scattered through worker code - is Checkpoint 53's own
# "no ambiguous boolean-only state... every transition must be tested"
# requirement, made mechanically enforceable.
_TRANSITIONS: dict[tuple[WorkerState, WorkerEvent], WorkerState] = {
    (WorkerState.STOPPED, WorkerEvent.START_REQUESTED): WorkerState.STARTING,
    (WorkerState.STARTING, WorkerEvent.AUTH_SUCCEEDED): WorkerState.CONNECTING,
    # STARTING implicitly begins authenticating - AUTHENTICATING is the
    # state a caller reports WHILE that is in flight, reached the
    # instant STARTING begins (a real worker sets this explicitly);
    # the state machine itself only needs to know what AUTHENTICATING
    # can legally transition to next.
    (WorkerState.STARTING, WorkerEvent.AUTH_FAILED_EVENT): WorkerState.AUTH_FAILED,
    (WorkerState.AUTHENTICATING, WorkerEvent.AUTH_SUCCEEDED): WorkerState.CONNECTING,
    (WorkerState.AUTHENTICATING, WorkerEvent.AUTH_FAILED_EVENT): WorkerState.AUTH_FAILED,
    (WorkerState.CONNECTING, WorkerEvent.CONNECTED): WorkerState.SUBSCRIBING,
    (WorkerState.CONNECTING, WorkerEvent.CONNECTION_LOST): WorkerState.RECONNECTING,
    (WorkerState.SUBSCRIBING, WorkerEvent.SUBSCRIBED): WorkerState.RUNNING,
    (WorkerState.SUBSCRIBING, WorkerEvent.CONNECTION_LOST): WorkerState.RECONNECTING,
    (WorkerState.RUNNING, WorkerEvent.HEARTBEAT_OK): WorkerState.RUNNING,
    (WorkerState.RUNNING, WorkerEvent.HEARTBEAT_TIMEOUT): WorkerState.DEGRADED,
    (WorkerState.RUNNING, WorkerEvent.CONNECTION_LOST): WorkerState.RECONNECTING,
    (WorkerState.RUNNING, WorkerEvent.TOKEN_EXPIRED_EVENT): WorkerState.TOKEN_EXPIRED,
    (WorkerState.RUNNING, WorkerEvent.STOP_REQUESTED): WorkerState.STOPPING,
    (WorkerState.DEGRADED, WorkerEvent.HEARTBEAT_OK): WorkerState.RUNNING,
    (WorkerState.DEGRADED, WorkerEvent.CONNECTION_LOST): WorkerState.RECONNECTING,
    (WorkerState.DEGRADED, WorkerEvent.TOKEN_EXPIRED_EVENT): WorkerState.TOKEN_EXPIRED,
    (WorkerState.DEGRADED, WorkerEvent.STOP_REQUESTED): WorkerState.STOPPING,
    (WorkerState.RECONNECTING, WorkerEvent.RECONNECT_SUCCEEDED): WorkerState.SUBSCRIBING,
    (WorkerState.RECONNECTING, WorkerEvent.RECONNECT_EXHAUSTED): WorkerState.FAILED,
    (WorkerState.RECONNECTING, WorkerEvent.STOP_REQUESTED): WorkerState.STOPPING,
    (WorkerState.TOKEN_EXPIRED, WorkerEvent.AUTH_SUCCEEDED): WorkerState.CONNECTING,
    (WorkerState.TOKEN_EXPIRED, WorkerEvent.AUTH_FAILED_EVENT): WorkerState.AUTH_FAILED,
    (WorkerState.TOKEN_EXPIRED, WorkerEvent.STOP_REQUESTED): WorkerState.STOPPING,
    (WorkerState.STOPPING, WorkerEvent.STOPPED_CLEANLY): WorkerState.STOPPED,
    (WorkerState.AUTH_FAILED, WorkerEvent.STOP_REQUESTED): WorkerState.STOPPED,
    (WorkerState.AUTH_FAILED, WorkerEvent.START_REQUESTED): WorkerState.STARTING,
    (WorkerState.FAILED, WorkerEvent.STOP_REQUESTED): WorkerState.STOPPED,
    (WorkerState.FAILED, WorkerEvent.START_REQUESTED): WorkerState.STARTING,
}

# Terminal-ish "not currently trustworthy" states - a caller building
# health/readiness reporting on top of this state machine should never
# report anything resembling healthy for these (Checkpoint 53's own
# "never classify 'process exists' as 'market data healthy'"). Exposed
# as a set so a future health evaluator has ONE authoritative place to
# check this, rather than every caller re-deriving its own list.
UNTRUSTWORTHY_STATES = frozenset(
    {
        WorkerState.STOPPED,
        WorkerState.DEGRADED,
        WorkerState.RECONNECTING,
        WorkerState.AUTH_FAILED,
        WorkerState.TOKEN_EXPIRED,
        WorkerState.STOPPING,
        WorkerState.FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class TransitionResult:
    accepted: bool
    new_state: WorkerState
    """When `accepted` is `False`, equals the UNCHANGED current state -
    an illegal event is refused, never silently applied."""


def apply_event(current: WorkerState, event: WorkerEvent) -> TransitionResult:
    """The ONE function that may change a worker's state. Returns a
    refusal (never raises, never guesses) for any `(current, event)`
    pair not in the explicit table above - a caller receiving
    `accepted=False` knows unambiguously that this was an illegal
    transition attempt, worth logging/alerting on, not silently
    ignored."""
    new_state = _TRANSITIONS.get((current, event))
    if new_state is None:
        return TransitionResult(accepted=False, new_state=current)
    return TransitionResult(accepted=True, new_state=new_state)
