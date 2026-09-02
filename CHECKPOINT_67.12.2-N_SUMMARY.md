```
checkpoint: 67.12.2-N
verdict: GENUINE_REGRESSION_FOUND_DEFERRED
shares_root_cause_with_J: NO (scenario_b uses the same RELIANCE/CATEGORY_I_CAS
  instrument as J's fix, but fails via an unrelated mechanism -
  INELIGIBLE_PROVENANCE, not a CAS-session bar-count/cache_hits drift)
classification_summary: { stale_test_infra: 0, genuine_regression: 0, environment_drift: 4, undetermined: 0 }
fixes_applied: 0
still_failing: 4 (all four -- ENVIRONMENT_DRIFT, deferred, see D)
  - test_scenario_a_empty_database_run_completes_via_real_progress_state
  - test_scenario_b_repeat_run_makes_zero_api_requests
  - test_coverage_preview_reports_100_percent_after_a_completed_run
  - test_a_decimal_typed_strategy_parameter_sent_as_a_json_string_succeeds
contention_errors_resolved: YES (root cause was not K's pattern; see C)
full_sweep_result: 729 passed / 733 total (4 known failures; 0 new regressions
  vs the 719-passed baseline + 14 tests in this file)
commit: <filled in after commit, see final line of this file's git log entry>
blockers:
  - "ResearchDataGateService.get_research_eligible_bars() rejects
    SYNTHETIC_TEST-provenance rows (INELIGIBLE_PROVENANCE), which is
    CORRECT, intentional, confirmed-working production behavior
    (verified by 67.12.2-L). test_historical_backtesting_api.py's four
    failing tests all route through _select_historical_bar_provider()'s
    honest no-Dhan-credentials fallback to SyntheticHistoricalBarProvider
    (src/intraday/infrastructure/api/tasks.py:212-242), so every bar the
    orchestrator fetches and persists in-test is SYNTHETIC_TEST and is
    then correctly rejected by the research gate before a backtest can
    reach COMPLETED. This is not a narrow fixture/literal fix -- fixing
    it requires redesigning this test file's data-seeding strategy
    (e.g. seed REAL_DHAN-provenance HistoricalBar rows directly, per the
    pattern already used in test_research_data_gate.py and
    test_checkpoint_67_12_2_L_gate_filters_synthetic.py, instead of
    relying on the orchestrator's own synthetic-provider fetch path) --
    out of this checkpoint's provably-narrow-fix bar."
```

## A. Re-confirmed git-stash evidence (this run, not merely trusted from L)

[F] Starting state: `git status` clean at `708380c` (67.12.2-L), only an
untracked `docs.rar` present throughout (irrelevant, untouched).

[F] Ran the 4 failing tests individually against `708380c` with `-s` and a
temporary `print("DEBUG_BODY", body)` (reverted immediately after, confirmed
via `git diff --stat` showing only the 1-line addition, then `git checkout --`
to restore the file exactly). Full `/progress/` response body for
`test_scenario_a_...`:

```
{'status': 'FAILED', 'phase': 'FAILED', ...,
 'failed_instruments': [{'reason':
   'INELIGIBLE_PROVENANCE: 72x SYNTHETIC_TEST not research-eligible '
   '(only REAL_DHAN is) for NSE:RELIANCE Timeframe.FIVE_MINUTE in '
   '[2026-01-05T03:45:00+00:00, 2026-01-05T10:00:00+00:00] ...',
   'instrument_id': 'NSE:RELIANCE'}], ...}
```

Identical `INELIGIBLE_PROVENANCE: ... SYNTHETIC_TEST ...` reason confirmed
independently for `test_coverage_preview_reports_100_percent_after_a_completed_run`
via the same debug-print-and-revert technique. `test_scenario_b_...`'s
traceback shows its *first* assertion (`first_progress["api_requests"] > 0`,
line 149) PASSING and only the second assertion (line 161, `status ==
COMPLETED`) failing -- consistent with 1 API request being made and then
rejected, the same shape. `test_a_decimal_typed_strategy_parameter_...`
fails at the identical `status == COMPLETED` check (line 365) after a
202-Accepted create -- same shape via the same orchestrator path with a
different `strategy_id`.

[F] `git checkout 6c9e5c6 -- .` (pre-L, i.e. HEAD~1) applied cleanly; `git
status --short` showed only `M src/intraday/infrastructure/api/
backtesting_views.py` reverted plus the pre-existing untracked `docs.rar` --
confirming L touched only that one production file (its Part 3 provider-
selection fix) relative to K.

[F] Ran `test_historical_backtesting_api.py` against this pre-L tree twice
(first run hit a transient teardown-contention error from an immediately-
preceding invocation, see section C; the second run was clean):
`4 failed, 10 passed` -- **the same 4 tests, same failure shape**, confirming
these 4 failures predate L and are not caused by L's changes. This
independently re-derives L's own claim rather than merely trusting it.

[F] Restored via `git checkout 708380c -- .`; `git status --short` again
showed a clean tree (only `docs.rar` untracked). Working tree returned to
exactly the pre-diagnosis state before Part 2/3 began.

## B. Per-failure diagnosis

All four failures were investigated independently (per the directive's
explicit instruction not to assume shared cause just because same file).
Each one's `/progress/` response body was captured directly (not inferred)
and each carries the identical `failed_instruments[0].reason` string:
`INELIGIBLE_PROVENANCE: 72x SYNTHETIC_TEST not research-eligible (only
REAL_DHAN is) for NSE:RELIANCE ...`. All four independently trace to the
same code path:

1. `_client_as_operator()` posts to `/api/v1/config/backtesting/
   historical-runs/` -> `historical_backtesting_views.
   create_historical_backtest_run_view` -> `tasks.
   build_historical_backtest_orchestrator()`.
2. `build_historical_backtest_orchestrator()` wires
   `HistoricalDataPreparationService(provider=_select_historical_bar_
   provider())`. The file's own `autouse` fixture (`_no_real_dhan_
   credentials`) forces `DhanSettingsService.effective_credentials()`
   to return `None`, so `_select_historical_bar_provider()` (tasks.py:212)
   takes its documented "HONEST FALLBACK" branch and returns
   `SyntheticHistoricalBarProvider()`.
3. The orchestrator fetches 72 bars from the synthetic provider, persists
   them (tagged `provenance=SYNTHETIC_TEST`), then hands off to
   `BacktestingService.for_database_backed_research()`'s wired
   `ResearchDataGateService.get_research_eligible_bars()`
   (`research_data_gate.py:216`, `is_research_eligible()` in
   `provenance.py:57-63`), which rejects every row because only
   `PROVENANCE_REAL_DHAN` is research-eligible -- correctly, by design.
4. The run terminates `FAILED` with `INELIGIBLE_PROVENANCE`, so every
   assertion downstream of `status == "COMPLETED"` fails identically.

Classification for all four: **ENVIRONMENT_DRIFT**. The research-
eligibility restriction to `REAL_DHAN`-only provenance is genuine,
intentional, already-confirmed-correct production behavior (independently
re-confirmed working end-to-end by 67.12.2-L). It is not a regression --
`provenance.py`'s `is_research_eligible()` (git-blamed to checkpoint
65.14) and its wiring into `BacktestingService.for_database_backed_
research()` (git-blamed to checkpoint 67.1, `ea17691`) both predate this
diagnosis and were deliberately built. `test_historical_backtesting_api.py`
itself was last substantively touched by pre-67.x commits (`35dae5a`
"Real Dhan historical market data...", `4ef614c` "Fix DECIMAL strategy
parameters...") -- i.e., this test file's reliance on the synthetic-
provider fallback to reach a real `COMPLETED` status predates checkpoint
67.1's research-gate wiring and was never updated for it.

**test_scenario_b_repeat_run_makes_zero_api_requests specifically**: uses
`NSE:RELIANCE`, which IS `CATEGORY_I_CAS`-classified (confirmed against
`test_historical_data_preparation.py`'s own comment: "Checkpoint 64.87
... classified RELIANCE CATEGORY_I_CAS"). However, **this is NOT the same
bug shape as J's Failure 1**. J's CAS-drift bug was about a stale expected
*bar-count/cache-hit* literal that predated CAS-awareness in the coverage-
completeness calculation for a CAS-classified instrument. Scenario_b never
reaches any bar-count or cache-hit assertion tied to CAS session
structure -- it fails at the `status == COMPLETED` gate before that,
for the identical `INELIGIBLE_PROVENANCE` reason as the other 3 API
tests in this file. The shared instrument (RELIANCE) is coincidental,
not evidence of a shared root cause. Explicitly: **shares_root_cause_
with_J: NO**.

The other 3 failures were each traced independently to the exact same
`_select_historical_bar_provider()` -> `SyntheticHistoricalBarProvider`
-> `INELIGIBLE_PROVENANCE` chain, with no CAS-related code on their
failure path at all (`test_coverage_preview_...` and `test_a_decimal_
typed_strategy_parameter_...` never even reach a coverage/cache-hit
assertion).

## C. What was fixed and why safe

**Nothing in the 4 API-level test failures was fixed.** Per the
checkpoint's explicit bar ("provably narrow: stale fixture, mismatched
literal, renamed field"), the required change here does not qualify: it
is not a one-line constant/literal update. Correcting these tests would
require redesigning how each test seeds its `HistoricalBar` rows (e.g.
seeding `REAL_DHAN`-provenance rows directly before hitting the API,
matching the pattern already established in `test_research_data_gate.py`
and `test_checkpoint_67_12_2_L_gate_filters_synthetic.py`, or replacing
the no-credentials fallback with a fake `REAL_DHAN`-stamped provider
double for this file specifically). That is genuine test-design work,
not a narrow patch, and risks silently changing what these API tests are
actually proving if done hastily -- so it was deliberately left
untouched and reported instead.

**Contention ERRORs**: diagnosed as NOT matching 67.12.2-K's pattern.
K's fix (`INTRADAY_TEST_DB_NAME`) addresses a *subprocess* spawned
*within* a single test process (the migration dry-run re-run subprocess
in `test_migration_67_10_execute.py`) racing the *same* outer pytest
session's `test_intraday` database while that session is still active.
What this checkpoint reproduced instead was purely an artifact of my own
back-to-back tool invocations: an earlier pytest command that failed on
an unrelated `tee`/file-permission error left two orphaned
`.venv\Scripts\python.exe -m pytest ...` processes still running (
`tasklist` confirmed PIDs 21396 and 600, both still holding the exact
sweep command line), which held connections against `test_intraday` and
caused the next invocation to see "database ... already exists" /
"being accessed by other users" / then cascading `does not exist` /
`relation does not exist` errors as two pytest runs raced to
create/drop/recreate the same database. Killing the orphaned PID 21396
(600 had already exited) and re-running produced a completely clean
sweep with zero contention errors. **No production or test-infra code
change was needed or applied for this** -- it was an execution-hygiene
issue in this diagnosis session, not a reproducible flaw in the test
suite or its fixtures, and it does not match K's subprocess-collision
shape. `contention_errors_resolved: YES` reflects "resolved by killing
the stray process," not "a code fix was applied."

## D. What remains and why deliberately deferred

All 4 `test_historical_backtesting_api.py` failures remain failing,
deliberately. They are not classified `GENUINE_REGRESSION_IN_PRODUCTION_
CODE` -- the production research-gate behavior they hit is confirmed
correct and intentional (per L's independent proof and this checkpoint's
own re-derivation of the same rejection reason). But they are also not
`STALE_TEST_INFRASTRUCTURE` in the narrow sense this checkpoint's fix bar
requires (a literal/constant/fixture-value update) -- fixing them
requires a genuine test-design decision about how this file seeds
research-eligible data, which risks masking a real gap if done as an
inline patch under this checkpoint's already-large scope. This is
reported, not patched, per P14 ("no property may be reported as fixed
merely because it is documented") and the checkpoint's own prohibition
against anything beyond a provably narrow fix.

## E. Recommended next checkpoint

A dedicated checkpoint (67.12.2-O or later) should redesign
`test_historical_backtesting_api.py`'s 4 failing tests' data setup to be
research-gate-compatible -- most likely by seeding `REAL_DHAN`-provenance
`HistoricalBar` rows directly (bypassing `_select_historical_bar_
provider()`'s synthetic fallback for these specific tests), reusing the
exact seeding pattern already proven in `test_checkpoint_67_12_2_L_
gate_filters_synthetic.py` and `test_research_data_gate.py`, OR by
introducing a small `FakeRealDhanHistoricalBarProvider` test double (test-
only, never touching `tasks.py`/`backtesting_views.py` production code)
that this file's `autouse` fixture substitutes in place of `Synthetic
HistoricalBarProvider`, stamping `provenance=REAL_DHAN` on its output so
the existing `api_requests`/`cache_hits`/`cache_misses`/bar-count
assertions keep proving what they were written to prove. That checkpoint
should NOT touch `research_data_gate.py`, `provenance.py`, or `tasks.py`
-- the gate is correct; only the test fixture is stale.
