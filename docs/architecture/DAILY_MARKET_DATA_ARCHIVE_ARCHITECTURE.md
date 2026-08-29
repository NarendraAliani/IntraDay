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

**Reconciliation** — 64.73 **models** independent reconciliation; 64.79
**computes** it; 64.84 **persists** it. A refresh deliberately **never**
overwrites the reconciliation columns: recomputing the archive from our
*own* observations must never be able to promote a day to "reconciled."
They exist so an independent candle-authority cross-check has somewhere
truthful to record its verdict, and so nothing can mistake "aggregated
from our own ticks" for "verified against an independent source."

Since 64.84 the cell carries five reconciliation columns —
`reconciliation_status` (the coarse three-valued claim),
`reconciliation_outcome` (the exact four-valued verdict),
`reconciliation_reason`, `reconciliation_evidence_source` and
`reconciled_at`. The archive cell is the **persistence boundary**: there
is no reconciliation table, and re-running a reconciliation updates the
same row rather than appending. `reconciled_at` stays `NULL` unless a
bar-by-bar comparison genuinely ran, so it can never be produced merely
by calling the persistence API. Full semantics, the outcome→status
mapping and the archive-vs-reconciliation distinction are documented in
`MARKET_DATA_ARCHIVE_QUERY_API.md` § *Reconciliation persistence*.

**The independent reference source remains REQUIRED and unsolved.** The
only reference pipeline wired up is Dhan's historical-candle REST API.
It differs from the live path in transport, subsystem and table, but not
in **vendor** — Dhan-vs-Dhan is corroboration, not candle authority.
Even a `PASS` from it would not satisfy `TRADING_GRADE_BAR` condition 3.
Persisting verdicts does not change this; it is a future milestone, not
one closed by 64.84.

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

## 10. Full-session live workflow (Checkpoint 64.84 — documented, NOT executed)

Every step below is **already built**. What has never happened is a
single uninterrupted run of them across one whole NSE session, which is
research blocker (1). This section records the procedure so that run is
a rehearsed sequence rather than an improvisation. **Nothing here was
executed in 64.84 — the market was closed and no Dhan connection was
made.**

| # | Step | Component | Ready |
|---|---|---|---|
| 1 | 09:15 IST — session opens; worker already connected and subscribed | `run_market_data_worker` | Yes |
| 2 | Live observation via Dhan WebSocket | `dhan` live provider → `LiveQuoteObservation` | Yes |
| 3 | 1-minute bar aggregation and persistence, continuously | `aggregate_quotes_into_bars` → `AggregatedBarObservation` | Yes |
| 4 | 15:30 IST — session closes; bars stop forming | `domain.session.calendar` | Yes |
| 5 | Archive refresh for the trading date | `MarketDataArchiveService.refresh_trading_date` | Yes |
| 6 | `COMPLETE` / `PARTIAL` determination per cell | `domain.market_data.archive.assess_archive_day` | Yes |
| 7 | Independent reference fetch for the same cells | `HistoricalDataPreparationService` → `HistoricalBar` | Yes, but **not independent of Dhan** |
| 8 | Reconciliation of archive vs. reference | `MarketDataReconciliationService` (64.79) | Yes |
| 9 | **Persist the reconciliation verdict** | `MarketDataReconciliationPersistenceService` (64.84) | Yes — new in this checkpoint |
| 10 | Graceful shutdown | worker shutdown path | Yes |
| 11 | Final archive state read back | archive query API (64.83) | Yes |
| 12 | Research Readiness re-evaluation | `TRADING_GRADE_BAR` gate | Yes |

### The two things that must be true for step 7 to be meaningful

1. **Coverage must overlap.** The reference fetch must request the
   *same* symbols, the *same* timeframe (`1m`) and the *same* trading
   date the archive holds. Today's 5,100 `HistoricalBar` rows are all
   `5m` on different symbols, which is why every reconciliation
   truthfully reports `no_reference_bars_available`. Fixing the fetch
   parameters is a prerequisite for any non-`NOT_RECONCILED` verdict.
2. **The source must be independent.** Even with perfect overlap, a
   Dhan-REST reference checked against a Dhan-WebSocket archive yields
   corroboration, not candle authority. This does **not** block the
   full-session rehearsal — the rehearsal is still worth running for
   blockers (1), (4) and (5) — but it does block `TRADING_GRADE_BAR`
   condition 3 regardless of the outcome.

### Expected result of the first full-session run

If steps 1–6 succeed, one day reaches `archive_status = COMPLETE` for
the first time. Step 9 will still persist `NOT_RECONCILED` unless step 7
is also fixed to fetch overlapping `1m` data. `COMPLETE` +
`NOT_RECONCILED` is the correct outcome of a successful rehearsal, and
must not be read as a failure of the reconciliation path.

---

## Checkpoint 65.12 — `HistoricalBar.provenance`: separating "which
stage wrote this row" from "what kind of data is it"

65.00/65.01's audit found the concrete ambiguity this section closes:
`HistoricalBar.source` (Checkpoint 63.x) has only ever meant *which
pipeline stage wrote the row* — every single one of the 5,100 rows in
this table carries `source="API_FETCH"`, whether the row came from
`SyntheticHistoricalBarProvider` (a deterministic, hash-seeded
generator — see that module's own docstring) or from anything else.
Formula-replay in 65.00/65.01 reproduced roughly 3,900 of those 5,100
rows exactly from the synthetic generator; the remaining ~1,200 have
no corroborating evidence either way (some fall outside the
generator's fixed 100–999 price range, proving they were **not**
produced by that path, but that alone does not prove they are real
NSE data).

### The new field

`HistoricalBar.provenance` (migration `0036_historicalbar_provenance`,
pure `ADD COLUMN` with a fixed default — see that migration's own
docstring for the full safety note) is a **second, explicit** per-row
field, orthogonal to `source`:

| Field | Question it answers | Values |
|---|---|---|
| `source` | Which pipeline stage wrote this row? | `"API_FETCH"` (unchanged since 63.x) |
| `provenance` | What kind of data is it? | `REAL_DHAN` / `SYNTHETIC_TEST` / `UNKNOWN` (`domain.market_data.provenance`, new in 65.12) |

All 5,100 pre-65.12 rows were left `provenance="UNKNOWN"` by the
migration — **not** relabeled, **not** inferred, **not** upgraded from
the 65.00/65.01 formula-replay finding. That finding is real evidence,
but applying it is a deliberate, reviewed backfill decision, not
something a schema migration should do silently; it remains available
as future work (§ Remaining Gaps in the 65.12 task report) if the
project chooses to run it.

### Where it gets stamped

`HistoricalBarProvider` (the Protocol in
`application.services.historical_data_preparation`) now declares a
`provenance` attribute. `SyntheticHistoricalBarProvider` declares
`PROVENANCE_SYNTHETIC_TEST`; a provider that declares nothing is
treated as `PROVENANCE_UNKNOWN` by
`HistoricalDataPreparationService`, never silently upgraded. This
fixes 65.01's root-cause bug #1 (the preparation service used to write
one hardcoded label regardless of which provider ran) for every future
fetch; it does **not** retroactively fix the 5,100 existing rows,
which is why the migration leaves them `UNKNOWN` rather than
back-dating this stamping logic onto them.

`infrastructure/api/backtesting_views.py`'s `_prepare_if_needed` still
unconditionally constructs `SyntheticHistoricalBarProvider()` for
every non-fixture instrument (65.01 root-cause bug #2) — this is now
**honestly labelled** (every bar it writes is stamped
`SYNTHETIC_TEST`) rather than fixed by selecting a different provider,
because no real Dhan historical-candle adapter exists yet to select.
See that function's own 65.12 docstring for the exact one-line change
required the day one does.

### Research eligibility

`domain.market_data.provenance.is_research_eligible(provenance)`
returns `True` only for `PROVENANCE_REAL_DHAN`. This is the smallest
possible answer to "can this bar be used for research?" (Part B) — it
is a pure function callers can apply, **not** a change to
`BacktestingService`, `HistoricalMarketDataService`, or any repository
read path's default behavior, all of which remain untouched. Wiring
this gate into the canonical backtest's default (research) execution
path — so a `RESEARCH` run rejects non-`REAL_DHAN` bars instead of
merely being *able* to check them — is explicitly **not done** in
65.12: that is a backtest-execution-layer change, out of this
checkpoint's data-foundation scope, and is named as the concrete next
step in the 65.12 task report.

### What this does not change

`AggregatedBarObservation` and `MarketDataArchiveDay` are unmodified
by 65.12 — `MarketDataArchiveDay` still shows 0 `COMPLETE` cells (4
`IN_PROGRESS`, 16 `PARTIAL` as of 65.12's audit), and the completeness
vocabulary and derivation in `domain.market_data.archive` (§7 above)
is unchanged. No `HistoricalBar` row was deleted, no synthetic data
was generated, and no row was relabeled `REAL_DHAN`.

## Checkpoint 65.13 — next real NSE session capture procedure (READINESS ONLY, NOT EXECUTED)

65.13 is an offline audit. The market was closed throughout; no Dhan
connection was made, no worker was started, and nothing in this
section was executed. It records the exact procedure so the next real
capture is a rehearsed sequence, not an improvisation — the same
discipline as §10's 64.84 full-session-workflow table above, updated
with a deliberately small first target.

### Selected target (smallest defensible)

- **Symbols:** 1–3 liquid NSE cash-equity symbols already present in
  the operator's configured watchlist (`run_market_data_worker.py`
  resolves its subscription set from `DjangoWatchlistRepository` —
  the worker does not hardcode a symbol list). Do not widen to the
  full NSE universe for the first capture.
- **Timeframe:** `ONE_MINUTE` only — the finest-grained
  completeness-supported timeframe (§7) and the one
  `expected_bar_timestamps()`/`is_completeness_supported()` are
  already proven against.
- **Session window:** 09:15–15:30 IST, the existing
  `domain.session.calendar` continuous session (or the CAS-aware
  09:15–15:15 continuous window for a CATEGORY_I_CAS symbol, via
  `build_cas_aware_session_for` / `is_continuous_completeness_supported`
  — do not use the plain 375-minute window for a CAS instrument).
- **Reason:** every mechanism this target exercises (ingestion →
  aggregation → archive refresh → completeness) is already built and
  targeted-tested (§ below); a 1–3 symbol / 1m / one-session capture is
  the smallest run that can turn a `MarketDataArchiveDay` cell
  `COMPLETE` without adding load, without touching option/index/sector
  ingestion, and without exercising any code path not already covered
  by existing tests.

### Procedure at next market open

1. Confirm the date is a trading day (`domain.session.calendar.is_trading_day`).
2. Start `run_market_data_worker` for the Dhan provider only, scoped to
   the chosen 1–3 symbol watchlist. Do not start it in 65.13.
3. Let it run untouched 09:15–15:30 IST. No manual intervention unless
   `WorkerRuntimeStatus` reports a failure.
4. At/after 15:30 IST, run `python manage.py market_data_archive --date
   <trading_date> --refresh` (or call
   `MarketDataArchiveService.refresh_trading_date()` directly) for the
   captured symbols and `ONE_MINUTE`.
5. Read back `describe_trading_date()` / the archive query API and
   record the resulting `ArchiveStatus` per cell.
6. Do **not** run reconciliation against Dhan-REST as a substitute for
   an independent source (§9) — persist `NOT_RECONCILED` if no
   independent reference is fetched; this is the correct, honest
   outcome per the 64.84 precedent, not a failure.

### Completeness expectation

Per §7, the cell becomes `COMPLETE` only when: the continuous session
has closed, `ONE_MINUTE` is completeness-supported (it is), and the set
difference between `expected_bar_timestamps()`/
`expected_continuous_bar_timestamps()` and the observed closed-bar
timestamps is empty, with duplicates reported separately and never
counted toward coverage. No loosening of this gate is proposed or
made.

### Provenance expectation

`HistoricalBar.provenance=REAL_DHAN` is **not** produced by this
capture directly — capturing a COMPLETE `MarketDataArchiveDay` cell
populates the live-observation/archive tables only.
`HistoricalBar.provenance` (65.12) is stamped by a *separate*
projection path (`HistoricalBarProvider` → `HistoricalDataPreparationService`)
that, as of 65.12/65.13, has no genuine Dhan-historical-candle provider
implementation — only `SyntheticHistoricalBarProvider`
(`PROVENANCE_SYNTHETIC_TEST`) exists today. A future checkpoint must
add a real Dhan-historical-candle-backed `HistoricalBarProvider` (or a
COMPLETE-archive-to-HistoricalBar projector) that declares
`PROVENANCE_REAL_DHAN` before any row can honestly carry that value.
65.13 does not build this projector — see `PART K` of its directive.

### Reconciliation checklist after session close

- Observation count for the trading date/symbol/timeframe.
- Expected bar count vs. closed bar count (`expected_bar_count`,
  `closed_bar_count`, `missing_bar_count`).
- First/last observation timestamps.
- Gaps (`missing_bar_timestamps`) and duplicates
  (`duplicate_bar_timestamps`).
- Resulting `ArchiveStatus` per cell and the day-level rollup
  (worst-status-wins, §"Query model"/`_rollup_status`).
- `reconciliation_status` — expected `NOT_RECONCILED` unless a genuine
  independent-source comparison was also run.

### Failure handling

- A worker crash/restart mid-session: `LiveQuoteObservation`/
  `AggregatedBarObservation` writes are append-only and already
  persisted per-observation, so a restart resumes ingestion without
  losing already-written data; `MarketDataArchiveDay` is a recomputable
  projection (§5) so refreshing after a restart reproduces the correct
  state from whatever was actually observed — no distributed
  scheduler or new recovery infrastructure is required for this first
  capture. `WorkerRuntimeStatus` (Checkpoint 22/64.63) is read to
  confirm the process's own view of RUNNING/STOPPED/FAILED.
- A genuinely failed ingestion run should be recorded as
  `ingestion_failed=True` at refresh time so the cell is honestly
  `FAILED`, never inferred from a low row count (§7).
- No missing bar is ever auto-filled, interpolated, or fabricated —
  gaps stay gaps in `missing_bar_timestamps` until a genuine future
  observation or reconciliation resolves them.
