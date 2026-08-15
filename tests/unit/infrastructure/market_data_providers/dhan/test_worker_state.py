# tests/unit/infrastructure/market_data_providers/dhan/test_worker_state.py
#
# Checkpoint 53: coverage for the persistent-worker state machine -
# every documented transition, plus proof that illegal transitions are
# refused rather than silently guessed.
from __future__ import annotations

from intraday.infrastructure.market_data_providers.dhan.worker_state import (
    UNTRUSTWORTHY_STATES,
    WorkerEvent,
    WorkerState,
    apply_event,
)


def test_full_happy_path_from_stopped_to_running_to_stopped() -> None:
    state = WorkerState.STOPPED

    for event, expected in [
        (WorkerEvent.START_REQUESTED, WorkerState.STARTING),
        (WorkerEvent.AUTH_SUCCEEDED, WorkerState.CONNECTING),
        (WorkerEvent.CONNECTED, WorkerState.SUBSCRIBING),
        (WorkerEvent.SUBSCRIBED, WorkerState.RUNNING),
        (WorkerEvent.HEARTBEAT_OK, WorkerState.RUNNING),
        (WorkerEvent.STOP_REQUESTED, WorkerState.STOPPING),
        (WorkerEvent.STOPPED_CLEANLY, WorkerState.STOPPED),
    ]:
        result = apply_event(state, event)
        assert result.accepted is True
        assert result.new_state is expected
        state = result.new_state


def test_auth_failure_from_starting_is_a_distinct_terminal_ish_state() -> None:
    result = apply_event(WorkerState.STARTING, WorkerEvent.AUTH_FAILED_EVENT)
    assert result.accepted is True
    assert result.new_state is WorkerState.AUTH_FAILED


def test_heartbeat_timeout_degrades_but_does_not_stop_the_worker() -> None:
    result = apply_event(WorkerState.RUNNING, WorkerEvent.HEARTBEAT_TIMEOUT)
    assert result.accepted is True
    assert result.new_state is WorkerState.DEGRADED

    recovered = apply_event(WorkerState.DEGRADED, WorkerEvent.HEARTBEAT_OK)
    assert recovered.accepted is True
    assert recovered.new_state is WorkerState.RUNNING


def test_connection_lost_while_running_enters_reconnecting() -> None:
    result = apply_event(WorkerState.RUNNING, WorkerEvent.CONNECTION_LOST)
    assert result.accepted is True
    assert result.new_state is WorkerState.RECONNECTING


def test_successful_reconnect_returns_to_subscribing_not_directly_to_running() -> None:
    """A reconnect must re-subscribe before being trusted as RUNNING
    again - it does not skip straight back to RUNNING, since the
    subscription state on the NEW connection is not yet proven."""
    result = apply_event(WorkerState.RECONNECTING, WorkerEvent.RECONNECT_SUCCEEDED)
    assert result.accepted is True
    assert result.new_state is WorkerState.SUBSCRIBING


def test_exhausted_reconnect_attempts_reach_failed() -> None:
    result = apply_event(WorkerState.RECONNECTING, WorkerEvent.RECONNECT_EXHAUSTED)
    assert result.accepted is True
    assert result.new_state is WorkerState.FAILED


def test_token_expiry_while_running_is_distinct_from_a_connection_drop() -> None:
    result = apply_event(WorkerState.RUNNING, WorkerEvent.TOKEN_EXPIRED_EVENT)
    assert result.accepted is True
    assert result.new_state is WorkerState.TOKEN_EXPIRED


def test_a_failed_worker_can_be_restarted() -> None:
    result = apply_event(WorkerState.FAILED, WorkerEvent.START_REQUESTED)
    assert result.accepted is True
    assert result.new_state is WorkerState.STARTING


def test_illegal_transition_is_refused_and_state_is_unchanged() -> None:
    """RUNNING has no legal path directly to SUBSCRIBING - only via
    CONNECTION_LOST -> RECONNECTING -> RECONNECT_SUCCEEDED."""
    result = apply_event(WorkerState.RUNNING, WorkerEvent.SUBSCRIBED)
    assert result.accepted is False
    assert result.new_state is WorkerState.RUNNING  # unchanged, never guessed


def test_stopped_cannot_receive_a_running_only_event() -> None:
    result = apply_event(WorkerState.STOPPED, WorkerEvent.HEARTBEAT_OK)
    assert result.accepted is False
    assert result.new_state is WorkerState.STOPPED


def test_untrustworthy_states_never_includes_running() -> None:
    assert WorkerState.RUNNING not in UNTRUSTWORTHY_STATES


def test_untrustworthy_states_includes_every_not_actively_serving_state() -> None:
    assert {
        WorkerState.STOPPED,
        WorkerState.DEGRADED,
        WorkerState.RECONNECTING,
        WorkerState.AUTH_FAILED,
        WorkerState.TOKEN_EXPIRED,
        WorkerState.STOPPING,
        WorkerState.FAILED,
    } == UNTRUSTWORTHY_STATES
