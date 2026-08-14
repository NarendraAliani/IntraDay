# Live Market Data Foundation

Checkpoint 23. Establishes the first live, real-market data path this
platform has ever had: read-only NSE cash-equity price observation.
Explicitly scoped to unlock Level 1 manual testing (live market-data
observation) from the readiness assessment performed after Checkpoint
22 — not signal generation (Checkpoint 24), not paper trading, and
categorically not any order/trading capability.

```
Dhan Live Data (read-only) → Market Data Layer → Market Data Health
        → Persistence / API → Frontend Observation

  NO SIGNALS · NO ORDERS · NO TRADING ENGINE · NO POSITION MANAGEMENT
```

## Scope boundary

What this checkpoint IS: a read-only live quote fetch (Dhan's Market
Quote REST API), session-hours awareness, freshness/health
classification, an append-only observation log, a read-only API, and an
observation-only frontend screen.

What this checkpoint is NOT: `trading_engine/*` remains untouched -
`order_management`, `execution_management`, `risk_engine`,
`session_management`, `strategy_execution` all remain empty Checkpoint-4
scaffolding, exactly as before. `signal_intelligence.signal_generation`
is deliberately never wired to this live feed (Checkpoint 23 §13) - it
still consumes only the synthetic fixture repository, unchanged.
`domain.broker`'s `BrokerGateway` Protocol (order placement, position
queries) is never imported anywhere on this checkpoint's live-data path
- mechanically proven, not just documented, by
`tests/unit/architecture/test_live_market_data_boundaries.py`.

## Why REST polling, not WebSocket

This Django/WSGI application has no already-running persistent process
a WebSocket client could safely live inside — `asgi.py` is an unused
Checkpoint-1 stub, and no Celery worker/beat schedule exists anywhere in
this repository yet. Building one now, purely to support this
checkpoint, would mean introducing brand-new long-lived-process
infrastructure under a checkpoint explicitly scoped to "the smallest
production-safe implementation" (Checkpoint 23 §6). A single-shot,
rate-limited, explicit-trigger REST call
(`infrastructure/market_data_providers/dhan/client.py`'s `fetch_quotes()`)
is the smaller, safer, more testable increment — and Dhan's own
documented rate limit (1000 instruments/request, 1 request/second)
comfortably accommodates this checkpoint's four-symbol universe. A
WebSocket-based live-tick adapter remains a natural, larger future
increment once a persistent process exists to host it.

## Why the Market Quote ("full quote") endpoint, not LTP

Dhan exposes three market-quote variants: `/marketfeed/ltp` (price
only), `/marketfeed/ohlc` (price + OHLC), and `/marketfeed/quote` (the
above plus `last_trade_time`). Only the full quote variant includes a
source timestamp — required by Checkpoint 23 §6's "preserve source
timestamps... distinguish market-data time from application processing
time." The narrower endpoints were considered and rejected specifically
for this reason.

## Instrument identity — configuration-driven, verified, not invented

`infrastructure/market_data_providers/dhan/instruments.py` maps a
small, `MARKET_DATA_OBSERVATION_SYMBOLS`-configured symbol list (default
`RELIANCE,TCS,INFY,HDFCBANK`) to Dhan's own `security_id` values.
These four security IDs were verified directly against Dhan's official,
published instrument/scrip-master CSV
(`https://images.dhan.co/api-data/api-scrip-master.csv`) during this
checkpoint (2026-08-14) — never guessed or carried over from another
broker's identifiers. A symbol with no verified entry raises
`UnknownObservationSymbolError` rather than silently guessing an ID. A
full scrip-master ingestion pipeline (to support an arbitrary, larger
universe) is explicitly deferred — unnecessary machinery for a
"small configured list."

## Market session awareness

`domain/session/calendar.py` is the first market-hours computation this
codebase implements — fixed NSE cash-equity hours (09:15–15:30 IST,
square-off deadline 15:20 IST), computed via `zoneinfo`'s
`Asia/Kolkata` zone (stdlib, `tzdata` added as an explicit dependency
for cross-platform correctness). Deliberately minimal, per Checkpoint
23 §8's "minimum... necessary": **no holiday calendar, no half-day
handling** — an explicit, documented limitation, not an oversight. A
date that is actually an exchange holiday still computes a PRE_OPEN/
OPEN/CLOSED session shape as if it were a normal trading day; callers
must not treat "a session was computed" as "the market is actually open
today." `session_for_instant()` correctly derives the IST calendar date
from a UTC instant (handling the ~5.5 hours/day where the UTC and IST
calendar dates differ), rather than naively calling `.date()` on a UTC
timestamp.

## Market-data health — Configured ≠ Connected ≠ Fresh

`control_plane/market_data_health` gives this checkpoint's health model
a third dimension beyond Checkpoint 22's Configured/Connected: **fresh**.
The classifier (`evaluator.py`) is a pure function of raw persisted
facts, with documented precedence:

1. Never attempted a fetch at all (no success, no failure recorded) →
   `DISCONNECTED`.
2. Most recent attempt was a failure → `AUTHENTICATION_FAILED` (error
   text names an auth/token problem) or `ERROR` (anything else).
3. Market is not currently open → `MARKET_CLOSED` — a fresh quote from
   a closed market is meaningfully different from a genuinely live one.
4. Otherwise: `CONNECTED_FRESH` or `CONNECTED_STALE`, purely a function
   of `FRESHNESS_THRESHOLD_SECONDS` (120s — a deliberately generous
   default suited to this checkpoint's explicit-trigger, not
   continuous-stream, design; see the constant's own docstring for the
   full rationale).

`reconnect_count`/`subscription_active` are always `0`/`False` this
checkpoint — REST polling has no reconnect/subscription concept of its
own; these fields exist in the contract for a future WebSocket adapter,
never fabricated as though that capability exists today.

"Not configured" (no Dhan credentials at all) is deliberately **not**
recorded as a failure — no attempt was made, so nothing failed;
`GET .../health/` in that case honestly reflects whatever the health
record already was (typically `DISCONNECTED`), mirroring Checkpoint
22's own "Configured ≠ Connected" honesty principle.

## Persistence and retention

`LiveQuoteObservation` (append-only — one row per instrument per
refresh, never overwritten) and `MarketDataHealthStatus` (singleton,
`get_or_create(pk=1)`, matching Checkpoint 22's credential-singleton
convention). Retention is explicitly **not** rotated or capped this
checkpoint: given the explicit-trigger, four-symbol, REST-polling
design (never a continuous multi-second stream), row growth is
inherently bounded by how often an operator manually clicks Refresh —
a documented, revisit-before-scaling limitation, not an unbounded tick
firehose.

## API — read/refresh/status separation

Mirrors Checkpoint 22's settings API pattern exactly:

- `GET .../session/`, `GET .../health/`, `GET .../quotes/` — read
  already-persisted/computed state, **never** perform a live fetch
  (mechanically proven by
  `test_reading_session_health_or_quotes_never_calls_dhan`).
- `POST .../refresh/` — performs exactly one live Dhan call, persists
  the result. Rate-limited (`ScopedRateThrottle`, 10/min) and debounced
  (5s), reusing Checkpoint 22's exact mechanism and cache backend.

RBAC is fully reused, no new capability token: reads need
`configuration.read`; refresh needs `configuration.activate` — the
same two-tier model established at Checkpoint 11 and reused at
Checkpoint 22.

## Frontend

`frontend/src/features/market-data/LiveMarketDataMonitor.tsx` — a third
top-level screen alongside Configuration and Settings, observation-only
by construction: no Buy/Sell/Order/Quantity/Stop Loss/Target/Position/
P&L/Execute/Trade control or field exists anywhere in this component,
verified both by manual review and a dedicated frontend test
(`never renders any trading control or field`). Client-side auto-refresh
(every 5s) polls only the read endpoints — never triggers a live Dhan
call automatically; a live fetch happens only via the explicit
"Refresh Quotes" button, shown only to users with `configuration.activate`.

## Manual live-market validation (2026-08-14, market genuinely open)

Performed against the real Django dev server with the project owner's
real Dhan credentials (already present via `.env`/environment — never
requested, never printed, never written to any file this session)
during actual NSE market hours (13:31 IST, a trading Friday). Session
status correctly reported `OPEN`. The live `POST /v2/marketfeed/quote`
call was genuinely made and genuinely reached Dhan's servers — Dhan
rejected the configured credentials (`AUTHENTICATION_FAILED`, HTTP
401/403), correctly and safely classified and reported with a sanitized
message, no token leaked to any log or response. Debounce (200/429/429)
and RBAC (403 for a reader attempting refresh, 200 for the same reader
reading session status) were both confirmed live, not just in
automated tests. Live quote retrieval itself was not achieved this
session — the configured credential was rejected by Dhan, a fact about
the credential, not a defect in this implementation (the identical
401 was independently observed against Dhan's read-only `/v2/profile`
endpoint during Checkpoint 22, confirming this is not new/checkpoint-23-
specific behavior).

## Deferred / explicitly out of scope

Signal generation wiring (Checkpoint 24), paper trading, any order/
position/execution capability, WebSocket streaming, a full scrip-master
ingestion pipeline, exchange holiday calendar, per-instrument health
(this checkpoint's health model is process-wide, not per-symbol),
automatic/scheduled polling (Celery beat), Docker (unchanged, still
deferred).
