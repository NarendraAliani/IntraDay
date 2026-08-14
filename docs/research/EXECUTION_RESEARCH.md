# Execution Research

Checkpoint 34 Parts 2-3. Closes the remaining Dhan/regulatory research
gaps Checkpoint 33 explicitly left open, before the execution domain
model is frozen (Part 4). Read-only research only — no orders, no
credentials exercised beyond what was already established as safe.

Classification used throughout: `VERIFIED_PRIMARY` (fetched directly
from Dhan's/SEBI's own official page this checkpoint),
`VERIFIED_SECONDARY` (corroborated via search-engine-surfaced summaries
of an official page, not independently fetched in full),
`UNKNOWN` (genuinely not established by any source consulted — never
converted into an assumption), `NOT_APPLICABLE`.

## 1. Dhan Positions

**Source:** `https://dhanhq.co/docs/v2/portfolio/` (fetched live,
2026-08-14). **VERIFIED_PRIMARY.**

`GET /positions` returns open positions with: `dhanClientId`,
`tradingSymbol`, `securityId`, `exchangeSegment`, `productType`
(`CNC`/`INTRADAY`/`MARGIN`/`MTF`/`CO`/`BO` — this is how Dhan
distinguishes intraday from delivery, not a separate field),
`dayBuyQty`/`daySellQty` vs. `carryForwardBuyQty`/`carryForwardSellQty`,
`positionType` (`LONG`/`SHORT`/`CLOSED`), `netQty`, `realizedProfit`,
`unrealizedProfit`. Positions can be converted between product types
(`POST /positions/convert`) or exited (`DELETE /positions`).

**Project impact:** `domain/position/contracts.py`'s existing `Position`
shape does not yet capture `productType`, realized-vs-unrealized split
sourced from the broker, or day-vs-carry-forward quantities — a
genuine future extension point once a real Dhan adapter is built. Not
addressed this checkpoint (paper trading's own `Position` shape is
simpler by design — see `PAPER_TRADING_ARCHITECTURE.md`).

## 2. Dhan Funds / Margin

**Source:** `https://dhanhq.co/docs/v2/funds/` (fetched live,
2026-08-14). **VERIFIED_PRIMARY.**

`GET /fundlimit` returns available balance, SOD (start-of-day) limit,
collateral, utilized amount, blocked payout, withdrawable balance.
`POST /margincalculator` (single order) and `POST /margincalculator/multi`
(multiple) compute SPAN margin, exposure margin, variable margin,
brokerage, and leverage before an order is placed.

**Project impact:** confirms a real, documented pre-trade margin-check
capability exists at Dhan's side — a future live-execution checkpoint
should call the margin calculator before submission, not attempt to
replicate SPAN/exposure margin math locally. This project's paper
`Funds` model (this checkpoint) intentionally does NOT attempt to
replicate real margin/leverage math — it tracks simple
cash/available-capital only, explicitly disclosed as a simplification.

## 3. Dhan Trade Book

Already established (Checkpoint 33): `GET /trades` (all trades today),
`GET /trades/{order-id}` (trades for one order). **VERIFIED_PRIMARY**
(Checkpoint 33's live fetch, re-confirmed unchanged this checkpoint).

## 4. Dhan Order-Update WebSocket

**Source:** `https://dhanhq.co/docs/v2/order-update/` (fetched live,
2026-08-14). **VERIFIED_PRIMARY.**

Endpoint: `wss://api-order-update.dhan.co`. Authentication: a JSON
message (code 42) with client ID + JWT + `"SELF"` (individual users) or
partner credentials. Messages: `{"Data": {...}, "Type": "order_alert"}`
with `OrderNo`/`ExchOrderNo`, `TradedQty`/`TradedPrice`/
`AvgTradedPrice`, `Price`/`TriggerPrice`/`Quantity`/`RemainingQuantity`,
`Status`/`ReasonDescription`/`LastUpdatedTime`, instrument/product/
transaction-type fields.

**Reconnect/heartbeat: UNKNOWN** — the fetched page did not specify
heartbeat interval, keepalive, or reconnection procedure for this
specific WebSocket (distinct from the already-documented 10s/40s
ping/pong on the market-feed WebSocket, Checkpoint 25.1 — never
assumed to be identical without confirmation).

**Project impact:** this is the real-time counterpart to the domain
`OrderEvent` model built this checkpoint (Part 5) — the eventual Dhan
adapter's job is to translate these exact fields into canonical
`OrderEvent`s, never leaking `OrderNo`/`ExchOrderNo` naming into the
domain layer itself.

## 5. Dhan Postback (Webhook)

**Source:** search-engine-surfaced summary of
`https://dhanhq.co/docs/v2/postback/`. **VERIFIED_SECONDARY** (not
independently fetched in full this checkpoint — the WebSocket page was
prioritized as the more directly relevant mechanism for a persistent
process, per the Checkpoint 32 runtime decision).

Postback sends an HTTP POST to a configured webhook URL on order-status
change (`TRANSIT`/`PENDING`/`REJECTED`/`CANCELLED`/`TRADED`/`EXPIRED`)
or modification/partial fill. The Postback URL is configured at
access-token generation time on `web.dhan.co`.

**Project impact:** a second, redundant real-time channel to the
WebSocket above — useful as a durability backstop (a webhook delivered
even if a WebSocket connection was briefly down) but requires a
publicly-reachable HTTPS endpoint, itself dependent on the same
static-IP/deployment questions Checkpoint 33 already flagged as
BLOCKED. Not designed further this checkpoint.

## 6. Correlation-ID Behavior / Uniqueness Rules

**Source:** `dhanhq.co/docs/v2/orders/` (Checkpoint 33's fetch,
re-confirmed). **VERIFIED_PRIMARY** for existence (max 30 characters,
`GET /orders/external/{correlation-id}` lookup). **UNKNOWN**: exact
uniqueness scope (per-day? per-account? lifetime?) and exact behavior
when a duplicate correlation ID is submitted (rejected outright?
returns the original order? silently accepted as a new order?) — not
stated on the fetched page, not found via search this checkpoint.

**Project impact:** this project's own `idempotency_key` design (Part
6) cannot yet assume any particular duplicate-detection behavior from
Dhan's side — the mapping design (Part 6) must remain defensive (treat
Dhan's behavior as unverified) rather than relying on Dhan to reject a
resubmission.

## 7. Token Renewal / Refresh Lifecycle

Already established (Checkpoint 25.1): 24-hour access-token validity,
a documented Renew Token API for an *active* token, a separate Generate
Token flow (TOTP) for a fresh token. **VERIFIED_PRIMARY** (Checkpoint
25.1's live documentation fetch). **UNKNOWN, still**: exact behavior at
expiry mid-WebSocket-connection (does Dhan proactively disconnect, or
does the stream silently stop delivering valid data?) — explicitly
re-confirmed still unknown this checkpoint, not newly resolved.

## 8. Rate Limits Relevant to Order Workflows

Already established (Checkpoint 25.1): Order APIs 10/sec, 250/min,
1,000/hour, 7,000/day (from Dhan's own documented category table).
**VERIFIED_PRIMARY.** Not re-verified against a live order call this
checkpoint (no order was ever placed, per this checkpoint's absolute
safety rule).

## 9. Broker Error Responses Relevant to Retry/Recovery

**UNKNOWN** — no dedicated Dhan documentation page enumerating
order-specific error codes/bodies was fetched this checkpoint. Only
generic HTTP-status-level behavior is established (401/403 for
authentication failures, confirmed at Checkpoints 22-23). A future
live-execution checkpoint must research this specifically before
implementing any broker-side retry policy — not assumed here.

## 10. Order Slicing / Freeze Quantity

Already established (Checkpoint 33): `POST /orders/slicing` exists for
orders exceeding exchange freeze limits. **VERIFIED_PRIMARY.** Exact
freeze-quantity values per instrument: **UNKNOWN** (instrument-specific,
not investigated this checkpoint — would come from the scrip-master
data already identified as a gap in `PRODUCT_READINESS_GAP_ANALYSIS.md`
Part 13).

## 11. Product Types Required for Indian Cash Intraday Trading

**Source:** `dhanhq.co/docs/v2/portfolio/` and `dhanhq.co/docs/v2/funds/`
(this checkpoint). **VERIFIED_PRIMARY.** `INTRADAY` is Dhan's own
documented product type for intraday cash-equity positions (distinct
from `CNC` for delivery). **Project impact:** `domain.order.OrderIntent`
(Checkpoint 5) has no `product_type` field at all — a genuine gap for
a future live/adapter checkpoint, not addressed this checkpoint (paper
trading does not need it, since paper trading has no delivery-vs-
intraday distinction to make against a real exchange).

## 12. Regulatory Research (SEBI/NSE)

**Attempted this checkpoint:** a direct fetch of the NSE retail-algo
FAQ PDF surfaced by Checkpoint 33's search
(`nsearchives.nseindia.com/web/sites/default/files/inline-files/
FAQ_Retail%20Algo_03112025_NSE.pdf`) was not performed this checkpoint
— PDF binary content is outside this session's `WebFetch` tool's
demonstrated capability (the SEBI circular fetch at Checkpoint 33 only
returned page metadata, not PDF body text, for the same reason).
**This is disclosed as a genuine, unresolved research gap, not
silently skipped.** The regulatory findings from Checkpoint 33 (SEBI
circular existence/timeline extension = `REGULATOR_FACT`, confirmed
`VERIFIED_PRIMARY` via SEBI's own site metadata; registration
thresholds/algo-ID tagging/hosting requirements = `BROKER_REQUIREMENT`
per secondary summaries, `VERIFIED_SECONDARY`) stand unchanged and
uncontradicted by anything found this checkpoint. No new regulatory
fact was established this checkpoint beyond re-confirming the
Checkpoint 33 findings remain the current state of research.

**Explicit remaining UNKNOWNs, named per this checkpoint's own
requirement (Part 20):**

1. Dhan positions `productType`/day-vs-carryforward mapping onto our
   domain `Position` — UNKNOWN how a future live adapter should
   reconcile this against the simpler paper-trading `Position` shape.
2. Dhan funds/margin — real SPAN/exposure margin math — UNKNOWN,
   intentionally not replicated.
3. Order-update WebSocket reconnect/heartbeat semantics — UNKNOWN.
4. Postback delivery guarantees (retry-on-failure? at-least-once?
   exactly-once?) — UNKNOWN, not independently fetched this checkpoint.
5. Exchange registration / algo-ID process, exact mechanics — UNKNOWN
   beyond the secondary-sourced SEBI summary.
6. Static-IP deployment solution — UNKNOWN / EXTERNAL_DEPENDENCY,
   unchanged from Checkpoint 33.
7. Token-renewal mid-connection behavior — UNKNOWN, unchanged from
   Checkpoint 25.1.
8. Correlation-ID duplicate-submission behavior — UNKNOWN (§6 above).
9. Order-specific broker error codes — UNKNOWN (§9 above).
10. Instrument-specific freeze quantities — UNKNOWN (§10 above).

None of these block paper trading (this checkpoint's actual
implementation target) — they are named explicitly as LIVE-execution
blockers, per this checkpoint's own instruction not to convert UNKNOWN
into an assumption anywhere.
