```
checkpoint: 67.12.2-B-retry
verdict: BASELINE_ESTABLISHED
concurrent_safety_confirmed: YES
content_checksum: 3d2d6db480215ae048d10184c3b99458bef96338543d2e59eee56a1b914a27a7
legacy_checksum_match: YES
schema_fingerprint: 3e9b7d907eb56fdeac45083c383ba5017d154ef9fd3015de765a46c20732ab19
unknown_classification: { reproducible: 3900, plausible_unverified: 817, implausible: 383 }
tests_passing: 20/20
commit: <see final `git log -1` after commit — recorded below>
blockers: []
```

## A. Part 0 self-check

1. **No Dhan network call.** `verify_data_integrity.py` imports only `django.db`,
   `hashlib`, `json`, `decimal`, `datetime`, and three pure `intraday.domain.*`
   helpers (`build_session_for`, `is_trading_day`, `expected_bar_timestamps`,
   `Timeframe`) — no `requests`/`httpx`/`websockets`/Dhan client import
   anywhere in the file. `[F]` grep confirmed zero matches for those tokens.
2. **No `ScannerConfiguration` read/write.** Zero references to
   `ScannerConfiguration` in the new command or its test. `[F]`
3. **No `run_market_data_worker` start/stop/restart.** The command does not
   import or shell out to `run_market_data_worker`, `request_market_data_worker_stop`,
   or any subprocess/`call_command` targeting them. `[F]`
4. **Read-only, `HistoricalBar`-only.** The single transaction issues `SET
   TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE` as its first
   statement, then only `SELECT`/`SHOW`/`SET LOCAL` statements against
   `persistence_historicalbar`, `persistence_migrationrun/unit/row` (read-only
   counts), and `information_schema.columns`. It never references
   `LiveQuoteObservation`/`AggregatedBarObservation`. `[F]` — verified by
   reading the finished file and by the zero-write test
   (`test_command_makes_zero_writes_to_historical_bar`) and the structural
   source-scan test (`test_command_source_contains_no_mutating_calls_or_sql`),
   both passing.

All four hold. Ran twice against the real (concurrently-live) database with
`transaction.set_rollback(True)` as a second, defense-in-depth guarantee on
top of `READ ONLY DEFERRABLE`; both runs succeeded and produced an identical
checksum, and `pg_current_xact_id` differed by exactly 1 between the two
independent CLI invocations (`2975705` then a fresh id on the next run) —
consistent with the concurrently-running 67.12.2-E worker committing its own,
unrelated transactions in between, and with nothing here interfering with it.
**Nothing HALTs Part 0.**

## B. Decisions 219+, cost model, instrument master (Part 1)

**1. Highest Decision number.** `[F]` The highest numbered row in
`docs/architecture/ARCHITECTURE_DECISIONS.md`'s decision table is **218**
(`grep -oE "^\| [0-9]+ \|" | sort -n | tail`). There is no Decision 219 or
higher anywhere in the file — RECON-01's "nothing past 219" reads correctly
as "nothing exists past 218 either," not as a search failure; the true
highest is 218, one short of what RECON-01 was asked to look for. One line
each for 210-218 (the tail of the log):

```
210 | New run_worker_session() - sync, I/O-free orchestration driven by scripted WorkerEvents
211 | New stream_framing.py + FakeDhanTcpServer - real local asyncio TCP server/client
212 | New `manage.py run_market_data_worker` + async_worker.py - real long-lived worker process
213 | New ACTIVE_PRODUCT_SCORECARD.md - grep-verified lifecycle scorecard, corrects stale claim
214 | Bar aggregation now triggers every 5 quotes mid-stream, not only after stream ends
215 | WebSocket library decision RESOLVED: `websockets` (PyPI 17.0.1) selected
216 | `websockets` added to pyproject.toml; new DhanWebSocketTransport (real RFC 6455 client)
217 | `run_market_data_worker` gained --provider fake-ws using real DhanWebSocketTransport
218 | New SignalRecord model + DjangoSignalRepository + GET /api/v1/... signals endpoint
```

**2. Cost model.** `[F]` `CostModel` Protocol at
`src/intraday/research/backtesting/cost_model.py:110`; the one production
implementation is `IndianCashEquityIntradayCostModel` (line 199, `name =
"INDIAN_CASH_EQUITY_INTRADAY"`) — applies to **NSE cash-equity intraday**
trades only (brokerage/STT/exchange-charges/GST/stamp-duty all sized for
that instrument class; no options-specific fee schedule exists anywhere in
the file). Reachability from an `OptionQuoteObservation`-derived instrument:
**`NO_OPTION_BACKTEST_PATH_EXISTS`** — `[F]` `research/backtesting/engine.py`
and `historical_execution.py` only ever operate on `Bar`/`HistoricalBar`
objects; grepping both files plus `application/services/*.py` for
`OptionQuoteObservation` returns zero hits. The backtest engine has no code
path that ever constructs a `Bar` from `OptionQuoteObservation` rows, so the
cost model is unreachable from that table today, not merely untested against
it.

**3. Instrument master.** `[F]` There is **no Django model** named
`InstrumentMaster` anything, and no table `persistence_instrumentmasterentry`
(confirmed absent — RECON-01 was right that this literal name does not
exist). The actual "instrument master" is
`application/services/instrument_master.py::InstrumentMasterEntry` (a plain
`@dataclass`, not an ORM model) sourced live from
`infrastructure/market_data_providers/dhan/instrument_master.py::
DhanInstrumentMasterProvider`, which fetches Dhan's public
`api-scrip-master.csv` — a Protocol/CSV construct, never persisted to
PostgreSQL. Row counts by segment: **`NO_SUCH_TABLE`** — correct and literal,
not a guess-then-fail; there is nothing in `information_schema.tables` for
this codebase's own "instrument master" concept because it was never
designed as a table.

## C. Integrity command + checksum spec (Part 2)

New file: `src/intraday/infrastructure/persistence/management/commands/verify_data_integrity.py`.

- Wraps its entire read side in `transaction.atomic()` + one
  `connection.cursor()`, first statement `SET TRANSACTION ISOLATION LEVEL
  SERIALIZABLE READ ONLY DEFERRABLE`, then `SET LOCAL TimeZone='UTC'`,
  `DateStyle='ISO, YMD'`, `extra_float_digits=3`, `lc_numeric='C'` — pinned
  session settings that differ from this environment's real defaults
  (`ISO, DMY` / `1` / `English_India.1252`, reconfirmed live this run, see
  below).
- `transaction.set_rollback(True)` forces ROLLBACK at the end regardless —
  belt-and-braces on top of `READ ONLY` (there are no writes to roll back;
  this only guarantees nothing this command does can ever finalize one).
- Content checksum: `sha256` over `payload_format_version=1` +
  `\x1e`-joined, `\x1f`-field-delimited canonical rows in fixed column order
  (`id, instrument_id, exchange, symbol, timeframe, bar_timestamp,
  open_price, high_price, low_price, close_price, volume, source,
  provenance, canonicalization_state`), `ORDER BY id`. `Decimal` values use
  `format(value, "f")` (fixed scale, no exponent, no locale); `datetime`
  values are normalized to UTC and ISO-8601'd; `NULL` becomes the literal
  token `\x00NULL\x00`. Never a bare Python `str()` of the whole row.
- Legacy checksum: `sha256(str([(id, bar_timestamp), ...]))` — the exact,
  unmodified 65.x formula, read from the SAME in-snapshot query as the
  content checksum (no second round trip, no risk of a different snapshot).
- Schema fingerprint: `sha256` over `information_schema.columns` rows for
  `persistence_historicalbar` (column_name, data_type, is_nullable,
  char/precision/scale), `ORDER BY ordinal_position`, read inside the same
  snapshot.
- Snapshot identity: `pg_current_snapshot()`, `pg_backend_pid()` captured
  first and last; `pg_current_xact_id()`, `transaction_timestamp()`,
  `pg_current_wal_lsn()`, `current_setting('transaction_isolation')`,
  `pg_control_system().system_identifier`, `current_database()`,
  `server_version_num` captured once.
- Counts (provenance/source/timeframe/distinct-dates-and-symbols-per-
  provenance/`MigrationRun`/`MigrationUnit`/`MigrationRow`) are all read by
  **one** SQL statement (CTEs + scalar subqueries returning `json_agg`).
- Emits JSON to stdout via `self.stdout.write(json.dumps(...))`.

**Environment defaults reconfirmed live this run** (before the command's own
`SET LOCAL` pinning is applied, i.e. this session's ordinary settings):
`DateStyle='ISO, DMY'`, `extra_float_digits='1'`,
`lc_numeric='English_India.1252'`, `server_version_num='160014'`,
`current_database='intraday'` — all `[F]`, matching RECON-01 exactly.

Ran the command three times against the real database this run
(`baseline_run1/2/3`); run1 (before the `transaction.atomic()` fix) showed
`snapshot_matches: false` because Django's default autocommit mode was
giving each `cursor.execute()` its own implicit transaction — a real bug,
caught and fixed before committing anything. runs 2 and 3, after wrapping in
`transaction.atomic()`, both show `snapshot_matches: true`,
`backend_pid_matches: true`, and an **identical** `content_checksum`,
`legacy_id_timestamp_checksum`, and `schema_fingerprint` across both runs.

## D. Full invariant results (against the real, current database)

All eight invariants ran; **all zero-count / clean** on the live
`HistoricalBar` archive:

| invariant | count |
|---|---|
| duplicate (symbol, timeframe, bar_timestamp) | 0 |
| OHLC sanity violations | 0 |
| non-positive prices | 0 |
| negative volume | 0 |
| required-column NULLs | 0 |
| weekend bar timestamps | 0 |
| holiday bar timestamps (non-trading-day) | 0 |
| out-of-session bar timestamps (CAS-aware, per symbol/timeframe) | 0 |

Per-cell bar-count-vs-expected is reported in full in Part F below (1m
archive coverage), not duplicated here — the invariant here only flags rows
whose timestamp falls outside the session's own expected-timestamp set, and
that count is zero.

## E. `UNKNOWN` classification incl. Adani/Tata resolution (Part 3)

Replayed `SyntheticHistoricalBarProvider._synthetic_bar()` against all 5,100
`UNKNOWN` rows using their real `(instrument_id, timeframe, bar_timestamp)`
identity, matching on all five OHLCV fields exactly.

- **Exact match: 3,900 / 5,100.** `[F]` — confirms the prior checkpoint
  §65.12 "~3,900" figure precisely.
- **Non-matches: 1,200.** Root cause identified for all of them: the
  generator's formula caps price at `100 + (seed % 900)` — i.e. **never above
  ~999.xx** — while these 1,200 rows carry real Adani/Tata-group prices in
  the ₹1,000-1,900 range (e.g. `ADANIENSOL` open `1569.40`), a value the
  generator is structurally incapable of producing for ANY seed. 383 of the
  1,200 have an open or close price `> 999` and are classified
  `STRUCTURALLY_IMPLAUSIBLE` (cannot have come from this generator, full
  stop — not "didn't match this run," but "mathematically cannot match any
  run"). The remaining 817 mismatch on OHLCV values but sit within the
  generator's achievable price band; without a second, independent way to
  rule them in or out they are `STRUCTURALLY_PLAUSIBLE_UNVERIFIED`.
- **Partition (query committed below, relabels nothing):**
  - `REPRODUCIBLE_BY_SYNTHETIC_GENERATOR`: 3,900
  - `STRUCTURALLY_PLAUSIBLE_UNVERIFIED`: 817
  - `STRUCTURALLY_IMPLAUSIBLE`: 383
- **Adani/Tata thematic-fetch reading — resolved with evidence, not
  convenience.** The 22 `UNKNOWN` symbols and 9-trading-day `5m`-only window
  do look like a deliberate human fetch. But 3,900 of the 5,100 rows
  (76.5%) reproduce EXACTLY, byte-for-byte on all five OHLCV fields, under a
  pure deterministic hash of `(instrument_id, timeframe, bar_timestamp)` —
  a coincidence rate of essentially zero for real market data (real OHLCV
  cannot be re-derived from a SHA-256 of its own identity). The correct
  reading is: **the "thematic" symbol/date selection describes what was
  REQUESTED (a plausible operator fetch pattern), not what was RETURNED**
  — most of what was returned for that request came from the synthetic
  fallback path (same `HistoricalDataPreparationService` codepath
  `synthetic_historical.py`'s own docstring says exists), not real Dhan
  data. The 1,200 non-matching rows (23.5%) are the genuinely open
  question — plausibly a MIX of real Dhan data (explaining prices >999,
  a range the synthetic generator cannot reach) fetched in the same
  operator session, alongside more synthetic rows that happen not to
  match (e.g. if the provider or seed inputs changed between generator
  versions). **UNPROVEN HISTORICAL FACT**, not resolved further than this
  without provenance-relabeling, which P4/this checkpoint's own scope
  forbid.
- **Negative control:** replayed the same formula against 500 random
  `REAL_DHAN` rows. **0/500 matched.** `[F]` No HALT condition triggered.

## F. 1m coverage / `TRADING_GRADE_BAR` reachability (Part 4)

`HistoricalBar` archive table only (not today's live
`AggregatedBarObservation` rows, a separate, not-yet-archived pipeline).

- `1m` bar total: **880** rows, all `REAL_DHAN` provenance, across 5
  symbols (`RELIANCE`, `TCS`, `INFY`, `HDFCBANK`, ...) and several trading
  dates. `[F]`
- Per (symbol, trading_date) `1m` count: **44** bars observed for every
  cell sampled (top-10 by count, all exactly 44) versus an expected
  **375** for a full continuous session — **44/375 ≈ 11.7% coverage**.
  `[F]`
- `MarketDataArchiveDay.status` distribution: `IN_PROGRESS` = 19,
  `PARTIAL` = 16, **`COMPLETE` = 0**. `[F]` No cell is currently
  `COMPLETE`.
- `TRADING_GRADE_BAR` reachability: **not reachable on current archive
  data**, structurally, not just empirically. `evaluate_bar_promotion()`
  (`domain/market_data/promotion.py`) requires a live `AggregatedBar`
  object carrying `BarStatus`, `observation_count`, a `TradingSession`, and
  a `connection_is_healthy` flag — none of which `HistoricalBar` rows
  carry (`HistoricalBar` has no `status`/`observation_count`/session
  linkage columns at all). The gate's six conditions
  (`BAR_IS_CLOSED`, `SESSION_IS_OPEN`, `NO_DUPLICATE_OR_OUT_OF_ORDER`,
  `NO_GAP_BEFORE_THIS_BAR`, `CONNECTION_HEALTHY`,
  `SUFFICIENT_OBSERVATIONS`) are evaluable only against the LIVE
  aggregation pipeline's `AggregatedBar`/`LiveQuoteObservation` inputs, a
  different table entirely from this checkpoint's read scope (and one this
  checkpoint is explicitly forbidden from touching while 67.12.2-E's
  worker uses it). Verdict: **0 of 6 conditions currently evaluated** for
  any archived `HistoricalBar` row — the gate has never been run against
  this table because it cannot be, by construction.

## G. Stale comment / gate trace (Part 5)

**Stale comment**, `backtesting_views.py::_prepare_if_needed`, lines
124-128:

> "Checkpoint 65.12 note (65.01's root-cause bug #2): this still
> unconditionally constructs `SyntheticHistoricalBarProvider()` for every
> non-fixture instrument, because NO real Dhan historical-candle adapter
> exists in this codebase yet — there is nothing else to select between..."

`[F]` False as written: `DhanHistoricalBarProvider`
(`infrastructure/market_data_providers/dhan/historical_provider.py:351`) IS
a real Dhan historical-candle adapter and does exist. The exact one-line
change that would select it (**not made**, per instructions):

```python
provider = SyntheticHistoricalBarProvider()
```
→
```python
provider = _select_historical_bar_provider()
```
(the same selector function `tasks.py:256` already uses for the
multi-instrument path — reusing it here is the one-line fix; not applied.)

**`ResearchDataGateService`/`is_research_eligible` call sites:** exactly two
places construct a live `ResearchDataGateService` —
`backtesting_views.py:108` (single-instrument REST endpoint, via
`BacktestingService.for_database_backed_research(..., research_gate=...)`)
and `tasks.py:272` (multi-instrument historical-run panel, same
`for_database_backed_research()` factory). Both go through
`for_database_backed_research()`, which requires `research_gate` as a
**mandatory keyword argument** — there is no plain-dataclass-constructor
path that can build a `BacktestingService` without one (per the Checkpoint
66.2 comment at `tasks.py:258-263`). **A default `RESEARCH` backtest run
PASSES THROUGH the gate — it does not bypass it.** `[F]`

## H. Test results

`pytest tests/unit/infrastructure/persistence/management/
test_verify_data_integrity_command.py -q` → **20 passed, 0 failed** (one
false-positive on the structural zero-write scan was caught and fixed
before commit — the first version of that test matched `hasher.update(`,
a hashlib call, not an ORM mutation; narrowed the token list). Covers:
zero-write structural proof, zero-write runtime proof, checksum stability
across two runs, checksum change on `close_price` mutation (with legacy
checksum PROVEN blind to the same mutation), checksum change on
`provenance` mutation (same blind-spot proof), legacy-formula-reproduction
proof, row-reordering invariance (`VACUUM FULL` + `REINDEX` on the test
DB), session-setting invariance (`DateStyle`/`extra_float_digits`/
`lc_numeric` changed on the raw connection, checksum unaffected because the
command pins its own `SET LOCAL`s), snapshot-identity match, and each of
5 of the 8 invariants both positive and negative (duplicate, OHLC sanity,
non-positive price, negative volume, weekend timestamp — required-column-
NULLs tested negative only, since Django model field constraints make a
NULL required-column row impossible to construct through the ORM fixture
path used here).

## I. `[CONFLICT]` register

- `[CONFLICT]` `backtesting_views.py`'s own in-repo comment ("no real Dhan
  historical adapter exists") vs. the actual code
  (`DhanHistoricalBarProvider` exists and is used elsewhere) — see Part G.
  Not fixed (out of scope; report only).
- `[CONFLICT]` none found between this run's live counts and the
  previously-recorded `TOTAL=16,542 / REAL_DHAN=11,442 / UNKNOWN=5,100` —
  they match exactly, so today's live 67.12.2-E capture is confirmed NOT
  to be adding to `HistoricalBar` (as expected — it writes
  `LiveQuoteObservation`/`AggregatedBarObservation` only).

## J. Remaining blockers

None for this checkpoint's own scope. Open items for future checkpoints:
the 817 `STRUCTURALLY_PLAUSIBLE_UNVERIFIED` rows remain genuinely
unresolved (see Part E) — no further evidence exists in this repo to
adjudicate them without either a second independent generator-fingerprint
or actual Dhan API confirmation, both out of this checkpoint's scope.

## K. Recommended next checkpoint

Build a SECOND, independent discriminator for the 817
`STRUCTURALLY_PLAUSIBLE_UNVERIFIED` `UNKNOWN` rows — e.g. checking whether
their `ingested_at` timestamps cluster with the 3,900 exact matches (same
operator session, same provider call) vs. with the 383 confirmed-
implausible rows (different session) — rather than attempting a third
provenance heuristic on OHLCV values alone, which this checkpoint's Part E
already showed is not decisive for prices that happen to land in the
generator's achievable band by chance.
