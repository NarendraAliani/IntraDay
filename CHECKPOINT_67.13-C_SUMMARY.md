# Checkpoint 67.13-C — Build the Missing Production Execution Entry Point

```
checkpoint: 67.13-C
verdict: ENTRY_POINT_BUILT_AND_PROVEN
command_name: migration_production_execute
refuses_test_database: YES (test_gate_2_refuses_a_test_database_even_when_gate_1_is_bypassed)
authorize_one_unit_execution_now_has_a_real_caller: YES
real_execution_attempted: NO
tests_added: 5
full_sweep_result: 158/158 (153 pre-existing + 5 new)
commit: (recorded below)
blockers: []
```

## A. Design

**`python manage.py migration_production_execute --unit
SYMBOL,TIMEFRAME,YYYY-MM-DD --expected-scope-fingerprint <hex>`**

A new file
(`infrastructure/persistence/management/commands/migration_production_execute.py`),
a new command name — **not** a flag added to `migration_67_10`. Two
required arguments only:

- `--unit` — exactly one `(symbol, timeframe, trading_date)`, parsed
  with the same `SYMBOL,TIMEFRAME,YYYY-MM-DD` convention
  `migration_67_10 --execute` already uses (reused verbatim, not
  reinvented).
- `--expected-scope-fingerprint` — the operator's own,
  independently-recorded expectation, exactly the shape
  `authorize_one_unit_execution()`'s check (3) already requires
  (confirmed by re-reading that check, not guessed).

**No `--artifact-file` argument.** Re-read `build_canary_backup()`'s
actual signature first (`build_canary_backup(unit_result:
UnitDryRunResult, *, checkpoint: str)`) — it takes a live dry-run
result object, not a file path. Rather than inventing a
serialize-to-disk-then-reload step (a second, unproven mechanism), the
command re-derives the dry-run evidence **fresh, live, right before
authorization is evaluated** — the same 67.12-PRE lesson this session
already learned the hard way (a stale, never-actually-computed
fingerprint was the real root cause of 67.12's original HARD_STOP).

**Control flow**: Gate 1 (`verify_environment_identity()`) → Gate 2
(this command's own dedicated test-database refusal) → build a fresh
dry-run report, select the requested unit, build a fresh
`CanaryBackupArtifact` → Gate 3 (`authorize_one_unit_execution()`,
composing everything including its own internal re-check of the
write-capability guard) → only past all three, call the same,
unchanged `HistoricalBarMigrationExecutor` every other execution path
already uses.

## B. The build — defense-in-depth explained

Three independent gates, not one hidden behind another:

1. **`verify_environment_identity()`** — must report
   `VERIFIED_PRODUCTION`. Unmodified, called exactly as it already
   exists.
2. **This command's own `_refuse_if_test_database()`** — a
   **structurally distinct function**, in this new file, that reads
   `connection.settings_dict["NAME"]` directly and raises a
   **new, distinct exception type**
   (`ProductionEntryPointTestDatabaseRefusalError`, deliberately not
   `ProductionWriteGuardError`) if it starts with `test_`. This is the
   exact inverse of the existing guard, built new rather than reused,
   so a reviewer can see this command refuses a test database in its
   own dedicated code path — not merely inheriting protection from
   gate 3's own internal check.
3. **`authorize_one_unit_execution()`** — unmodified, called with real
   evidence (real `EnvironmentIdentityReport`, a freshly-built real
   `CanaryBackupArtifact`, the operator's `--expected-scope-fingerprint`).
   Its own check (5) independently re-invokes
   `assert_write_capable_connection_is_test_database()` — the
   **original**, pre-existing guard, called a second time via an
   entirely separate code path from gate 2 above.

**Nothing about any of the three gates was modified.** `git diff`
against `migration_environment_identity.py`,
`migration_execution_authorization.py`, and `migration_execute.py`:
empty — confirmed no existing file touched, only the one new command
file and its one new test file added.

## C. The proof — 5 new tests, all against the disposable test database

1. `test_gate_1_denies_by_default_in_the_real_test_environment` — zero
   mocking, the ordinary case: this project's real test settings
   module can never satisfy `VERIFIED_PRODUCTION`, so gate 1 alone
   already refuses.
2. **`test_gate_2_refuses_a_test_database_even_when_gate_1_is_bypassed`
   — the test that matters most.** Monkeypatches *only*
   `verify_environment_identity()` to return a fake
   `VERIFIED_PRODUCTION` report (proving gate 2 is not merely riding on
   gate 1's own separate denial), confirms the real connection
   underneath is genuinely `test_intraday` (asserted directly via
   `connection.settings_dict`, not assumed), and confirms
   `ProductionEntryPointTestDatabaseRefusalError` fires — this
   command's own dedicated refusal, working on its own.
3. `test_gate_3_still_denies_even_if_gates_1_and_2_were_both_bypassable`
   — the hypothetical-defense-in-depth proof: monkeypatches gate 1 to
   fake-pass **and** gate 2 to a no-op, seeds real dense `RELIANCE`
   `5m` rows (the same proven-scope fixture pattern
   `test_migration_67_10_execute.py` already uses, reused not
   reinvented), and confirms gate 3 is what actually stops it —
   `authorize_one_unit_execution()`'s own internal guard re-check,
   genuinely independent of gate 2.
4. `test_missing_required_arguments_are_rejected_before_any_gate_runs`
   — CLI-argument validation, before any gate logic even runs.
5. `test_authorize_one_unit_execution_now_has_a_real_non_test_caller`
   — source-inspection confirmation that `authorize_one_unit_execution(`
   genuinely appears in this new command module, closing the exact gap
   `67.13`/`67.13-B`'s trace found (zero real callers anywhere in
   `src/` before this checkpoint).

**A real bug found and fixed along the way, honestly reported**: the
first version of test 3 failed with a genuine PostgreSQL error
(`SET TRANSACTION ISOLATION LEVEL must be called before any query`) —
not a design flaw, a test-marker mistake. My own test file initially
used the default `@pytest.mark.django_db` (Django's wrapped
savepoint-per-test transaction), but `build_canary_backup()`'s
`_repeatable_read_atomic()` requires `SET TRANSACTION ISOLATION LEVEL`
to be the literal first statement of a real transaction. Fixed by
switching to `@pytest.mark.django_db(transaction=True)` +
`@requires_postgres` on every test — the exact marker convention
`test_migration_67_10_execute.py` already uses throughout, which I
should have matched from the start rather than defaulting to the
plain marker.

## D. Explicit confirmation nothing real was executed

- `INTRADAY_VERIFIED_PRODUCTION_IDENTITY` was **never set** to any
  value, real or fake, at any point in this checkpoint — confirmed via
  direct shell check (`echo $INTRADAY_VERIFIED_PRODUCTION_IDENTITY` →
  empty) immediately before writing this report.
- The real `intraday` database's `HistoricalBar` state, re-queried
  directly after all testing completed: `REAL_DHAN`/`UNCANONICALIZED`
  = 11,442, `REAL_DHAN`/`UNKNOWN` = 20,880, `UNKNOWN`/`NOT_APPLICABLE`
  = 5,100 — **identical** to `RECON-BACKTEST`'s own count, confirming
  nothing changed.
- `MigrationRun`/`MigrationUnit`/`MigrationRow`: still **0/0/0**.
- Every test in this checkpoint ran against Django's disposable
  `test_intraday` database only, proven directly (test 2 asserts the
  connection name starts with `test_` before proceeding).
- `migration_production_execute` has been invoked, in this checkpoint,
  **only** by the 5 tests above — every single invocation was
  engineered to be refused by one of its three gates. It has never
  once reached its final write step.

## E. The actual next step — a separate, future, operator-decided checkpoint

This checkpoint's job was narrowly to give
`authorize_one_unit_execution()` a real, tested, non-test caller — done.
**Using `migration_production_execute` against real data is
deliberately not part of this checkpoint, and should not become part
of any checkpoint without the operator's own, direct, separate
decision to run it** — because doing so requires:

1. Deciding what `INTRADAY_VERIFIED_PRODUCTION_IDENTITY` should
   concretely mean for this project's real, single-environment
   deployment (67.13's own recommended next step, still not resolved
   here on purpose — that is a design decision, not something this
   build-only checkpoint should infer).
2. Actually booting the process under `intraday.settings.production`
   (which cannot currently boot in this workspace — missing
   `SETTINGS_ENCRYPTION_KEY`, a separate, already-known fact from
   earlier checkpoints) or resolving that gap too.
3. The operator personally choosing to run
   `migration_production_execute` with real arguments, having reviewed
   this command's own gate-by-gate output for the specific real unit
   in question — not something any checkpoint should do on the
   operator's behalf, even now that the tooling exists and is proven.
