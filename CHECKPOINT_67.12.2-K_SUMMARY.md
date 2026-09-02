# CHECKPOINT 67.12.2-K — Fix the migration dry-run meta-test's database isolation

```
checkpoint: 67.12.2-K
verdict: ISOLATION_FIXED_AND_VERIFIED
fix_approach: distinct-db-name (subprocess given its own INTRADAY_TEST_DB_NAME-driven test database; subprocess spawn itself unchanged)
process_isolation_intent_preserved: YES - the subprocess is still a genuine separate OS process (fresh interpreter, fresh Django app registry) that independently proves 67.10's additions did not alter 67.7's suite; only the Postgres test-database NAME it provisions was made distinct, not the process boundary
nested_sweep_reproduction_now_passes: YES
cas_coverage_gap: NEW_TEST_ADDED
full_sweep_result: 715 passed / 715 total
commit: <filled in after commit>
blockers: []
```

## A. Original-intent finding (Part 1)

- No docstring/`ARCHITECTURE_DECISIONS.md`/checkpoint history entry found that explicitly states *why* Checkpoint 67.10 chose a subprocess spawn (`subprocess.run([sys.executable, "-m", "pytest", ...])`) over an in-process `pytest.main()` call for `test_migration_67_7_dry_run_test_suite_still_passes_unmodified`. [D] No explicit design-rationale comment exists in `test_migration_67_10_execute.py` beyond "re-runs the ENTIRE pre-existing 67.7 dry-run test file as a subprocess, proving this checkpoint's additions did not alter its behavior in any way."
- Best-evidenced inference [I]: a subprocess spawn is the *only* one of the three options (subprocess / in-process `pytest.main()` / sweep-detection skip) that gets a fresh Python interpreter and a fresh Django app registry, and therefore actually proves 67.10's own module-level changes (imports, monkeypatches, app-registry side effects) did not leak into or alter 67.7's suite when both are loaded together. An in-process `pytest.main()` call would share the outer interpreter's already-imported module state (including whatever `test_migration_67_10_execute.py` itself imported), which would not prove the same thing. Since no contradicting rationale is documented, this checkpoint treats process-level isolation as the intended, load-bearing property and preserves it.
- Part 1.2 — checked `src/intraday/settings/testing.py` and `src/intraday/settings/base.py` for any existing environment-variable-driven test-database-name override before adding one. [F] None existed: `DATABASES["default"]` in `base.py` had no `"TEST"` key at all (Django's implicit default `"test_" + NAME` was in effect everywhere), and no other code in the repo read an env var to override it. This checkpoint is the first to introduce `INTRADAY_TEST_DB_NAME`.

## B. Fix implemented and why it preserves the intent

- `src/intraday/settings/testing.py`: added `DATABASES["default"]["TEST"]["NAME"] = os.environ.get("INTRADAY_TEST_DB_NAME") or None`. Unset (every other test invocation in the repo, including this same file's own outer sweep), this is a no-op — Django falls back to its normal `"test_" + NAME` default, so no other test run's database name changes.
- `tests/unit/application/services/test_migration_67_10_execute.py::test_migration_67_7_dry_run_test_suite_still_passes_unmodified`: the `subprocess.run(...)` call is otherwise **unchanged** (same `sys.executable -m pytest -q <file>` invocation, same file re-run, same fresh-interpreter/fresh-app-registry process boundary) — only its `env` now copies `os.environ` and sets `INTRADAY_TEST_DB_NAME=test_intraday_migration_meta`, so the subprocess's own Django settings load provisions/tears down a distinctly-named test database (`test_intraday_migration_meta`) instead of racing the outer sweep's `test_intraday`.
- Confirmed zero changes to `migration_execute.py`, `migration_dry_run.py`, or `migration_67_10.py`/`migration_67_7`'s command logic — `git status` for this checkpoint shows only `src/intraday/settings/testing.py`, `tests/unit/application/services/test_migration_67_10_execute.py`, and `tests/unit/application/services/test_historical_data_preparation.py` (Part 4) touched.
- Cleanup verified: ran the fixed meta-test standalone, then queried Postgres directly (`SELECT datname FROM pg_database WHERE datname LIKE 'test_intraday%'`) — result `[]`, i.e. neither `test_intraday_migration_meta` nor any other stray test database was left behind. pytest-django's own fixture teardown (unaffected by this change — no `--keepdb` used) drops the subprocess's database at the end of its own session in both the pass and fail case.

## C. Nested-sweep proof (Part 3)

Reproduced 67.12.2-J's exact broad-sweep invocation:

```
.venv/Scripts/python.exe -m pytest -q tests/unit/infrastructure/persistence/ tests/unit/infrastructure/market_data_providers/ tests/unit/application/services/
```

Result: `715 passed, 2 warnings in 126.34s (0:02:06)` — includes
`test_migration_67_10_execute.py::test_migration_67_7_dry_run_test_suite_still_passes_unmodified`
passing nested inside the sweep (previously the one confirmed failure). One
pre-existing, unrelated `PytestWarning` at teardown
(`test_token_lifecycle.py::test_expiring_soon_renewal_rejected_reports_auth_failure`
— outer session's own `test_intraday` teardown reporting another session
still connected) remains; it is a warning, not a failure, was already present
in this exact form in 67.12.2-J's evidence, and is orthogonal to the fix
(nothing in this checkpoint touches `test_token_lifecycle.py` or its
fixtures) — no new regression, full sweep is green.

## D. CAS coverage gap resolution (Part 4)

- Searched for existing coverage of "fully cached ⇒ zero provider calls" for
  a `CATEGORY_I_CAS` instrument: `test_historical_data_coverage.py` only
  covers the coverage-service-level "fully cached range has zero missing
  ranges" invariant (`test_fully_cached_range_is_complete_with_zero_missing_ranges`),
  not the preparation-service "provider is never called again" behavior that
  `test_fully_cached_range_triggers_zero_provider_calls` proves. No test
  anywhere exercises that specific preparation-service invariant for a
  CAS-classified instrument after J's fix moved it to `TATASTEEL`
  (`CATEGORY_II_NON_CAS`). Gap confirmed, not already covered.
- `NEW_TEST_ADDED`: `test_fully_cached_cas_instrument_range_triggers_zero_provider_calls`
  in `tests/unit/application/services/test_historical_data_preparation.py`,
  using `RELIANCE` (`CATEGORY_I_CAS`). It does **not** modify J's fix
  (`test_fully_cached_range_triggers_zero_provider_calls`, still using
  `TATASTEEL`, untouched). It asserts `second.cache_hits` against
  `len(_expected_timestamps(START, END, Timeframe.FIVE_MINUTE, RELIANCE))`
  — derived live from the same private helper
  `HistoricalDataCoverageService`'s module uses internally, not a hardcoded
  `72` — so the assertion tracks the CAS session definition if it ever
  changes. `api_requests == 0`, `bars_fetched == 0`, and
  `provider.fetch_calls == 1` (unchanged after the second `prepare()` call)
  are asserted exactly as strictly as the non-CAS test.

## E. Final sweep result

`715 passed, 2 warnings in 126.34s` — the previously-failing meta-test now
passes nested in the sweep, no new regression, and the new CAS-instrument
test passes as part of the same run (also verified standalone: `5 passed`
in `test_historical_data_preparation.py`).
