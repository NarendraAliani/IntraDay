# Market Data Archive & Reconciliation Query API

Checkpoint 64.83. A **read-only** HTTP surface over the market-data
evidence this platform already stores. Two endpoints, both `GET`, both
`IsAuthenticated`.

This document exists mainly to keep five claims apart. They are
routinely conflated, and conflating them is how a research platform
starts trusting data it has no right to trust.

## The five separate claims

| # | Claim | What proves it | Status today |
|---|---|---|---|
| 1 | **Data was archived** | An archive cell exists for the (date, symbol, timeframe) | TRUE for 8 cells across 2 days |
| 2 | **The archive is complete** | `archive_status == COMPLETE`: every expected bar present | FALSE for every cell ever recorded |
| 3 | **Reconciliation was performed** | A reconciliation report with a real reference series | FALSE — no overlapping reference data exists |
| 4 | **Independent candle authority** | Agreement with a source independent **of Dhan** | FALSE — the only reference pipeline is Dhan |
| 5 | **Research readiness** | The full 5-criterion gate in `BACKTESTING_ARCHITECTURE.md` | **NO** |

Each row requires everything above it and more. **1 does not imply 2, 2
does not imply 3, 3 does not imply 4, and 4 does not imply 5.** The API
below is deliberately shaped so a caller cannot accidentally read one as
another.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/market-data/archive/{trading_date}/` | What the archive holds for one NSE trading date |
| `GET /api/v1/market-data/reconciliation/{trading_date}/` | Reconciliation evidence for one trading date |

Both accept optional `?symbol=` and `?timeframe=` filters, and both echo
the applied filters back (`symbol_filter` / `timeframe_filter`) so a
filtered subset can never be mistaken for a whole day.

**Two endpoints, not four.** A `/archive/{date}/{symbol}/` route would
return a strict subset of `/archive/{date}/?symbol=X` at identical query
cost while adding a second contract and a second OpenAPI schema to keep
consistent. Filtering is composable; endpoint proliferation is not.

### Not a source of truth

Neither endpoint computes, stores, or changes anything.

* The archive endpoint reads the existing 64.73 `MarketDataArchiveDay`
  projection through the existing `DjangoMarketDataArchiveRepository`.
* The reconciliation endpoint calls the existing 64.79
  `MarketDataReconciliationService`, which by its own design **writes
  nothing** — a reconciliation result is reported, never recorded. A
  test asserts that calling the endpoint leaves
  `MarketDataArchiveDay.reconciliation_status` untouched.

The **read API is still read-only after 64.84.** Persistence was added
in 64.84 as a separate explicit service
(`MarketDataReconciliationPersistenceService`) that a caller must invoke
deliberately; querying the reconciliation endpoint continues to compute
and report without recording. See *Reconciliation persistence* below.

No new table, no second archive, no second comparator.

## Archive status semantics

`archive_status` is `domain.market_data.archive.ArchiveStatus`,
unchanged:

| Value | Meaning |
|---|---|
| `NOT_OBSERVED` | No data. **Correct** on a weekend/holiday; a real gap on a trading day — `is_trading_day` distinguishes them |
| `IN_PROGRESS` | Session not closed yet. Never `PARTIAL`, never `COMPLETE` |
| `PARTIAL` | Session over, data exists, expected bar series has gaps |
| `COMPLETE` | Every expected bar present. **The only status entitling a consumer to treat the day as a whole session** |
| `FAILED` | Ingestion explicitly reported unrecoverable. Never inferred from row counts |

A **day** rolls up to the **worst** cell status on it, and does so even
when the response is filtered — one broken symbol can never hide behind
a majority of healthy ones.

### Completeness

`completeness_supported` is `false` for TICK, DAY, 30m and 1h, whose bar
boundaries do not align with the 09:15–15:30 IST session. Such a cell
can **never** be `COMPLETE`.

**The null rule.** For an unsupported timeframe, `expected_bar_count`
and `missing_bar_count` are `null`, not `0`. A `0` would read as
"nothing was expected and nothing is missing" — a different and false
claim. Throughout this API, `null` means *this platform does not have
this value* and `0` means *this platform measured zero*. They are never
interchanged, and a test pins it.

### Gap detection

`missing_bar_count` and `duplicate_bar_count` come from the stored 64.73
assessment, which delegates gap arithmetic to
`domain.market_data.quality.missing_bar_timestamps`. This API adds no
gap logic of its own.

## Reconciliation semantics

`reconciliation_status` on a **reconciliation cell** is
`ReconciliationOutcome`: `NOT_RECONCILED` / `PASS` / `PARTIAL` / `FAIL`.

`NOT_RECONCILED` is a **first-class outcome, not an error** — it is the
honest answer whenever no usable reference series exists. `PASS` is
never returned merely because the comparison ran; the domain requires
full expected-bar coverage on both sides plus zero mismatches.

Note that `reconciliation_status` on an **archive cell** is a different
field with a different meaning: it is what the stored archive row
*claims* (`NOT_RECONCILED` / `RECONCILED` / `MISMATCH`), not the result
of running a comparison. The two are never merged.

## Reconciliation persistence (Checkpoint 64.84)

64.79 computed a verdict and stopped. 64.84 records it — and records
**only** what was actually computed.

### The rule

> Calling the persistence service is **never** evidence of
> reconciliation. The verdict stored is the verdict the domain
> computed, unmodified. A successful write says nothing whatsoever
> about agreement of the data.

`MarketDataReconciliationPersistenceService.reconcile_and_persist_cell()`
runs a fixed sequence: **compute first** through the untouched 64.79
service, project the verdict, stamp the time only if earned, then write.
If the comparison raises, the exception propagates and **nothing is
written** — there is no `except` clause, because swallowing the error is
exactly how a failed calculation would leave a successful-looking status
behind.

### When each value is stored

| Computed `ReconciliationOutcome` | Stored `reconciliation_status` | `reconciled_at` |
| --- | --- | --- |
| `NOT_RECONCILED` (no reference bars, no observed bars, unsupported timeframe) | `NOT_RECONCILED` | **`null`** |
| `PARTIAL` (everything compared agreed, coverage incomplete) | `NOT_RECONCILED` | evaluation time |
| `PASS` (full coverage both sides, zero mismatches) | `RECONCILED` | evaluation time |
| `FAIL` (value disagreement or duplicate timestamp) | `MISMATCH` | evaluation time |

Two vocabularies are kept deliberately, bridged in exactly one place
(`reconciliation.persisted_status_for`):

* `reconciliation_outcome` stores the **exact** four-valued verdict;
* `reconciliation_status` is the coarse three-valued claim every
  existing consumer already reads. Its vocabulary was **not widened**,
  because a new value would silently change what
  `classify_archive_evidence`, the archive API and the correlation trace
  mean.

`PARTIAL` therefore appears as `NOT_RECONCILED` in the coarse column.
That is the one judgement in the mapping: a partially-covered comparison
is not an independently validated day, and it is not a disagreement
either — of the three stored values, `NOT_RECONCILED` is the only one
that claims nothing false. Nothing is lost: the exact `PARTIAL` verdict
and its reason remain readable on the same row.

### What `NOT_RECONCILED` means

**"This day has not been checked against an independent reference."** It
is not an error and not a failure. It is the correct and current value
for every cell in this database.

### What `reconciled_at` means

**"A bar-by-bar comparison actually ran, at this instant."** It is
`null` whenever the outcome is `NOT_RECONCILED`, because that outcome is
returned precisely when `reconcile_bar_series` short-circuited *before*
comparing anything. A non-null `reconciled_at` is therefore evidence
that bars were genuinely compared — never merely that a persistence API
was called. The instant recorded is the evaluation `as_of`, not the
moment a row happened to be written.

### Archive status vs. reconciliation status

They are independent claims, written by different code paths that do not
touch each other's columns:

* an archive **refresh** never writes any reconciliation column, so
  recomputing the archive from our own observations cannot promote a day
  to "reconciled";
* a reconciliation **persist** writes only the five reconciliation
  columns via a single bounded `UPDATE`, so it cannot alter an archive
  status, count or timestamp.

`archive_status: "COMPLETE"` together with
`reconciliation_status: "NOT_RECONCILED"` is a **valid** combination —
complete is not validated.

### Persistence boundary and idempotency

**There is no reconciliation table.** The archive cell *is* the
persistence boundary. Re-running a reconciliation for the same
(date, symbol, timeframe) `UPDATE`s the same row, so the stored result is
a current verdict rather than an append-only history that could disagree
with itself. Three consecutive runs produce one row, proven by test.

A reconciliation **never creates** an archive cell. If no cell is
archived there is nothing to make a claim about, and a row conjured by a
reconciliation would assert observation that never happened; the result
reports `archive_cells_updated == 0` instead.

### Evidence source — the important caveat

Every reconciliation cell carries `evidence_source`. Today it is always
`dhan_historical_candle_api`.

**That source is not independent of Dhan.** The archive it would check
is built from Dhan's live WebSocket feed; the reference is Dhan's
historical-candle REST API. Different transport, different subsystem,
different table — but the same vendor. `TRADING_GRADE_BAR` condition 3
(candle authority) and the gate's own §3 explicitly require a
Dhan-independent source. **Even a future `PASS` from this pipeline would
not satisfy condition 3.** `evidence_source` is mandatory on the wire so
this is always visible at the point of use.

### What the data actually says today

Run against the real database (2026-08-26, offline):

* 8 archive cells: 4 symbols × 2 days, all `1m`, all source `dhan`.
* 2026-08-24: `PARTIAL`, **1 of 375** expected bars per symbol.
* 2026-08-25: `IN_PROGRESS`, **24 of 375** expected bars per symbol.
* **No cell has ever been `COMPLETE`.** Best coverage ever achieved on
  one session: **6.4%**.
* Every reconciliation returns `NOT_RECONCILED`, reason
  `no_reference_bars_available`. The 5,100 stored `HistoricalBar` rows
  are all `5m` and cover different symbols — **zero overlap** with the
  archived `1m` cells.

Re-verified on 2026-08-26 **after** 64.84 wired persistence, running the
real service against the real database twice: all 8 cells persisted as
`reconciliation_status = NOT_RECONCILED`, `reconciliation_outcome =
NOT_RECONCILED`, `reason = no_reference_bars_available`, `reconciled_at =
NULL`, row count unchanged at 8, archive statuses untouched. The one
near-miss is instructive: `TCS` on 2026-08-24 has **71** reference bars
at `5m` but **no archived 5m observed bars**, so it reports
`no_observed_bars_to_reconcile` and matches no archive cell to write to.
Persisting the verdict changed nothing about it, which is the point.

## Archive → Outcome traceability

Every correlation trace (64.82) carries `market_data_outcome_status`,
now resolved against the real archive rather than the 64.82 placeholder
`ARCHIVE_API_NOT_IMPLEMENTED`:

`ARCHIVE_NOT_AVAILABLE` · `ARCHIVE_PARTIAL` ·
`ARCHIVE_COMPLETE_NOT_RECONCILED` · `ARCHIVE_RECONCILED` ·
`ARCHIVE_RECONCILIATION_FAILED`

Resolution is exact: the signal's stored `instrument_id`
(`"NSE:RELIANCE"`) is split into exchange and symbol, and its stored
`signal_timestamp` is converted to a trading date through the one
canonical IST rule (`archive.trading_date_for`). An `instrument_id` with
no parseable exchange prefix yields `ARCHIVE_NOT_AVAILABLE` — never a
lookup under an assumed default exchange.

### Traceability vs. correlation vs. causality

This is the distinction the whole checkpoint turns on.

* **Traceability** — recorded identifiers link a signal to an order to a
  trade. This the platform has.
* **Correlation** — archived market data exists for the *same*
  instrument and *same* trading date as a decision. This is what
  `market_data_outcome_status` reports.
* **Causality** — that data was the input the strategy read, and it
  produced this outcome. **The platform stores no such link and this API
  does not claim one.**

A status of `ARCHIVE_COMPLETE_NOT_RECONCILED` means archived evidence
for that instrument-day exists and is complete. It does **not** mean the
strategy read it, that it produced the signal, or that it caused the
realised P&L. No amount of archive completeness upgrades correlation
into causality.

## Query performance

* Archive day: **fixed** query count, independent of symbol count —
  asserted by comparing a 2-symbol day against a 12-symbol day.
* Correlation trace: the archive lookup is **one bulk query** for the
  whole response — a 12-signal run costs the same as a 2-signal run.
  The single-signal trace went from 4 fixed queries to 5 fixed queries.
* Reconciliation: **deterministic and strictly linear per symbol** (2
  queries per symbol). This is inherent to the 64.79 service, which
  reconciles one cell per call by design; 64.83 reuses it exactly rather
  than building a second engine. Bounded work proportional to the data
  requested, not unbounded N+1 across unrelated tables. A test pins the
  exact linear constant.

## Authorization

`IsAuthenticated`, GET-only — identical to the 64.82 correlation
surface. No new auth mechanism and no new capability token. Anonymous
requests are rejected (401/403) and every write method returns 405; both
are asserted by tests. No credential, token, secret, or stack trace is
reachable from any response.

A malformed date returns a typed **400**, never a routing 404 — "this
date is malformed" and "this date has no archived data" must remain
distinguishable. An unknown `timeframe` filter is likewise a 400 rather
than a silently-ignored filter.

## Gainz

Gainz remains **disabled and unimplemented**. No Gainz module, math,
adapter, or activation path exists or was added. This document mentions
it only to record a prerequisite: **archive-qualified outcome evidence
is a precondition for any future Gainz attribution.** Attribution needs
exactly what claims 2–4 above establish, and none of them is true yet.

## NSE_FNO

Frozen and untouched. No option, OI, IV, Greeks or option-bar structure
is read, written, or referenced by this surface.
