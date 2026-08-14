# Active Product Readiness Research

Checkpoint 33. External research performed against primary/authoritative
sources to determine what is still required for this platform to
operate as a real Indian cash-equity intraday algorithmic trading
system. Read-only research only — no orders, no live credentials
exercised beyond the already-established read-only connectivity/
historical-data pattern (Checkpoints 22-31).

## Research method

Real `WebFetch`/`WebSearch` calls were made this checkpoint against
Dhan's own official documentation and SEBI's own circular archive
(and, where SEBI's raw PDF text wasn't machine-extractable, corroborating
secondary summaries were used and explicitly labeled as secondary, never
presented as primary). Every finding below states its source, what the
source establishes, and how it affects this project — nothing is
invented or inferred beyond what the source states.

---

## 1. Dhan Order API (new research this checkpoint)

**Source:** `https://dhanhq.co/docs/v2/orders/` (fetched live, 2026-08-14).

| Finding | What it establishes | Project impact |
|---|---|---|
| `POST /orders` places an order (dhanClientId, transaction type, exchange segment, product type, order type, validity, security ID, quantity) | The real order-placement request shape | `domain.order.OrderIntent` (Checkpoint 5) does not yet map cleanly onto this — no `product type` (CNC/INTRADAY/MARGIN) concept exists in our domain contract at all |
| `PUT /orders/{order-id}` modifies a pending order | A real modify endpoint exists | No `infrastructure/brokers/dhan` code calls this or any adapter exists for it — **MISSING** |
| `DELETE /orders/{order-id}` cancels, returns HTTP 202 | Cancellation is asynchronous (202 Accepted, not a synchronous confirmation) | Our system has no cancellation flow at all, and would need to handle "accepted for cancellation" as a distinct state from "confirmed cancelled" |
| `GET /orders` (order book), `GET /trades` (trade book) | Real, per-day order/trade retrieval endpoints exist | No polling/reconciliation code exists against either — directly relevant to Part 8's reconciliation question |
| Order types: LIMIT, MARKET, STOP_LOSS, STOP_LOSS_MARKET | Matches `domain.order.OrderType` exactly (Checkpoint 5 got this right) | No gap here |
| **Order lifecycle: TRANSIT, PENDING, REJECTED, CANCELLED, PART_TRADED, TRADED, EXPIRED** | The REAL broker-facing state set — 7 states | `domain.order.OrderStatus` (Checkpoint 5) has only 6: PENDING/SUBMITTED/PARTIALLY_FILLED/FILLED/CANCELLED/REJECTED. **`TRANSIT` and `EXPIRED` do not exist in our domain contract at all** — a genuine, previously-undiscovered gap (see Gap Register, Part 7 analysis) |
| Correlation ID support (max 30 chars, `GET /orders/external/{correlation-id}`) | A real idempotency/correlation mechanism Dhan itself provides | `OrderIntent.idempotency_key` (Checkpoint 5) already anticipated needing this, but nothing wires it to Dhan's correlation-ID field yet |
| Order slicing (`POST /orders/slicing`) for exceeding freeze limits | Large orders must be sliced client-side or via this endpoint | Not represented anywhere in this project |
| **"Order Placement, Modification and Cancellation APIs requires Static IP whitelisting"** | A hard operational requirement, stated by Dhan itself | **Not documented anywhere in this project before this checkpoint.** A static IP is a prerequisite this platform's current development/deployment model (a developer's local machine, no fixed egress IP) does not satisfy — this alone blocks any live order capability regardless of code readiness |

## 2. SEBI — Safer Participation of Retail Investors in Algorithmic Trading

**Primary source confirmed live this checkpoint:** SEBI circular
`SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132` (September 30, 2025),
"Extension of timeline for implementation of SEBI Circular dated
February 04, 2025 on 'Safer participation of retail investors in
Algorithmic trading'" —
`https://www.sebi.gov.in/legal/circulars/sep-2025/...96979.html`
(fetched live; confirms the February 4, 2025 circular exists, is
still being phased in, and its implementation timeline was extended
as recently as September 2025 — i.e. this regulatory framework is
active and evolving as of this project's "today," 2026-08-14, not a
settled historical rule).

**Secondary sources** (multiple industry summaries — NOT primary,
labeled explicitly as such, used only to corroborate/summarize what
the primary circular is understood to require, since this session's
tooling could not machine-extract the full circular PDF text):

| Finding (secondary-sourced, corroborated across multiple summaries) | Labeled as | Project impact |
|---|---|---|
| Retail algo strategies exceeding an orders-per-second threshold must be registered with the exchange | Broker/exchange implementation requirement, per secondary summaries of the SEBI circular | This project has never placed an order, so registration has never been triggered — but any future live-execution checkpoint must account for exchange algo registration before enabling order placement |
| Brokers act as the "principal," algo providers/vendors as "agents" — brokers bear liability for API-based orders | Broker/exchange implementation requirement, per secondary summaries | This platform, if it ever executes live orders through Dhan, operates as a vendor/agent under Dhan's principal responsibility — Dhan's own onboarding/approval process (not yet investigated) would govern this, not purely this project's own code |
| Unique algo IDs must be tagged to orders for tracking | Broker/exchange implementation requirement, per secondary summaries | `OrderIntent.idempotency_key`/`strategy_id` exist but are not the same concept as an exchange-registered algo ID — a genuine future requirement, not yet designed for |
| Cybersecurity requirements: OAuth, 2FA, encrypted data exchange | Broker/exchange implementation requirement, per secondary summaries | Largely Dhan's own responsibility as the API provider, but credential handling on this project's side (already encrypted-at-rest, never logged — Checkpoint 22) is consistent with the spirit of this requirement |
| Retail algos must be hosted on Indian servers | Broker/exchange implementation requirement, per secondary summaries | **Directly relevant**: this project's current development/deployment has never specified a hosting region. Any future live-execution deployment decision must account for this — not yet documented anywhere in this project |
| Implementation phased from April 2025, effective from August 2025, timeline extended again in September 2025 | Directly stated by the primary circular's own title/metadata (confirmed live) | The regulatory bar is not static — a future live-execution checkpoint must re-verify current requirements at that time, not rely on this checkpoint's snapshot |

**Explicit labeling, per Part 19's own requirement:**
- **Directly stated by regulator:** the February 4, 2025 circular exists and its implementation timeline was extended by a further SEBI circular dated September 30, 2025 (both confirmed via live fetch of SEBI's own site).
- **Broker implementation requirement:** algo registration thresholds, principal/agent liability model, algo ID tagging, cybersecurity standards, Indian server hosting — all *reported by secondary sources describing the circular's content*, not independently verified against the primary PDF text this session (a genuine, disclosed limitation, not hidden).
- **Project interpretation:** none of the above is legal advice. This project draws exactly one interpretation from it: **live order execution cannot be treated as "just an engineering task" — it carries broker-onboarding and exchange-registration prerequisites this project has not yet investigated, let alone satisfied.**

## 3. What this research does NOT establish

- The exact orders-per-second threshold above which registration is required (not found in the sources fetched this checkpoint).
- Dhan's own specific broker-onboarding process for API-based retail algo trading under this framework (not investigated — would require account-specific research, likely direct contact with Dhan, not a public documentation page).
- NSE's own specific technical/registration process for algo IDs (the NSE FAQ PDF found via search was not fetched this checkpoint — noted as a gap, not fabricated).

## 4. Honest limitation

This checkpoint's SEBI research relied on WebSearch-surfaced secondary
summaries for most of the circular's substantive content, because the
primary SEBI PDF was not machine-extractable via this session's
`WebFetch` tool (it returned only title/metadata for the September
2025 circular). This is disclosed here explicitly, per this project's
established "honest limitation disclosure" discipline (used previously
for the NSE primary-source cross-check timeout at Checkpoint 29, and
Playwright's unavailability at every frontend-validation checkpoint) —
not presented as a fully-primary-sourced regulatory finding.
