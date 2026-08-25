# Daily Market Data Archive Architecture

**Introduced:** Checkpoint 64.73
**Status:** Minimum viable foundation implemented. NOT a complete
historical-data platform, and NOT a reconciled archive.

Checkpoint 64.72 proved that real Dhan market data is *persisted*
(4,869 real Quote packets, 80 CLOSED + 4 FORMING 1-minute bars, read
back from PostgreSQL). It also named the honest gap that this document
closes the first half of:

> DAILY MARKET DATA ARCHIVE = NOT YET COMPLETE — no trading-date
> identity column, no retention/completeness guarantee.

Before 64.73 the system could answer *"do rows exist?"* and nothing
more. "Give me everything for trading day X" was not an expressible
query, and "rows exist" was the only — and false — available proxy for
"the day was fully observed."

---

## 1. What this archive is (and is not)

**It is** a trading-day-aware, queryable, auditable index over market
data this platform has *actually observed*, plus an explicit,
non-inflating statement of how much of each day it holds.

**It is not** a claim that any day is complete, that any day has been
independently verified, or that the data is research-grade. Those are
separate, still-unmet gates (§9).

---

## 2. Trading session identity

Identity is the **natural key `(exchange, trading_date)`** —
`domain.market_data.archive.TradingSessionIdentity`, rendered as
`"NSE:2026-08-25"`.

Deliberately **not** a random UUID and **not** a per-process run id.
Two ingestion runs on the same calendar day must converge on the *same*
session rather than manufacturing a second "session" for one day. This
is what makes the archive idempotent.

## 3. Trading date

**One trading day = one IST calendar date**, and the single canonical
derivation is `domain.market_data.archive.trading_date_for(instant)`.

The rule: `instant.astimezone(Asia/Kolkata).date()`.

A naive `instant.date()` on a UTC timestamp would be wrong for the ~5.5
hours per day where the UTC and IST calendar dates differ — for an NSE
session that means **every observation before 05:30 UTC**, i.e. the
entire 09:15–11:00 IST opening range, filed under the previous day.
This is a silent, data-corrupting class of bug, so the derivation lives
in exactly one place and is asserted by test.

- **Quotes** are stamped from `Quote.timestamp` (the *source* instant),
  never from `fetched_at` (our local receive clock).
- **Bars** are stamped from `interval_end` — a bar belongs to the
  trading day it **closed** in.

Stamping happens at the single write boundary
(`live_market_data_repositories.py`), so no ingestion path can bypass
it.

## 4. Timezone

`Asia/Kolkata` via stdlib `zoneinfo`, reused from
`domain/session/calendar.py` (Checkpoint 23). Session hours
(09:15–15:30 IST), weekend handling, and the NSE 2026 holiday list are
**not redefined here** — the archive composes the existing calendar
rather than growing a second, divergent notion of market hours.

Holidays outside 2026 remain a documented pre-existing limitation of
`NSE_HOLIDAYS_2026`; the archive inherits it rather than hiding it.

## 5. Persistence model

Two existing tables gain one derived column each; one new table is
added.

| Table | Role | Write pattern |
|---|---|---|
| `LiveQuoteObservation` | raw observations | append-only |
| `AggregatedBarObservation` | aggregated bars | upsert by `(symbol, timeframe, interval_start)` |
| `MarketDataArchiveDay` | **new** — archival status projection | upsert by `(exchange, trading_date, symbol, timeframe, data_source)` |

`MarketDataArchiveDay` is explicitly a **projection, not a second
source of truth**. Every value on it is recomputable from the
underlying observations via
`MarketDataArchiveService.refresh_trading_date()`. If the table were
dropped it could be rebuilt exactly. It exists so that "which days are
COMPLETE?" is one indexed query rather than a recomputation over every
observation ever recorded.

**Idempotency guarantee:** refreshing the same day repeatedly rewrites
the same rows with the same values. Proven by test.

## 6. Query model

Indexes added in migration `0028`:

- `LiveQuoteObservation (trading_date, instrument_symbol)`
- `AggregatedBarObservation (trading_date, instrument_symbol, timeframe)`
- `MarketDataArchiveDay (-trading_date, status)` and
  `(trading_date, instrument_symbol, timeframe)`

The column ordering means "everything for day X" is a prefix scan and
"symbol S on day X" is a full index match — neither degrades to a
full-table scan of an append-only tick log that grows by thousands of
rows per 20 minutes of observation.

Supported first-class queries (`MarketDataArchiveService`):

| Question | Method |
|---|---|
| Is day Y COMPLETE / PARTIAL / IN_PROGRESS / NOT_OBSERVED? | `describe_trading_date()` |
| Which symbols are archived for day Y? | `archived_symbols()` |
| All 1m bars for symbol X on day Y | `bars_for()` |
| All quote observations for symbol X on day Y | `quote_observations_for()` |
| Gaps for symbol X on day Y | `gaps_for()` |
| Bars expected vs. persisted | `expected_bar_count` / `closed_bar_count` |
| Has day Y been reconciled? | `reconciliation_status` |

Operator entry point: `python manage.py market_data_archive
--date YYYY-MM-DD [--refresh] [--symbol SYM]`. Read-and-classify only —
it never deletes data and never contacts a provider.

## 7. Completeness model

**The central rule: rows existing NEVER implies the day is complete.**

Five statuses (`domain.market_data.archive.ArchiveStatus`):

| Status | Meaning |
|---|---|
| `NOT_OBSERVED` | no data. Either nothing ingested, or the date is not a trading day (`reason` distinguishes — an empty Saturday is *correct*; an empty open trading day is a real outage) |
| `IN_PROGRESS` | the session has not closed yet. Can never be COMPLETE or PARTIAL — "the day isn't over" must not be confused with "the day is over and we missed data" |
| `PARTIAL` | session over, data exists, expected bars are missing |
| `COMPLETE` | session over, **every** expected interval present |
| `FAILED` | ingestion explicitly reported an unrecoverable termination. Never inferred from low row counts |

Evidence required to declare a day COMPLETE: the session must be
closed, the timeframe must be completeness-evaluable (below), and the
set difference between expected and observed bar-close timestamps must
be **empty**. Expected timestamps come from the pre-existing
`domain.market_data.quality.expected_bar_timestamps()` — the archive
does not invent its own gap arithmetic. The NSE session yields **375**
expected 1-minute bars.

A day rolls up to the **worst** cell status present, so one
un-observed symbol can never hide behind a majority of healthy ones.

### Explicitly modelled limitation: unsupported timeframes

Completeness is only evaluable for timeframes whose boundaries align
with the session window. The session is 375 minutes and the aggregator
anchors buckets at the UTC epoch (09:15 IST = 03:45 UTC). A timeframe
qualifies only when both 375 and 225 are exact multiples of its
duration:

- **Supported:** 1m, 3m, 5m, 15m
- **Unsupported:** 30m, 1h, DAY, TICK

An unsupported timeframe is reported `PARTIAL` with
`reason=completeness_unsupported_timeframe:<tf>` and
`completeness_supported=False`. It can **never** be reported COMPLETE.
Inventing an expected bar count for a timeframe whose first and last
buckets straddle the session boundary would be a fiction, so the
limitation is modelled rather than papered over.

## 8. Gap detection, reconciliation, retention

**Gap detection** — the exact missing bar-close timestamps are computed
per cell; the stored row keeps the *count* so "which symbol-days have
gaps" stays an indexed query. Duplicate bar timestamps are reported
separately and are not double-counted toward coverage.

**Reconciliation** — 64.73 **models** independent reconciliation; it
does **not perform** it. `reconciliation_status` is honestly
`NOT_RECONCILED` on every row this checkpoint writes, and a refresh
deliberately **never** overwrites it: recomputing the archive from our
*own* observations must never be able to promote a day to "reconciled."
The column exists so a future independent candle-authority cross-check
has somewhere truthful to record its verdict, and so nothing can
mistake "aggregated from our own ticks" for "verified against an
independent source."

**Retention** — `domain.market_data.archive_retention`. The active
policy is `RETAIN_FOREVER`. **Nothing in this checkpoint deletes any
market data**: there is no scheduled job, no purge command, and no
production caller of `select_purgeable_trading_dates()`. Observed
market data is irreplaceable — an automatic deleter introduced casually
is a far worse defect than unbounded growth. The policy is written down
as a testable value *before* any deletion capability is built on it,
with two fail-safes that make the purge set empty today regardless of
configuration: a day may never be purged unless it is COMPLETE, and
never before it has been independently reconciled (which nothing yet
does).

## 9. Relationship to TRADING_GRADE_BAR and Research Readiness

This archive **does not** advance `TRADING_GRADE_BAR`. Conditions 3
(candle authority), 5 (reconciliation/gap recovery *validated*) and 6
(one full session independently validated) all require an **independent
source of truth** that this checkpoint neither adds nor consults.

What the archive *does* contribute is the substrate those conditions
will need: a trading-day identity to reconcile *against*, a defensible
expected-vs-observed count, and a truthful place to record a
reconciliation verdict.

**Research Readiness remains NO.** The 5-criterion gate in
`BACKTESTING_ARCHITECTURE.md` is unchanged and not redefined here.
`BacktestTrustLevel` is untouched.

## 10. Worker lifecycle: process-independent graceful shutdown

64.72 made three genuine attempts to stop a running worker gracefully
(CTRL_C_EVENT via console attach, plain `taskkill`, and a repeat) and
all three failed for one structural reason: a background-launched
Windows process is not console-attached the way
`GenerateConsoleCtrlEvent` requires, and Windows has no deliverable
SIGTERM. The worker was force-terminated and `worker_state` was left
lying at `RUNNING`.

64.73 **abandons OS signals as the primary mechanism** rather than
adding a fourth signal workaround:

1. `manage.py request_market_data_worker_stop [--provider dhan]`
   records `stop_requested_at` on the worker's own
   `WorkerRuntimeStatus` row. It kills nothing.
2. The running worker polls that row
   (`application/services/worker_stop_request.py`) and sets the shared
   `asyncio.Event`.
3. The event stops the reconnect supervisor opening further
   connections; the provider disconnects; aggregation drains;
   persistence flushes.
4. `WorkerRuntimeStatus` is written `STOPPED`; the archive is
   refreshed; the process exits. The watcher task is cancelled *and
   awaited*, so no orphan task survives.

Why this shape: it is **process-independent** (no PID discovery, no
console attachment), **project-native** (reuses the established
one-row-per-provider pattern from Checkpoint 22 — no new control
plane), **not a network endpoint** (unnecessary given a shared
database), and **deterministically testable with no live provider
connection at all**.

**Staleness guard:** the worker clears any pending request at startup,
so a leftover flag can never instantly kill a freshly started worker,
and clears it again once honoured.

OS signal handlers are **kept** as a best-effort secondary path for the
interactive-foreground case.

## 11. Safety

The archive is read-and-classify only. It runs no strategy, creates no
`OrderIntent`, touches no PaperBroker or LiveBroker, places no order,
and does not activate Gainz. It never changes live Dhan ingestion
behavior — the only ingestion-path change is stamping the derived
`trading_date` column at the existing write boundary.

---

## Checkpoint 64.78 â€” option observations and this archive

**`MarketDataArchiveDay` is unchanged by 64.78.** It was not modified,
not extended, and explicitly not made derivatives-specific. Its cell
identity remains `(exchange, trading_date, instrument_symbol, timeframe,
data_source)` â€” a cash-equity shape with no expiry/strike dimension.

**There is no option daily archive.** 64.78 adds two raw option
observation tables (`OptionQuoteObservation`, `OpenInterestObservation`)
and nothing else. No archive assessment, no completeness model, and no
`ArchiveStatus` is computed for any option series. Any claim that "the
option daily archive is implemented" would be false.

**What 64.78 does guarantee** is that a future option archive layer will
have the identity it needs, already present and indexed on every option
observation row:

| Requirement | Where it lives |
|---|---|
| Trading-day identity | `trading_date`, from the **same canonical** `domain.market_data.archive.trading_date_for()` used by the equity archive â€” never a naive `.date()`, never a second implementation |
| Observation instant | `source_timestamp` (provider's own) / `observed_at` (our receipt, for OI) |
| Our ingestion clock | `fetched_at`, stamped at the single write boundary |
| Contract identity | canonical `contract_id`, plus exploded `underlying_symbol` / `expiry` / `strike` / `option_type` / `lot_size` |
| Provider identity | `provider`, `provider_security_id` |
| Provenance | `data_source` (64.75's discipline, verbatim, never defaulted) |

The open design question a future option-archive checkpoint must answer
â€” and which 64.78 deliberately does **not** answer â€” is what an option
archive *cell* should be. `(trading_date, contract_id, data_source)` is
the obvious candidate, but an option universe changes shape daily as
contracts list and expire, so "expected coverage for the day" cannot be
derived from a fixed symbol list the way the equity model does it. That
is a real modelling problem, not a mechanical extension.

Retention is unchanged: `domain/market_data/archive_retention.py`
remains retain-forever and non-acting, and nothing in 64.78 deletes or
rotates any observation.
