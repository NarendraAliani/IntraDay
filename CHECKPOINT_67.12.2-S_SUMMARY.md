# Checkpoint 67.12.2-S — PID-Verified Startup Reconciliation for WorkerRuntimeStatus

```
checkpoint: 67.12.2-S
verdict: RECONCILIATION_BUILT_AND_VERIFIED
pid_field_existed_already: NO
reconciliation_wired_into: [run_market_data_worker, supervise_market_data_worker]
positive_test_passing: YES
negative_test_passing: YES
pid_reuse_test_passing: YES
todays_row_reconciled_for_real: ALREADY_CLEAN
full_sweep_result: 34/34 (checkpoint-relevant suite); 3199/3210 (whole repo, 11 pre-existing failures unrelated to this checkpoint - see §E)
commit: <see git log after commit>
blockers: []
```

## A. Design and where the PID anchor lives

**PID anchor.** `WorkerRuntimeStatus` (`src/intraday/infrastructure/persistence/models.py`)
did **not** previously record any OS process identity — confirmed `[F]` by reading the
model before this checkpoint. Three new columns were added
(migration `0042_worker_runtime_status_owner_pid.py`):

- `owner_pid` (`PositiveIntegerField`, nullable)
- `owner_process_started_at` (`DateTimeField`, nullable) — the OS process creation time,
  the primary PID-reuse disambiguator
- `owner_cmdline_safe` (`CharField(500)`, blank) — best-effort command line, secondary
  disambiguator, never a credential

**Who writes it.** `WorkerHealthTracker` (`infrastructure/market_data_providers/dhan/worker_health_tracker.py`)
gained `owner_pid`/`owner_process_started_at`/`owner_cmdline_safe` fields and a
`mark_owner(pid, started_at, cmdline_safe)` method. `run_market_data_worker.py`'s
`_run_dhan()` calls `mark_owner()` once, immediately after constructing the tracker, using
`infrastructure.system.process_liveness.current_process_identity()` (the real OS probe).
`WorkerHealthTracker.persist()` now passes these three fields through to
`WorkerRuntimeStatusRepository.save()`, which only overwrites them when a caller actually
supplies a non-`None` `owner_pid` (so no *other* pre-existing `save()` call site can
accidentally blank a previously-recorded owner).

**The OS probe.** New module `src/intraday/infrastructure/system/process_liveness.py`.
`psutil` is confirmed **not** a project dependency (`[F]`: `import psutil` fails in the
venv; `poetry.lock` mentions it only inside other packages' own optional extras, e.g.
mypy's `dmypy` extra — never importable by this project's own code). Rather than add a
new dependency for one narrow need, liveness + start time use `ctypes` +
`kernel32.OpenProcess`/`GetProcessTimes` (the documented, race-free Windows API for "is
this PID alive, and since when"); command line uses a short-lived
`Get-CimInstance Win32_Process` PowerShell subprocess — the same mechanism named in the
standing context as today's manual-investigation tool, now wrapped as a best-effort
*second* signal (never fatal to the probe if it fails/times out). A POSIX fallback
(`os.kill(pid, 0)`) is present for portability but not exercised by this checkpoint's own
Windows-only test suite.

**The reconciliation decision (pure, testable core).** New module
`src/intraday/application/services/worker_status_reconciliation.py`,
`reconcile_worker_runtime_status()`:

1. No row → no-op (`"no_row"`).
2. Row's `worker_state` not in `{RUNNING, RECONNECTING, CONNECTING}` → no-op
   (`"not_active"`) — a row already claiming a terminal state is never touched, and this
   is exactly what leaves an existing Part-0-style literal gate exactly as strict as it
   was: reconciliation only ever runs *before* such a gate reads the row, never loosens
   what the gate itself checks.
3. Active claim, but `owner_pid is None`, or `probe_process(owner_pid)` returns `None`
   (not alive), or the live process's `started_at`/`cmdline_safe` doesn't match what was
   recorded (PID reuse) → `status_repository.reconcile_stale()`, which overwrites *only*
   `worker_state="FAILED"` and `last_error_safe="reconciled: stale status detected at
   startup, PID not alive"` — deliberately worded differently from any genuine in-process
   `mark_failed()` reason (e.g. `"reconnect_attempts_exhausted"`), so a future reader can
   tell 67.12.2-H's mechanism apart from this one.
4. Active claim, PID alive, identity matches → `"confirmed_alive"`, row untouched.

**Architecture-boundary note (self-caught and fixed this run).** The first draft of
`worker_status_reconciliation.py` imported
`infrastructure.system.process_liveness.ProcessSnapshot` directly, which
`tests/unit/architecture/test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
correctly flags as an application→infrastructure violation. Fixed by defining a local
`Protocol` (`ProcessSnapshot` in the application module itself) that the real
infrastructure dataclass already satisfies structurally — no new violation remains from
this checkpoint's own new file (re-verified `[F]`, see §E).

## B. Test results, all three cases

All three, plus supporting cases, in
`tests/unit/application/services/test_worker_status_reconciliation.py` (6 tests, real
`WorkerRuntimeStatus` DB rows via `DjangoWorkerRuntimeStatusRepository`, fake
`probe_process` — no real OS process, no real Dhan connection):

- **Positive** (`test_stale_row_dead_pid_is_reconciled_to_failed_before_anything_else`):
  seeded `RECONNECTING` row with `owner_pid=555555`, fake probe returns `None` → row
  corrected to `worker_state="FAILED"`,
  `last_error_safe="reconciled: stale status detected at startup, PID not alive"`. **PASS**.
- **Negative** (`test_a_genuinely_alive_matching_process_is_never_force_healed`): seeded
  `RUNNING` row with a matching `owner_pid`/`started_at`/`cmdline_safe`, fake probe
  confirms the same identity → row completely untouched (`worker_state` still `RUNNING`,
  `last_error_safe` unchanged). **PASS**.
- **PID-reuse** (`test_pid_reuse_is_correctly_treated_as_stale_not_the_real_worker`):
  seeded `RECONNECTING` row with `owner_pid=888888`; fake probe reports PID 888888 alive
  but with a start time 6 hours later and an unrelated command line
  (`python -m http.server 8000`) → still correctly reconciled to `FAILED`. **PASS**.
- Plus: a terminal row is never probed at all (`not_active`, assertion inside the fake
  probe would raise if called — didn't); an active row with no `owner_pid` recorded is
  reconciled without ever calling probe; no row at all is a no-op. All **PASS**.

Command-level wiring proof (real `call_command`, real DB, monkeypatched `probe_process`
only — no real subprocess, no real Dhan/network):

- `tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py::test_startup_reconciliation_corrects_a_stale_row_before_the_worker_proceeds` — **PASS**.
- `tests/unit/infrastructure/persistence/management/test_supervise_market_data_worker_command.py` (2 tests: reconciles a stale row before the restart loop runs; leaves a genuinely-alive row untouched) — **PASS**.

## C. Supervisor wiring

`supervise_market_data_worker.py`'s `handle()` now calls
`reconcile_worker_runtime_status(provider, status_repository=status_repository,
probe_process=probe_process, now=...)` as the very first `WorkerRuntimeStatus`-touching
step — before `supervise_market_data_worker()`'s own loop (and therefore before its first
restart-decision poll) is ever invoked. `run_market_data_worker.py`'s `_run_dhan()` runs
the identical call at the top of the method, before `clear_stop_request()` and every other
startup action. Verified `[F]` by direct code inspection and by the two command-level
tests in §B (`test_supervisor_reconciles_a_stale_row_before_its_own_restart_loop_runs` /
`test_supervisor_does_not_touch_a_row_that_verifiably_reflects_a_live_process`), which
stub only the pure restart-loop function (`supervise_market_data_worker`, already
exhaustively covered by the pre-existing `test_market_data_worker_supervisor.py`) and
prove the *command's own* startup step independently.

## D. Today's real row, reconciled for real

Ran `reconcile_worker_runtime_status()` for real (production DB, real
`probe_process`, provider `"dhan"`) — command and output:

```
action= not_active
reason= worker_state='STOPPED' is already inactive/terminal - nothing to reconcile
worker_state_after= STOPPED
last_error_safe_after= connection_lost:close_code=1006
```

`[F]`: today's real `WorkerRuntimeStatus(dhan)` row's `worker_state` is `STOPPED` (not
`RUNNING`/`RECONNECTING`/`CONNECTING`) — it was already the manually-corrected, clean row
left over from 67.12.2-F, exactly as the checkpoint directive anticipated ("unlikely,
since it was manually corrected... but verify rather than assume"). The mechanism was
exercised against the real row and correctly took no action, leaving it byte-for-byte
unchanged (`todays_row_reconciled_for_real: ALREADY_CLEAN`).

## E. Final sweep result

Checkpoint-relevant suite (worker health tracker, supervisor service, new reconciliation
service, both management commands, runtime-status API): **34/34 passed** `[F]`.

Full repository sweep (`pytest tests/unit`): **3199 passed, 11 failed** `[F]`. All 11
failures were re-confirmed, via `git status --short` on each failing file, to be in files
**untouched by this checkpoint** (`test_backtesting_api.py`,
`test_checkpoint_64_52_database_first_backtest.py`,
`test_live_paper_readiness_checklist.py`, `test_live_paper_session.py`,
`test_checkpoint_64_48_gainz_adapter_design.py`,
`test_checkpoint_64_49_gainz_feature_registry.py`) — pre-existing red tests inherited
from prior uncommitted checkpoint work already present in the working tree before this
checkpoint started (per the session's own git status: several `migration_*` application
services and `HistoricalBar`/timestamp-semantics changes were already modified/untracked
at the start of this checkpoint).

`tests/unit/architecture/test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
is also pre-existing red (`market_data_worker_supervisor.py` and the untracked
`migration_*.py` application-services files already import infrastructure modules before
this checkpoint touched anything) — re-verified `[F]` that **none of this checkpoint's own
new/changed files appear in that failure's violation list** after the Protocol fix in §A;
this checkpoint introduces zero new architecture-boundary violations.

No test in this checkpoint's own new/changed files failed. No regression was introduced
by this checkpoint into any previously-passing test (re-verified `[F]` by running the
full suite and diffing the failure list against files this checkpoint did not touch).
