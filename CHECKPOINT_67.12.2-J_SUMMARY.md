# CHECKPOINT 67.12.2-J — Diagnose two pre-existing test failures

```
checkpoint: 67.12.2-J
verdict: PARTIALLY_RESOLVED_REST_DEFERRED
root_cause_shared: NO (two independent causes, one per failure)
classification_summary: { stale_test_infra: 1, genuine_regression: 0, environment_drift: 1, undetermined: 0 }
fixes_applied: 1
still_failing: 1 (test_migration_67_10_execute.py::test_migration_67_7_dry_run_test_suite_still_passes_unmodified — ENVIRONMENT_DRIFT / test-isolation design flaw, deliberately not touched)
full_sweep_result: 713 passed / 714 total (1 deliberately-deferred failure)
commit: <filled in after commit>
blockers: []
```

## A. Full traceback evidence

### Failure 1 — `test_fully_cached_range_triggers_zero_provider_calls`

Run standalone (`pytest tests/unit/application/services/test_historical_data_preparation.py -v`), full traceback:

```
    second = service.prepare(RELIANCE, Timeframe.FIVE_MINUTE, START, END)

    assert second.status == PreparationStatus.COMPLETE
    assert second.api_requests == 0
    assert second.bars_fetched == 0
>   assert second.cache_hits == first.bars_persisted
E   AssertionError: assert 72 == 75
E    +  where 72 = PreparationOutcome(instrument_id='NSE:RELIANCE', ..., cache_hits=72, bars_fetched=0, bars_persisted=0, ...).cache_hits
E    +  and   75 = PreparationOutcome(instrument_id='NSE:RELIANCE', ..., cache_hits=0, bars_fetched=75, bars_persisted=75, ...).bars_persisted

tests\unit\application\services\test_historical_data_preparation.py:135: AssertionError
```
Only one assertion in one test — no other frames to show. Deterministic, reproduces every run (72 vs 75, always).

### Failure 2 — `test_migration_67_10_execute.py::test_migration_67_7_dry_run_test_suite_still_passes_unmodified` (cascading 16 errors)

`test_migration_67_7_dry_run.py` run **standalone**: all 16 tests PASS (`16 passed, 1 warning in 2.27s`).

`test_migration_67_10_execute.py::test_migration_67_7_dry_run_test_suite_still_passes_unmodified` run **standalone**: PASSES (`1 passed, 1 warning in 4.05s`).

The same test run as part of the **broad sweep** (`tests/unit/infrastructure/persistence/` + `tests/unit/infrastructure/market_data_providers/` + `tests/unit/application/services/`) FAILS. The subprocess it spawns produces this shape for all 16 inner tests (representative — every one of the 16 shares this identical traceback shape, differing only in test name):

```
  File ".../django/test/utils.py", line NNN, in setup_databases
    ...
  File ".../django/db/backends/base/creation.py", line NNN, in create_test_db
    ...
            with self.db.wrap_database_errors:
                ...
E           django.db.utils.OperationalError: database "test_intraday" is being accessed by other users
    .venv\Lib\site-packages\psycopg\cursor.py:117: OperationalError

  Got an error creating the test database: database "test_intraday" already exists
  Got an error recreating the test database: database "test_intraday" is being accessed by other users
  1 warning, 16 errors in 89.83s (0:01:29)
```

All 16 collected items in the subprocess error out identically at the Django `setup_databases` fixture stage (a collection-level DB-provisioning error, not 16 independent test bodies failing) — one shared cause, not 16 bugs. The outer test process then fails its own assertion:

```
    result = subprocess.run([sys.executable, "-m", "pytest", "-q",
        "tests/unit/application/services/test_migration_67_7_dry_run.py"], ...)
>   assert result.returncode == 0, result.stdout + result.stderr
E   assert 1 == 0

tests\unit\application\services\test_migration_67_10_execute.py:419: AssertionError
```

And the outer pytest-django session itself logs, at its own teardown:

```
PytestWarning: Error when trying to teardown test databases: OperationalError(
  'database "test_intraday" is being accessed by other users\nDETAIL:  There is 1 other session using the database.')
```

## B. Root-cause finding

**Failure 1** — RELIANCE is `CATEGORY_I_CAS` (Checkpoint 64.87's classification: `HDFCBANK`/`INFY`/`RELIANCE`/`TCS` end continuous trading at 15:15 IST, not 15:30). Checkpoint 65.27 wired that classification into `HistoricalDataCoverageService._expected_timestamps` (`src/intraday/application/services/historical_data_coverage.py:95-108`) — for `CATEGORY_I_CAS` symbols it now uses `build_cas_aware_session_for` + `expected_continuous_bar_timestamps`, which produces 72 five-minute bar-closes for the test's session window (03:45–10:00 UTC = 09:15–15:30 IST), not the uniform 75.

`test_historical_data_preparation.py`'s `_AlwaysAvailableProvider` fixture, written for Phase 22 (Checkpoint 63.x, before CAS-awareness existed), still unconditionally builds a uniform, non-CAS session via `build_session_for` + `expected_bar_timestamps` regardless of instrument — for RELIANCE it fetches/persists 75 bars (the full 09:15–15:30 window, including the 15:15–15:30 slice that RELIANCE's real CAS-aware coverage no longer counts as "expected"). On the second `prepare()` call, coverage's own `cached_bar_count` (=`cache_hits`) only counts the 72 CAS-aware-expected timestamps that are present, undercounting the 75 that were actually persisted.

This is a **fixture/production drift**, not a live bug: `missing_ranges` is still correctly empty (72 expected ⊆ 75 persisted), so `is_complete` stays `True` and zero refetches happen — the mandatory Phase 22 "zero provider calls" behavior itself is intact and unaffected. Only the test's stricter invariant (`cache_hits == bars_persisted`), which implicitly assumed a uniform, non-CAS session, no longer holds for a CAS-classified instrument.

**Failure 2** — Not a code bug in the migration or dry-run logic at all. `test_migration_67_10_execute.py::test_migration_67_7_dry_run_test_suite_still_passes_unmodified` spawns `python -m pytest tests/unit/application/services/test_migration_67_7_dry_run.py` as a **separate OS subprocess**, which independently runs Django's `setup_databases`/`create_test_db` against the same Postgres server and the same database name (`test_intraday`, driven by `DATABASES['default']['NAME']` in `intraday.settings.testing`). When this test runs as part of a **broad sweep**, the *outer* pytest-django process already holds an open connection to `test_intraday` for the whole sweep's duration; Postgres refuses to `DROP DATABASE`/recreate a database another session is connected to, so the subprocess's own `create_test_db()` fails immediately at collection/fixture setup for all 16 of its tests — one shared cause (a `django.db.utils.OperationalError: database "test_intraday" is being accessed by other users`), producing exactly the "16 errors in one file" shape. Confirmed by: (a) the file passes 16/16 alone, (b) the meta-test passes alone, (c) both fail together only inside the sweep, and (d) the outer session's own teardown logs the identical "being accessed by other users" `OperationalError`.

## C. Classification

| Failure | Classification |
|---|---|
| #1 `test_fully_cached_range_triggers_zero_provider_calls` | `STALE_TEST_INFRASTRUCTURE` — test fixture predates Checkpoint 64.87/65.27's CAS-awareness and used a now-CAS-classified instrument without updating its uniform-session assumption. Production coverage/preparation logic is correct and behaves as 65.27 intended. |
| #2 `test_migration_67_7_dry_run_test_suite_still_passes_unmodified` (+ its 16 cascaded inner errors) | `ENVIRONMENT_DRIFT` — a database-state assumption ("no other session is connected to `test_intraday` when this subprocess recreates it") that was true when this meta-test was written in isolation, but breaks in a broad concurrent sweep. Nothing in `migration_execute.py`/`migration_dry_run.py`/the dry-run's actual safety assertions is implicated — all 16 inner tests pass cleanly on their own, proving the dry-run logic itself is unaffected. |

## D. What was fixed and why it was safe

**Fixed (Failure 1 only)** — `tests/unit/application/services/test_historical_data_preparation.py`:
- Added `NON_CAS_INSTRUMENT = make_instrument_id(Exchange.NSE, "TATASTEEL")` (a `CATEGORY_II_NON_CAS` symbol — not in `CATEGORY_I_CAS_SYMBOLS = {"HDFCBANK", "INFY", "RELIANCE", "TCS"}`), documented with the CAS-drift explanation above.
- Parametrized `_bar()` to accept an `instrument_id` (defaulting to `RELIANCE`, so every other test in the file is byte-for-byte unaffected) and had `_AlwaysAvailableProvider.fetch()` stamp bars with the `instrument_id` it was actually called with, instead of hardcoding `RELIANCE`.
- Changed only `test_fully_cached_range_triggers_zero_provider_calls` to call `service.prepare(NON_CAS_INSTRUMENT, ...)` instead of `RELIANCE`.

This is test-only, does not touch `historical_data_coverage.py`, `historical_data_preparation.py`, or any CAS classification logic, and does not weaken the assertion — `cache_hits == bars_persisted` still holds exactly, now verified against an instrument for which the fixture's uniform-session provider and the coverage service's expected-count logic actually agree (the same invariant the test always intended to prove, just no longer accidentally exercising a CAS-classified symbol it was never updated for). Re-ran `test_historical_data_preparation.py` standalone: **4 passed** (was 3 passed / 1 failed).

**Not fixed (Failure 2)** — left failing, per the checkpoint's explicit elevated-care instruction. A "fix" would mean either (a) making the subprocess use an isolated/differently-named test database, (b) skipping/xfailing the meta-test under detected concurrent-DB conditions, or (c) replacing the subprocess-spawn design with an in-process re-run — none of these is a "stale import path / renamed fixture / mismatched literal"-class narrow fix; all involve a real design decision about how this project wants its self-verifying dry-run meta-test to behave under concurrent sweeps, which the directive reserves for a dedicated checkpoint.

## E. What remains failing and why it was deliberately not touched

`test_migration_67_10_execute.py::test_migration_67_7_dry_run_test_suite_still_passes_unmodified` (and its 16 cascaded inner `test_migration_67_7_dry_run.py` errors, all sharing the single root cause above) remain failing in the broad sweep. This was deliberately not patched because:
- It classifies as `ENVIRONMENT_DRIFT`, not `STALE_TEST_INFRASTRUCTURE` — the fix is not a one-line literal/import/fixture correction, it is a test-isolation design change.
- The checkpoint directive explicitly calls this one out for "elevated care" given what it's meant to protect (the migration dry-run safety net), and prohibits any fix that isn't provably narrow.
- Independent evidence (16/16 pass standalone, meta-test passes standalone) already proves the actual dry-run logic under test is unaffected — there is no doubt cast on `migration_execute.py`/`migration_dry_run.py` correctness by this failure, only on the meta-test's own concurrency assumption.

## F. Recommended next checkpoint

**Redesign `test_migration_67_7_dry_run_test_suite_still_passes_unmodified`'s re-run mechanism so it does not race the outer pytest-django session for the same Postgres test database.** Concrete options to evaluate in that checkpoint (not decided here): give the subprocess run a distinct `DJANGO_SETTINGS`/database-name override (e.g. a `--reuse-db`-safe distinct test DB name via env var), replace the subprocess spawn with an in-process `pytest.main()` invocation that shares the outer connection instead of provisioning its own database, or mark the meta-test to only run when it can detect it's not nested inside a larger sweep (e.g. via `pytest -p no:cacheprovider` isolation or a dedicated CI job that runs this file alone). Whatever is chosen must preserve the meta-test's actual purpose (proving 67.10's additions didn't silently alter 67.7's dry-run test suite) without depending on exclusive access to a shared database name.
