# tests/unit/domain/test_order_state_machine.py
#
# Checkpoint 34 Part 4/18: exhaustive coverage of the broker-neutral
# order state machine - every allowed transition, forbidden
# transitions, terminal-state finality, and the documented races
# (cancel-vs-fill).
from __future__ import annotations

import pytest

from intraday.domain.order.contracts import OrderStatus
from intraday.domain.order.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    InvalidOrderTransitionError,
    is_terminal,
    validate_transition,
)

HAPPY_PATH = [
    (OrderStatus.CREATED, OrderStatus.SUBMITTED),
    (OrderStatus.SUBMITTED, OrderStatus.TRANSIT),
    (OrderStatus.TRANSIT, OrderStatus.ACKNOWLEDGED),
    (OrderStatus.ACKNOWLEDGED, OrderStatus.PENDING),
    (OrderStatus.PENDING, OrderStatus.FILLED),
]


@pytest.mark.parametrize(("current", "target"), HAPPY_PATH)
def test_happy_path_transitions_are_allowed(current: OrderStatus, target: OrderStatus) -> None:
    validate_transition(current, target)  # must not raise


def test_partial_fill_then_full_fill() -> None:
    validate_transition(OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED)
    validate_transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.PARTIALLY_FILLED)
    validate_transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED)


def test_cancellation_flow() -> None:
    validate_transition(OrderStatus.PENDING, OrderStatus.CANCEL_REQUESTED)
    validate_transition(OrderStatus.CANCEL_REQUESTED, OrderStatus.CANCELLED)


def test_cancel_fill_race_is_explicitly_allowed() -> None:
    """A fill can race a cancellation already in flight - Dhan's own
    DELETE /orders/{id} returns HTTP 202 (accepted, not confirmed) per
    this checkpoint's research (EXECUTION_RESEARCH.md)."""
    validate_transition(OrderStatus.CANCEL_REQUESTED, OrderStatus.PARTIALLY_FILLED)
    validate_transition(OrderStatus.CANCEL_REQUESTED, OrderStatus.FILLED)


def test_rejection_can_occur_at_multiple_stages() -> None:
    validate_transition(OrderStatus.SUBMITTED, OrderStatus.REJECTED)
    validate_transition(OrderStatus.TRANSIT, OrderStatus.REJECTED)
    validate_transition(OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED)
    validate_transition(OrderStatus.PENDING, OrderStatus.REJECTED)


def test_expiry_only_from_pending_or_partially_filled() -> None:
    validate_transition(OrderStatus.PENDING, OrderStatus.EXPIRED)
    validate_transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.EXPIRED)
    with pytest.raises(InvalidOrderTransitionError):
        validate_transition(OrderStatus.CREATED, OrderStatus.EXPIRED)


def test_impossible_transition_skipping_states_is_forbidden() -> None:
    with pytest.raises(InvalidOrderTransitionError):
        validate_transition(OrderStatus.CREATED, OrderStatus.FILLED)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for state in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[state] == frozenset()
        with pytest.raises(InvalidOrderTransitionError):
            validate_transition(state, OrderStatus.CREATED)


def test_is_terminal_matches_terminal_states_constant() -> None:
    for state in OrderStatus:
        assert is_terminal(state) == (state in TERMINAL_STATES)


def test_every_order_status_has_a_transition_table_entry() -> None:
    """No state may be silently missing from the table - a missing key
    would make every outgoing transition from that state incorrectly
    forbidden by omission rather than by explicit design."""
    for state in OrderStatus:
        assert state in ALLOWED_TRANSITIONS


def test_error_reachable_from_every_non_terminal_state() -> None:
    for state in OrderStatus:
        if state in TERMINAL_STATES:
            continue
        assert OrderStatus.ERROR in ALLOWED_TRANSITIONS[state]
