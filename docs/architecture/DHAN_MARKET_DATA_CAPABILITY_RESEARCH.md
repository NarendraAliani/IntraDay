# Dhan Market-Data Capability Research

Checkpoint 25.1. **Research and verification only — no code changed.**
Answers the question left open at Checkpoint 24A/25:
`MARKET_DATA_QUALITY_ASSESSMENT.md` classified the current bars
`SAMPLE_BAR` and named two candidate paths to `TRADING_GRADE_BAR`
(Dhan's WebSocket feed, or a historical/intraday OHLC endpoint) as an
**OPEN decision, not implemented, not verified**. This document closes
that verification gap using Dhan's own official documentation.

## Executive Summary

Dhan provides **both** capabilities named as open in the prior
checkpoint: a documented WebSocket live-market-feed (tick-by-tick, not
periodic snapshots) and a documented REST historical/intraday-candle
API. Both are real, confirmed against Dhan's own official
documentation (`https://dhanhq.co/docs/v2/...`), with exact endpoint
shapes recorded below — nothing in this document is invented.

The WebSocket feed's tick-by-tick nature (confirmed: "tick-by-tick
event based data," not a sampled feed) would structurally eliminate
the sampling-gap problem that defines `SAMPLE_BAR` today — a
continuous stream sees every trade, so OPEN/HIGH/LOW/CLOSE built from
it are no longer one-sided approximations. However, Dhan's
documentation leaves **three material facts unconfirmed** that are
directly relevant to trusting either path alone: whether the
intraday-OHLC endpoint returns real-time same-day (not just prior-day)
candles, whether those candles are exchange-authoritative or
Dhan-computed, and the exact timezone convention for its date
parameters and returned timestamps.

**Recommendation:** the target architecture is a **hybrid**
(WebSocket for real-time forming-candle construction + historical/
intraday OHLC for authoritative closed-candle backfill/reconciliation
after gaps) — but implementing it now, before the three unconfirmed
facts above are resolved, would mean building a reconciliation
mechanism against an authority whose own behavior isn't yet verified.
**Checkpoint 26 should be a narrow, read-only, hands-on API
verification step** (not implementation) confirming those three facts
against Dhan's live API, using the read-only pattern already proven
safe at Checkpoints 22-24A. The hybrid architecture itself should be
implemented only after that verification, in a subsequent checkpoint.

`SAMPLE_BAR` remains the correct classification. It cannot yet be
promoted — see §20 for the exact, evidence-based conditions.

## Research Scope

This document covers only market-data (quote/candle/tick) capability.
It does not research or reference Dhan's order-placement, portfolio,
funds, or option-chain APIs — those remain out of scope for this
project's current phase and were not investigated.

## Official Dhan Sources

Every Dhan-specific claim below was fetched directly from Dhan's own
official documentation site during this checkpoint (not a third-party
summary, blog, or SDK README):

| Page | URL |
|---|---|
| Live Market Feed (WebSocket) | `https://dhanhq.co/docs/v2/live-market-feed/` |
| Historical Data (candles) | `https://dhanhq.co/docs/v2/historical-data/` |
| API Introduction (rate limits) | `https://dhanhq.co/docs/v2/` |
| Authentication | `https://dhanhq.co/docs/v2/authentication/` |
| Instrument List (scrip master) | `https://dhanhq.co/docs/v2/instruments/` |

No blog, Medium article, Stack Overflow answer, third-party GitHub
repository, or unofficial SDK was used as the basis for any capability
claim in this document. Where a fact could not be found on these
official pages, it is explicitly marked **UNCONFIRMED** below, never
assumed.

---

## WebSocket Findings

**Endpoint:** `wss://api-feed.dhan.co?version=2&token={access-token}&clientId={client-id}&authType=2`

**Authentication:** the access token and client ID are passed as URL
query parameters at connection time (not a header, unlike the REST
APIs) — `authType=2` is a fixed, documented default.

**Subscription (JSON, sent after connecting):**
```json
{
  "RequestCode": 15,
  "InstrumentCount": 2,
  "InstrumentList": [
    {"ExchangeSegment": "NSE_EQ", "SecurityId": "1333"}
  ]
}
```
**Unsubscription:** `{"RequestCode": 12}`.

**Instrument identity:** the same `(ExchangeSegment, SecurityId)` pair
already used by this project's REST client
(`infrastructure/market_data_providers/dhan/instruments.py`) —
verified consistent, not a new/different identity scheme.

**Limits (documented):** 100 instruments per subscription message,
5,000 instruments per connection, 5 connections per user maximum (a
6th connection causes Dhan to disconnect the first with error code
805).

**Subscription modes / response packets** (all binary, little-endian,
common 8-byte header: response code / message length / exchange
segment / security ID):

| Packet | Response code | Contents |
|---|---|---|
| Ticker | 2 | Last Traded Price + Last Trade Time (12 bytes) |
| Quote | 4 | Ticker fields + Last Traded Quantity, Average Trade Price, Volume, Total Buy/Sell Quantity, day Open/High/Low/Close (42 bytes) |
| Full | 8 | Quote fields + Open Interest, day high/low OI (NSE_FNO only), 5-level market depth (162+ bytes) |
| Prev Close | 6 | Previous day close + prior open interest (sent automatically) |
| Disconnect | 50 | Disconnection reason code |

**Delivery model — the single most important finding for this
project's purpose:** Dhan's own documentation describes this as
"tick-by-tick event based data ... sent over the websocket" — i.e.
**individual trade events, not periodic snapshots**. This is
structurally different from this project's current REST point-sampling
design (Checkpoints 23-24A), where a price reading only exists at
whatever instant an operator happened to click Refresh.

**Timestamp format:** "EPOCH" (Unix timestamp), granularity not
explicitly stated as seconds vs. milliseconds in the fetched page;
timezone is not explicitly stated either — **UNCONFIRMED**, exchange
time is implied but not documented in words.

**Heartbeat / connection health:** server sends a ping every 10
seconds; if the client doesn't respond within 40 seconds, Dhan closes
the connection server-side. Standard WebSocket ping/pong is expected
to be handled automatically by any conformant WebSocket client
library.

**Reconnection behavior:** not documented beyond the heartbeat-timeout
disconnect above and the 6th-connection eviction (error 805). No
documented sequence-numbering or gap-detection mechanism was found on
this page — **UNCONFIRMED** whether Dhan provides any way to detect a
dropped tick during a brief disconnect versus relying entirely on the
historical endpoint to backfill afterward.

**Ordering guarantees:** not explicitly documented; WebSocket runs
over TCP, which guarantees in-order delivery of bytes on the wire, but
Dhan's documentation does not state whether ticks can arrive
out-of-order relative to their own trade time under any server-side
condition (e.g. multi-threaded fan-out) — **UNCONFIRMED**.

---

## Historical / Intraday OHLC Findings

**Two distinct endpoints, both `POST`, both requiring the `access-token` header:**

| Endpoint | Purpose |
|---|---|
| `https://api.dhan.co/v2/charts/historical` | Daily candles |
| `https://api.dhan.co/v2/charts/intraday` | Intraday candles |

**Common request parameters:** `securityId`, `exchangeSegment`,
`instrument` (type classification), `fromDate`/`toDate`.

**Intraday-specific:** `interval` — documented supported values are
**1, 5, 15, 25, and 60 minutes** (not a continuous range — these five
values are the only ones stated). Optional `oi` boolean for
derivatives open interest.

**Range/depth limits (documented):** intraday requests are capped at
**90 days of data per single request**; intraday data is available
going back **5 years**; daily candles are available back to an
instrument's own listing/inception date.

**Response fields:** `open`, `high`, `low`, `close`, `volume`
(integer), `timestamp` (epoch), plus `open_interest` when requested
for derivatives.

**What the documentation does NOT state (verified absent, not just
overlooked) — each a material gap for this project's decision:**

1. **Whether candles are exchange-generated (authoritative) or
   computed by Dhan itself from its own tick data.** This matters
   directly: if Dhan's own historical candles are themselves
   aggregated from samples/ticks Dhan captured, "authoritative" only
   means "Dhan's own aggregation," not necessarily "the exchange's own
   official OHLC" — a materially different trust claim.
2. **Whether `/v2/charts/intraday` returns TODAY's already-elapsed
   candles in real time**, or only prior trading days. The one
   documented hint — "It is recommended that you store this data at
   your end for day-to-day analysis" — is suggestive of a
   retrieve-and-archive workflow rather than a live intraday polling
   workflow, but does not explicitly confirm or deny same-day
   availability.
3. **Whether the currently-forming (incomplete) candle is ever
   returned**, or only fully-closed candles.
4. **Exact timezone** for the `fromDate`/`toDate` request parameters
   and the returned `timestamp` field (IST is the reasonable
   assumption for an India-only broker, but is not stated in words on
   this page).
5. **Corporate-action adjustment behavior** (split/bonus/dividend
   adjusted vs. raw prices) — not addressed on this page at all.
6. **Explicit rate limit** for these two endpoints specifically — see
   Rate Limit Findings below for what could and couldn't be confirmed.

**Conclusion for this section:** the historical/intraday endpoint
**does** provide OHLCV records directly (the application would not
need to compute OPEN/HIGH/LOW/CLOSE from raw ticks if using this
endpoint) — but whether those records are trustworthy as
"exchange-faithful" and whether they cover the live trading day are
both genuinely unconfirmed by Dhan's own documentation, not merely
undocumented in this project's prior research.

---

## Instrument Mapping Findings

Confirms and extends Checkpoint 23's own findings (`RELIANCE=2885`,
`TCS=11536`, `INFY=1594`, `HDFCBANK=1333`, verified against the same
CSV at that checkpoint):

- **Scrip master CSVs** (unchanged): compact
  `https://images.dhan.co/api-data/api-scrip-master.csv` and detailed
  `https://images.dhan.co/api-data/api-scrip-master-detailed.csv`.
  Key columns: `SEM_SMST_SECURITY_ID` (security ID), `EXCH_ID`/
  `SEM_EXM_EXCH_ID` (NSE/BSE/MCX), `SEGMENT` (Equity/Derivatives/
  Currency/Commodity), `SEM_TRADING_SYMBOL` (exchange symbol),
  `SEM_CUSTOM_SYMBOL` (Dhan's own display symbol).
- **New finding this checkpoint:** a REST alternative to the CSV
  exists — `GET https://api.dhan.co/v2/instrument/{exchangeSegment}`
  — not used by this project (Checkpoint 23 deliberately chose a
  small, hand-verified static table over any ingestion pipeline;
  unchanged conclusion, but this REST endpoint is the natural
  foundation if a future checkpoint needs to support a larger,
  dynamically-resolved universe instead of four hand-verified
  symbols).
- **Not documented on this page:** scrip-master update frequency,
  corporate-action handling, symbol-change handling, or newly-listed-
  security handling — genuinely absent from Dhan's own documentation,
  not an oversight in this research.

**Relative to this project's 4-symbol observation universe
(`MARKET_DATA_OBSERVATION_SYMBOLS`, Checkpoint 23):** nothing found
this checkpoint suggests the 4-symbol universe is anything other than
a deliberate, small verification set — Dhan's own documented limits
(5,000 instruments/WebSocket connection, 90-day/request on intraday
REST) comfortably support a much larger universe whenever a future
checkpoint chooses to grow it. The 4-symbol limitation is a project
choice, not a Dhan constraint.

---

## Timestamp Findings

| Source | Format | Timezone | Confidence |
|---|---|---|---|
| WebSocket tick (`Last Trade Time`) | EPOCH (Unix timestamp) | Not stated in words; exchange time implied | Medium |
| Historical/intraday candle `timestamp` | EPOCH | Not stated in words | Medium |
| `fromDate`/`toDate` request parameters | Not stated (string) | Not stated | Low |

**PROJECT DECISION (not a Dhan fact):** this project's own established
convention (`domain/session/calendar.py`, Checkpoint 23) already
treats India Standard Time as the exchange's own wall-clock time and
converts to UTC at the one documented ingestion boundary. Given Dhan's
own documentation does not explicitly state a timezone for any of the
three timestamp sources above, this project should **not assume** IST
without empirical confirmation (see §20's conditions) — a wrong
assumption here would silently misalign every bar boundary by however
many hours the actual offset differs, which is exactly the kind of
error a "trading-grade" claim cannot tolerate.

**Candle boundary semantics** (09:15 open, 15:29/15:30 close,
pre-open/post-market, market holidays): not addressed by either Dhan
documentation page fetched this checkpoint — this project's own
existing `domain/session/calendar.py` (fixed 09:15-15:30 IST, no
holiday calendar) remains a project-level assumption, not something
Dhan's documentation confirms or denies.

---

## Volume Findings

**WebSocket Quote/Full packets** include a `Volume` (int32) field.
Dhan's documentation does not state whether this is cumulative-since-
market-open or a per-tick incremental quantity — the field name alone
("Volume," not "Last Traded Quantity," which is a separate documented
field in the same packet) strongly suggests **cumulative day volume**,
consistent with the REST `/v2/marketfeed/quote` endpoint's own
cumulative-volume behavior already confirmed at Checkpoint 24A's
finalization review — **UNCONFIRMED as certain, but consistent with
every other Dhan volume field investigated so far.**

**Critical distinction from the current REST point-sampling design:**
with continuous WebSocket tick coverage (every trade seen, not
sporadic samples), computing a true per-minute volume as
`cumulative_volume(interval_end) - cumulative_volume(interval_start)`
becomes **safe and exact** — there is no sampling gap in which the
counter could have reset or jumped unobserved. This is a materially
different situation from Checkpoint 24A's explicit-trigger REST
design, where the same delta computation was correctly assessed as
unsafe specifically because of the sampling gaps.

**Historical/intraday candle `volume` field:** presumed to be genuine
per-candle traded volume (that is the field's evident purpose in a
standard OHLCV response), but not explicitly described by Dhan's
documentation as exchange-sourced vs. Dhan-computed — same
uncertainty as the OHLC fields themselves (§ above).

**Edge cases (counter reset, missing updates, reconnect, duplicates,
delayed updates):** none of these are addressed in Dhan's fetched
documentation. A future implementation would need to treat a
volume-counter decrease (implying a reset) as an anomaly requiring
investigation, not silently accepted — consistent with this project's
existing "reject/report anomalies explicitly, never silently
fabricate" discipline (`domain/market_data/quality.py`,
`domain/market_data/aggregation.py`'s `AnomalousObservation`).

**No volume figure is fabricated by this research or recommended for
fabrication** — this document proposes only how a future, verified
implementation could compute a real value; it does not compute one.

---

## Rate Limit Findings

From Dhan's own documentation introduction page:

| Category | Per second | Per minute | Per hour | Per day |
|---|---|---|---|---|
| Order APIs | 10 | 250 | 1,000 | 7,000 |
| Data APIs | 5 | — | — | 100,000 |
| Quote APIs | 1 | Unlimited | Unlimited | Unlimited |
| Non-Trading APIs | 20 | Unlimited | Unlimited | Unlimited |

**Confidence note:** Dhan's page presents these four categories by
name but the fetched summary did not explicitly state which named
category the historical/intraday charts endpoints or the marketfeed
quote/LTP endpoints fall under — the mapping above ("Quote APIs" for
`/v2/marketfeed/*`, "Data APIs" for `/v2/charts/*`) is a **reasonable
inference from the category names and this project's own prior,
independently-confirmed finding** (Checkpoint 22/23: `/v2/marketfeed/*`
is rate-limited at 1 request/second, which exactly matches the "Quote
APIs" row above) — not a directly-quoted statement pairing endpoint to
category. Marked **Medium confidence** in the evidence table below for
this reason.

**WebSocket connection limits** (High confidence, directly from the
Live Market Feed page): 5 connections/user, 5,000 instruments/
connection, 100 instruments/subscription message.

---

## Authentication Findings

- **Access token validity: 24 hours** (explicitly documented).
- **Renewal:** a documented Renew Token API extends an *active* token
  by another 24 hours; a separate Generate Token flow (requiring TOTP)
  can mint a fresh token programmatically without web-portal access.
  An already-expired token cannot be renewed via the Renew Token API
  (it "will return an error").
- **WebSocket authentication:** the same access token is passed as a
  URL query parameter (`token=`) at WebSocket connection time — the
  Live Market Feed page does not explicitly confirm this is *the same
  token value* as the REST `access-token` header, but no separate
  WebSocket-specific token/credential type is documented anywhere,
  making this the only reasonable reading — marked Medium confidence,
  not High, since it is inferred rather than stated in those exact
  words.
- **Expired-token behavior:** not explicitly documented as a specific
  HTTP status/error code on the pages fetched this checkpoint (this
  project's own Checkpoint 22/23 testing independently found Dhan
  returns HTTP 401/403 for a rejected credential on the REST profile/
  quote endpoints — consistent, not contradicted, by anything found
  here).

**Compared against this project's own existing credential
architecture** (`infrastructure/persistence/encryption.py`,
`docs/architecture/PROVIDER_CONNECTIVITY_ARCHITECTURE.md`, Checkpoint
22): encrypted-at-rest storage, never logged, never returned by any
API response — the 24-hour expiry finding means a future WebSocket/
historical-data implementation would need a **token-refresh or
re-prompt mechanism** distinct from anything built so far (every
prior checkpoint's Dhan interaction has been a single, short-lived
REST call, never a long-lived connection that could outlive a 24-hour
token). This is a genuine new architectural requirement any future
implementation checkpoint must account for — not addressed by any
existing code.

No real credential was used, requested, or exposed during this
research. All investigation was against Dhan's public documentation
pages only.

---

## WebSocket vs. Historical OHLC vs. Hybrid Comparison

| Dimension | Option A: WebSocket | Option B: Historical/Intraday OHLC | Option C: Hybrid |
|---|---|---|---|
| Accuracy (vs. true market activity) | High — every tick observed | Unconfirmed — candle authority not verified | High, once B's authority is confirmed |
| Latency | Real-time (event-driven) | Poll-driven, not designed for live forming-candle use | Real-time for forming candle, authoritative for closed |
| Completeness | Complete while connected; gaps during disconnects | Complete for whatever range is requested, but same-day availability unconfirmed | Best of both, if B can backfill A's gaps |
| Reliability | Depends on connection stability; no documented gap-detection | High for already-elapsed history | Depends on both |
| Complexity | Moderate-high (binary protocol, persistent connection, reconnect logic) | Low (simple POST request/response) | Highest (both, plus reconciliation logic) |
| Reconnection behavior | Documented heartbeat/timeout; no documented sequence numbers for gap detection | N/A (stateless requests) | B is A's own gap-recovery mechanism |
| Historical backfill | Not designed for this | Yes, this is its purpose | Yes, via B |
| Current/forming candle support | Yes — this is its core strength | Unconfirmed, likely no | Yes, via A |
| Closed candle authority | Only as good as the application's own aggregation | Unconfirmed whether exchange-authoritative | Best available, once confirmed |
| Volume correctness | High, if cumulative-volume delta is computed continuously (no gaps) | Presumed correct per-candle, unconfirmed as exchange-sourced | Best available |
| Storage requirements | Higher (persist every tick, or at minimum every bar) | Lower (candles already pre-aggregated) | Highest |
| Operational complexity | Requires a persistent process (this app has none yet - see below) | None beyond normal request/response | Highest - needs both |
| Testing complexity | High (binary protocol, connection lifecycle, timing) | Low (deterministic request/response, easy to mock) | Highest |
| Scalability (per Dhan's own limits) | 5,000 instruments/connection - generous | 90-day/request cap, otherwise generous | Generous |
| Suitability for SMA/EMA/ATR | High, once implemented correctly | Adequate if candle authority is confirmed | High |
| Suitability for breakout logic | High (true HIGH/LOW, no sampling gaps) | Adequate if candle authority is confirmed | High |
| Suitability for backtest parity | Requires care - live ticks vs. historical candles must use identical aggregation rules | Naturally consistent if the SAME endpoint serves both backtest and live gap-fill | Requires the SAME care as A for the WebSocket portion |

### A critical, project-specific complexity note

This project's own architecture (`docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md`,
Checkpoint 23) explicitly chose REST polling over WebSocket **because
this Django/WSGI application has no already-running persistent process
to host a WebSocket client** (no Celery worker/beat schedule, an
unused ASGI stub). That architectural fact has not changed. Any
WebSocket-based option (A or C) requires solving that infrastructure
gap first — this is not a new finding from Dhan's documentation, it is
a reminder that the comparison above is about Dhan's *capabilities*,
not about what this application can safely host today without
additional infrastructure work.

---

## Hybrid Architecture Analysis

**Conceptual shape:**
```
Dhan WebSocket (tick stream)
    ↓
Real-time forming-candle construction (this project's own aggregation logic,
    extended from domain/market_data/aggregation.py's existing Checkpoint 24A design)
    ↓
Displayed as FORMING (unchanged concept from Checkpoint 24A)

Dhan historical/intraday OHLC (POST /v2/charts/intraday)
    ↓
Periodic reconciliation pass
    ↓
Replaces/confirms CLOSED bars once each interval has fully elapsed,
    and backfills any interval the WebSocket connection missed
```

This is technically possible based on the documentation gathered — both
data sources use the same `(ExchangeSegment, SecurityId)` instrument
identity, and this project's existing `AggregatedBar`/`BarStatus`
(FORMING/CLOSED) model already has the right shape to receive an
authoritative revision of a CLOSED bar, since Checkpoint 24A's own
design already treats bars as an upserted, recomputable projection
(Decision 112-114), not an append-only, immutable log.

**Why hybrid over either option alone:**
- WebSocket alone has no documented gap-recovery mechanism for
  disconnects — the historical endpoint is the natural fill for that
  gap, *if* it is confirmed to return same-day intraday data (§ open
  question).
- Historical OHLC alone cannot serve a live "what is the price doing
  right now" observation need (Checkpoint 23's own original purpose)
  — it is fundamentally a look-back mechanism, not a live feed.

---

## Trading-Grade Bar — Proposed Acceptance Definition

Not a rename of `SAMPLE_BAR` — a materially stricter, distinct
contract. Each requirement below is labeled by its source.

| Field/Property | Requirement | Source |
|---|---|---|
| OPEN | Must be the price of the first genuinely observed trade/tick within the interval, with zero gap between interval start and first observation | PROJECT DECISION, enabled by WebSocket's tick-by-tick delivery |
| HIGH | Must be the true maximum price of every trade within the interval — not a lower bound | PROJECT DECISION, enabled by WebSocket coverage |
| LOW | Must be the true minimum price of every trade within the interval — not an upper bound | PROJECT DECISION, enabled by WebSocket coverage |
| CLOSE | Must be the price of the last genuinely observed trade before the interval boundary, with zero gap between that trade and the boundary | PROJECT DECISION |
| VOLUME | Must be a computed delta between consecutive cumulative-volume readings taken with no observation gap in between, OR a directly-provided per-candle volume figure independently confirmed as exchange-sourced | PROJECT DECISION, contingent on Volume Findings above |
| Timestamp | Must use a timezone empirically confirmed against Dhan's actual behavior, not merely assumed | PROJECT DECISION, per Timestamp Findings' explicit gap |
| Interval | Fixed, deterministic boundaries (this project's existing epoch-anchored flooring, `domain/market_data/aggregation.py`) | Existing project design, unchanged |
| Completeness | Zero unexplained gaps within the interval — any disconnect must be either fully backfilled from the historical endpoint or the bar must be explicitly flagged incomplete, never silently presented as complete | PROJECT DECISION |
| Gap detection | Every missing interval reported, never fabricated (existing `MissingInterval` mechanism, Checkpoint 24A) | Existing project design, unchanged |
| Ordering | Ticks must be processed in true trade-time order; the existing tie-break-by-arrival-order rule (Checkpoint 24A) remains the fallback only for the rare true-simultaneous-timestamp case, not for out-of-order delivery in general | PROJECT DECISION |
| Duplicate handling | A duplicate tick (same trade reported twice) must not double-count into OHLC or volume | PROJECT DECISION - not yet designed; WebSocket documentation does not confirm duplicates cannot occur |
| Correction/revision handling | A CLOSED bar may be revised only by the authoritative historical-endpoint reconciliation pass, never by a late WebSocket tick alone (once the WebSocket's own interval has genuinely elapsed) | PROJECT DECISION, extends Checkpoint 24A's existing upsert-revision model |
| FORMING vs. CLOSED | Unchanged concept from Checkpoint 24A - a bar is FORMING until its interval has elapsed AND (for trading-grade status specifically) the historical-endpoint reconciliation has confirmed it, whichever is later | PROJECT DECISION, new refinement for trading-grade only |
| Session boundaries | Unchanged from Checkpoint 23's `domain/session/calendar.py`, pending the same holiday-calendar limitation already documented there | Existing project design, unchanged |

**Example judgment calls, answered explicitly (per the checkpoint's
own request):**

- *One tick was missed:* bar is NOT trading-grade for that interval
  unless the historical-endpoint reconciliation successfully backfills
  it — PROJECT DECISION.
- *One quote was delayed (arrived late but before interval close):*
  acceptable — it is still a real observation within the interval,
  handled by the existing sort-before-aggregate design (Checkpoint
  24A) — PROJECT DECISION, no change needed.
- *Network connectivity was interrupted:* the affected interval(s) are
  not trading-grade until reconciled via the historical endpoint —
  PROJECT DECISION.
- *The WebSocket reconnects:* any interval spanning the disconnect
  must be reconciled before being trusted as trading-grade — PROJECT
  DECISION.
- *A historical candle conflicts with locally-aggregated WebSocket
  data:* the historical candle wins (it is the designated authority in
  this hybrid design) and the local bar is revised — PROJECT DECISION,
  contingent on the historical endpoint's own authority being
  confirmed (§ open question) - if that confirmation fails, this rule
  itself would need to be revisited.

---

## Failure / Recovery Analysis

Worked conceptual example, per the checkpoint's own scenario:

```
09:15-09:30   WebSocket active, ticks flowing normally
09:31         Network failure - WebSocket disconnects
09:31-09:35   WebSocket disconnected (4 intervals affected: 09:31-09:35)
09:36         Reconnect succeeds, subscriptions re-established
```

**Recovery, conceptually (not implemented):**

1. On reconnect, the application knows exactly which intervals
   (09:31-09:35) had no WebSocket coverage - `domain/market_data/
   aggregation.py`'s existing `MissingInterval` mechanism already
   detects this shape of gap today (with REST point samples; the same
   detection logic applies unchanged to a tick gap).
2. Those intervals are explicitly marked incomplete/not-trading-grade
   (never silently presented as normal CLOSED bars) - PROJECT
   DECISION, extending the existing gap-reporting discipline.
3. A backfill request against `POST /v2/charts/intraday` for that
   exact time range would need to succeed and return same-day data for
   this recovery to work at all - **this is precisely the unconfirmed
   fact from § Historical/Intraday OHLC Findings**. If Dhan's endpoint
   does NOT return same-day intraday data, this recovery step is not
   possible via this endpoint, and the gap simply remains permanent and
   explicitly flagged - the honest, "reject rather than fabricate"
   outcome this project has followed since Checkpoint 14.
4. The FORMING candle active at the moment of disconnect (if any) is
   discarded and rebuilt fresh once ticks resume, not silently
   continued with a hole in the middle - PROJECT DECISION.
5. Duplicate bars: prevented by the existing upsert-by-`(instrument,
   timeframe, interval_start)` identity (Checkpoint 24A, unchanged).

**Explicit conclusion:** whether this recovery strategy actually works
end-to-end is **contingent on the same unconfirmed fact** raised
throughout this document. This is not evaded — it is the central
reason this checkpoint recommends a verification step before
Checkpoint 26 implements anything.

---

## Backtesting Parity Analysis

This project's research/backtesting bounded context does not yet
consume live market data at all (confirmed by re-inspecting
`research/` and `signal_intelligence/signal_generation` - both remain
unwired from anything built at Checkpoints 23-24A, per those
checkpoints' own architecture tests). Backtesting parity is therefore
a **forward-looking design constraint**, not a currently-violated
property.

**The core risk, stated precisely:** if a future backtest consumes
candles from `POST /v2/charts/historical`/`intraday` (Dhan's own
retrospective aggregation) while live signal generation consumes
candles built from the WebSocket tick stream (this project's own
aggregation), and the two aggregation methods produce even slightly
different OHLC values for the same nominal interval (e.g. due to a
timestamp-boundary rounding difference, or Dhan's own historical
endpoint using a different tie-break rule than this project's
documented arrival-order rule), a strategy tuned against one candle
definition could behave differently when it encounters the other.

**Mitigation implied by the hybrid design already proposed above:**
using the SAME historical/intraday endpoint as both (a) backtesting's
data source and (b) live trading's gap-reconciliation authority
naturally converges the two toward the same candle definition for
every CLOSED bar - the live FORMING candle (WebSocket-only, not yet
reconciled) is the only piece that could differ, and it is explicitly
never presented as trading-grade until reconciled (§ Trading-Grade Bar
Definition above). This is a promising alignment, but it is a design
implication of the hybrid architecture, not yet a proven, tested
property - proving it would require an actual implementation and
side-by-side comparison, out of scope for this research checkpoint.

---

## Open Questions

Every fact in this document marked **UNCONFIRMED** or **Medium/Low
confidence**, collected here as the literal next-step verification
list:

1. Does `POST /v2/charts/intraday` return today's already-elapsed
   intraday candles in real time, or only prior trading days?
2. Are `/v2/charts/historical`/`intraday` candles exchange-generated
   (authoritative) or computed by Dhan from its own captured data?
3. What exact timezone applies to the `fromDate`/`toDate` request
   parameters and the returned `timestamp` fields on both the
   historical/intraday endpoints and the WebSocket ticker/quote
   payloads?
4. Is the WebSocket's `token` query parameter genuinely the same
   value as the REST `access-token` header, or a distinct credential
   type?
5. Does Dhan provide any sequence-numbering or gap-detection mechanism
   on the WebSocket feed to distinguish "no trades happened" from "a
   tick was dropped"?
6. Which documented rate-limit category (`Data APIs` vs. a more
   specific one) precisely governs `/v2/charts/historical` and
   `/v2/charts/intraday`?
7. Are historical/intraday candles corporate-action-adjusted or raw?
8. What is the WebSocket's exact behavior at token expiry (24 hours)
   mid-connection - does Dhan disconnect proactively, or does the
   connection silently stop receiving valid data?

---

## Evidence Table

| Question | Finding | Official Source | Confidence |
|---|---|---|---|
| WebSocket available? | Yes | `dhanhq.co/docs/v2/live-market-feed/` | High |
| Historical intraday OHLC? | Yes | `dhanhq.co/docs/v2/historical-data/` | High |
| 1-minute candles? | Yes, one of 5 documented intervals (1/5/15/25/60 min) | `dhanhq.co/docs/v2/historical-data/` | High |
| Volume available? | Yes, in both WebSocket Quote/Full packets and historical candles; per-tick vs. cumulative semantics not explicitly stated | `dhanhq.co/docs/v2/live-market-feed/`, `dhanhq.co/docs/v2/historical-data/` | Medium |
| Exchange timestamps? | EPOCH format confirmed; timezone not stated in words | `dhanhq.co/docs/v2/live-market-feed/`, `dhanhq.co/docs/v2/historical-data/` | Medium |
| Security ID mapping? | Yes, `(ExchangeSegment, SecurityId)`, matches this project's existing implementation | `dhanhq.co/docs/v2/instruments/` | High |
| Rate limits? | Table found (Order/Data/Quote/Non-Trading APIs); exact endpoint-to-category mapping partly inferred | `dhanhq.co/docs/v2/` | Medium |
| Reconnection support? | Heartbeat/timeout documented; no documented gap-detection/sequence numbers | `dhanhq.co/docs/v2/live-market-feed/` | Medium |
| Today's intraday candle via REST? | Not confirmed either way | `dhanhq.co/docs/v2/historical-data/` | Low |
| Candles exchange-authoritative vs. Dhan-computed? | Not confirmed either way | `dhanhq.co/docs/v2/historical-data/` | Low |
| WebSocket token = REST access-token? | Strongly implied, not explicitly stated | `dhanhq.co/docs/v2/live-market-feed/`, `dhanhq.co/docs/v2/authentication/` | Medium |

No item above is marked High confidence merely because it "sounds
right" - every High-confidence row is a direct, explicit statement on
Dhan's own documentation page.

---

## Decision Matrix

| Capability | WebSocket | Historical OHLC | Hybrid |
|---|---|---|---|
| Real-time | YES | NO | YES |
| Closed candle authority | PARTIAL (application's own aggregation only) | UNKNOWN (authority unconfirmed) | PARTIAL, pending confirmation |
| Forming candle | YES | NO | YES |
| Historical backfill | NO | YES | YES |
| Gap recovery | NO (no documented mechanism) | YES, if same-day availability confirmed | YES, if same-day availability confirmed |
| Volume | PARTIAL (delta computation, needs continuous coverage) | UNKNOWN (authority unconfirmed) | PARTIAL, pending confirmation |
| Latency | YES (low) | NO (poll-driven, not designed for this) | YES for forming candle |
| Reliability | PARTIAL (no documented gap-detection) | YES for already-elapsed history | PARTIAL, better than either alone |
| Complexity | Higher | Lower | Highest |
| Backtest parity | PARTIAL (needs identical aggregation rules) | YES (single source for backtest) | PARTIAL, converges toward YES for closed bars |
| Scalability | YES (Dhan limits are generous) | YES (90-day/request, otherwise generous) | YES |
| Trading-grade suitability | PARTIAL alone (no gap recovery) | PARTIAL alone (no live coverage, authority unconfirmed) | YES, once the open questions are resolved |

---

## Final Architectural Recommendation

**Target architecture: Hybrid (WebSocket for real-time forming-candle
construction + historical/intraday OHLC for authoritative closed-candle
reconciliation and gap backfill).**

This is the only option of the three that can plausibly satisfy the
Trading-Grade Bar definition proposed above - WebSocket alone has no
documented recovery from a disconnect, and historical OHLC alone
cannot serve live observation or forming-candle needs at all.

**However, per this checkpoint's own explicit instruction ("if Dhan
documentation is insufficient to make the decision safely, explicitly
recommend another verification step") - implementation should NOT
begin immediately.** Three genuinely unconfirmed facts (same-day
intraday availability, candle authority, and exact timezone) are each
load-bearing for the hybrid design's core safety claim (that
reconciliation against the historical endpoint is trustworthy).
Building the reconciliation mechanism before confirming its authority
is trustworthy would repeat exactly the mistake this project has
avoided at every prior checkpoint: building on an assumption instead
of a verified fact.

## SAMPLE_BAR Gate

**Can SAMPLE_BAR be promoted to TRADING_GRADE_BAR?**

**CONDITIONAL.**

Exact conditions, all required:

1. Directly verify (via a real, read-only API call - not further
   documentation reading) whether `POST /v2/charts/intraday` returns
   today's already-elapsed candles in real time.
2. Directly verify the exact timezone convention for both the
   WebSocket tick timestamps and the historical/intraday endpoint's
   date parameters and returned timestamps.
3. Obtain reasonable confidence (from Dhan support, more detailed
   documentation, or empirical cross-checking against a known reliable
   third-party price source) that historical/intraday candles reflect
   genuine exchange activity, not merely Dhan's own possibly-imperfect
   aggregation.
4. Implement WebSocket-based continuous tick ingestion (requires first
   solving this application's own persistent-process hosting gap,
   unchanged from Checkpoint 23's own finding).
5. Implement gap detection and historical-endpoint-based reconciliation
   for any interval affected by a disconnect.
6. Validate the resulting OHLCV against an independent, trusted price
   source for at least one full trading session before promoting the
   classification.

**Until all six conditions are met, `SignalGenerationService` and
`FeatureEngineService` remain unwired from live market data** -
unchanged from Checkpoint 24A's own conclusion, now with a concrete,
evidence-based checklist rather than an open-ended deferral.

## Checkpoint 31 update — conditions 1 and 2 verified live

A genuine, one-shot, read-only `POST /v2/charts/intraday` call
(HDFCBANK, 2026-08-14, using the project owner's already-configured
credential, never printed/logged) resolved two of this document's Open
Questions directly against Dhan's real API, not further documentation
reading:

- **Open Question #1** (same-day intraday availability): **VERIFIED**
  — 360 real, same-day 1-minute candles were returned.
- **Open Question #3** (exact timezone): **VERIFIED** — the first
  candle's epoch (`1786679100.0`), read as standard UTC epoch, equals
  exactly `2026-08-14 09:15:00 IST` (this project's own documented
  market-open instant). Dhan's intraday-endpoint epoch is genuine UTC.
- **Open Question #2** (exchange-authoritative vs. Dhan-computed):
  still not resolved by documentation; one independent cross-check
  (Google Finance) showed an exact price match, partial corroboration
  only.
- A previously-unknown gap was observed and disclosed, not explained
  away: the returned candles stopped at 15:14-15:15 IST, ~15 minutes
  short of the documented 15:30 close.

See `docs/research/TRADING_GRADE_BAR_VALIDATION.md` for the full
evidence and the SAMPLE_BAR gate's updated status (2 of 6 conditions
now met; WebSocket ingestion remains blocked by the unchanged
persistent-process infrastructure gap - Docker remains permanently
deferred per this project's invariant rules).

---

## Checkpoint 64.12 Addendum: Token Lifecycle Research Classification

Re-reviewed this document's own "Authentication Findings" section
(above) against Checkpoint 64.12's explicit research questions, using
ONLY what was already gathered from official Dhan documentation pages
(no new fetch was performed this checkpoint - the existing findings
above remain the authoritative source, re-classified here rather than
re-researched from scratch):

| Question | Finding | Classification |
|---|---|---|
| Does Dhan support token renewal? | Yes - a documented Renew Token API exists. | CONFIRMED (official docs, cited above) |
| Is the access token automatically/silently renewable? | No - the Renew Token API only extends an ALREADY-ACTIVE token; an expired token is explicitly documented to return an error if renewal is attempted. | CONFIRMED (official docs, cited above) |
| What credentials are required for a fresh token? | A separate Generate Token flow, requiring TOTP (time-based one-time password), can mint a fresh token without web-portal access. | CONFIRMED (official docs, cited above) |
| What is the expected expiry behavior? | Access tokens are valid for 24 hours from issuance. | CONFIRMED (official docs, cited above) |
| Does this application need a human-generated new token when EXPIRED? | Yes - per the above, an expired token cannot be renewed via the Renew Token API; only a human-driven Generate Token flow (TOTP) or web-portal re-authentication can produce a usable token once EXPIRED. | CONFIRMED (derived directly from the two facts above, not independently stated by Dhan in those exact words) |
| Is there a safe way to detect expiry before making an API call? | Yes - the JWT's own `exp` claim can be decoded locally with no network call (`token_lifecycle.evaluate_dhan_token_lifecycle()`, Checkpoint 64 Part 1, reused unmodified this checkpoint). | CONFIRMED (this project's own implementation, verified by direct code reading and passing tests) |
| Is there an official Dhan-recommended reconnect/backoff strategy for the WebSocket feed? | Not found in the pages fetched for this project's existing research (see "Authentication Findings" above - no such recommendation is quoted or cited). | UNCONFIRMED |
| Are there official session restrictions (e.g. one connection per account) relevant to this project? | WebSocket connection limits are documented: 5 connections/user, 5,000 instruments/connection, 100 instruments/subscription message (cited above, High confidence). | CONFIRMED (official docs, cited above) |

**Design conclusion (unchanged from the existing implementation,
re-confirmed this checkpoint): automatic silent refresh is NOT
implemented, and NOT implementable for an already-expired token per
Dhan's own documented behavior.** The system is correctly designed
around human renewal + local readiness validation
(`live_paper_readiness.py`, Checkpoint 64.12) - no refresh mechanism
was invented or silently introduced this checkpoint.

---

## Checkpoint 64.71 — WebSocket Timestamp Normalization, Quote-Packet Subscription, Graceful Shutdown

Offline implementation checkpoint. **No live Dhan connection was made.**
It implements the fixes for the two defects Checkpoint 64.70's real
~9.5-minute observe-only session exposed, plus the shutdown gap that
session ran into.

### 1. The 64.70 evidence

64.70 collected **2,154 real WebSocket Ticker observations** across
HDFCBANK / INFY / RELIANCE / TCS, persisted as `LiveQuoteObservation`
rows 72-2225. Re-measured read-only this checkpoint:

| Metric | `source_timestamp - fetched_at` |
|---|---|
| mean | **+19,799.250 s** |
| median | +19,799.26 s |
| stdev | 0.385 s |
| min | +19,797.271 s |
| max | +19,799.990 s |
| samples | 2,154 (100% of the session) |

19,800 s is **exactly 5h30m**, the IST (Asia/Kolkata, UTC+05:30)
offset. The spread is sub-second-to-2.7s - ordinary tick latency plus
the LTT field's own 1-second wire resolution. This is a **systematic
labelling error, not clock drift**.

### 2. The timestamp problem

Dhan's live-feed WebSocket LTT field is documented only as "Last Trade
Time (EPOCH)". Empirically, that integer counts seconds from the Unix
epoch **as if IST wall-clock time were UTC**. Decoding it with
`datetime.fromtimestamp(ltt_epoch, tz=UTC)` therefore produced an
instant 5h30m in the *future*.

`domain/market_data/aggregation.py` correctly rejects any observation
with `quote.timestamp > as_of`. Because 100% of live quotes were
future-dated, **100% were rejected and ZERO bars formed** across the
entire live session.

### 3. The normalization, and its exact conversion point

One canonical function:

- `infrastructure/market_data_providers/dhan/timestamp_normalization.py`
  provides `normalize_dhan_websocket_timestamp(ltt_epoch)`, plus the
  single `IST_UTC_OFFSET` constant.
- Applied at exactly two call sites, both in
  `dhan/packet_decoder.py` - the Ticker (code 2) and Quote (code 4)
  `last_trade_time` construction, replacing
  `datetime.fromtimestamp(ltt_epoch, tz=UTC)`.

The conversion is `timestamp_utc = fromtimestamp(epoch, tz=UTC) - 5h30m`.
A regression test asserts the literal `hours=5, minutes=30` appears
**nowhere else under `src/`**.

**Why generic aggregation was NOT modified:** the `quote.timestamp >
as_of` guard is a genuine safety property - it is what stops
future-dated data from corrupting bars, and it behaved exactly as
designed. Widening its tolerance to ~5h30m would have disabled that
protection for *every* provider in order to work around one provider's
labelling quirk. The correction belongs at the provider boundary,
before the value ever enters the canonical domain. The guard is
unchanged, and a test asserts that an *uncorrected* Dhan timestamp is
still rejected as future.

**Scope:** Dhan WebSocket LTT only. Dhan REST, historical/candle data,
Backtest, synthetic providers, other providers, and already-stored DB
rows are untouched. The `Quote`/`Bar`/`AggregatedBar` timestamp
contracts are unchanged - they still receive a timezone-aware UTC
`datetime`, just a correct one.

### 4. Before/after evidence (all 2,154 samples)

| | Before | After |
|---|---|---|
| mean delta vs receipt | +19,799.250 s | -0.750 s |
| range | +19,797.27 to +19,799.99 s | -2.73 to -0.01 s |
| future-dated observations | 2,154 / 2,154 (100%) | **0 / 2,154 (0%)** |

Every corrected observation now lands slightly *before* its receipt
instant, which is the physically correct ordering (a trade is always
observed after it happens). The sanitized corpus is frozen in
`tests/unit/research/checkpoint_64_70_timestamp_fixtures.py` (symbol
plus two timestamps only, no prices or credentials). **The original DB
rows were read only and not modified.**

### 5. Quote packets - root cause of the "Ticker only" finding

64.70 received only Ticker (code 2) packets and never Quote (code 4).
The cause is fully explained, and it was in this project's own code.

`RequestCode: 15` had been hard-coded as though it were a generic
"subscribe" code. It is not. Dhan's Annexure feed-request-code enum
(`https://dhanhq.co/docs/v2/annexure/#feed-request-code`, re-verified
this checkpoint) maps each code to a specific **data mode**:

| Code | Meaning |
|---|---|
| 11 / 12 | Connect / Disconnect feed |
| **15 / 16** | **Subscribe / Unsubscribe - Ticker packet** |
| **17 / 18** | **Subscribe / Unsubscribe - Quote packet** |
| 21 / 22 | Subscribe / Unsubscribe - Full packet |
| 23 / 24 | Subscribe / Unsubscribe - Full market depth |

**Dhan does not choose the packet type server-side - the client selects
it per subscription message.** The worker only ever received Ticker
packets because it only ever asked for Ticker. Nothing was wrong with
the decoder, the transport, or Dhan.

**Change made:** `run_market_data_worker.py`'s default subscribe code
is now `17` (Quote). Quote is a strict superset of Ticker (same LTP and
LTT, plus volume / ATP / day OHLC), so nothing that worked before stops
working. The Ticker code remains available to an explicit caller as a
documented fallback.

### 6. Volume path

The Ticker packet has **no volume field at all** in its documented
12-byte layout, so subscribing to Ticker made real cumulative volume
*structurally* unobtainable - no amount of downstream work could have
recovered it, and none was fabricated.

The Quote packet carries the documented cumulative day `volume` field,
which `packet_to_quote.py` has mapped into `Quote.cumulative_volume`
since Checkpoint 64.64. That path is **unchanged** by this checkpoint;
the subscription change simply makes it reachable for the first time.

**Honest limitation:** real volume is now *technically* obtainable, but
it has **not** been observed against live data. Volume validation
remains an open gap until a live session actually receives real Quote
packets.

### 7. Graceful shutdown

64.70 required `taskkill /T /F`: `run_worker_against_websocket()` had
no `stop_event`, and the reconnect supervisor checked one only *after*
a disconnect. A hard kill gives the worker no chance to close the
socket, flush pending quotes, or record a final status.

Implemented:

- `run_worker_against_websocket()` now accepts an optional
  `stop_event`, reaching parity with `run_worker_against_stream()`
  (which has had one since Checkpoint 57).
- A stop cannot be polled "between packets" - `receive_packets()`
  awaits the *next* message, which on a quiet feed may never arrive. A
  small watcher task awaits the event and **closes the transport**,
  ending the iteration promptly and sending a proper RFC 6455 close
  frame. The watcher is cancelled *and awaited* in `finally`, so no
  orphan task survives.
- A close caused by our own stop is recorded as a clean `STOPPED`,
  never as a reconnect-relevant disconnect.
- `run_worker_with_reconnect()` now also checks the stop event
  **before** opening a connection, so a stop requested during backoff
  cannot be followed by one more reconnect attempt.
- `WorkerHealthTracker.mark_stopped()` (new) records a clean stop and
  clears `consecutive_failures` - a deliberate stop is not a failure.
  The worker persists `WorkerRuntimeStatus` = `STOPPED` on shutdown
  instead of leaving a stale `RUNNING`.
- `_install_stop_signal_handlers()` wires SIGINT/SIGTERM to the event.
  **Cross-platform note:** this project runs on Windows, where
  asyncio's `loop.add_signal_handler()` is unimplemented and SIGTERM is
  not deliverable; the loop-native path is tried first and
  `signal.signal()` is the documented fallback. Installation is
  best-effort and never prevents the worker from starting.

**Reconnect behavior is preserved:** a real disconnect with no stop
request still reconnects with bounded backoff, proven by dedicated
tests.

### 8. What this checkpoint does NOT claim

- No live Dhan session was run; the correction is validated **offline
  only**, against synthetic packets and the frozen 64.70 corpus.
- No live bar has been observed forming from real Dhan data.
- Real Quote packets have never been received from Dhan.
- Research Readiness is unchanged - it still requires the existing
  5-criterion gate in `BACKTESTING_ARCHITECTURE.md`, including real
  live-market TRADING_GRADE_BAR data.

Live validation of all of the above is REAL NSE SESSION #3's job.

---

## Checkpoint 64.76 â€” Stock-Options / Option-Chain / OI / IV / Greeks Capability Verification

Research-only. **No live Dhan connection. No options schema created.**
This section deliberately extends the "Research Scope" note above, which
had explicitly excluded Dhan's option-chain API from investigation.

### Sources fetched this checkpoint (official Dhan documentation only)

| Page | URL |
|---|---|
| Option Chain | `https://dhanhq.co/docs/v2/option-chain/` |
| Annexure (enums) | `https://dhanhq.co/docs/v2/annexure/` |
| Live Market Feed | `https://dhanhq.co/docs/v2/live-market-feed/` |
| Historical Data | `https://dhanhq.co/docs/v2/historical-data/` |
| Instrument List | `https://dhanhq.co/docs/v2/instruments/` |

No blog, forum, third-party SDK, or GitHub repository was used.

### Capability register

| CAPABILITY | Endpoint / feed | Format | Snapshot/Streaming | Live/Historical | Source | Status |
|---|---|---|---|---|---|---|
| Option chain (all strikes, CE+PE) | `POST /optionchain` | JSON `data.oc.{strike}.{ce,pe}` | SNAPSHOT | LIVE only | option-chain | VERIFIED |
| Expiry list | `POST /optionchain/expirylist` | JSON | SNAPSHOT | LIVE | option-chain | VERIFIED |
| LTP (option premium) | chain `last_price`; WS Ticker/Quote | JSON / binary | both | both | option-chain, live-market-feed | VERIFIED |
| Bid / ask + quantities | chain `top_bid_price`/`top_ask_price`/`top_bid_quantity`/`top_ask_quantity`; WS Full (code 8, 5-level depth) | JSON / binary | both | LIVE only | option-chain, live-market-feed | VERIFIED |
| Volume | chain `volume`, `previous_volume`; WS Quote; historical candles | JSON / binary | both | both | all three | VERIFIED |
| Open interest | chain `oi`; WS **OI packet code 5**; historical `oi=true` -> `open_interest` | int32 | both | both | annexure, live-market-feed, historical-data | VERIFIED |
| OI change | **NOT a published field** | â€” | â€” | â€” | option-chain | VERIFIED ABSENT |
| Implied volatility | chain `implied_volatility` | float | SNAPSHOT | **LIVE ONLY** | option-chain | VERIFIED |
| Greeks delta/gamma/theta/vega | chain `greeks.{delta,gamma,theta,vega}` | float | SNAPSHOT | **LIVE ONLY** | option-chain | VERIFIED |
| Greek rho | **NOT published** | â€” | â€” | â€” | option-chain | VERIFIED ABSENT |
| Underlying LTP | chain root `data.last_price` | float | SNAPSHOT | LIVE | option-chain | VERIFIED |
| Instrument master (strike/expiry/CE-PE/underlying/lot) | scrip-master CSV | CSV | SNAPSHOT | REFERENCE | instruments | VERIFIED |
| Chain observation timestamp | **NOT published** | â€” | â€” | â€” | option-chain | VERIFIED ABSENT |

### Headline findings

1. **Dhan genuinely supplies OI, IV and four Greeks** â€” but *only* through
   the REST Option Chain snapshot, and *only* for the live moment. There
   is **no historical IV/Greeks endpoint of any kind**. Any IV or Greeks
   time series this project ever wants must be **self-archived, snapshot
   by snapshot, as the trading day happens**. This is the single most
   consequential finding of the checkpoint: IV/Greeks history is
   *unrecoverable after the fact*.
2. **The Option Chain API is rate-limited to one unique request every 3
   seconds** (VERIFIED, quoted from Dhan). This is a hard architectural
   constraint on any multi-underlying options scanner: N underlyings x M
   expiries costs 3*N*M seconds per full sweep. It is roughly 20x slower
   than the equity Quote API's 1/second.
3. **OI is available live via WebSocket** (feed response code 5, a 12-byte
   packet) and **historically via the charts endpoints** (`oi` request
   flag, `open_interest` response field). OI is therefore the one
   options-specific field with both a live and a historical path.
4. **OI change is never supplied.** Dhan gives `oi` and `previous_oi`
   (previous *day's* close). Intraday OI delta must be computed by this
   project against its own stored baseline â€” exactly the same discipline
   `aggregate_quotes_into_bars()` already applies to cumulative volume.
5. **The option chain carries no timestamp.** The consumer must stamp its
   own observation instant. Relevant directly to the "exact market state
   at a Gainz signal timestamp" requirement â€” the chain alone cannot
   answer it without project-side stamping.
6. **Stock options vs index options:** Dhan's documentation draws **no
   distinction whatsoever** in the option-chain, feed, or historical
   contracts. The Annexure lists `OPTSTK` and `OPTIDX` as sibling
   instrument types in the same `NSE_FNO` (code 2) segment, consumed by
   the same endpoints with the same fields. Whether Greeks/IV *coverage
   quality* is equivalent for less-liquid stock options is **UNVERIFIED**
   and cannot be established from documentation â€” it needs an empirical
   read-only check in a future live-market checkpoint.

### Architectural compatibility with the existing market-data domain

Read this checkpoint: `domain/market_data/contracts.py` (`Bar`, `Quote`),
`domain/market_data/archive.py`, `domain/shared_kernel/contracts.py`,
`dhan/packet_decoder.py`, `dhan/instruments.py`.

| Existing element | Fits options? | Why |
|---|---|---|
| `Quote` | PARTIAL | Premium/bid/ask/volume map cleanly. Has **no OI, IV, or Greeks field**. |
| `Bar` | MOSTLY | Option premium OHLCV is structurally identical. Positive-price validation holds for real traded premiums. Carries no OI. |
| `InstrumentId` (plain `str`) | PARTIAL | Can *hold* an option trading symbol, but has no structure for underlying/expiry/strike/CE-PE, so "all options for expiry X" is not an expressible query. |
| `Exchange` enum (`NSE`/`BSE` only) | **NO** | Cash-equity-only vocabulary. No `NSE_FNO` concept exists anywhere in the domain. |
| `NSE_EQ_SEGMENT` in `instruments.py` | **NO** | Live universe hard-pins `"NSE_EQ"`. |
| `packet_decoder.py` | **NO** (safely) | OI packet code 5 is classified `UNSUPPORTED_PACKET_TYPE` â€” correctly rejected, never misdecoded, but never captured either. |
| `MarketDataArchiveDay` | PARTIAL | Trading-date/completeness model generalises well; cell identity is `(symbol, timeframe, source)` with no expiry/strike dimension. |

**Recommended architectural decision (NOT implemented this checkpoint):
generalise, do not duplicate.** The bar/quote/archive/aggregation
machinery is instrument-agnostic in substance and should be reused. What
must be *added* is (a) a structured `OptionContract` reference identity
(underlying, expiry, strike, option_type, security_id, lot_size) sourced
from the scrip master, and (b) a separate observation type for the
fields `Quote` genuinely lacks (OI/IV/Greeks) rather than bolting five
optional nullable columns onto the equity contract every provider shares.
Forcing OI/IV/Greeks into `Quote` would put derivatives-only concepts
into the one contract backtest, paper and live all share for equities.

**Standing scope conflict, raised explicitly:** `Exchange`,
`instruments.py`, and several domain docstrings all cite "Rule 2: the
project's scope is permanently Indian cash equities only." The stated
intent that this platform is primarily for STOCK OPTIONS contradicts
that recorded invariant. **This is a product-scope decision for the
owner, not an engineering one, and it blocks the options data model.**

> **RESOLVED at Checkpoint 64.77.** Primary trading instrument = NSE
> stock options (OPTSTK); NSE cash equities retained as supporting/
> reference/underlying instruments; NSE index options, BSE options and
> BSE equities not enabled. See
> [PRODUCT_SCOPE.md](PRODUCT_SCOPE.md). The recommended "generalise,
> do not duplicate" decision above was adopted: 64.77 added the
> `OptionContract` reference identity and extended the existing Dhan
> instrument master; the OI/IV/Greeks observation layer remains
> deferred.

### Minimum historical retention contract (specification only)

To answer "all RELIANCE option data for date X" / "OI history" / "IV
history" / "market state at a Gainz signal timestamp":

| Object | Class | Must be archived because |
|---|---|---|
| `OptionContract` | REFERENCE-MASTER | Strike/expiry/CE-PE identity; scrip master is a *current-state* file with no history â€” expired contracts may vanish from it. Must be snapshotted daily. |
| `OptionChainSnapshot` | RAW | The ONLY way IV/Greeks/full-chain OI ever become historical. Unrecoverable if not captured live. |
| `OptionQuote` | RAW | Per-contract tick observations from the WebSocket. |
| `OIObservation` | RAW | Time-stamped OI readings (WS code 5). |
| `OptionBar` | AGGREGATED | Premium OHLCV; also re-derivable from the historical charts endpoint. |
| `OIChange` | DERIVED | Never store as raw â€” compute from the OI series against a declared baseline. |
| `IVObservation` / `GreeksObservation` | RAW (provider-supplied) | Despite "looking derived", these are **provider-supplied values**, not project computations, and must be stored as observations with provenance. |

### Open questions (UNVERIFIED â€” cannot be closed from documentation)

1. Does `POST /charts/intraday` serve **expired** option contracts, or
   only currently-listed ones? Decisive for whether option price/OI
   history is retrievable retroactively at all. Not stated by Dhan.
2. Are Greeks/IV populated for illiquid **stock** option strikes, or
   returned as zero/null?
3. Does the scrip master retain expired contracts?
4. What `instrument` value (`OPTSTK`) and `expiryCode` semantics do the
   charts endpoints require for options? Documented as parameters, but
   their option-specific usage is not spelled out.
5. Is the WebSocket 5,000-instrument-per-connection limit sufficient for
   a realistic stock-option universe? (A single underlying's full chain
   across 3 expiries is easily 200+ contracts.) Arithmetic is clear; the
   universe target is a product decision not yet made.


---

## Checkpoint 64.78 â€” Option Observation Layer + NSE_FNO Live-Subscription Foundation

64.77 built option IDENTITY (`domain/instrument/options.py`) and
deliberately deferred every OBSERVATION concept. 64.78 builds the
smallest clean observation layer on top of it, and **nothing more**.
The end-to-end path now exists, offline and tested:

```
OptionContract (64.77)
  -> NSE_FNO subscription (RequestCode 17, existing batching)
  -> Dhan Quote packet (code 4)  -> OptionQuote     -> OptionQuoteObservation
  -> Dhan OI packet    (code 5)  -> OIObservation   -> OpenInterestObservation
```

### The two observation contracts

`domain/market_data/option_observations.py` â€” provider-independent,
no Django, no Dhan.

| Contract | Carries | Deliberately absent |
|---|---|---|
| `OptionQuote` | canonical `OptionContract`, `provider`, `provider_security_id`, `timestamp` (provider instant), `last_price` (premium), day OHLC + `previous_close`, `cumulative_volume`, bid/ask + quantities, `data_source` | open interest, IV, Greeks |
| `OIObservation` | canonical `OptionContract`, `provider`, `provider_security_id`, `observed_at`, `open_interest`, `data_source` | OI change, premium, IV, Greeks |

**Why OI is not a field on `OptionQuote`.** Dhan does not deliver them
together: premium arrives in the Quote packet (code 4), open interest in
a separate OI packet (code 5). They have independent arrival instants
and either can arrive without the other. An `open_interest: int | None`
on `OptionQuote` would be `None` on *every* quote-sourced row, making
"this packet has no OI field" indistinguishable from "OI unknown". This
follows 64.76's own recommendation to add a separate observation type
rather than bolt nullable derivative-only columns onto a shared contract.

**Why `OIObservation.observed_at` is not called `timestamp`.** The OI
packet carries **no timestamp field** â€” its 12 bytes are header + int32.
The instant is necessarily our receipt clock, and the name says so
rather than implying a provider-supplied instant that does not exist.

**`fetched_at` is not on either contract**, matching the equity `Quote`:
our local receive clock is stamped at the single persistence write
boundary, because it is a fact about our ingestion, not about the market.

**OI change is never stored as raw data.** Dhan does not publish it
(64.76: VERIFIED ABSENT). It is derived later from this project's own
stored OI series against a declared baseline â€” the same discipline
`aggregate_quotes_into_bars()` already applies to cumulative volume.

### Dhan OI packet, feed response code 5

`packet_decoder.py` previously classified code 5 as
`UNSUPPORTED_PACKET_TYPE` (correctly refused, never captured). It now
decodes it into `DhanOpenInterestPacket`.

Wire layout (VERIFIED 64.76, unchanged): **12 bytes** = the shared
8-byte header + one little-endian **int32** open interest. Nothing else.
No timestamp, no price, no day high/low OI (those live only in the Full
packet, code 8, still unimplemented). No undocumented field is inferred.

Validation order is deliberate â€” shape, then addressability, then
segment â€” each with its own distinct, inspectable failure reason:

| Condition | Result |
|---|---|
| exactly 12 bytes, segment 2, security_id > 0 | `DhanOpenInterestPacket` |
| < 12 bytes | `TRUNCATED_BODY` |
| < 8 bytes | `TRUNCATED_HEADER` |
| **> 12 bytes** | `MALFORMED_LENGTH` (new) |
| `security_id <= 0` | `INVALID_SECURITY_ID` (new) |
| segment != NSE_FNO (2) | `UNSUPPORTED_SEGMENT` (new) |

`MALFORMED_LENGTH` applies to the OI packet **only**. The pre-existing
Ticker/Quote/Disconnect paths keep their historical `len(raw) >= size`
tolerance â€” this checkpoint does not retroactively tighten packet types
that have already run against a real feed.

**Signedness.** The field is a documented int32 and is decoded with the
signed `i` code, exactly as the Quote packet's volume already is, so
whatever Dhan sends is reproduced faithfully. Open interest is a
contract count and can never legitimately be negative; the decoder still
reports what the wire said (its job is faithful decoding) and the
**domain** boundary (`OIObservation`) rejects a negative rather than
archiving it. Zero is a legitimate reading â€” a listed strike with no
open positions â€” and is accepted.

**Response codes are not request codes.** These are two separate,
non-overlapping Dhan enumerations that happen to share small integers.
There is **no "subscribe to OI" request code 5**: OI arrives as a
response packet on an existing Quote subscription. Nothing in the
subscription layer may ever send a `5`.

### NSE_FNO subscription â€” what was actually missing

Almost nothing, and that is the point. `_build_subscribe_messages()`
(64.4) already emitted `{"ExchangeSegment": i.exchange_segment,
"SecurityId": ...}`, reading the segment **per instrument**. It was
never pinned to NSE_EQ â€” only the *universe* feeding it was, since
`instruments.py` is an equity symbol table whose dataclass merely
*defaults* the segment to `"NSE_EQ"`.

So the whole capability is `option_subscription.py::
option_subscription_instruments()`: produce the same `DhanInstrument`
rows carrying `"NSE_FNO"`, from the 64.77 option instrument master. No
parallel batching mechanism, no second transport, no new request-code
vocabulary. Batching, chunk determinism and the **unchanged** documented
100-instruments-per-message limit are therefore correct for options by
construction rather than by re-implementation.

Request codes are reused verbatim from 64.71's verified Annexure table:
**17 = Subscribe Quote**, **18 = Unsubscribe Quote**
(`_build_unsubscribe_messages()` delegates to the subscribe builder so
the batching rule cannot drift between the two).

**Index options remain structurally excluded.** `option_subscription_
instruments()` filters non-stock options unconditionally â€” the last gate
before bytes go on the wire â€” and the routing boundary rejects them
again on the way back in. "Index options are not enabled" is a
structural property, not a comment.

**The equity path is byte-for-byte unchanged.** `packet_to_quote.py` is
untouched. The one change to the equity workers is an explicit skip of
the newly-decodable OI packet (which a cash instrument can never
produce), *not* counted as a decode failure â€” the packet decoded
perfectly, it simply does not belong to that consumer.

### Routing and provider identity resolution

`packet_to_option_observation.py` is a **sibling** of
`packet_to_quote.py`, not a fork of it. The two differ in identity
resolution, not arithmetic: the equity mapper resolves
`security_id -> symbol -> InstrumentId`; the option mapper resolves
`security_id -> ProviderOptionIdentity -> OptionContract`.

**The hard rule: strike, expiry and CE/PE are never read out of a
packet.** A Dhan feed packet carries only `(segment, security_id)`; the
contract those address is looked up in the 64.77 instrument master via a
caller-supplied index. Every rejection is typed, never a free-text log
line, so a worker can count rejections by cause:
`UNRESOLVED_SECURITY_ID`, `INDEX_OPTION_NOT_IN_SCOPE`,
`NON_POSITIVE_PREMIUM`, `NEGATIVE_OPEN_INTEREST`, `INVALID_OBSERVATION`.
A contract identity is **never fabricated** â€” a fabricated identity
would file a real market print against the wrong strike, permanently
and undetectably.

Dhan's Quote packet wire format is identical for NSE_EQ and NSE_FNO, so
the decoder is reused verbatim; only identity resolution and the output
contract differ.

### Persistence

Two new tables, `OptionQuoteObservation` and `OpenInterestObservation`
(migration `0030_option_observations`, which only CREATEs â€” it touches
no existing table and rewrites no forensic-evidence row).

Both store the **canonical** contract identity (`contract_id` plus
exploded `underlying_symbol`/`expiry`/`strike`/`option_type`/`lot_size`,
so "all RELIANCE CE at expiry X" is an indexed query rather than a
string parse) **and** the provider identity (`provider`,
`provider_security_id`). Neither substitutes for the other:
`contract_id` is stable across instrument-master refreshes and
providers; the provider pair traces a row to the exact stream that
produced it. `lot_size` is stored on the observation because the scrip
master is a current-state file with no history â€” a historical row must
stay interpretable after a contract expires out of the master.

Options are **not** routed into `LiveQuoteObservation`. That table's
identity is a plain `instrument_symbol`; an option's identity is
(underlying, expiry, strike, CE/PE).

**Trading date** is the canonical 64.73 `trading_date_for()`, applied to
the provider's own instant (never `fetched_at`), stamped at the single
write boundary â€” the same derivation the equity archive uses. No second
trading-date function was created.

**Idempotency: neither table has a unique constraint**, exactly like
`LiveQuoteObservation`, and this is deliberate. Dhan's WebSocket
last-trade-time has **one-second** resolution and a liquid strike trades
many times within a second, so a unique constraint on
`(contract, timestamp)` â€” or any timestamp-containing tuple â€” would
silently **destroy real market events**. That is a far worse failure
than storing a duplicate, and it is the explicit lesson carried from
64.73's Phase 11. Append-only raw observations plus a recomputable
downstream projection is this project's established pattern.

### Archive compatibility (documented, NOT implemented)

**No option daily archive exists.** `MarketDataArchiveDay` was not
modified and was not made derivatives-specific â€” its cell identity
remains `(exchange, trading_date, symbol, timeframe, data_source)` with
no expiry/strike dimension.

What 64.78 guarantees is that a future option archive layer has the
identity it will need, present and indexed on every row: `trading_date`,
observation instant, `provider`, `provider_security_id`, canonical
contract identity (and its exploded components), and `data_source`.
Building that layer â€” an option-aware archive cell identity and a
completeness model for option series â€” is future work.

### Explicitly deferred at 64.78

`OptionChainSnapshot`, `IVObservation`, `GreeksObservation`,
`OptionBar`, and any option aggregation layer. IV and Greeks are
REST-option-chain-sourced and **LIVE-ONLY** provider values (64.76), so
capturing them needs a snapshot layer with its own rate-limit
architecture (one unique request per 3 seconds). None of it is built,
and no table for any of it exists.

**No live validation was performed.** Everything above is verified
offline against synthetic fixtures: synthetic security_ids in the
obviously-fake 9000000+ range, RELIANCE CE and PE, two strikes, two
expiries, plus an OPTIDX row for exclusion testing. **Real option
packets have never been received from Dhan.**
