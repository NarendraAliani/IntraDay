# File: src/intraday/domain/execution/contracts.py
#
# Checkpoint 64.41: the canonical `Fill` domain contract — one ACTUAL
# execution/fill event, and nothing else. This is the FIRST checkpoint
# permitted to introduce this contract (per the 64.39 audit's §12
# candidate design and §19 sequencing, re-evaluated fresh against
# current source per 64.41's own instruction, not assumed final).
#
# Scope, deliberately narrow (64.41 directive):
#   - Define `Fill` ONLY. No unified execution engine, no Backtest/
#     PaperBroker producer wiring, no FillBook/FillManager/
#     ExecutionLedger/FillService, no accounting-event object.
#   - `Fill` is a value object representing ONE execution event, not a
#     collection, not a subsystem.
#
# What a Fill is NOT (kept deliberately separate, never collapsed):
#   - Not a strategy signal (`signal_intelligence`/`domain.signal`, not
#     read this checkpoint — irrelevant to Fill).
#   - Not an `OrderIntent` (`domain.order.contracts`) — that is a
#     REQUEST; a Fill is the RESULT of (possibly) executing part of one.
#   - Not a `Position` (`domain.position.contracts`) — that is current
#     holdings, a running snapshot a Fill (eventually) feeds into, never
#     represented by a Fill itself.
#   - Not a `Trade` (`domain.trade.contracts`) — that is a CLOSED
#     round-trip (entry + exit), an aggregate over potentially many
#     Fills, never a single execution event.
#   - Not a partial-exit DECISION — that is a strategy-level choice to
#     reduce a Position; a Fill only ever records that an execution
#     happened, never why it was requested.
#   - Not a `RiskDecision`/`OrderRiskDecision` (`domain.risk.contracts`)
#     — risk approval happens strictly BEFORE any Fill can exist.
#
# Domain-layer discipline (`.importlinter` contract 1): this module
# imports ONLY `intraday.domain.*` and the standard library — no
# Django, no Dhan, no `PaperBroker`, no Backtest engine, no
# `research`/`application`/`infrastructure` code of any kind.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.order.contracts import OrderStatus
from intraday.domain.shared_kernel.contracts import InstrumentId, OrderId, Side, ensure_utc

# Checkpoint 64.41: `status_at_fill` is restricted to these two members
# of the EXISTING `domain.order.contracts.OrderStatus` vocabulary — a
# fill event necessarily leaves the order either fully or partially
# filled (any other status — REJECTED, CANCELLED, PENDING, etc. — is
# definitionally not a fill outcome). No new `FillStatus` enum is
# introduced (the directive explicitly forbids inventing one when
# `OrderStatus` already expresses the required state) — this constant
# is validation data, not a new vocabulary.
_VALID_STATUS_AT_FILL = (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)


class FillSource(enum.Enum):
    """Explicit execution-environment provenance for a `Fill` — required
    (Checkpoint 64.41 directive §5) so a downstream accounting consumer
    can apply environment-specific caveats (e.g. a BACKTEST fill never
    reflects genuine liquidity/latency; a LIVE fill is real money) WITHOUT
    guessing from `order_id`, `fill_id`, or any other field.

    Repo-wide grep (this checkpoint) found no existing canonical
    enum/type for "which execution environment produced this event" —
    `domain.strategy.contracts.StrategyMaturityState.PAPER` is a
    strategy LIFECYCLE stage (IDEA -> ... -> PRODUCTION), a different
    concept entirely (a strategy can be in maturity stage PAPER while
    its Fills, once the Fill producer exists, are still tagged PAPER
    for a different reason — execution venue, not promotion stage).
    Reusing it here would conflate two unrelated vocabularies, which is
    why this checkpoint defines a new, minimal, closed enum instead of
    a bare `Literal["BACKTEST","PAPER","LIVE"]` — matching this
    project's own established convention of typed enums over string
    literals everywhere else in `domain/*/contracts.py`
    (`OrderStatus`, `PositionStatus`, `Side`, `TradingHaltStatus`, ...).
    """

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass(frozen=True, slots=True)
class Fill:
    """ONE actual execution/fill event — immutable, a historical fact
    that is recorded once and never mutated (Checkpoint 64.41 §13).

    Fill semantics (directive §2): if an `OrderIntent` for quantity 100
    fills 40 now and the remaining 60 later, that is TWO separate `Fill`
    values (`quantity=40` then `quantity=60`), each with its own unique
    `fill_id`, both sharing the same `order_id`. A `Fill.quantity` must
    NEVER represent an order's entire requested quantity unless that
    entire quantity genuinely executed in this one event — enforcing
    that boundary against a live order's `remaining_quantity` is the
    PRODUCER's responsibility (Backtest/PaperBroker/future Live), not
    this dataclass's, because `Fill` must remain independently
    constructible as a valid event without depending on an entire Order
    aggregate (directive §19's own instruction — this project's
    canonical `OrderIntent` contract has no mutable `remaining_quantity`
    of its own to check against here).

    `price` (directive §12): the ACTUAL execution price — AFTER
    slippage AND after any limit-boundary clamp (Checkpoint 64.40
    Finding F2's own enforcement). Never the raw observed/reference
    price, never the stated limit price, never a pre-slippage value.
    `slippage_applied` records the signed adjustment SEPARATELY (see
    below) so `price` alone is never ambiguous about whether slippage
    is already baked in — it always is.

    `transaction_cost` is a plain `Decimal`, not `CostBreakdown`
    (`research.backtesting.cost_model.CostBreakdown`) — deliberately.
    `CostBreakdown` lives in `intraday.research.backtesting`, and
    `.importlinter` contract 1 forbids `intraday.domain` from importing
    ANYTHING under `intraday.research` (domain is the innermost layer).
    Reusing `CostBreakdown` here would either violate that contract or
    require relocating `CostBreakdown` into the domain layer — a much
    larger, unrelated architectural change explicitly out of scope for
    a "canonical contract only" checkpoint. A scalar total also matches
    what BOTH current producers already have at their own fill-price
    computation point today: Backtest computes a `CostBreakdown` and can
    trivially pass `.total`; `PaperBroker._attempt_fill` already only
    ever has a scalar `cost` (from its injected `compute_cost` closure,
    `(is_buy, notional) -> Decimal`). No second, competing cost model is
    created — this field carries a NUMBER an existing cost model
    produced, not a new way to compute one.

    `slippage_applied` is a signed `Decimal` PRICE adjustment (not a
    percentage, not a `CostBreakdown` line item) — the actual per-unit
    price delta versus the pre-slippage reference price used for this
    fill (positive when the fill was worse than that reference for the
    side executing, by this project's existing sign convention; zero
    when `slippage_percent=0`, as both current producers already allow).
    Kept structurally separate from `transaction_cost`, mirroring
    `CostBreakdown.total`'s own explicit "excludes slippage" design
    (`research/backtesting/cost_model.py`, Part 8: slippage is priced
    into the fill price, never summed into a cost total, to avoid
    double-counting it as both a price adjustment and a cost line item).

    `timestamp` (directive §9): the ACTUAL execution timestamp — for
    Backtest, the historical simulated bar/tick time the fill occurred
    at; for Paper, the real observed time `record_price()`/
    `submit_order()` produced the fill. Never signal time, never order
    creation time. UTC-enforced via the same `ensure_utc()` convention
    every other domain timestamp in this codebase already uses — no
    custom time type introduced.

    `fill_id` (directive §10): the Fill's OWN identity, distinct from
    `order_id` precisely because one `OrderIntent` may produce more than
    one `Fill`. Producer responsibility: deterministic for Backtest,
    uniquely generated for Paper/Live — this contract only requires
    non-empty, never prescribes a generation scheme (mirrors
    `OrderIntent.idempotency_key`'s own "caller supplies, contract
    validates non-empty" pattern).
    """

    fill_id: str
    order_id: OrderId
    instrument_id: InstrumentId
    side: Side
    quantity: Decimal
    price: Decimal
    timestamp: datetime
    transaction_cost: Decimal
    slippage_applied: Decimal
    status_at_fill: OrderStatus
    source: FillSource

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="Fill.timestamp")
        if not self.fill_id.strip():
            raise ValueError("Fill.fill_id must be non-empty")
        if not self.order_id.strip():
            raise ValueError("Fill.order_id must be non-empty")
        if not self.instrument_id.strip():
            raise ValueError("Fill.instrument_id must be non-empty")
        if self.quantity <= 0:
            raise ValueError(
                "Fill.quantity must be positive (one execution event, never zero " "or negative)"
            )
        if self.price <= 0:
            raise ValueError("Fill.price must be positive")
        if self.transaction_cost < 0:
            raise ValueError("Fill.transaction_cost must not be negative")
        if self.status_at_fill not in _VALID_STATUS_AT_FILL:
            raise ValueError(
                "Fill.status_at_fill must be OrderStatus.FILLED or "
                "OrderStatus.PARTIALLY_FILLED (the only two states a fill event can produce), "
                f"got {self.status_at_fill!r}"
            )
