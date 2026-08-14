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
