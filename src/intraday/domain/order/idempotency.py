# File: src/intraday/domain/order/idempotency.py
#
# Checkpoint 34 Part 6: the canonical idempotency/correlation chain
# shape, broker-neutral. This module defines the CONTRACT only (an
# immutable record of one mapping) - the STATEFUL registry that
# remembers which idempotency keys have already been submitted is an
# adapter/application concern (mutable state does not belong in
# `domain`, per this project's established discipline), implemented by
# `infrastructure/brokers/paper/broker.py`'s `PaperBroker` this
# checkpoint, reused by a future real broker adapter unchanged.
#
# The chain (Part 6):
#     Internal idempotency key (OrderIntent.idempotency_key)
#           -> Broker correlation ID (submitted to the broker, e.g.
#              Dhan's documented 30-char correlation-id field)
#           -> Broker order ID (assigned by the broker once accepted)
#           -> Internal order ID (OrderIntent.order_id, unchanged
#              throughout - never renamed to the broker's own ID)
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.domain.shared_kernel.contracts import OrderId, ensure_utc


class DuplicateOrderSubmissionError(Exception):
    """Raised when an `OrderIntent.idempotency_key` that has already
    been submitted is submitted again - the ONE defined behavior for
    Part 6's "duplicate request is detected" scenario: reject outright,
    never silently resubmit and never silently return a fabricated
    second order. The caller (application layer) is expected to look up
    and return the ORIGINAL order's current state instead - this
    exception itself does not do that lookup."""

    def __init__(self, idempotency_key: str, existing_order_id: OrderId) -> None:
        self.idempotency_key = idempotency_key
        self.existing_order_id = existing_order_id
        super().__init__(
            f"idempotency_key {idempotency_key!r} was already submitted as "
            f"order {existing_order_id!r} - refusing to submit a second order "
            f"for the same key"
        )


@dataclass(frozen=True, slots=True)
class IdempotencyMapping:
    """One immutable record of the full chain for one order, recorded
    at the moment the broker FIRST acknowledges submission (never
    before - Part 6's "broker accepted the order but response was
    lost" scenario is exactly why this is written only after
    acknowledgement is confirmed, not optimistically before the call is
    even made)."""

    idempotency_key: str
    correlation_id: str
    broker_order_id: str | None
    order_id: OrderId
    recorded_at: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.recorded_at, field_name="IdempotencyMapping.recorded_at")
        if not self.idempotency_key.strip():
            raise ValueError("IdempotencyMapping.idempotency_key must not be empty")
        if not self.correlation_id.strip():
            raise ValueError("IdempotencyMapping.correlation_id must not be empty")


def derive_correlation_id(idempotency_key: str) -> str:
    """Deterministically derives a broker-facing correlation ID from
    this project's own idempotency key - truncated to Dhan's documented
    30-character maximum (`docs/research/EXECUTION_RESEARCH.md` §6),
    never a random value, so the SAME idempotency key always produces
    the SAME correlation ID (a genuine retry of the same logical
    request must be recognizable as such, not merely "some string under
    30 chars"). A future real-broker adapter reuses this unchanged - it
    is broker-neutral by construction (only Dhan's LENGTH LIMIT is
    referenced, not any Dhan-specific field or format)."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key must not be empty")
    return idempotency_key.strip()[:30]
