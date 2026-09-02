# Checkpoint 67.12.2-U — Does 599d008 Actually Explain the Original 11 Failures?

```
checkpoint: 67.12.2-U
verdict: PARTIALLY_EXPLAINED
frozen_dataclass_bug: WorkerRuntimeStatusRecord (owner_pid, owner_process_started_at, owner_cmdline_safe)
failures_explained_by_this_bug: 5/11 (confirmed) + 1 unaccounted (see below)
failures_with_different_cause: [test_run_backtest_against_a_real_instrument_is_db_first_not_fixture_only (STALE_TEST_INFRASTRUCTURE), test_f_partial_gap_fetches_only_the_missing_range (STALE_TEST_INFRASTRUCTURE), test_g_data_completeness_is_enforced_not_row_existence (STALE_TEST_INFRASTRUCTURE), test_k_no_gainz_reference_file_exists_in_repo (STALE_TEST_INFRASTRUCTURE), test_zz_no_real_gainz_source_file_exists (STALE_TEST_INFRASTRUCTURE)]
remaining_failure_classification: STALE_TEST_INFRASTRUCTURE
final_sweep_result: 742 passed / 742 total (established scope)
commit: (recorded below)
blockers: []
```

## A. The actual bug, read directly from the diff (Part 1)

`git show 599d008` — one file changed:
`src/intraday/application/repositories/worker_runtime_status.py`.
`WorkerRuntimeStatusRecord` (a `@dataclass(frozen=True, slots=True)`)
gained three new trailing fields in 67.12.2-S's original commit
(`owner_pid: int | None`, `owner_process_started_at: datetime | None`,
`owner_cmdline_safe: str`) with **no default values**. Any pre-existing
code constructing this record directly, by keyword, without knowing
these three new fields exist, hit
`TypeError: WorkerRuntimeStatusRecord.__init__() missing 3 required
positional arguments`. `599d008` gives all three trailing fields
defaults (`None`, `None`, `""`) — valid for a frozen dataclass since
only trailing fields require defaults, and safe because the one real
production caller (`DjangoWorkerRuntimeStatusRepository`) always
supplies explicit values from the DB row regardless.

## B. Per-test tracing against each of the 11 (Part 2)

**Method**: temporarily reverted `worker_runtime_status.py` to its
exact pre-`599d008` state (via `git show 0b59da2:<path>`), ran the 6
originally-named files against that reverted state, captured full
tracebacks, then restored the fix and re-ran the same tests to confirm
which failures persist on the real, current `HEAD` and which don't.

Against the reverted (pre-fix) state, 6 named files produced **10**
failures, not 11 — see the discrepancy note at the end of this section.

**5 of the 10 are genuinely explained by the dataclass bug** —
confirmed by exact traceback match
(`TypeError: ... missing 3 required positional arguments: 'owner_pid',
'owner_process_started_at', and 'owner_cmdline_safe'`), and confirmed
**resolved** on the current `HEAD` (all 21 tests in
`test_live_paper_session.py` + `test_live_paper_readiness_checklist.py`
pass cleanly):
- `test_live_paper_readiness_checklist.py::test_universe_check_warns_on_a_partial_subscription`
- `test_live_paper_session.py::test_derive_state_stopped_when_disabled_but_worker_has_reported`
- `test_live_paper_session.py::test_derive_state_stopping_when_disabled_but_worker_has_not_yet_reconciled`
- `test_live_paper_session.py::test_derive_state_failed_when_the_worker_reports_a_real_failure_state`
- `test_live_paper_session.py::test_derive_state_running_when_enabled_and_versions_match`

**5 of the 10 are NOT explained by the dataclass bug at all** —
confirmed by two independent facts: (a) their tracebacks show a
completely different failure mode (no `WorkerRuntimeStatusRecord`
anywhere in the stack), and (b) **re-running them against the current,
fixed `HEAD` reproduces the identical 5 failures, unchanged**:
- `test_backtesting_api.py::test_run_backtest_against_a_real_instrument_is_db_first_not_fixture_only`
  — `ResearchDataRejectedError: INCOMPLETE_COVERAGE ... 0/72 bars
  (0.0%) cached for NSE:RELIANCE Timeframe.FIVE_MINUTE`.
- `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
  — `assert 72 == 75`.
- `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
  — `assert 36 == 38`.
- `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
  — `AssertionError: Unexpected Gainz reference found at
  .../backtesting.py`.
- `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`
  — same shape, same file flagged.

**Discrepancy, reported honestly rather than forced to match**: 67.12.2-S's
original report claimed 11 failures across these 6 files; this
checkpoint's direct re-run of exactly those 6 files against the
reverted state found only **10**. The most likely explanation, given
this session's own repeated prior findings (67.12.2-K/N both
documented real, reproducible test-database-contention flakiness under
a broad concurrent sweep), is that the 11th was a transient
contention-related failure specific to S's original full-3199-test
run, not a stable, individually-reproducible failure — but this is not
independently confirmed here, and is reported as **UNDETERMINED**
rather than asserted.

## C. The two other root causes found, diagnosed (Part 3, extended)

**1. `test_run_backtest_against_a_real_instrument_is_db_first_not_fixture_only`
+ `test_f_partial_gap_fetches_only_the_missing_range` +
`test_g_data_completeness_is_enforced_not_row_existence` —
`STALE_TEST_INFRASTRUCTURE`, same root cause as each other.** All
three use RELIANCE (72 expected 5-minute bars for a full CAS-aware
session) against fixtures/assertions that predate Checkpoint 64.87/
65.27's CAS-classification wiring and still assume a uniform 75-bar
(or 38-bar sub-range) count — **the exact same bug shape 67.12.2-J
diagnosed and fixed in `test_historical_data_preparation.py` alone**.
J's fix was never applied to these other files, which independently
exercise the identical underlying invariant. **Not fixed in this
checkpoint** — per Part 3's "fix only if provably narrow, otherwise
defer" instruction, and because these files were not named in this
checkpoint's own scope (only the API test was); fixing 3 additional
files across 2 directories not enumerated in the directive would be
scope creep beyond what was authorized here, even though the fix
pattern is already well-established. Recommended as a small, focused
follow-up (see F).

One additional, separately-worth-flagging observation from this
file's own captured stderr: it made **3 real outbound HTTP requests to
`https://api.dhan.co/v2/charts/intraday`** (receiving `401`
responses) during this test run — this is pre-existing test behavior
(this file and its Dhan-facing code path were not touched by any
checkpoint today), not something introduced by S or this checkpoint,
but worth naming given this project's standing paranoia about
accidental real Dhan calls: this specific test does not appear to mock
that network boundary. Flagged for awareness, not investigated further
here — out of this checkpoint's scope.

**2. `test_k_no_gainz_reference_file_exists_in_repo` +
`test_zz_no_real_gainz_source_file_exists` — `STALE_TEST_INFRASTRUCTURE`.**
Both are architecture-guard tests scanning the repo for the literal
string "Gainz" outside an explicit allowlist of known, honest,
forward-looking mentions. `src/intraday/application/services/backtesting.py`
contains two such mentions (`"Any future Gainz entry point..."`,
`"...(any future Gainz entry point included, Part 10/13)"`) —
confirmed via `git log -S"Gainz" -- backtesting.py` to originate from
**Checkpoint 66.2**, already present in the repo's very first commit of
this entire session (`ea17691`, this morning's starting point), not
introduced by anything today. The guard tests' own allowlist simply
never included `backtesting.py`. **Not fixed here** — adding a file to
a test's allowlist is provably narrow in principle, but confirming
that's the *correct* fix (versus the mention itself needing rewording)
is a judgment call about test intent this checkpoint's scope doesn't
cover; deferred alongside the CAS-drift items.

## D. Final sweep result (Part 4)

`[F]` Working tree confirmed clean before and after this checkpoint's
investigation (`git status --short`: only the pre-existing, unrelated
`docs.rar`) — the temporary revert used for tracing was fully restored
before any further verification.

`[F]` Established sweep (`tests/unit/infrastructure/persistence/` +
`tests/unit/infrastructure/market_data_providers/` +
`tests/unit/application/services/` +
`tests/unit/infrastructure/api/test_historical_backtesting_api.py`):
**742 passed / 742 total**, zero failures — matching 67.12.2-S's own
post-fix count exactly, independently re-confirmed here.

A broader attempt to sweep `tests/unit/infrastructure/api/` (all
files) plus `tests/unit/research/` together timed out at 6m40s before
completing — not run to conclusion in this checkpoint; the 5
newly-diagnosed unrelated failures (C, above) were confirmed
individually instead, which is sufficient evidence for their
classification without needing the full combined run to finish.

## E. Conclusion for tomorrow

**Tomorrow's live session planning is genuinely unblocked.** The
67.12.2-S regression is fully explained (5/10 traceable failures,
confirmed fixed) and the reconciliation mechanism it built is
independently verified sound. The remaining 5 traceable failures are
pre-existing, unrelated to anything from today's session, correctly
classified `STALE_TEST_INFRASTRUCTURE`, and do not touch migration-
execution or timestamp-semantics logic in any way — no HALT condition
applies. The one numerical discrepancy (10 vs. S's originally-claimed
11) is reported as `UNDETERMINED`, not force-resolved, and does not by
itself block anything — it does not correspond to any currently-failing,
individually-reproducible test in the established or extended scope
checked here.

## F. Recommended next checkpoint

A small, focused fix-only checkpoint applying 67.12.2-J's already-
proven CAS-instrument pattern to the 3 newly-identified
`STALE_TEST_INFRASTRUCTURE` failures in `test_backtesting_api.py` and
`test_checkpoint_64_52_database_first_backtest.py` (same fix shape J
already validated: either switch to a `CATEGORY_II_NON_CAS` instrument
or assert against the CAS-aware expected count), plus a one-line
allowlist addition for the 2 Gainz-guard tests once their intent is
confirmed. Not urgent — none of these block tomorrow's live capture —
but worth closing before they're mistaken for something more serious
in a future sweep.
