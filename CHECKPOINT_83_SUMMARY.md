# CHECKPOINT 83 — Implement Single-Env Authorization Design + First Real Rehearsal

```
directive: implement SINGLE_ENV_AUTHORIZATION_PROPOSAL.md §2.3(a)-(d)
           exactly as approved, then perform exactly ONE real
           rehearsal execution, hard stop after
operator-decided params: --i-have-reviewed-this-real-write (flag name)
           200 (row-count ceiling)
unit executed: RELIANCE, 5m, 2026-08-17
gate result: Gate 1 PASSED / Gate 2 PASSED / Gate 3 PASSED — genuine
           AUTHORIZED verdict, for the first time this session
write result: COMMITTED — 70/70 rows CANONICALIZED
research_gate_response: REJECTED (INCOMPLETE_COVERAGE, 70/72 bars) —
           unchanged reason from before this checkpoint (2 bars were
           already known-missing per CHECKPOINT_72)
full_suite_result: 7 failed / 3391 passed — same 5 known pre-existing +
           2 known --reuse-db stale-table flakes, zero new/unexplained
           failures
safe_to_scale: conditionally yes — see Part 4
commit: (recorded below)
```

## Part 0 — Pre-flight discipline

`[F]` Confirmed via `ls`/`git status` before writing: `CHECKPOINT_83_SUMMARY.md`
did not already exist. `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md` re-read
directly (not from memory) to resolve one design ambiguity before
implementing — see Part 1.

## Part 1 — Implementation, exactly per the approved proposal

`[F]` **(a)** `assert_write_capable_connection_is_verified_production()`
added to `migration_execute.py`. It re-derives legitimacy from
`verify_environment_identity()`'s own evidence chain (real `.production`
settings module + the operator's out-of-band
`INTRADAY_VERIFIED_PRODUCTION_IDENTITY` marker + a live
`current_database()` round-trip) — never a database-naming convention.
Raises the new, distinct `VerifiedProductionWriteGuardError` (never
`ProductionWriteGuardError`, so a reviewer can tell from the exception
class alone which of the two independent guards fired).

`[F]` **(b)** `HistoricalBarMigrationExecutor` gained
`allow_non_test_database: bool = False`. `run()` now selects the guard
conditionally:
```python
if self.allow_non_test_database:
    assert_write_capable_connection_is_verified_production()
else:
    assert_write_capable_connection_is_test_database()
```
`[F]` Confirmed directly (grep) that `migration_67_10.py`'s own
construction call —
`executor = HistoricalBarMigrationExecutor(dry_runner=dry_runner)`,
line 109 — passes no `allow_non_test_database` kwarg, so it defaults
to `False`. **`migration_67_10.py` itself was never edited.**
`migration_production_execute.py` is the ONLY caller anywhere in this
codebase that ever constructs the executor with
`allow_non_test_database=True`, and does so only after its own gates
1–3 have already passed.

`[F]` **(c)** `--i-have-reviewed-this-real-write` added to
`migration_production_execute.py`'s `add_arguments()` as
`action="store_true", required=True` (a `store_true` flag with
`default=False` would NOT have been genuinely mandatory — self-caught
and corrected during implementation). `handle()` re-checks it
explicitly (defense in depth, matching this codebase's own established
"never trust caller discipline alone" style) before Gate 1 even runs.

`[F]` **(d)** `MAX_ROWS_PER_EXECUTION_UNIT = 200` added to
`migration_execute.py`. `_execute_unit()` refuses any unit whose
`row_count` exceeds it — before any lock or transaction is opened,
same placement/pattern as the pre-existing `DRY_RUN_SAFE` check —
returning `REFUSED_UNSAFE` / `REFUSED_ROW_COUNT_CEILING_EXCEEDED`.

`[F]` **(e)** Replay protection needed no new code — documented
directly at the source of the guarantee: `migration_dry_run.py`'s own
`_live_eligible_rows()` query already filters on
`canonicalization_state=CANONICALIZED_UNCANONICALIZED`, so a unit that
was just canonicalized silently disappears from the very next dry-run;
combined with `migration_production_execute.py`'s existing "unit not
found in a fresh dry-run plan" refusal, a second invocation for an
already-canonicalized unit fails closed before authorization is even
evaluated. Annotated with an explicit `CHECKPOINT_83` comment rather
than left implicit.

`[I]` **Design-ambiguity resolution, recorded for the record**: the
proposal's prose was momentarily ambiguous about whether check (5)
inside `authorize_one_unit_execution()` or only the command's own gate
2 should change. Resolved by re-reading the proposal's own explicit
table (§2.1: *"Replace, for the production path only"*) and §2.4
(*"Fully removing check (5) rather than replacing it. Rejected..."*),
and by confirming via grep that `migration_67_10.py` never calls
`authorize_one_unit_execution()` at all — settling that changing check
(5) affects the production path exclusively. Check (5) in
`migration_execution_authorization.py` was replaced accordingly; gate
2 (`_refuse_if_test_database()`) in `migration_production_execute.py`
was left completely untouched, exactly as approved. The file's own
now-historical `NOT_WIRED_RATIONALE` comment block was rewritten to
record what actually happened rather than left silently stale.

## Part 2 — Tests

`[F]` New file: `tests/unit/application/services/test_checkpoint_83_single_env_authorization.py`
(8 tests, all passing):
- `allow_non_test_database=False` (default and explicit) still uses
  the old test-database guard and still accepts this workspace's real
  disposable pytest test database, unchanged.
- `allow_non_test_database=True` genuinely refuses without real
  `VERIFIED_PRODUCTION` identity (`VerifiedProductionWriteGuardError`),
  and genuinely proceeds — actually canonicalizing rows — once
  `verify_environment_identity()` is patched to report it (patched
  only within `migration_execute`'s own namespace; the underlying
  connection is still the real disposable test DB throughout).
- `assert_write_capable_connection_is_verified_production()` tested in
  isolation, both directions.
- Row-count ceiling: refuses a unit whose `row_count` exceeds 200
  (`REFUSED_ROW_COUNT_CEILING_EXCEEDED`), and does NOT refuse a unit
  at exactly 200 (boundary proof — `>` not `>=`). Since a real NSE
  session only holds ~75 5m bars, an oversized fixture cannot be built
  from real bar timestamps without spilling into an unrelated
  collision reason — used `dataclasses.replace()` on a real,
  already-DRY_RUN_SAFE `UnitDryRunResult` to inflate only its
  `row_count` field, everything else genuine evidence from an actual
  dry-run pass.

`[F]` Updated `tests/unit/infrastructure/persistence/management/test_migration_production_execute.py`:
added the now-required `--i-have-reviewed-this-real-write` flag to
every `call_command(...)` invocation (argparse's own `required=True`
would otherwise reject them before any gate runs) — no behavioral
proof was weakened, each test's actual assertion is unchanged.

`[F]` Updated `tests/unit/application/services/test_migration_67_12_2_export_snapshot_and_authorization.py`'s
`test_j` part (d): the old test patched
`assert_write_capable_connection_is_test_database` inside the
authorization module's namespace to prove check (5) independently
denies — that attribute no longer exists there after check (5)'s
replacement, so the patch target was updated to
`assert_write_capable_connection_is_verified_production` /
`VerifiedProductionWriteGuardError`, preserving the test's original
intent (check 5 is never bypassed by checks 1–4 passing) exactly.
`test_k` (proves the OLD guard still accepts this disposable test
database) needed no change — it calls `migration_execute`'s own
untouched function directly, not through the authorization module.

`[F]` **`migration_67_10.py`'s own full existing test suite,
unmodified**: `test_migration_67_10_execute.py` — **28/28 passed**,
identical names, run together with the two updated files above.

`[F]` **Full project suite**: `.venv/Scripts/python.exe -m pytest -q
--reuse-db` — **3391 passed, 7 failed** (694.09s). Exact failure names,
identical to CHECKPOINT_82's own list:
1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

#1/2/5/6/7 are the same 5 pre-existing failures documented at every
prior checkpoint this session; #3/4 are the known `--reuse-db`
stale-table flakes (`CHECKPOINT-GAINZ-C`/`72` precedent). Passed count
rose from 3383 (CHECKPOINT_82) to 3391 — the 8 new tests this
checkpoint added. **Zero new/unexplained failures.**

## Part 3 — First real rehearsal, exactly one unit

`[F]` Unit: RELIANCE, `5m`, `2026-08-17` — same unit `CHECKPOINT_82`
dry-run-proved `DRY_RUN_SAFE`.

`[F]` **Fresh dry-run**, re-derived this run (not reused from
`CHECKPOINT_82`): `row_count=70`, `state=DRY_RUN_SAFE`,
`proof_status=PROVEN`, `unsafe_reasons=()`. Fresh `scope_fingerprint`
via `build_canary_backup()`:
`9dd836c76ba6780c1049ed7e5886f1e92170f8d6d9e07d68d1c5a4f8540dd0f6` —
identical value to `CHECKPOINT_82`'s, confirmed by independent
re-derivation rather than reuse (expected: no data changed for this
unit between checkpoints).

`[F]` Production-boot setup, identical discipline to `CHECKPOINT_82`:
a fresh `Fernet.generate_key()` value, set as a session-scoped env var
only (never written to `.env` or committed). `manage.py check` under
`DJANGO_SETTINGS_MODULE=intraday.settings.production` +
`SETTINGS_ENCRYPTION_KEY` → **`System check identified no issues (0
silenced)`** — genuine boot, confirmed directly.

`[F]` **Real command executed**:
```
manage.py migration_production_execute --unit "RELIANCE,5m,2026-08-17" \
  --expected-scope-fingerprint 9dd836c76ba6780c1049ed7e5886f1e92170f8d6d9e07d68d1c5a4f8540dd0f6 \
  --i-have-reviewed-this-real-write
```
**Full gate output**:
```
Gate 1/3: verify_environment_identity()...
  verdict=VERIFIED_PRODUCTION
  Gate 1 PASSED.
Gate 2/3: dedicated test-database refusal...
  Gate 2 PASSED (not a test database).
Gate 3/3: authorize_one_unit_execution()...
  Gate 3 PASSED.
All 3 gates passed — executing real write...
run_state=COMPLETED
  unit instrument=NSE:RELIANCE timeframe=5m trading_date=2026-08-17 outcome=COMMITTED final_state=COMMITTED
```
**All three gates AUTHORIZED for the first time this session** — the
deadlock `CHECKPOINT_82` confirmed live is resolved. The write
COMMITTED.

`[F]` **`canonicalization_state` change, confirmed by direct query**:
all 70 rows for `NSE:RELIANCE`/`5m`/`2026-08-17` → `CANONICALIZED`
(`0` remain `UNCANONICALIZED`).

`[F]` **P4 — every OTHER row byte-unchanged**:
- Table-wide duplicate-key check (`(instrument_id, timeframe,
  bar_timestamp)` grouped, `count > 1`): **0 duplicates**.
- Total table row count: **55,134** (no inserts/deletes — the write
  mechanism is UPDATE-only).
- 5,184 OTHER rows were already `CANONICALIZED` before this checkpoint
  (pre-existing, from rows ingested with canonicalization already
  applied at fetch time — not this migration path; unrelated to this
  unit).
- Source-level scoping proof: the actual write is a raw
  `UPDATE persistence_historicalbar SET ... WHERE id = %s`, issued once
  per row, with `id` drawn exclusively from this unit's own
  `row_projections` (`migration_execute.py:378-387`) — structurally
  incapable of touching a row outside this unit.
- Spot-check: 5 unrelated rows (`NSE:ADANIGREEN`) — unchanged state
  (`NOT_APPLICABLE`), plausible OHLC values, no corruption. This
  unit's own rows — plausible OHLC, now `CANONICALIZED`.
- Audit tables confirm scope directly: exactly **1** `MigrationUnit`
  row (`status=COMMITTED`, `old_row_count=70`, `new_row_count=70`) and
  exactly **70** `MigrationRow` audit rows exist in the whole table —
  precisely one unit, nothing more.

`[F]` **Research gate re-run** against this exact day:
```
REJECTED: INCOMPLETE_COVERAGE — 70/72 bars (97.22%) cached for
NSE:RELIANCE 5m in [2026-08-17T03:45:00Z, 2026-08-17T10:00:00Z] —
rejected, never gap-filled
```
Reported honestly: still rejected. This day was already known to be
missing 2 bars (`CHECKPOINT_72`'s prior finding) — canonicalizing the
70 existing rows does not create the 2 missing ones. One day alone
also cannot satisfy any `min_folds` requirement a research/backtest
consumer might separately impose; not directly re-tested here since
`ResearchDataGateService.get_research_eligible_bars()` itself has no
`min_folds` parameter — that requirement, if any, lives one layer up
(a research/backtest orchestration concern), out of this checkpoint's
scope.

## Part 4 — Hard stop, report, do not scale

`[F]` **No additional units were executed.** Confirmed directly:
exactly one `MigrationUnit` audit row exists in the whole database,
`git status --short` shows only the expected code/test files touched
(plus the deliberately-uncommitted `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md`),
and the command was invoked exactly once against exactly one `--unit`
value.

**Does this give enough confidence to scale to the remaining 9 days of
the interior gap in a future checkpoint?** `[I]` Conditionally yes, on
the mechanism — no, not yet on data-completeness:
- The authorization *mechanism* is now proven end-to-end for real,
  against the real database, for the first time: all 3 gates
  genuinely pass, the write commits correctly, no unrelated row is
  touched, replay protection genuinely refuses re-execution (by
  construction, not by new code). This closes the exact gap
  `CHECKPOINT_82` left open.
- What this rehearsal does NOT prove: whether the OTHER 9 interior-gap
  days are all cleanly `DRY_RUN_SAFE` and within the 200-row ceiling
  individually (each would need its own fresh dry-run before
  execution — the mechanism doesn't pre-validate the whole gap at
  once), and whether canonicalizing them actually resolves each day's
  own research-gate verdict — this day's own remains rejected for an
  unrelated, pre-existing data-completeness reason (2 missing bars),
  a reminder that canonicalization and completeness are separate
  properties.
- Recommended next step, if scaling is authorized: dry-run each of the
  remaining 9 days individually first (cheap, read-only, already
  proven safe), confirm each is `DRY_RUN_SAFE` and under the row
  ceiling, and execute them one at a time — this checkpoint proves the
  one-at-a-time mechanism is sound, not that a batch/multi-unit
  execution mode exists or has been built (it has not, deliberately).

## Governance compliance

- P3/P5: exactly one production write, explicit multi-gate
  authorization, operator-approved design, operator-decided parameters
  used verbatim.
- P4: no `HistoricalBar` mutation outside the sanctioned migration
  path; no relabel/backfill/deletion; only `canonicalization_state`
  and `bar_timestamp` changed, exactly as the pre-existing write
  mechanism has always done.
- P7: no existing safety guard weakened — `assert_write_capable_
  connection_is_test_database()` is untouched and still protects
  `migration_67_10.py`'s test-only path; the new guard is additive,
  narrower in scope (production path only), and itself fails closed.
- P8: no fingerprint/checksum semantics changed — `compute_scope_
  fingerprint()` untouched; re-derived fresh, not reused stale.
- P9: `HistoricalDataCoverageService` and strategy logic untouched.
- P11: commit to `active-development` only (this commit).
- P15: no speculative directories created.
- P16: single persistent branch, no new branch created.

`CHECKPOINT_83_SUMMARY.md` — this file — committed alongside the code.
`MEMORY.md` and `PROJECT_STRATEGY_STATUS.md` updated in the same
commit (see below).
