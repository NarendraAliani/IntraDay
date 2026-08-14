# Order Lifecycle

Checkpoint 34 Part 4/5/7. The broker-neutral order state machine and
event model this platform now uses for paper trading — and will reuse,
unchanged, for a future real broker adapter.

## State diagram

```
CREATED
   |
   v
SUBMITTED
   |
   v
TRANSIT -----------------------------> REJECTED
   |                                       ^
   v                                       |
ACKNOWLEDGED --------------------------->--+
   |                                       |
   v                                       |
PENDING -----------------------------> ----+
   |    \            \          \          |
   |     v             v          v         |
   |  PARTIALLY_    CANCEL_    EXPIRED       |
   |  FILLED <---   REQUESTED               |
   |     |    \        |  \                 |
   |     |     \       |   \                |
   v     v      v      v    v               |
 FILLED <---  FILLED CANCELLED  (race:      |
              (race)            fill wins)  |
                                             |
Any non-terminal state --------------------> ERROR
```

Rendered as a table (the authoritative form — `domain/order/state_machine.py`'s
`ALLOWED_TRANSITIONS` is the single source of truth; this document
describes it, never redefines it):

| From | Allowed To |
|---|---|
| `CREATED` | `SUBMITTED`, `ERROR` |
| `SUBMITTED` | `TRANSIT`, `REJECTED`, `ERROR` |
| `TRANSIT` | `ACKNOWLEDGED`, `REJECTED`, `ERROR` |
| `ACKNOWLEDGED` | `PENDING`, `REJECTED`, `ERROR` |
| `PENDING` | `PARTIALLY_FILLED`, `FILLED`, `CANCEL_REQUESTED`, `REJECTED`, `EXPIRED`, `ERROR` |
| `PARTIALLY_FILLED` | `PARTIALLY_FILLED`, `FILLED`, `CANCEL_REQUESTED`, `EXPIRED`, `ERROR` |
| `CANCEL_REQUESTED` | `CANCELLED`, `PARTIALLY_FILLED` (race), `FILLED` (race), `ERROR` |
| `FILLED` / `CANCELLED` / `REJECTED` / `EXPIRED` / `ERROR` | *(none — terminal)* |

## Why this state set, not a copy of Dhan's

Dhan's own documented order lifecycle (`docs/research/EXECUTION_RESEARCH.md`,
`dhanhq.co/docs/v2/orders/`) has exactly 7 states: `TRANSIT`, `PENDING`,
`REJECTED`, `CANCELLED`, `PART_TRADED`, `TRADED`, `EXPIRED`. This
project's domain state set is deliberately **broader**, because a
broker-neutral model must represent states meaningful regardless of
which broker sits behind `domain.broker.BrokerGateway`:

- `CREATED` has no Dhan equivalent — Dhan only ever sees an order once
  it has already been submitted; this project needs a state for "an
  `OrderIntent` exists locally but has not yet reached any broker."
- `ACKNOWLEDGED` splits Dhan's implicit "the broker has confirmed
  receipt" moment from `PENDING` ("resting, waiting to fill") — useful
  for latency/acknowledgement-timeout monitoring (a real gap named in
  `PRODUCT_READINESS_GAP_ANALYSIS.md`) even though Dhan's own lifecycle
  doesn't name it separately.
- `CANCEL_REQUESTED` exists because Dhan's `DELETE /orders/{id}`
  returns HTTP 202 (accepted, not confirmed) — this project needed an
  explicit "cancellation in flight" state to represent that honestly,
  rather than jumping straight to `CANCELLED`.
- `ERROR` is reachable from every non-terminal state — a genuine
  application/network failure (not a broker-reported rejection) needs
  its own terminal state, distinct from `REJECTED` (which means the
  broker/exchange itself refused the order).

Naming differences from Dhan (`TRADED`→`FILLED`, `PART_TRADED`→`PARTIALLY_FILLED`)
are cosmetic and resolved entirely inside the broker adapter
(`infrastructure/brokers/<broker>`) — never inside `domain.order`
(Checkpoint 3 §7's "no broker-specific status codes in the domain").

## Documented races (never pretended away)

- **Cancel-vs-fill**: `CANCEL_REQUESTED → PARTIALLY_FILLED` and
  `CANCEL_REQUESTED → FILLED` are both explicitly *allowed* transitions
  — a fill can legitimately race a cancellation already in flight,
  because Dhan's own cancel endpoint is asynchronous. Pretending this
  race cannot happen would be dishonest about the state machine's
  actual behavior.
- **Rejection at multiple stages**: `REJECTED` is reachable from
  `SUBMITTED`, `TRANSIT`, `ACKNOWLEDGED`, and `PENDING` — a real broker
  can reject an order at more than one point in its lifecycle (initial
  validation, exchange-side validation, or a later risk check on the
  broker's own side).

## Terminal states

`FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`, `ERROR` — once reached, no
further transition is ever allowed (`domain/order/state_machine.py`'s
`validate_transition()` raises `InvalidOrderTransitionError` for any
attempted transition FROM a terminal state, mechanically enforced,
tested exhaustively in `tests/unit/domain/test_order_state_machine.py`).

## Reconciliation behavior

`domain.order.OrderStatus` is the local ledger's own belief about an
order's state. `control_plane.reconciliation.reconciler.reconcile_orders()`
compares this against whatever the broker (`BrokerGateway.get_orders()`)
currently reports, classifying any disagreement as `STATUS_MISMATCH`,
`MISSING_LOCALLY`, or `MISSING_AT_BROKER` — see
`docs/architecture/RISK_ENGINE_ARCHITECTURE.md` §"Reconciliation" for
the full reconciliation design. The state machine itself performs no
reconciliation — it only validates transitions the LOCAL side is told
about (whether from a real broker event or, this checkpoint, the paper
broker's own simulated events).

## Order event model

`domain/order/events.py`'s `OrderEvent` — one immutable fact per
lifecycle transition, with `event_type` (`OrderEventType`: `ORDER_CREATED`,
`ORDER_SUBMITTED`, `ORDER_ACCEPTED`, `ORDER_REJECTED`,
`ORDER_PARTIALLY_FILLED`, `ORDER_FILLED`, `ORDER_CANCEL_REQUESTED`,
`ORDER_CANCEL_ACCEPTED`, `ORDER_CANCELLED`, `ORDER_EXPIRED`,
`ORDER_MODIFIED`, `BROKER_ERROR`), `timestamp_utc` (when it genuinely
happened) vs. `received_at_utc` (when this process learned about it —
mirrors `Quote.source_timestamp`/`fetched_at`'s existing split,
Checkpoint 23), `previous_state`/`new_state`, `quantity`/
`filled_quantity`/`remaining_quantity` (invariant-checked to always sum
correctly), and an optional `broker_metadata` mapping — the ONLY place
a broker-specific field (Dhan's `OrderNo`/`ReasonDescription`/etc.) may
ever appear, never a required, typed field on the event itself.

## Idempotency / correlation chain

```
Internal idempotency key (OrderIntent.idempotency_key)
      -> Broker correlation ID (derive_correlation_id(), deterministic,
         truncated to Dhan's documented 30-char limit)
      -> Broker order ID (assigned once the broker accepts)
      -> Internal order ID (OrderIntent.order_id, never renamed)
```

`domain/order/idempotency.py`'s `DuplicateOrderSubmissionError` is
raised (never silently resubmitted, never silently returns a second
order) whenever an already-used `idempotency_key` is submitted again —
proven in both `PaperBroker` (`tests/unit/infrastructure/brokers/paper/test_paper_broker.py::test_duplicate_idempotency_key_raises`)
and the risk engine (a duplicate key is also an explicit
`DUPLICATE_ORDER` rejection reason, defense in depth).

**What happens on timeout/lost response (Part 6's explicit scenarios)**:
this checkpoint's `PaperBroker` is synchronous and in-memory, so a
network timeout/lost-response scenario does not literally occur — the
DESIGN for a future real adapter is: the correlation ID is derived
deterministically from the idempotency key BEFORE the network call is
made, so a retry after a timeout submits the SAME correlation ID,
allowing Dhan's own `GET /orders/external/{correlation-id}` lookup
(confirmed to exist, `docs/research/EXECUTION_RESEARCH.md` §6) to
recover the original order's state rather than blindly resubmitting.
**Dhan's own duplicate-correlation-ID behavior is UNKNOWN** (not
found in documentation this checkpoint) — a real adapter must verify
this empirically before relying on it, not assume it.
