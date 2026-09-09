# CHECKPOINT 84 — Scale Migration to Remaining Interior Gap (9 days × 4 symbols)

```
directive: scale CHECKPOINT_83's proven mechanism to the rest of the
           2026-08-17–08-28 interior gap (9 remaining real trading
           days x 4 symbols)
units targeted: 36 (9 days x 4 symbols)
units committed: 35
units skipped (pre-existing, correctly ineligible): 1
           (TCS, 2026-08-24 — provenance=UNKNOWN, not REAL_DHAN)
gate failures: 0 — every attempted unit passed all 3 gates cleanly
full_suite_result: 7 failed / 3391 passed — identical to CHECKPOINT_83
           (same 5 known pre-existing + 2 known --reuse-db flakes),
           zero new/unexplained failures
new gate-verified day count: 18 — UNCHANGED from before this checkpoint
47-day tuning threshold met: NO
commit: (recorded below)
```

## Part 0 — Pre-flight

`[F]` Confirmed via `ls`/`git status` before writing: `CHECKPOINT_84_SUMMARY.md`
did not already exist. Git tree was clean (only the deliberately-
uncommitted `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md` present) before this
checkpoint's own writes began.

## Part 1 — Pre-scan (read-only, before any write)

`[F]` A read-only dry-run scan across all 36 candidate `(symbol, day)`
slots (9 days `2026-08-18`–`08-28` × 4 symbols) found:
- `2026-08-22`/`08-23` were never candidates at all — confirmed these
  are Saturday/Sunday, not real trading days (9 real trading days in
  the range, matching the directive's own count).
- 35 of 36 slots: `DRY_RUN_SAFE`, `PROVEN`, row counts 62–70 (never
  uniform — confirmed per-unit, not assumed), all comfortably under
  the 200-row ceiling.
- **1 slot, TCS/`2026-08-24`, was absent from the dry-run plan
  entirely.** Investigated directly rather than assumed benign: all 71
  rows for that day carry `provenance=UNKNOWN` (not `REAL_DHAN`), so
  the dry-run's own eligibility filter correctly excludes the whole
  day — there is nothing for this migration path to touch. Confirmed
  this is a genuine, pre-existing data characteristic, not a bug:
  TCS/`2026-08-18` and `2026-08-19` show the same pattern *partially*
  (62/70 rows `REAL_DHAN`-eligible, the other 8 already `UNKNOWN`/
  `NOT_APPLICABLE`) — `2026-08-24` is simply the case where ALL 71 of
  that day's rows happen to be `UNKNOWN`. **This checkpoint therefore
  targets 35 real units, not 36** — reported plainly rather than
  silently working around it.

## Part 2 — Execution, one unit at a time

`[F]` Every one of the 35 eligible units was processed by a driver
script that, per unit, in order: (1) ran a **fresh, full dry-run**
(never reused across units — re-derived from the live database every
single iteration, per the design's own replay/staleness protection);
(2) selected that unit's own result and confirmed `DRY_RUN_SAFE` and
`row_count <= 200`; (3) built a **fresh canary backup /
scope fingerprint** for that unit only via `build_canary_backup()`;
(4) invoked the real `migration_production_execute` management
command with that fresh fingerprint and
`--i-have-reviewed-this-real-write`; (5) confirmed the write's own
postcondition (`canonicalization_state=CANONICALIZED` row count
exactly equals that unit's own dry-run `row_count`) before proceeding
to the next unit. **The loop was configured to stop immediately and
report on any gate failure, unsafe state, ceiling breach, or
postcondition mismatch — none of the 35 units triggered this.**

`[F]` One assumption inside the driver's own postcondition check was
initially too strict (it compared `canonicalization_state=CANONICALIZED`
count against the day's TOTAL row count, not the unit's own eligible
`row_count`) and correctly halted execution on TCS/`2026-08-18`
(`canon=62, total=70`). Investigated directly before resuming: the
other 8 rows for that day are the same pre-existing `UNKNOWN`-
provenance rows noted in Part 1 — untouched, exactly as intended. This
was a check-logic error in this checkpoint's own driver, not a
migration defect; the check was corrected (compare against
`row_count`, not `total_count`) and execution resumed from the next
unit. No unit's own write was ever repeated or retried — each of the
35 real writes ran exactly once.

`[F]` **Result table** (unit → row count → outcome), all 35 attempted
units:

| Symbol | Day | Row Count | Outcome |
|---|---|---|---|
| RELIANCE | 08-18 | 70 | COMMITTED |
| RELIANCE | 08-19 | 70 | COMMITTED |
| RELIANCE | 08-20 | 70 | COMMITTED |
| RELIANCE | 08-21 | 70 | COMMITTED |
| RELIANCE | 08-24 | 70 | COMMITTED |
| RELIANCE | 08-25 | 70 | COMMITTED |
| RELIANCE | 08-26 | 70 | COMMITTED |
| RELIANCE | 08-27 | 70 | COMMITTED |
| RELIANCE | 08-28 | 70 | COMMITTED |
| TCS | 08-18 | 62 | COMMITTED |
| TCS | 08-19 | 62 | COMMITTED |
| TCS | 08-20 | 70 | COMMITTED |
| TCS | 08-21 | 70 | COMMITTED |
| TCS | 08-24 | — | SKIPPED (provenance=UNKNOWN, not REAL_DHAN — not in plan) |
| TCS | 08-25 | 70 | COMMITTED |
| TCS | 08-26 | 70 | COMMITTED |
| TCS | 08-27 | 70 | COMMITTED |
| TCS | 08-28 | 70 | COMMITTED |
| HDFCBANK | 08-18 | 70 | COMMITTED |
| HDFCBANK | 08-19 | 70 | COMMITTED |
| HDFCBANK | 08-20 | 70 | COMMITTED |
| HDFCBANK | 08-21 | 70 | COMMITTED |
| HDFCBANK | 08-24 | 70 | COMMITTED |
| HDFCBANK | 08-25 | 70 | COMMITTED |
| HDFCBANK | 08-26 | 70 | COMMITTED |
| HDFCBANK | 08-27 | 70 | COMMITTED |
| HDFCBANK | 08-28 | 70 | COMMITTED |
| INFY | 08-18 | 70 | COMMITTED |
| INFY | 08-19 | 70 | COMMITTED |
| INFY | 08-20 | 70 | COMMITTED |
| INFY | 08-21 | 70 | COMMITTED |
| INFY | 08-24 | 70 | COMMITTED |
| INFY | 08-25 | 70 | COMMITTED |
| INFY | 08-26 | 70 | COMMITTED |
| INFY | 08-27 | 70 | COMMITTED |
| INFY | 08-28 | 70 | COMMITTED |

**35/35 attempted units COMMITTED. Zero gate failures, zero refusals,
zero unexpected outcomes.**

## Part 3 — Verification at full scale

`[F]` **Every migrated row's `canonicalization_state`**, direct query
across all 35 target units, filtered to `provenance=REAL_DHAN` (the
only rows this migration path ever touches): **zero mismatches** — all
2,434 `REAL_DHAN` rows across the 35 units are `CANONICALIZED`.

`[F]` **P4 at full scale**:
- Table-wide duplicate-key check (`(instrument_id, timeframe,
  bar_timestamp)` grouped, `count > 1`) across the ENTIRE
  `HistoricalBar` table (55,134 rows): **0 duplicates**.
- Total table row count: **55,134** — identical to `CHECKPOINT_83`'s
  own post-write count. No inserts, no deletes (the write mechanism is
  UPDATE-only, unchanged from `CHECKPOINT_83`).
- Total `CANONICALIZED` rows in the whole table: **7,688** — up from
  5,254 (`CHECKPOINT_83`'s own count) by exactly **2,434**, matching
  this checkpoint's own total precisely.
- Audit tables confirm scope directly: **36** total `MigrationUnit`
  rows exist in the whole database (1 from `CHECKPOINT_83` + 35 from
  this checkpoint), **all `status=COMMITTED`**; **2,504** total
  `MigrationRow` audit rows (70 + 2,434) — exactly matching, nothing
  more.
- Broader spot-check sample (30 rows), proportional to this
  checkpoint's larger scope: 15 random rows from before the gap
  (`< 2026-08-17`) and 15 from after it (`> 2026-08-28`), across all
  instruments in the table (including symbols never touched by this
  migration, e.g. `ADANIGREEN`, `ATGL`) — all show plausible,
  non-zeroed OHLC values and pre-existing states (`CANONICALIZED`,
  `UNKNOWN`, `NOT_APPLICABLE`) consistent with their own history, no
  corruption.
- `CHECKPOINT_83`'s own unit (RELIANCE, `2026-08-17`) re-confirmed
  still exactly 70/70 `CANONICALIZED` — untouched by this checkpoint.
- 12,713 rows belong to instruments outside the 4 target symbols
  entirely — untouched by design (this migration path is scoped by
  `instrument_id` per unit).

## Part 4 — Research gate re-run: the honest, unwelcome finding

`[F]` Re-ran `ResearchDataGateService.get_research_eligible_bars()`
for all 4 symbols across the full `2026-08-03`–`09-09` range.
**Result: 18 gate-verified days per symbol, common across all 4
symbols — completely UNCHANGED from before this checkpoint.**

`[F]` Diagnosed directly, not assumed: **every one of the 9
interior-gap days, for every symbol, is independently rejected with
`INCOMPLETE_COVERAGE`** — each shows exactly 70/72 (or in two RELIANCE
cases, 68/72) bars cached, 1–2 missing sub-ranges each. Spot-checked
RELIANCE/`2026-08-18`: the 70 `REAL_DHAN` rows form one unbroken
5-minute-spaced run (`04:00`–`09:45`) with zero *internal* gaps — the
missing bars are at the session boundary (the window's own expected
start, `03:45`, is absent), the same day-start/day-end truncation
pattern already documented since `CHECKPOINT_69`/`72`, not a new
defect this checkpoint introduced or could fix (P4/P9: this checkpoint
never mutates, backfills, or relabels any bar — canonicalization only
flips a state flag and shifts an existing bar's own timestamp forward
by the CAS offset, it does not create missing bars).

**Canonicalization and research-eligibility are separate, independently
required properties — this checkpoint proves the former, decisively,
for 35 real units, and changes nothing about the latter.** The
interior gap is now fully canonicalized (35/36 possible units; the
36th was never eligible) but remains **zero-for-nine on research
eligibility**, exactly as `CHECKPOINT_83`'s own single-unit rehearsal
already foreshadowed with RELIANCE/`2026-08-17`.

## Part 5 — Full test suite

`[F]` `.venv/Scripts/python.exe -m pytest -q --reuse-db` —
**3391 passed, 7 failed** (698.62s). Exact failure names, identical to
`CHECKPOINT_83`'s own list (no source code changed this checkpoint —
only real data writes):
1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

#1/2/5/6/7 are the same 5 pre-existing failures documented at every
prior checkpoint this session; #3/4 are the known `--reuse-db`
stale-table flakes. Passed count identical to `CHECKPOINT_83`'s own
3391 (this checkpoint added no new test files and modified no test
files). **Zero new/unexplained failures.**

## The new baseline, stated plainly

- **Gate-verified day count: 18 — UNCHANGED from before this
  checkpoint.** This checkpoint canonicalized 35 new units (a real,
  substantial, verified change to the underlying data's
  `canonicalization_state`), but **zero of them became newly
  research-eligible**, because every one of the 9 interior-gap days
  independently fails the SAME, separate `INCOMPLETE_COVERAGE` check
  that already blocked `2026-08-17` in `CHECKPOINT_83`.
- **47-day Gainz/VWAP/ORB tuning-resumption criterion
  (`CHECKPOINT_75`/`76`/`79`): NOT MET.** 18 is not just short of 47 —
  it is unchanged from the count going into this checkpoint. Stated
  plainly, not buried: **this checkpoint made zero progress toward
  the 47-day threshold**, despite successfully executing 35 real
  production writes.
- **No strategy tuning was resumed** — per this checkpoint's own rule,
  and doubly moot given the finding above.
- **What would actually move the day count**: resolving the
  `INCOMPLETE_COVERAGE` gap itself (the missing session-boundary bars)
  is a separate, not-yet-authorized problem — likely a data-fetch/
  backfill question (are these bars missing from Dhan's own historical
  API response, or dropped somewhere in this project's own ingestion
  path?), not a migration-authorization question. This checkpoint's
  own scope (P9/P10) does not include diagnosing or fixing bar
  ingestion — flagged here as the honest next blocker, not
  investigated further.

## Governance compliance

- P3/P5: 35 real writes, each independently gated through all 3
  authorization checks plus the mandatory confirmation flag; zero
  writes attempted outside this mechanism.
- P4: no `HistoricalBar` mutation outside the sanctioned migration
  path; no relabel/backfill/deletion; only `canonicalization_state`
  and `bar_timestamp` changed per row, exactly as the pre-existing,
  unchanged write mechanism has always done. The one ineligible unit
  (TCS/`2026-08-24`) was correctly left untouched, not forced through.
- P7/P8: no guard weakened, no fingerprint semantics changed — every
  fingerprint was freshly re-derived per unit, never reused or
  batch-computed.
- P9: no strategy logic or `HistoricalDataCoverageService` change;
  no tuning resumed despite the (unmet) threshold check performed.
- P11: commit to `active-development` only (this commit). No source
  code was modified this checkpoint — only data (via the sanctioned
  path) and this checkpoint's own tracking documents.
- P15: no speculative directories created.
- P16: single persistent branch, no new branch created.

`CHECKPOINT_84_SUMMARY.md` — this file — committed alongside the
tracking-document updates. `MEMORY.md` and `PROJECT_STRATEGY_STATUS.md`
updated in the same commit (see below).
