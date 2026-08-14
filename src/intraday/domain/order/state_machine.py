# File: src/intraday/domain/order/state_machine.py
#
# Checkpoint 34 Part 4: the broker-neutral order-lifecycle transition
# table. Pure, stateless - a table lookup plus one validation function,
# no I/O, no persistence, no broker knowledge. Deliberately separate
# from `contracts.py` (which only defines the `OrderStatus` vocabulary)
# so the transition RULES are independently reviewable and testable.
from __future__ import annotations

from intraday.domain.order.contracts import OrderStatus

TERMINAL_STATES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.ERROR,
    }
)
"""Once in a terminal state, an order can never transition again. This
is a domain invariant, not an implementation detail - a filled,
cancelled, rejected, expired, or errored order is DONE."""

# The allowed-transition table (Checkpoint 34 Part 4 deliverable #2).
# Every key is a FROM state; its value is the set of ALLOWED TO states.
# Reflects real-world races explicitly, rather than pretending they
# cannot happen:
#   - CANCEL_REQUESTED -> PARTIALLY_FILLED/FILLED: a fill can race a
#     cancellation that was already in flight when the fill happened
#     (Dhan's own DELETE /orders/{id} returns HTTP 202 - "accepted for
#     cancellation," not "confirmed cancelled" - Checkpoint 33/34
#     research).
#   - PENDING/ACKNOWLEDGED -> ERROR: a submission can fail at any point
#     after leaving CREATED, not only at the very first step.
ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset({OrderStatus.SUBMITTED, OrderStatus.ERROR}),
    OrderStatus.SUBMITTED: frozenset(
        {OrderStatus.TRANSIT, OrderStatus.REJECTED, OrderStatus.ERROR}
    ),
    OrderStatus.TRANSIT: frozenset(
        {OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED, OrderStatus.ERROR}
    ),
    OrderStatus.ACKNOWLEDGED: frozenset(
        {OrderStatus.PENDING, OrderStatus.REJECTED, OrderStatus.ERROR}
    ),
    OrderStatus.PENDING: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.ERROR,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,  # another partial fill
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.EXPIRED,
            OrderStatus.ERROR,
        }
    ),
    OrderStatus.CANCEL_REQUESTED: frozenset(
        {
            OrderStatus.CANCELLED,
            OrderStatus.PARTIALLY_FILLED,  # race: filled before cancel confirmed
            OrderStatus.FILLED,  # race: fully filled before cancel confirmed
            OrderStatus.ERROR,
        }
    ),
    # Terminal states: no outgoing transitions.
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.ERROR: frozenset(),
}


class InvalidOrderTransitionError(ValueError):
    """Raised by `validate_transition()` for any transition not present
    in `ALLOWED_TRANSITIONS` - includes both genuinely impossible
    transitions (e.g. CREATED -> FILLED, skipping every intermediate
    step) and any transition FROM a terminal state."""


def validate_transition(current: OrderStatus, target: OrderStatus) -> None:
    """Raises `InvalidOrderTransitionError` if `current -> target` is
    not an allowed transition. Never mutates anything - callers
    (the paper broker, a future real broker adapter) call this before
    applying a state change, and are responsible for actually applying
    it if this does not raise."""
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidOrderTransitionError(
            f"Order cannot transition from {current.value} to {target.value} "
            f"(allowed from {current.value}: "
            f"{sorted(s.value for s in ALLOWED_TRANSITIONS.get(current, frozenset()))})"
        )


def is_terminal(status: OrderStatus) -> bool:
    return status in TERMINAL_STATES
