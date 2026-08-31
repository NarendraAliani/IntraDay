# Checkpoint 67.1 — Dhan OPEN-Timestamp Normalization + Canonical Bar Interval Contract + Safe Migration Design

STATUS: ready for review. Zero Dhan network calls made. Zero database mutation performed. No migration executed. No commit/push.

## A. Current raw-to-canonical pipeline (BEFORE this checkpoint)

`historical_client.py::_candles_from_payload()` parses Dhan's raw parallel-array
response into `DhanHistoricalCandle(timestamp=datetime.fromtimestamp(raw_epoch_seconds, tz=UTC), ...)`
— `timestamp` here is exactly Dhan's raw epoch value, no semantic label attached.

`historical_provider.py::DhanHistoricalBarProvider.fetch()`:
1. Computes `envelope = _provider_request_envelope(start, end, interval_minutes)` —
   `from_time = canonical_start - one_bar`, `to_time = canonical_end` (lower widening only,
   66.8 state, unchanged).
2. Calls `fetch_intraday_candles(from_time=envelope.from_time, to_time=envelope.to_time)`.
3. **(the bug)** `return tuple(_candle_to_bar(...) for candle in candles if start <= candle.timestamp <= end)`
   — the `[start, end]` filter ran on `candle.timestamp`, i.e. the **raw, unshifted** Dhan
   timestamp, and `_candle_to_bar()` copied that raw timestamp verbatim into `Bar.timestamp`
   with no transform at all.

`HistoricalDataCoverageService` / `ResearchDataGateService` are both downstream of `Bar.timestamp`
and already treat it as canonical bar-close — they were never part of the bug; they simply
inherited whatever `Bar.timestamp` value the provider handed them.

## B. Exact filtering order (audit finding)

**The filter ran BEFORE canonicalization — and canonicalization did not exist at all.**
Concretely: raw candle timestamp → `start <= candle.timestamp <= end` filter → `_candle_to_bar()`
copies the (already-filtered) raw timestamp verbatim → persisted as `Bar.timestamp`. This is
precisely the wrong order the checkpoint directive warned against, and worse — no shift was ever
applied, so every persisted `REAL_DHAN` row's `Bar.timestamp` is Dhan's raw OPEN timestamp,
silently treated by the rest of the system as if it were bar-CLOSE.

**Fixed order (now):** raw candle → `_candle_to_bar()` canonicalizes (`raw_timestamp + interval`
for OPEN semantics) → returns a `Bar` with a canonical timestamp → `fetch()`'s filter runs on
`bar.timestamp <= end` and `start <= bar.timestamp`, i.e. on the **canonicalized** value. See the
worked example in F.

## C. Canonical timestamp contract

Unchanged and re-confirmed, not invented this checkpoint: `Bar.timestamp` (domain.market_data.contracts.Bar)
is bar-CLOSE, UTC, everywhere in the application — `HistoricalDataCoverageService._expected_timestamps`,
`ResearchDataGateService`, and every session-boundary calculation all already assume this. 67.1 makes
the Dhan adapter actually honor that contract instead of silently violating it.

## D. Provider timestamp convention contract (Part 2 design)

New module: `src/intraday/domain/market_data/source_timestamp.py` (created this checkpoint).
Deliberately the smallest possible design — one enum, one pure function, no new Bar variant:

- `SourceTimestampSemantics` enum: `OPEN`, `CLOSE`, `UNKNOWN`. `UNKNOWN` is not a "safe default" —
  it exists precisely so an unproven provider/endpoint can be represented honestly, and
  `canonicalize_close_timestamp()` **raises** (`UnknownSourceTimestampSemanticsError`) rather than
  guessing when given it.
- `canonicalize_close_timestamp(raw_timestamp, semantics, interval_duration) -> datetime`: pure
  arithmetic — `OPEN` → `raw + interval_duration`; `CLOSE` → `raw` unchanged; `UNKNOWN` → raises.
  Generic across every interval; never hard-codes a clock time, symbol, or category (mirrors the
  existing `_provider_request_envelope` discipline).

This is provider-agnostic by design — a second future broker/vendor adapter would classify its own
convention (`OPEN`/`CLOSE`/`UNKNOWN`) and reuse the same function, rather than each provider
reinventing its own shift logic.

## E. Exact production correction

File: `src/intraday/infrastructure/market_data_providers/dhan/historical_provider.py`.

- Added `_DHAN_INTRADAY_TIMESTAMP_SEMANTICS = SourceTimestampSemantics.OPEN` (the 67.0-proven
  classification for Dhan's `/v2/charts/intraday` endpoint) and
  `_DHAN_DAILY_TIMESTAMP_SEMANTICS = SourceTimestampSemantics.CLOSE` (daily endpoint untouched —
  out of 67.0's tested scope, and its existing raw-timestamp-as-canonical behavior is preserved
  exactly, not reclassified as proven).
- `_candle_to_bar()` now takes `semantics` and `interval_duration` keyword args and calls
  `canonicalize_close_timestamp()` to produce `Bar.timestamp`, instead of copying `candle.timestamp`
  verbatim.
- `fetch()` now builds `bars = tuple(_candle_to_bar(...) for candle in candles)` first (this is
  where canonicalization happens), and only then applies
  `tuple(bar for bar in bars if start <= bar.timestamp <= end)` — the filter is now unconditionally
  downstream of canonicalization for both the daily and intraday branches.
- `_provider_request_envelope()` arithmetic is **untouched**: `from_time = canonical_start - one_bar`,
  `to_time = canonical_end`. The pipeline audit did not require changing it — the envelope governs
  what is *requested* from Dhan (raw OPEN-labeled space), while the fix governs what happens to the
  response *after* it comes back; these remain correctly separate concerns.

## F. Why the correction does not lose the first/last candle — worked example

5m canonical research window `[09:20, 15:15]` IST (`[03:50, 09:45]` UTC).

- Envelope sent to Dhan: `from_time = 03:45 UTC` (09:15 IST, lower-widened), `to_time = 09:45 UTC` (15:15 IST).
- Dhan returns raw OPEN candles `09:15, 09:20, ..., 15:10` IST.
- **Before this checkpoint:** filter ran on raw timestamps: `09:15 IST (03:45 UTC) < start (03:50 UTC)`
  → **dropped**. The very candle that should have become the canonical 09:20 close was discarded
  before it ever got the chance to be shifted (in fact, no shift existed at all, so even the
  candles that passed the filter were persisted under the wrong, raw-OPEN timestamp).
- **After this checkpoint:** every raw candle is canonicalized first: `09:15 → 09:20`, ...,
  `15:10 → 15:15`. The filter then runs on canonical values: `09:20` passes (`== start`), `15:15`
  passes (`== end`). Both boundary bars are retained, and every interior bar now carries its
  correct canonical bar-close timestamp instead of its raw OPEN timestamp.

## G. Tests added

New: `tests/unit/domain/market_data/test_source_timestamp.py` (3 tests — OPEN shift, CLOSE
no-op, UNKNOWN raises — covers Part 6 test case 8).

Modified/added in `tests/unit/infrastructure/market_data_providers/dhan/test_historical_provider.py`:
- Rewrote the two pre-existing post-filter tests (`test_fetch_post_filter_still_bounds_returned_bars_to_the_requested_window`,
  `test_fetch_post_filter_excludes_a_candle_past_the_canonical_end`) — their old assertions encoded
  the pre-fix (buggy) raw-timestamp-filter behavior and would otherwise now be wrong; they are
  updated to assert the corrected canonicalize-then-filter behavior.
- Added 7 new tests directly covering Part 6 cases 1–7:
  - `test_raw_0915_ist_candle_canonicalizes_to_0920_ist_close_for_5m` (case 1)
  - `test_raw_1510_ist_candle_canonicalizes_to_1515_ist_close_for_5m` (case 2)
  - `test_canonical_filtering_retains_both_boundary_candles_together` (case 3)
  - `test_raw_timestamps_are_not_filtered_before_canonicalization` (case 4)
  - `test_candles_outside_canonical_range_are_excluded` (case 5)
  - `test_no_synthetic_candle_is_created_by_canonicalization` (case 6)
  - `test_canonicalization_arithmetic_is_generic_across_every_intraday_interval` — parametrized
    over 1m/5m/15m/1h (case 7; generic arithmetic only, explicitly not claimed as empirically
    validated for anything but 5m, per the checkpoint's hard rule)
- Case 8 (unknown semantics not silently OPEN) is covered in `test_source_timestamp.py`.

All tests are local, deterministic, and mock `fetch_intraday_candles`/`fetch_daily_candles` — no
network call, no DB access, no Dhan credentials.

## H. Test results

```
tests/unit/infrastructure/market_data_providers/dhan/test_historical_provider.py
tests/unit/domain/market_data/test_source_timestamp.py
22 passed, 1 warning (pre-existing schemathesis deprecation warning, unrelated)
```

Also re-ran (unmodified, sanity check only — not part of Part 6's required set):
```
tests/unit/application/services/test_historical_data_coverage.py
tests/unit/application/services/test_research_data_gate.py
18 passed
```
No full regression suite was run (per Part 15's NO/LESS/LIMITED instruction).

## I. Existing REAL_DHAN projected impact (read-only audit, Part 8)

Queried directly via Django ORM (`HistoricalBar.objects.filter(provenance='REAL_DHAN')`),
read-only, no writes:

| timeframe | row count | current min bar_timestamp (UTC) | current max bar_timestamp (UTC) |
|---|---|---|---|
| 1m | 880 | 2026-08-24 03:46 | 2026-08-28 04:29 |
| 5m | 10,562 | 2026-07-29 03:50 | 2026-08-28 09:40 |

Total REAL_DHAN = 11,442 (880 + 10,562), matching the expected count. Every one of these rows is a
candidate for the `raw_timestamp + interval` correction (projected new min/max = current min/max +
one interval per timeframe: 1m → +1 minute, 5m → +5 minutes). No SYNTHETIC_TEST rows exist (0), so
no synthetic bars are implicated.

## J. Collision analysis

Computed by comparing, for every REAL_DHAN row, `(instrument_id, shifted_timestamp)` against the
full existing `(instrument_id, timestamp)` set for that timeframe (read-only, no writes):

| timeframe | rows checked | rows whose `+interval` timestamp collides with an EXISTING row |
|---|---|---|
| 1m | 880 | 860 |
| 5m | 10,562 | 10,409 |
| **Total** | **11,442** | **11,269** |

This is exactly the expected consequence of contiguous intraday series: shifting bar N forward by
one interval lands it on bar N+1's existing (pre-migration) raw timestamp, which is itself present
as another REAL_DHAN row. **A naive `UPDATE bar_timestamp = bar_timestamp + interval` would violate
the `(instrument_id, timeframe, bar_timestamp)` unique constraint for ~98.5% of rows.** This
confirms the directive's explicit warning and is the central input to the migration design below.

## K. Safe migration design (Part 7 — DESIGN ONLY, not executed)

1. **Transaction boundary.** One DB transaction per `(instrument_id, timeframe)` partition (or the
   whole table, if lock duration is acceptable) — never row-by-row autocommit, so a failure midway
   leaves the prior state intact.
2. **Collision-free temporary namespace.** Within the transaction, first shift every affected row's
   `bar_timestamp` into a namespace that cannot collide with either the old or new canonical values
   — e.g. `bar_timestamp = bar_timestamp - LARGE_OFFSET` (a duration far outside any real trading
   calendar, such as 100 years), or add a temporary `migration_offset_applied` boolean/marker column.
   This two-phase shift (into temp space, then into final space) is the standard safe pattern for an
   in-place unique-key shift where the shift ranges overlap.
3. **Final canonical shift.** In the same transaction, shift from the temporary namespace to
   `bar_timestamp = original_bar_timestamp + interval_duration` (the real target value) — now
   collision-free because the temp-namespace pass already vacated every original slot.
4. **Uniqueness verification.** Before commit, assert `SELECT instrument_id, timeframe, bar_timestamp, COUNT(*) FROM historical_bar GROUP BY 1,2,3 HAVING COUNT(*) > 1` returns zero rows.
5. **Completeness verification.** Re-run `HistoricalDataCoverageService.get_coverage(...)` for a
   sample of previously-complete `(instrument_id, timeframe, date)` ranges and confirm
   `is_complete` still holds post-shift, with the *same* expected-timestamp set (canonical
   boundaries 09:15/15:15/15:30 unchanged) — a mechanical safety net that the shift did not silently
   create a new gap at either end of any trading day.
6. **Idempotency.** The migration must be safe to re-run: a `provenance='REAL_DHAN'` row already
   bearing the post-shift marker/flag is skipped on a second pass (e.g. a
   `migration_67_1_timestamp_shifted` boolean column, or simply detecting the row's timestamp is
   already `> 09:15` IST-equivalent minute-aligned to the shifted grid — a marker column is safer
   and unambiguous).
7. **Reversibility.** Because the shift is a pure `+interval_duration` transform, the exact inverse
   (`-interval_duration`, through the same temp-namespace two-phase pattern) is always available for
   as long as the marker column / audit log survives — this migration should not delete the
   pre-migration timestamps outright without first writing them to an audit table.
8. **Auditability.** Every row touched should be logged (row id, old timestamp, new timestamp,
   batch id) to a separate migration-audit table or structured log before commit, so the exact set
   of changed rows is independently reconstructable later.
9. **Execution boundary NOT crossed this checkpoint.** No step above was run against the database —
   this is a written design only, per the directive's explicit Part 7 instruction.

## L. CAS implications (Part 9)

The 66.3 70-bar CATEGORY_I_CAS sample's raw timestamps, if drawn from Dhan's intraday endpoint, are
subject to the same OPEN mislabeling as every other REAL_DHAN row analyzed in I/J. The CAS-aware
session boundary (continuous trading ends 15:15 IST, followed by the 15:15–15:35 IST closing-auction
window, per `HistoricalDataCoverageService`'s 65.27 docstring) is a canonical bar-CLOSE boundary — so
under the OPEN-labeling finding, a raw candle timestamped 15:10 IST is the LAST valid continuous-session
candle and canonicalizes correctly to the 15:15 IST close, exactly at the CAS boundary. This is
consistent, not newly broken, by the OPEN-labeling finding — but it means any of the 66.3 CAS sample's
rows that were inspected/asserted against their *raw* (currently-persisted, unshifted) timestamps were
implicitly inspected under the wrong label; no conclusion drawn from that sample's OHLC values changes
(OHLC values themselves are untouched by this checkpoint), only which canonical close-time each set of
OHLC values should be attributed to.

## M. Non-CAS implications (Part 9)

CATEGORY_II_NON_CAS instruments use the unchanged uniform 09:15–15:30 IST session
(`build_session_for` + `expected_bar_timestamps`), with no closing-auction carve-out. The same OPEN→CLOSE
relabeling applies uniformly: every raw candle in the 66.3 70-bar non-CAS sample should be understood as
representing the interval `[raw, raw+interval)`, so its canonical bar-close is `raw+interval`, not `raw`.
Because non-CAS has no auction-window boundary complication, the implication is simpler than CAS: the
entire non-CAS sample's canonical timestamps shift uniformly by one interval, with no boundary-adjacent
special case to reason about.

**Neither CAS nor non-CAS 66.3 sample data was re-read, re-fetched, or mutated this checkpoint** — this
is an on-paper analysis of what the (already-established) OPEN finding implies for data already
described in that checkpoint's own report.

## N. Research-gate impact (Part 11)

`ResearchDataGateService` (`research_data_gate.py`) and `HistoricalDataCoverageService`
(`historical_data_coverage.py`) were read in full this checkpoint and require **no code change**:
both already operate exclusively on `Bar.timestamp`/`HistoricalBar.bar_timestamp` treating it as
canonical bar-close (coverage's `_expected_timestamps`, the gate's provenance + completeness checks).
They were never the source of the bug — they inherited whatever timestamp the provider persisted.
`REAL_DHAN` provenance alone still does not equal research-ready: `ResearchDataGateService` still
requires 100% `HistoricalDataCoverageService.is_complete` (exact expected-timestamp-set match) AND
100% `REAL_DHAN` provenance before returning `ResearchEligibleBars` — unchanged, unweakened.

**Important caveat this checkpoint surfaces but does not resolve:** the gate's completeness check
compares existing DB timestamps against the canonical expected set. The 11,442 currently-persisted
REAL_DHAN rows still carry their OLD (unshifted, raw-OPEN) timestamps — they were correctly excluded
from this checkpoint's code changes (Part 13's hard rule). This means, going forward, *newly
ingested* Dhan intraday bars will be correctly canonicalized by the fixed provider, but they will not
line up on the same timestamp grid as the *existing* 11,442 rows until the Part 7 migration is
actually executed — a future checkpoint's job, not this one's.

## O. Backtest look-ahead risk (Part 12)

Not run, not modified, per hard rules. Assessment only: if a future backtest reads the *existing*
(pre-migration) 11,442 REAL_DHAN rows through `ResearchDataGateService`/`BacktestingService` without
first running the Part 7 migration, every bar's `Bar.timestamp` is still its raw Dhan OPEN timestamp
mislabeled as a CLOSE. A backtest engine that (correctly, per the canonical contract) treats
`Bar.timestamp` as "this bar's OHLC became fully known at this instant" would therefore believe each
bar's OHLC (in reality only knowable at `raw_timestamp + interval`) was knowable one full interval
EARLIER than it actually was — a clean, structural look-ahead bias of exactly one bar-duration,
uniform across every existing REAL_DHAN row. This is a real risk for any backtest run against the
current, unmigrated data, and is exactly why Part 7's migration exists as a next step — but per Part
12's explicit instruction, the backtest engine itself was not modified this checkpoint, since the
correct fix is upstream (the data itself, via the Part 7 migration), not the engine's timestamp
semantics.

## P. Gainz impact

Not touched, not executed, not analyzed beyond noting it is a consumer of backtest data and
therefore inherits whatever look-ahead risk O describes, once/if it reads unmigrated REAL_DHAN data
through the same research gate. No Gainz-specific code exists in the changes made this checkpoint.

## Q. Database before/after

Before: TOTAL=16,542, REAL_DHAN=11,442, UNKNOWN=5,100, SYNTHETIC_TEST=0 (verified via
`HistoricalBar.objects.values('provenance').annotate(Count('id'))`).

After: TOTAL=16,542, REAL_DHAN=11,442, UNKNOWN=5,100, SYNTHETIC_TEST=0 — **byte-identical**,
re-verified via the identical query after all code/test changes were made. Zero rows were read
with any UPDATE/DELETE statement issued against `HistoricalBar` this checkpoint — all DB access
was read-only `SELECT`/aggregate queries for Part 8/Q verification.

## R. 358-vs-360 status

Unchanged, still DEFERRED. Not investigated this checkpoint, no new Dhan call made toward it, per
Part 10/hard rules. Not reopened.

## S. Missing-15:15 status

Unchanged, still an open thread — but this checkpoint's OPEN-labeling fix directly bears on it:
the raw candle Dhan does return at 15:10 IST now correctly canonicalizes to 15:15 IST, which is
exactly the "missing" close that the 66.7 diagnostic could not produce by widening `to_time`. This
strongly suggests (on paper, consistent with 66.7/67.0's own reasoning, not re-verified by any new
call this checkpoint) that the "missing 15:15 bar" was never a genuinely absent candle — it was
always present as the raw 15:10 IST OPEN candle, just mislabeled. No new Dhan call was made to
confirm this beyond what 67.0 already established; this remains an inference, not a re-run
diagnostic.

## T. Whether additional Dhan data is required

No. This checkpoint required none and made none (Part 14 hard rule honored). Confirmation: no
`httpx.post`, no `fetch_intraday_candles`/`fetch_daily_candles` real call, no scrip-master call —
every test mocks the client-layer functions.

## U. Remaining blockers

1. The Part 7 migration is designed but not executed — the 11,442 existing REAL_DHAN rows remain
   on their old, raw-OPEN timestamp grid until a future checkpoint runs it.
2. Newly-ingested Dhan intraday bars (post-67.1) and the not-yet-migrated existing rows are on two
   different timestamp grids for the same underlying candles until migration runs — a real
   operational hazard if both get read together before the migration lands.
3. 1m/15m/1h canonicalization arithmetic is implemented generically but remains empirically
   unvalidated beyond the 5m case 67.0 tested — no further Dhan call was made to close this gap,
   per the hard rules.
4. 358-vs-360 and any residual missing-bar questions beyond the 15:15 inference in S remain
   formally open.

## V. ONE recommended next checkpoint

**Checkpoint 67.2 — Execute the Part 7 migration** (with a mandatory pre-flight dry run): run the
collision-free two-phase timestamp shift against the 11,442 REAL_DHAN rows inside a single
transaction, with the uniqueness and completeness verification steps from K executed as hard gates
(abort and roll back on any failure), followed immediately by a read-only re-verification of DB
counts (16,542/11,442/5,100/0 unchanged) and a coverage-service spot-check on a handful of
previously-complete date ranges — before any backtest or Gainz work is allowed to read REAL_DHAN
data again.

---

## 16. Git state (Part 16)

`git status --short`, `git diff --stat`, `git diff --name-only`, `git log -3 --oneline` were all
captured directly this checkpoint. Files changed/added **by 67.1 specifically**:

- Modified: `src/intraday/infrastructure/market_data_providers/dhan/historical_provider.py`
  (canonicalization fix — Parts A–F).
- Modified: `tests/unit/infrastructure/market_data_providers/dhan/test_historical_provider.py`
  (2 tests rewritten, 7 tests added — Part G).
- Added: `src/intraday/domain/market_data/source_timestamp.py` (Part 2/D design).
- Added: `tests/unit/domain/market_data/test_source_timestamp.py` (3 tests — Part G/case 8).
- Rewritten: `taskReport.md` (this file, overwritten not appended).

Everything else appearing in `git status --short`/`git diff --stat` (`historical_bars.py`,
`backtesting.py`, `celery.py`, `calendar.py`, the `api/*` files, `historical_bar_repository.py`,
`research_data_gate.py`, `research_bar.py`, `resolver.py`, `test_historical_data_coverage.py`,
`test_active_loop_runtime.py`, `research/datasets/`, `test_eod_sequence_task.py`,
`test_celery_beat_schedule.py`) is **pre-existing work from prior checkpoints (65.x/66.x)**, already
present in the working tree before this checkpoint began and not touched by it. No commit, no push,
performed this checkpoint.

**STOP after 67.1, per instruction — awaiting review before any further checkpoint.**
