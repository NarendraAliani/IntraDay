# Product Readiness Gap Analysis

Checkpoint 33. A critical, evidence-based audit of what is still
missing for this platform to operate as a real Indian cash-equity
intraday algorithmic trading system. This document does not treat
passing tests, existing documentation, or architectural elegance as
proof of trading readiness. Companion document:
[docs/research/ACTIVE_PRODUCT_READINESS_RESEARCH.md](../research/ACTIVE_PRODUCT_READINESS_RESEARCH.md).

**Headline conclusion, stated plainly:** the architecture is
disciplined and the research/backtesting subsystem is genuinely
strong, but **this product cannot yet execute a single live order,
cannot reconcile against a broker, has no risk engine, and has no
paper-trading layer.** It is a well-engineered research platform with
a live-data observation front end — not yet an operable trading
system, and not close to one without several more checkpoints of real
engineering work.

---

## Part 1-2: Implementation Map & Status Classification

Status values used throughout, exactly as specified: `VERIFIED_IMPLEMENTED`,
`IMPLEMENTED_BUT_NOT_VALIDATED`, `DESIGNED_NOT_IMPLEMENTED`,
`EXTERNAL_DEPENDENCY`, `ASSUMPTION`, `BLOCKED`, `MISSING`, `DEFERRED`.

| Capability | Status | Evidence |
|---|---|---|
| Domain contracts (Signal/Order/Position/Trade/Broker shapes) | DESIGNED_NOT_IMPLEMENTED | `domain/order/contracts.py` etc. exist as real, tested dataclasses, but nothing constructs/consumes them outside unit tests |
| Backtest engine (single + portfolio) | VERIFIED_IMPLEMENTED | Checkpoints 27-30; independently reference-validated |
| Verified Indian cost model | VERIFIED_IMPLEMENTED | Checkpoint 29; hand-audited |
| Strategy suite (EMA/SMA/ATR) | VERIFIED_IMPLEMENTED (research-only) | Checkpoint 26-27; never live-wired |
| Live market data (REST polling) | IMPLEMENTED_BUT_NOT_VALIDATED (as trading input) | Checkpoint 23; `SAMPLE_BAR` only, never fed into any strategy |
| WebSocket live tick ingestion | BLOCKED | No persistent-process host (Checkpoint 32 decision, not implemented) |
| TRADING_GRADE_BAR | BLOCKED | 2 of 6 conditions met (Checkpoint 31) |
| Broker connectivity (read-only profile check) | VERIFIED_IMPLEMENTED | Checkpoint 22, real HTTP call, real 401 observed |
| Order placement/modify/cancel | MISSING | No code anywhere in `infrastructure/brokers/dhan/` beyond one GET call |
| Order book / trade book polling | MISSING | No code calls `GET /orders` or `GET /trades` |
| `risk_engine` | MISSING | `__init__.py` only, 8 lines |
| `order_management` | MISSING | `__init__.py` only, 7 lines |
| `execution_management` | MISSING | `__init__.py` only, 7 lines |
| `session_management` | MISSING | `__init__.py` only, 7 lines |
| `broker_abstraction` | MISSING | `__init__.py` only, 7 lines |
| Kill switch | MISSING | No implementation found anywhere; referenced only in prose/safety-rule text every checkpoint |
| Paper trading | MISSING | Never designed beyond a name in the capability registry |
| Position/trade reconciliation | MISSING | No reconciliation code, job, or contract exists |
| Instrument master (beyond 4 hand-verified symbols) | ASSUMPTION | `MARKET_DATA_OBSERVATION_SYMBOLS` is a hardcoded 4-symbol list; no ingestion pipeline |
| Corporate-action handling | MISSING | `PriceAdjustment.ADJUSTED` is unreachable by any code path (Checkpoint 14's own admission) |
| Clock synchronization (NTP) | ASSUMPTION | No NTP verification, drift detection, or monitoring exists; relies entirely on the host machine's own clock |
| Session model (holidays, special sessions) | ASSUMPTION | `domain/session/calendar.py` explicitly has "no holiday calendar" (Checkpoint 23's own documented limitation) |
| Observability (structured logs/metrics/tracing/alerts) | MISSING | No metrics/tracing infrastructure found; logging is ad hoc (Python `logging`/Django defaults), no dashboards |
| Reporting foundation | DESIGNED_NOT_IMPLEMENTED | Checkpoint 32's `application/reporting/` is a real, tested contract layer, but only 2 of 10 report types have real content; no persistence, no export |
| Regulatory/SEBI compliance posture | EXTERNAL_DEPENDENCY | Governed by Dhan's own broker-onboarding process and SEBI's algo-trading framework, neither investigated to the account-specific level |
| Static IP for order APIs | BLOCKED | Confirmed requirement (this checkpoint's research); no static IP exists in this project's current dev/deployment model |

---

## Part 5: Broker Execution Gap Matrix

| Capability | Broker Supports | Our System Supports | Gap | Priority |
|---|---|---|---|---|
| Authentication | Yes (`access-token`/`dhanClientId` headers, 24h token) | Read-only connectivity check only | No order-capable client; no token-refresh flow | P0 |
| Market data (WebSocket) | Yes, tick-by-tick | No | Entire WebSocket path blocked (Checkpoint 32) | P1 |
| Market data (REST historical/intraday) | Yes, verified same-day (Checkpoint 31) | Read-only quote polling only, never intraday-chart-backed live pipeline | Not wired into any live strategy path | P2 |
| Order placement | Yes (`POST /orders`) | None | Complete gap | P0 |
| Modification | Yes (`PUT /orders/{id}`) | None | Complete gap | P0 |
| Cancellation | Yes (`DELETE /orders/{id}`, async 202) | None | Complete gap, plus async-ack handling not designed | P0 |
| Order status (order book) | Yes (`GET /orders`) | None | No polling, no reconciliation | P0 |
| Trade status (trade book) | Yes (`GET /trades`) | None | No polling, no reconciliation | P0 |
| Partial fills | Yes (`PART_TRADED` status) | Domain has `PARTIALLY_FILLED` but nothing populates it | Status exists on paper only | P0 |
| Position reconciliation | Implied (Dhan has a positions endpoint, not investigated this checkpoint) | None | Not designed | P0 |
| Funds/margin | Implied (not investigated this checkpoint - out of this checkpoint's research scope) | None | Not designed, not researched | P1 |
| Static IP | Required for order APIs (confirmed) | Not provisioned anywhere in this project | Blocks all order capability regardless of code | P0 |
| Token renewal | Yes (documented Renew Token API, 24h expiry) | None | No refresh flow; any long-lived process would eventually fail silently without one | P1 |
| WebSocket order updates | Likely exists (Dhan's WS live-feed doc covers market data; order-update WS not investigated this checkpoint) | None | Not researched, not built | P1 |
| Postback/webhooks | Not investigated this checkpoint | None | Not researched | P2 |
| Retry | N/A (application concern) | None | No retry policy exists anywhere for broker calls | P0 |
| Idempotency | Correlation ID field exists (Dhan) | `OrderIntent.idempotency_key` field exists (domain only) | Never wired to Dhan's correlation-ID mechanism | P0 |
| Correlation IDs | Yes, `GET /orders/external/{id}` | Field exists, unused | Same as idempotency above | P0 |
| Failure recovery | N/A (application concern) | None | No reconnection/recovery design for broker-side failures exists | P0 |

---

## Part 6: Real Trading Lifecycle Audit

Walking the full lifecycle named in the checkpoint brief and marking
what this project can and cannot currently represent:

| Stage | Current status |
|---|---|
| MARKET OPEN | VERIFIED_IMPLEMENTED (`domain/session/calendar.py`) |
| MARKET DATA HEALTHY | IMPLEMENTED_BUT_NOT_VALIDATED (health model exists, `SAMPLE_BAR` only) |
| STRATEGY ACTIVE | DESIGNED_NOT_IMPLEMENTED (registry/activation exists for backtesting, never for live) |
| SIGNAL GENERATED | IMPLEMENTED (research/backtesting only) - never wired to live data |
| SIGNAL VALIDATED | DESIGNED_NOT_IMPLEMENTED (`signal_intelligence.signal_verification` exists but unwired from any live path) |
| RISK APPROVED | MISSING - `risk_engine` is empty |
| ORDER CREATED | MISSING |
| ORDER SUBMITTED | MISSING |
| ORDER ACKNOWLEDGED | MISSING |
| ORDER PENDING | MISSING |
| PARTIAL FILL / FULL FILL / REJECT / CANCEL / EXPIRE | MISSING - and `TRANSIT`/`EXPIRED` are not even represented in the domain enum (see Part 7) |
| POSITION CREATED / UPDATED | MISSING - `domain/position/contracts.py` exists, nothing populates it live |
| STOP LOSS / TARGET / EXIT | MISSING |
| POSITION CLOSED | MISSING |
| TRADE RECORDED | MISSING (backtesting has its own `SimulatedTrade`, unrelated to a real broker trade record) |
| RECONCILIATION | MISSING |
| END-OF-DAY SQUARE-OFF | ASSUMPTION only - `SQUARE_OFF_DEADLINE_IST` is a computed timestamp field, no code acts on it |
| DAILY REPORT | DESIGNED_NOT_IMPLEMENTED (Checkpoint 32's report catalogue names it, PRODUCTION_REPORT is PLANNED) |

**Conclusion: 3 of 19 lifecycle stages are more than "designed."
Everything from RISK APPROVED onward is completely missing.** This is
the single most important finding of this checkpoint - the platform
has never crossed the line from "signal" to "order" in any live
context, by design, and every safety rule in every prior checkpoint has
correctly kept it that way. But it means the honest distance to
"operable" is large.

---

## Part 7: Order State Machine Research

**Real Dhan states (this checkpoint's research):** `TRANSIT`, `PENDING`,
`REJECTED`, `CANCELLED`, `PART_TRADED`, `TRADED`, `EXPIRED`.

**Current `domain.order.OrderStatus` (Checkpoint 5):** `PENDING`,
`SUBMITTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`.

| Finding | Detail |
|---|---|
| Missing state: `TRANSIT` | Dhan's "order sent, not yet acknowledged" state has no equivalent - our `SUBMITTED` may or may not be the right mapping, genuinely ambiguous without broker-adapter design work |
| Missing state: `EXPIRED` | No equivalent at all - a DAY order that expires unfilled at session end has nowhere to go in our domain model today |
| Naming mismatch: `TRADED` vs `FILLED`, `PART_TRADED` vs `PARTIALLY_FILLED` | Cosmetic only, and expected to be resolved at the `infrastructure/brokers/dhan` adapter boundary per Checkpoint 3's "broker-specific status codes never represented in domain" rule - **not yet a real problem, but the adapter that would resolve it does not exist yet** |
| Cancellation race | `DELETE /orders/{id}` returns HTTP 202 (accepted, not confirmed) - our domain has no "cancellation requested but not yet confirmed" state, which is a real, not hypothetical, race: a fill could occur between "cancel accepted" and "cancel confirmed" |
| Acknowledgement timeout | No design exists for "we submitted an order and heard nothing back within N seconds" - a genuine, unaddressed operational hazard |
| Retry hazard | `idempotency_key` exists on `OrderIntent` but nothing consumes it - a naive retry-on-timeout implementation today would have no protection against double-submission |
| Modify-order lifecycle | Not represented in the domain enum at all - Dhan's `PUT /orders/{id}` presumably produces new pending/transit states for the modification itself, not investigated this checkpoint |

**Conclusion:** the domain enum is a reasonable simplification for a
system that has never touched a real order, but it is **provably
incomplete** against the real broker's own documented lifecycle, not
merely "not yet validated." This is a concrete, evidence-based gap,
not a hypothetical one.

---

## Part 8: Position / Trade Reconciliation

**"What happens if our local database says one thing but Dhan says
another?"** Today: **nothing** - because there is no local order/
position/trade state that could diverge from Dhan in the first place.
This section documents the DESIGN this project would need, not
anything implemented.

| Reconciliation type | Authoritative source (proposed) | Current status |
|---|---|---|
| Startup reconciliation | Dhan's order/trade/position books, always | MISSING - no startup reconciliation job exists |
| Session reconciliation | Dhan | MISSING |
| Order reconciliation | Dhan (`GET /orders`) | MISSING |
| Trade reconciliation | Dhan (`GET /trades`) | MISSING |
| Position reconciliation | Dhan (positions endpoint, not yet researched) | MISSING |
| Funds reconciliation | Dhan (funds endpoint, not yet researched) | MISSING |
| End-of-day reconciliation | Dhan, cross-checked against local trade log | MISSING |
| Duplicate event handling | Idempotency key / correlation ID (design exists on paper, `OrderIntent.idempotency_key`) | DESIGNED_NOT_IMPLEMENTED |
| Missing event handling | Polling-based backstop against Dhan's order/trade books (mirrors the market-data gap-recovery pattern from Checkpoint 31) | DESIGNED_NOT_IMPLEMENTED (conceptually analogous, not actually designed for orders) |
| Late event handling | Not designed | MISSING |
| Restart recovery | Not designed | MISSING |

**Design principle this project should adopt (not yet adopted
anywhere in code):** Dhan is always the authoritative source for order/
trade/position/funds state - this project's own database is a
**cache/projection** of Dhan's state, never the source of truth. This
directly parallels the market-data "historical endpoint is the
gap-recovery authority" pattern already established in Checkpoint 31 -
the same architectural instinct, not yet extended to the execution
side.

---

## Part 9: Market Session Model

`domain/session/calendar.py` (Checkpoint 23) implements exactly:
fixed 09:15-15:30 IST, a computed 15:20 square-off deadline, no
holiday calendar, no half-day/special-session handling - **explicitly
documented as a limitation at the time it was built**, not a new
discovery this checkpoint.

**Missing concepts, confirmed still missing this checkpoint:**

- Pre-open session (08:00-09:15 order collection/price discovery) -
  not represented at all.
- Closing session/closing auction - not represented.
- Exchange holiday calendar - explicitly absent (a trading holiday
  still computes a normal PRE_OPEN/OPEN/CLOSED shape, which is
  actively wrong, not merely incomplete).
- Special/muhurat sessions - not represented.
- Trading halts (circuit breakers, security-specific halts) - no
  concept exists anywhere in this codebase.
- Exchange-wide outages - no detection or handling design exists.

**Verdict: the existing session model is NOT sufficient for live
operation.** It is sufficient for what it was built for (Checkpoint
23's read-only observation scope) and for backtesting against clean
historical data, but a live system operating on real trading days
would misclassify every actual holiday as a tradeable session.

---

## Part 10: Risk Engine Audit

`trading_engine/risk_engine/` is an 8-line `__init__.py`. **Every item
below is MISSING, not "designed" and not "partial":**

maximum daily loss, maximum strategy loss, maximum position size,
maximum total exposure, max concurrent positions (a *backtesting-only*
concept exists in `research.backtesting.portfolio` -
`max_concurrent_positions` - but this is a simulation parameter, not a
live risk control), per-symbol exposure, sector exposure, capital
allocation, order-size limits, price-band checks, liquidity checks,
stale-data checks, spread checks, volatility halt, repeated-loss
circuit breaker, strategy disable, system disable, broker-disconnect
response, market-data-disconnect response, kill switch, emergency
square-off, duplicate signal protection, duplicate order protection,
maximum order frequency, maximum modification frequency, end-of-day
forced exit.

**One partial exception, worth noting precisely:** `domain/shared_kernel`
has a `RiskLimits` contract (Checkpoint 5, extended Checkpoint 7) - a
real, tested, immutable dataclass shape for risk parameters, with
version/activation machinery (`RiskConfigurationPanel` in the frontend,
persisted `RiskConfigurationRecord`). **This is a configuration
contract, not a risk engine.** It defines what a limit *looks like*;
nothing evaluates a signal or order against it. This is a materially
important distinction this project's own documentation has been
careful about (`domain.strategy` "spec vs. implementation" pattern
applied the same way here) but worth stating with total clarity: **a
risk configuration schema is not a risk engine any more than a
strategy specification is a running strategy.**

**Verdict: this is the single largest gap in the entire system.** A
platform with real backtesting sophistication and zero risk-gating
capability cannot safely place a single live order under any
circumstance, regardless of how well-tested every other subsystem is.

---

## Part 11: Market-Data Quality Audit (beyond TRADING_GRADE_BAR)

The existing six-condition model (Checkpoint 25.1/31) covers same-day
availability, timezone, candle authority, WebSocket ingestion, gap
recovery, and one-session independent validation. This checkpoint's
research surfaces additional concerns not covered by that model:

| Concept | Status |
|---|---|
| Tick sequencing (exchange sequence numbers) | UNVERIFIED - Checkpoint 25.1 already flagged Dhan does not document a sequence-number mechanism |
| Exchange timestamp vs. local receive timestamp | PARTIALLY IMPLEMENTED - `Quote.timestamp`/`source_timestamp` distinguish provider time from processing time (Checkpoint 23), but no formal clock-drift monitoring exists |
| Duplicate ticks | DESIGNED_NOT_IMPLEMENTED for a real tick stream (no WebSocket exists yet to produce duplicates to guard against); REST polling's own duplicate-quote handling exists |
| Out-of-order ticks | Same as above - the aggregation logic (Checkpoint 24A) already sorts by timestamp, but this was designed for REST samples, not a real out-of-order tick stream |
| Stale ticks | PARTIALLY IMPLEMENTED - `CONNECTED_STALE` health state exists (Checkpoint 23) |
| Crossed markets (bid > ask) | MISSING - `Quote.bid`/`Quote.ask` have an ordering invariant (`bid <= ask`) but this is a data-integrity check, not a "crossed market" trading-halt signal |
| Zero/negative values | IMPLEMENTED - `Bar`/`Quote` reject non-positive prices at construction (Checkpoint 5/14) |
| Abnormal price movement (fat-finger/circuit detection) | MISSING |
| Missing volume | KNOWN, DOCUMENTED LIMITATION - live bars have `volume=0` as an explicit placeholder (Checkpoint 24A), never fabricated |
| Duplicate candles | IMPLEMENTED - upsert-by-identity prevents this (Checkpoint 24A) |
| Incomplete candles | IMPLEMENTED - FORMING vs. CLOSED distinction (Checkpoint 24A) |
| Session boundary correctness | PARTIALLY IMPLEMENTED - correct for a normal trading day, wrong on holidays (Part 9) |
| Corporate-action handling | MISSING - `PriceAdjustment.ADJUSTED` unreachable |
| Instrument master correctness | ASSUMPTION - 4 hand-verified symbols only (Part 13) |
| Symbol/security-ID mapping | IMPLEMENTED for the 4-symbol universe, not for a general universe |

---

## Part 12: Clock / Time Synchronization

- **UTC storage:** VERIFIED_IMPLEMENTED - `ensure_utc()` enforced at
  every domain boundary since Checkpoint 3, mechanically checked.
- **IST presentation:** VERIFIED_IMPLEMENTED - `zoneinfo`-based, one
  conversion boundary (`domain/session/calendar.py`).
- **Exchange/broker timestamps:** PARTIALLY VERIFIED - Checkpoint 31
  confirmed Dhan's historical-endpoint epoch is genuine UTC; the
  WebSocket tick timestamp convention remains UNVERIFIED (no WebSocket
  connection has ever been made).
- **Event time vs. ingestion time:** IMPLEMENTED for REST quotes
  (`source_timestamp` vs. `fetched_at`/`as_of`).
- **Server clock synchronization (NTP):** MISSING - no NTP
  verification, no drift detection exists anywhere. This project
  currently trusts the host machine's system clock unconditionally for
  every `datetime.now(UTC)` call site.
- **Clock drift detection:** MISSING.

**Verdict:** the UTC/IST architecture itself is sound and
well-enforced, but the project has never verified the underlying
assumption that the host machine's clock is actually correct. For a
system whose entire TRADING_GRADE_BAR claim rests on exact timestamp
matching (Checkpoint 31), an unmonitored local clock is a real,
currently-unaddressed risk.

---

## Part 13: Instrument Master / Corporate Actions

**Current state:** four symbols (RELIANCE, TCS, INFY, HDFCBANK),
hand-verified once against Dhan's scrip-master CSV at Checkpoint 23,
hardcoded in `MARKET_DATA_OBSERVATION_SYMBOLS`. No ISIN, tick size,
lot size, freeze quantity, or instrument-status field is captured
anywhere. No delisting/renaming/corporate-action detection exists.

**Is a 4-symbol hardcoded list acceptable?** For research/backtesting
against a small, deliberately-chosen universe: yes, and this project's
own prior checkpoints have been explicit and honest that this is a
deliberate scope choice, not a production instrument-master strategy.
**For live trading of any kind: no.** A real system needs, at minimum:
a periodic scrip-master refresh job, ISIN/tick-size/lot-size/freeze-qty
capture (all present in Dhan's own CSV, per Checkpoint 25.1's
research, simply not ingested), and a corporate-action detection/
adjustment pipeline before `PriceAdjustment.ADJUSTED` can ever be
truthfully set.

---

## Part 14: Strategy Research Quality Audit

| Capability | Status |
|---|---|
| Walk-forward validation | MISSING (Checkpoint 32's capability registry: PLANNED) |
| Out-of-sample testing | MISSING - no train/test split concept exists in the backtest engine |
| Parameter stability / sensitivity analysis | MISSING |
| Monte Carlo | MISSING (PLANNED) |
| Bootstrap resampling | MISSING |
| Regime analysis / market-condition segmentation | MISSING |
| Survivorship bias | PARTIALLY ADDRESSED - `survivorship_bias_note` is a mandatory disclosure field on every `DataQualityDisclosure` (Checkpoint 27), but no actual survivorship-bias-free universe construction exists |
| Look-ahead bias | VERIFIED ADDRESSED - next-bar-open execution model, independently reference-validated for causality (Checkpoint 30 Part 14) |
| Data leakage | Same as look-ahead - structurally addressed by the execution model, not separately audited beyond that |
| Overfitting | MISSING - no parameter-search/optimization capability exists at all yet, so overfitting from optimization specifically cannot yet occur, but neither can legitimate parameter tuning |
| Multiple-testing problem | MISSING - not relevant yet (no systematic multi-strategy comparison framework exists beyond manual side-by-side comparison) |
| Transaction-cost sensitivity | VERIFIED IMPLEMENTED - verified Indian cost model, cost-model identity tracked in every result (Checkpoint 29) |
| Slippage modelling | IMPLEMENTED BUT UNVALIDATED - a flat-percentage assumption exists, never independently validated against real fills (correctly and explicitly disclosed as an assumption, not hidden) |
| Liquidity constraints | MISSING - no volume/liquidity check exists in the backtest engine at all (a strategy could theoretically be sized larger than real market depth would support, with no warning) |
| Realistic order execution | PARTIALLY ADDRESSED - next-bar-open fill is realistic in direction (avoids look-ahead) but does not model partial fills, order-book depth, or rejection |
| Benchmark comparison | MISSING - no NIFTY/sector benchmark comparison exists anywhere in the backtest reporting |

---

## Part 15: Backtest vs. Live Parity Audit

This is the most important structural question for a platform whose
entire research asset is its backtest engine.

| Dimension | Parity status |
|---|---|
| Feature calculations | SHARED - `signal_intelligence.feature_engine` is the one dispatcher both backtesting and (if it existed) live signal generation would use. No parity break, because live signal generation does not exist yet to diverge. |
| Warm-up handling | SHARED (same dispatcher) |
| Timestamps | POTENTIAL BREAK, unverified - backtest bars derive from historical/fixture data with one timestamp convention; live bars derive from REST-polled quotes with a different aggregation path (`domain/market_data/aggregation.py`) built independently at a different checkpoint. Nothing has ever tested these two paths against each other for identical output on identical input. |
| Session boundaries | SHARED (`domain/session/calendar.py` used identically wherever session logic is needed) |
| Signal timing | Cannot be compared - live signal generation is unwired entirely (Checkpoint 24A's own explicit choice) |
| Execution assumptions | N/A for live (no live execution exists); backtest's next-bar-open model has no live counterpart to diverge from yet |
| Costs | Backtest uses the verified cost model; live has never computed a cost figure at all |
| Slippage | Backtest uses a flat-percentage assumption; live has no execution to slip |
| Order sizing | Backtest has `PositionSizingMode`; live has no sizing logic at all |
| Data-quality gates | DIVERGENT BY DESIGN - backtest explicitly runs on `FIXTURE_OR_HISTORICAL` data only, structurally forbidden from `SAMPLE_BAR` (Checkpoint 27's own safety-gate architecture test); this is a deliberate, correct, and verified separation, not a bug |
| Instrument mapping | SHARED (`InstrumentId` format identical everywhere) |

**Verdict:** most "parity breaks" don't yet exist as *breaks* because
the live side of the comparison (signal generation, execution) simply
doesn't exist yet to diverge. The one genuine, currently-unverified
risk is the bar-aggregation path itself: **live bars and
backtest/historical bars are built by two independently-written
pieces of code** (`domain/market_data/aggregation.py` for live,
`research.backtesting`'s bar handling for backtest) that have never
been tested against each other on the same underlying tick/quote data.
This is a real, concrete, previously-unstated gap.

---

## Part 16: Paper Trading Requirements

**Current state: MISSING entirely** - not even a schema exists.
Per this checkpoint's explicit instruction, a proper design (not
implementation) must model: order lifecycle (the full 7-state Dhan
model from Part 7, simulated realistically, not "if signal then
pretend buy"), latency (a fixed or sampled artificial delay between
signal and simulated fill - zero-latency paper trading is misleading),
partial fills (probabilistic or rule-based, not always 100% fill),
rejected orders (simulate realistic rejection scenarios - insufficient
margin, price-band violations), slippage (reuse the same cost/slippage
model already verified for backtesting - do not build a second one),
fees (reuse `IndianCashEquityIntradayCostModel` verbatim), stops/
targets, position management (reuse `domain/position`), broker-like
events (a simulated order-update feed shaped like Dhan's real one, so
the same downstream code that will eventually consume real broker
events can be tested against it first), and reconciliation (even a
paper account should reconcile its own simulated state against its own
event log, as a rehearsal for the real reconciliation logic).

**Should paper trading precede live execution?** Unambiguously yes -
this is not a judgment call. Every other serious trading-system design
pattern (and this project's own risk-averse discipline throughout
every checkpoint so far) supports building and validating the full
order-lifecycle/reconciliation machinery against a paper account
before any of it touches a real order. This also directly derisks
Part 5-8's entire gap list: the order-state-machine, reconciliation,
and risk-engine work can all be built and tested against paper trading
grounds before a single real rupee is at risk.

---

## Part 17: Observability Audit

**Current state:** Django's default logging, no metrics, no tracing,
no dashboards, no alerting infrastructure beyond the existing Telegram/
Discord notification adapters (which are notification *channels*, not
an observability *platform* - they can deliver an alert once one is
decided, but nothing currently decides to fire one for operational
events).

| Concept | Status |
|---|---|
| Structured logs | MISSING - standard Python/Django logging, not structured (no JSON logging, no correlation-ID threading through log lines) |
| Metrics (counters/gauges/histograms) | MISSING |
| Tracing | MISSING |
| Audit events | PARTIAL - configuration-change audit trail exists (Checkpoint 11+), no execution-side audit trail (nothing to audit yet) |
| Business metrics (P&L, win rate, etc.) | IMPLEMENTED for backtests only (`BacktestMetrics`), not for anything live |
| Market-data metrics | PARTIAL - health status exists, no historical metrics/trend view |
| Broker metrics | MISSING |
| Order/position metrics | MISSING - nothing to measure |
| Alerts | MISSING - no alerting rules/thresholds exist; Telegram/Discord are unused delivery channels with nothing wired to trigger them operationally |
| Incident state | MISSING |

**What an operator would actually need during live trading** (not
built): a real-time dashboard showing broker connection state, feed
freshness, active positions and their P&L, today's realized P&L vs.
daily loss limit, order-rejection rate, and a single, unmissable
kill-switch control - none of which exist today because none of the
underlying data exists to show.

---

## Part 18: Failure / Recovery Engineering

For every scenario named in the checkpoint brief, current status:

| Scenario | Detection | Response | Safe state | Recovery | Reconciliation | Operator notification |
|---|---|---|---|---|---|---|
| Internet disconnect | MISSING | MISSING | N/A (nothing live to make safe) | MISSING | MISSING | MISSING |
| Broker disconnect | PARTIAL (REST call failure is caught and classified - `DhanConnectionError`) | Logged, surfaced in health status | N/A | Manual retry only (operator clicks Refresh) | MISSING | Via UI badge only, no push alert |
| WebSocket disconnect | N/A - no WebSocket exists | - | - | - | - | - |
| REST timeout | IMPLEMENTED (10s timeout, classified) | Returns a typed error | N/A | Manual retry | N/A | UI badge only |
| Duplicate order request | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING |
| Application restart | MISSING (no persistent live state exists to lose yet) | - | - | - | - | - |
| Machine restart | Same as above | - | - | - | - | - |
| Token expiry | UNHANDLED - no refresh flow exists; a long-lived process would eventually see every call fail with `TOKEN_EXPIRED` and have no automatic recovery | Logged as `TOKEN_EXPIRED` health state | N/A | Manual - operator must re-enter credentials | N/A | UI badge only |
| Stale feed | IMPLEMENTED - `CONNECTED_STALE` classification (Checkpoint 23) | Displayed | N/A | Manual refresh | N/A | UI badge only |
| Database outage | MISSING - no explicit handling; Django's own default error surfaces | - | - | - | - | - |
| Redis outage | MISSING - Redis is used for cache/rate-limiting; no fallback/circuit-breaker for its absence | - | - | - | - | - |
| Process crash | MISSING - no supervisor/restart policy defined anywhere (relevant directly to Checkpoint 32's future worker process) | - | - | - | - | - |
| Clock drift | MISSING (Part 12) | - | - | - | - | - |
| Exchange outage | MISSING - no concept of "exchange itself is down" distinct from "our connection is down" | - | - | - | - | - |
| Broker outage | Same as broker disconnect above, no distinct handling | - | - | - | - | - |

**Verdict:** failure handling exists only where a checkpoint happened
to need it for a specific read-only call (REST timeout/auth failure
classification). Nothing resembling a systematic failure-recovery
strategy exists - understandable and appropriate for a system that has
never held live state, but a large, unstarted body of work before live
operation.

---

## Part 19: Security / Regulatory Findings

See `docs/research/ACTIVE_PRODUCT_READINESS_RESEARCH.md` for full
detail and source labeling. Summary:

- **Directly stated by regulator:** SEBI's February 4, 2025 circular
  on retail algorithmic trading exists and remains under active
  phased implementation (timeline extended again by a SEBI circular
  dated September 30, 2025 - both confirmed live this checkpoint).
- **Broker implementation requirement:** static IP whitelisting for
  order APIs (directly confirmed from Dhan's own documentation this
  checkpoint) - a hard, currently-unmet operational prerequisite for
  any live order capability, independent of code readiness. Algo
  registration/ID-tagging, broker-as-principal liability model, and
  Indian-server hosting are reported by secondary sources describing
  the SEBI circular's content, not independently verified against the
  primary text this session.
- **Project interpretation:** live execution readiness is not purely
  an engineering milestone - it has broker-onboarding and regulatory
  prerequisites this project has not yet investigated at the
  account-specific level. This does not block continued engineering
  work (backtesting, paper trading, risk engine, reconciliation design
  can all proceed under the existing safety rules), but it does mean
  "we finished the order-management code" would not, by itself, mean
  "we can legally and operationally place a live order."
- **This project's existing credential-handling discipline** (encrypted
  at rest, never logged, never exposed in any API response - Checkpoint
  22, re-verified every checkpoint since) remains consistent with the
  spirit of the cybersecurity expectations found in secondary sources,
  though no formal compliance audit has been performed.

---

## Part 20: Operator Workflow Audit

Walking the 15-step workflow named in the brief against the current UI:

| Step | Current UI support |
|---|---|
| 1. Configure broker | YES - `DhanSettingsCard.tsx` |
| 2. Validate connectivity | YES - Settings page connectivity check |
| 3. Validate market data | PARTIAL - Live Market Data Monitor shows health, but never validates it's *trading-grade* until this checkpoint's Reports page addition |
| 4. Select universe | PARTIAL - `MARKET_DATA_OBSERVATION_SYMBOLS` is env-configured, not a UI-driven universe selector |
| 5. Select strategy | YES - Strategy Configuration page |
| 6. Configure risk | PARTIAL - `RiskConfigurationPanel` exists and configures `RiskLimits`, but nothing enforces those limits (Part 10) |
| 7. Start session | MISSING - no concept of "starting a live trading session" exists anywhere |
| 8. Monitor system | PARTIAL - Live Market Data Monitor + (new) Reports page cover data/engine status, nothing covers strategy/order/position status because none exist |
| 9. Review signals | PARTIAL - only within a backtest result, never a live signal stream |
| 10. Approve/control execution | MISSING - no execution exists to approve |
| 11. Monitor positions | MISSING |
| 12. Handle failures | MISSING - no operator-facing failure-handling UI exists beyond passive health badges |
| 13. Square off | MISSING |
| 14. Reconcile | MISSING |
| 15. Review reports | PARTIAL - Checkpoint 32's Reports page, backtest results only |

**Missing screens, explicitly:** a live Session control screen, a
Signal Monitor (live, not backtest-only), an Order Monitor, a Position
Monitor, a Risk Monitor (limit utilization, not just limit
configuration), a Reconciliation screen, and an Alerts/Incident
screen.

---

## Part 21: Product UX Gap Analysis

| Surface | Status |
|---|---|
| Dashboard (single-pane system overview) | MISSING |
| System health | PARTIAL (spread across Market Data Monitor + Reports, not unified) |
| Market data health | YES |
| Strategy status | PARTIAL (configuration only, no live activity) |
| Signal monitor | MISSING (live) |
| Order monitor | MISSING |
| Position monitor | MISSING |
| Risk monitor | MISSING |
| Broker connectivity | YES |
| Session status | PARTIAL (computed, not surfaced as an actionable "session" concept) |
| Reconciliation | MISSING |
| Alerts | MISSING |
| Reports | YES (Checkpoint 32, catalogue-level) |
| Research workspace | YES (Backtesting Workbench, Comparison, Watchlists, Strategy Monitor) |
| Configuration | YES |
| Audit trail | PARTIAL (backend API exists, Checkpoint 12; no dedicated frontend audit-report view) |

**Priority for missing surfaces** (not "build all of this now" - a
priority ordering for when the underlying capability exists): Risk
Monitor and Order/Position Monitor are highest-value once paper
trading exists (they would serve paper trading immediately, not wait
for live); a unified Dashboard is high-value but purely presentational
once the underlying data exists; Alerts screen depends on an actual
alerting-rules engine that doesn't exist yet (Part 17).

---

## Part 22: Reporting Gap Analysis

Checkpoint 32 established the *catalogue and metadata contract* - it
did not build most of the actual reports an operator would need:

| Report | Status |
|---|---|
| Daily trading report | MISSING - no live trading exists to report on |
| Signal report | MISSING (catalogue entry: NOT_YET_IMPLEMENTED) |
| Order report | MISSING |
| Execution quality report | MISSING |
| Slippage report | MISSING (backtesting has a slippage *assumption*, never compared against real fills) |
| P&L report | PARTIAL - backtest-only P&L exists; no live P&L report |
| Risk breach report | MISSING - no risk engine exists to breach |
| Reconciliation report | MISSING |
| Broker health report | PARTIAL - covered informally by the connectivity/health status, not a dedicated report |
| Market-data quality report | YES (Checkpoint 32) |
| Strategy performance report | PARTIAL - single-run backtest reports exist; no cross-run aggregate performance report |
| Incident report | MISSING - no incident concept exists |
| Audit report | PARTIAL - raw audit API exists, no formatted report |

---

## Part 23: External Research Scorecard

| Area | Source | Finding | Impact | Project Action |
|---|---|---|---|---|
| Order API | dhanhq.co/docs/v2/orders (live fetch) | 7-state lifecycle including TRANSIT/EXPIRED not in our domain enum | Domain contract gap | Extend `OrderStatus` before any order-management implementation |
| Order API | dhanhq.co/docs/v2/orders (live fetch) | Static IP required for order APIs | Hard operational blocker | Must provision static IP before any live-order checkpoint; document as a prerequisite |
| Order API | dhanhq.co/docs/v2/orders (live fetch) | Correlation ID mechanism exists (`GET /orders/external/{id}`) | Idempotency design validated | Wire `OrderIntent.idempotency_key` to this field when the adapter is built |
| Order API | dhanhq.co/docs/v2/orders (live fetch) | Cancellation is async (202 Accepted) | Order state machine gap | Design an explicit "cancel requested, not yet confirmed" state |
| SEBI regulation | sebi.gov.in circular archive (live fetch, primary metadata) + secondary summaries | Retail algo framework active, still being phased in as of Sep 2025 | Regulatory prerequisite for live trading | Do not treat order-management code completion as sufficient for live trading; re-verify current requirements before any live-execution checkpoint |
| SEBI regulation | secondary summaries (not independently verified against primary PDF) | Indian server hosting required for retail algos | Deployment-region constraint | Document as an open question for a future deployment-architecture checkpoint |

---

## Part 24: MASTER GAP REGISTER

| Gap | Category | Severity | Current State | Evidence | Required Action |
|---|---|---|---|---|---|
| No risk engine of any kind | Risk | **P0** | `risk_engine/` is an empty scaffold | Part 10 | Design and implement before any order-management work begins |
| No kill switch implementation | Risk | **P0** | Referenced in every safety rule, never built | Repo-wide search found no implementation | Implement as part of the risk-engine checkpoint, not an afterthought |
| No order placement/modify/cancel capability | Execution | **P0** | `infrastructure/brokers/dhan/` has one GET call | Part 4/5 | Out of scope until risk engine + paper trading exist |
| No reconciliation of any kind | Execution | **P0** | No code found | Part 8 | Design before order-management implementation - Dhan must be authoritative |
| Static IP not provisioned | Operational | **P0** | Confirmed hard requirement, no IP exists | Part 4 research | Must be solved before any live order checkpoint, independent of code |
| Order domain enum missing TRANSIT/EXPIRED states | Domain Model | **P0** | `domain/order/contracts.py` has 6 of 7 real states | Part 7 research | Extend `OrderStatus` enum with evidence-based real states |
| No paper trading layer | Execution | **P0** | Not designed, not implemented | Part 16 | Should be the primary pre-live-trading milestone |
| No holiday calendar in session model | Market Data / Session | **P1** | Explicit documented limitation since Checkpoint 23 | Part 9 | Needed before any live-session-aware feature is built |
| No NTP/clock-drift monitoring | Reliability | **P1** | No detection exists | Part 12 | Needed before trusting any live timestamp-critical claim |
| No token-refresh flow for long-lived processes | Reliability | **P1** | 24h Dhan token, no refresh code | Part 4/18 | Required before any persistent worker process is built (Checkpoint 32's own next step) |
| Live vs. backtest bar-aggregation parity never tested | Research / Data | **P1** | Two independently-written aggregation code paths, never cross-tested | Part 15 | A dedicated parity test before live signal generation is ever wired |
| No observability/metrics/alerting infrastructure | Operations | **P1** | Logging only, no metrics/tracing/alert rules | Part 17 | Needed before operating any live/paper capability unattended |
| No failure-recovery design for most named scenarios | Reliability | **P1** | Ad hoc handling only for REST timeout/auth failure | Part 18 | Systematic design needed alongside the worker-process implementation |
| Instrument master is 4 hardcoded symbols | Data | **P2** | No ingestion pipeline, no corporate-action handling | Part 13 | Needed before universe expansion beyond the current 4 symbols |
| No walk-forward/Monte Carlo/robustness validation | Research | **P2** | Named PLANNED in capability registry | Part 14 | Valuable before trusting any strategy's backtest result for real capital sizing |
| No liquidity/volume constraint in backtest engine | Research | **P2** | Not modeled | Part 14 | Should precede any claim that a backtest result is realistically executable |
| No live P&L/position/order UI surfaces | UX | **P2** | Screens don't exist because underlying data doesn't exist | Part 20/21 | Build alongside paper trading, not before |
| Regulatory/broker-onboarding prerequisites not investigated at account level | Regulatory | **P2** | Only public documentation researched | Part 19 | Requires direct engagement with Dhan's onboarding process, not a code task |
| Reporting catalogue has 8 of 10 report types with no real content | Reporting | **P3** | Checkpoint 32 built the contract, not the content | Part 22 | Fill in as underlying capabilities (orders, positions, risk) are built |
| No export (PDF/CSV/JSON) for any report | Reporting | **P3** | Explicitly PLANNED, not built | Checkpoint 32 | Low priority until report content itself exists |
| Documentation narrative docs (`ARCHITECTURE.md`) not kept current every checkpoint | Documentation | **P3** | Explicitly noted at Checkpoint 32 | Self-evident from the doc's own "Note on this document's currency" | Low priority - `taskReport.md` already serves as the current-state source of truth |

---

## Part 17 (report section 17): Architecture Assumptions That Need Reconsideration

Explicitly asked, per the checkpoint's own Part 26:

- **Dhan-only design:** reasonable to keep for now - no evidence
  surfaced this checkpoint that a multi-broker abstraction is needed
  before a single broker even has order capability. `domain.broker`'s
  Protocol-based design already leaves room for a second broker later
  without a rewrite. **No change recommended.**
- **Standalone worker (Checkpoint 32 decision):** re-examined by this
  checkpoint's own token-refresh/failure-recovery findings (Part 12,
  18) - the decision itself still looks sound, but its *scope* needs
  to grow: the persistent-process contract from Checkpoint 32 did not
  explicitly cover token-refresh scheduling, which this checkpoint's
  research shows is a real, near-certain operational need for any
  process that outlives 24 hours. **Recommend extending, not
  replacing, the Checkpoint 32 contract.**
- **Redis's role:** currently cache/rate-limiting only. This
  checkpoint found no evidence Redis needs a larger role (e.g. a
  message bus for order events) yet - that question is premature
  before order-management exists at all. **No change recommended
  now; revisit once execution-management design begins.**
- **Persistence strategy:** the existing Django ORM + PostgreSQL
  model has handled every bounded context so far without strain.
  Reconciliation/order-state persistence will need careful design
  (Part 8) but nothing found this checkpoint suggests the underlying
  technology choice is wrong. **No change recommended.**
- **Report architecture (Checkpoint 32):** sound as a contract layer;
  this checkpoint's gap analysis (Part 22) shows the NEXT need is
  content, not a different architecture. **No change recommended.**
- **Frontend contract architecture (OpenAPI-generated types):** no
  evidence surfaced this checkpoint that this breaks down at larger
  scale. **No change recommended.**
- **Strategy execution ownership (`trading_engine.strategy_execution`,
  research-only today):** the eventual live-signal-generation path
  will need to decide whether it reuses this exact module or a
  parallel live-specific one. Part 15's parity finding (two
  independent aggregation paths already exist for market data)
  suggests this project should actively resist creating a second,
  parallel strategy-evaluation path for live use - reuse the existing
  one, wired to live data, rather than reimplementing. **Recommend
  explicit design attention at the live-signal-generation checkpoint,
  not a change now.**
- **Broker abstraction (`domain.broker`):** exists only as a Protocol
  shape, never implemented. Nothing found this checkpoint suggests the
  shape itself is wrong, but it has also never been exercised against
  a real order, so its adequacy is genuinely unverified. **No change
  recommended without first attempting a real implementation.**
- **Control-plane authority:** unchanged, no evidence against it.
- **Market-data reconciliation pattern (WebSocket + historical
  backfill):** Checkpoint 25.1/31's hybrid design remains the right
  target architecture; this checkpoint's Part 8 findings suggest the
  SAME pattern (a live, possibly-stale local state reconciled against
  an always-authoritative broker source) should be deliberately reused
  for order/position/trade reconciliation, not reinvented. **Recommend
  reuse, not redesign.**
- **Paper trading design:** did not exist as an architectural decision
  before this checkpoint. **This checkpoint recommends paper trading
  be designed as a genuinely first-class capability - reusing the
  verified cost model and the real order-state machine (once
  extended, Part 7) - not a "fake" simulation bolted on later.** This
  is a new recommendation, not a reconsideration of an existing one.
- **AI agent authority:** no AI agent capability exists yet
  (`CAPABILITY_REGISTRY`: NOT_YET_IMPLEMENTED). Nothing to
  reconsider.

---

## Part 27: Implementation vs. Research Decision (P0/P1 items)

| Item | Decision | Why |
|---|---|---|
| Risk engine | RESEARCH FIRST, then IMPLEMENT | The specific limit types (Part 10) need a design checkpoint before code - too large to implement without first deciding the exact scope (which limits, in what order) |
| Kill switch | IMPLEMENT NOW (as part of risk-engine checkpoint) | Small, well-understood, high-value, should not be deferred once risk-engine work begins |
| Order placement/modify/cancel | BLOCKED | Blocked on risk engine existing first (no order-management work should place an order without risk gating already in place) AND on static IP provisioning (external dependency) |
| Static IP provisioning | WAITING FOR EXTERNAL DEPENDENCY | Requires an infrastructure/hosting decision outside this project's code, likely coupled to the Checkpoint 32 worker-process deployment decision |
| Reconciliation design | RESEARCH FIRST | Needs the order domain model extended (Part 7) before a reconciliation design can be concrete rather than abstract |
| Order domain enum extension (TRANSIT/EXPIRED) | IMPLEMENT NOW | Small, evidence-based, low-risk, unblocks more precise design work for everything else in this list |
| Paper trading | IMPLEMENT NOW (next major checkpoint candidate) | Directly derisks risk-engine, reconciliation, and order-state-machine work without touching a real order - highest-value next step per Part 28 |
| Holiday calendar | RESEARCH FIRST | Needs an authoritative NSE holiday source identified (not yet researched this checkpoint) before implementation |
| NTP/clock-drift monitoring | IMPLEMENT NOW (small, standalone) | Independent of everything else, genuinely cheap to add, meaningfully de-risks the TRADING_GRADE_BAR timestamp claim |
| Token-refresh flow | RESEARCH FIRST, then IMPLEMENT alongside the Checkpoint 32 worker process | Needs to be designed as part of the persistent-process contract, not bolted on afterward |
| Observability/metrics | IMPLEMENT NOW (foundational, small increments) | Cheap relative to its long-term value; should be built alongside paper trading, not after |

---

## Part 28: What We Should Build NEXT

**Recommendation: Paper Trading (full-fidelity, per Part 16's design),
built on top of an extended order domain model (Part 7's TRANSIT/
EXPIRED states) and a minimal but real risk engine (Part 10's core
limits: max daily loss, max position size, max concurrent positions,
kill switch).**

**Why this, and not WebSocket implementation (the Checkpoint 32
recommendation), proven against the complete gap analysis above:**

1. WebSocket/TRADING_GRADE_BAR (Checkpoint 32's prior recommendation)
   only closes Part 11's market-data-quality gap. Even a fully
   trading-grade live feed would still leave **every single lifecycle
   stage from RISK APPROVED onward completely missing** (Part 6) - the
   platform would have excellent data and nothing capable of acting on
   it safely.
2. Paper trading, by contrast, forces exactly the design work this
   checkpoint found most urgently missing - order state machine (Part
   7), risk gating (Part 10), and reconciliation patterns (Part 8) -
   while remaining entirely within this project's existing safety
   rules (no real orders, ever).
3. It directly de-risks the eventual live-execution checkpoint by
   letting the order-lifecycle, risk-engine, and reconciliation code
   be built and tested against a simulated broker before a single
   rupee or a real Dhan order is at risk - the same "prove before you
   build on it" discipline this project has followed since Checkpoint
   14.
4. It does not require solving the static-IP/broker-onboarding
   external dependencies that currently block real order capability
   entirely (Part 4/24) - paper trading has no such prerequisite.
5. SAMPLE_BAR-quality live data is already sufficient to drive a paper
   trading engine honestly, AS LONG AS the paper engine's own results
   are clearly labeled with the same data-quality disclosure discipline
   already proven at Checkpoint 27-29 for backtesting - it does not
   need to wait for TRADING_GRADE_BAR.

**Therefore Checkpoint 32's WebSocket recommendation is explicitly
superseded by this checkpoint's evidence-based analysis** - not
because it was wrong in isolation, but because the complete gap
register shows a materially larger and more urgent gap exists
elsewhere.

## Part 20 (report section 20): What Must NOT Be Built Yet

- Real order placement/modification/cancellation - blocked on risk
  engine + static IP + broker-onboarding investigation (Part 24, 27).
- WebSocket live ingestion - not urgent relative to paper trading;
  revisit after paper trading proves out the order/risk/reconciliation
  design against SAMPLE_BAR-quality data first.
- Any multi-broker abstraction work - no second broker need has
  surfaced.
- Report export (PDF/CSV/JSON) - no report content exists yet to
  export.
- Walk-forward/Monte Carlo research tooling - valuable, but strictly
  lower priority than closing the P0 execution/risk gaps.
