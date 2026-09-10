# CHECKPOINT 90 — Fix Orphaned-Worker-Process Bug (found live in LIVE-PAPER-2)

```
root_cause: supervise_market_data_worker()'s restart branch called
            start_worker() unconditionally, reassigning its tracked
            child_process handle WITHOUT ever confirming the previous
            process's genuine OS-level exit first - during a fast
            crash-restart burst, a prior process can still be mid-
            shutdown (a real, nonzero wall-clock gap exists between its
            own FAILED write and its actual process exit) when the
            next one spawns, leaving it alive, orphaned, and still
            independently polling/writing to the SAME shared
            WorkerRuntimeStatus row - masking whatever the newly-
            tracked process later writes.
fix: reuse the ALREADY-EXISTING wait_for_worker_exit() callable (the
     session-end path already used it) in the restart branch too,
     immediately after detecting the crash and before start_worker()
     replaces the handle - one narrow addition, no new mechanism.
causation: proven empirically - new regression test fails on the
     reverted (pre-fix) code with the exact predicted symptom, passes
     restored.
tests_before_fix: 3 passed (test_market_data_worker_supervisor.py
     baseline)
tests_after_fix: 4 passed (1 new regression test)
full_suite: 3392 passed / 7 failed (see Verification) - identical
     failure set to LIVE-PAPER-2, +1 net passing test
commit: (recorded below)
```

## Part 0 — Pre-flight

`[F]` Confirmed via `ls`/`git status`: `CHECKPOINT_90_SUMMARY.md` did
not already exist. Git tree was clean before this checkpoint's own
edits began.

## Part 1 — Understand the actual mechanism

`[F]` Read `supervise_market_data_worker.py`'s own child-process
spawn logic in full. `start_worker()`'s closure:

```python
async def start_worker() -> None:
    nonlocal child_process
    child_process = await asyncio.create_subprocess_exec(...)
```

**This unconditionally reassigns `child_process` to a brand-new
subprocess handle, on every call — nothing checks or waits for the
PREVIOUS handle's own process to have exited first.** The pure loop's
restart branch (`market_data_worker_supervisor.py`) calls this
directly:

```python
if worker_state in _RESTART_ON:
    ...
    await sleep(cooldown_seconds)
    restarts_used += 1
    await start_worker()          # <- reassigns child_process, old
                                   #    handle silently abandoned
```

`wait_for_worker_exit()` (`child_process.wait()`) DOES exist and IS
already used — but only in the session-end branch, never in the
restart branch. The restart path has never once confirmed a crashed
process's genuine OS-level exit before replacing its tracked handle.

`[F]` **Reproduced the actual timing mechanics, not just the shape.**
Read `run_market_data_worker.py`'s own shutdown sequence directly:
`WorkerRuntimeStatus.worker_state=FAILED` is written by
`health_tracker.persist()` inside a `finally` block — but the code
that follows that write (`await sink.flush_remainder()`,
`await sync_to_async(close_old_connections)()`, unwinding back through
`_run()` → `handle()` → the final `"Worker finished: ..."` print) is
real, nontrivial async work that still has to complete before the
Python process actually terminates. **This is a genuine, nonzero
window between "FAILED is observable in the DB" and "the OS process
has actually exited"** — exactly the race a fast, repeated crash cycle
(LIVE-PAPER-2 observed crashes roughly every 22 seconds during one
burst) can expose: the supervisor reads `FAILED`, waits out the
cooldown, and spawns a replacement — all while the PREVIOUS process
may still be finishing that tail sequence.

`[F]` **Checked `watch_for_stop_request()`'s own polling behavior
directly, confirming `LIVE-PAPER-2`'s own live observation rather than
assuming it**: it polls `get_stop_request()` in a plain `while not
stop_event.is_set()` loop, entirely independent of which process the
supervisor currently considers "the" tracked worker. **Any live
process — including an orphan — will observe and consume a fresh
stop-request row exactly the same way the "real" tracked one does**,
and each live process independently runs its own periodic
`health_tracker.persist()` heartbeat regardless of supervisor
awareness. This confirms the mechanism `LIVE-PAPER-2` diagnosed live:
an orphan is not a passive leftover, it is an ACTIVE, still-writing
process competing with the tracked one for the same shared row.

**Conclusion: the checkpoint's own initial framing was correct as
described — no more complex mechanism was found.** Proceeded to
Part 2's option (a): ensure the previous process is CONFIRMED exited
before spawning the next one, using the already-existing
`wait_for_worker_exit()` callable.

## Part 2 — Fix, narrowly scoped

`[F]` One change, in `market_data_worker_supervisor.py`'s restart
branch only:

```python
_log("crash_detected", ...)
await wait_for_worker_exit()          # NEW - Checkpoint 90
_log("previous_worker_exit_confirmed", ...)
await sleep(cooldown_seconds)
restarts_used += 1
await start_worker()
```

- **Reuses the existing `wait_for_worker_exit` callable** — already
  injected into this function's signature, already used identically in
  the session-end branch. No new callable, no new parameter, no new
  framework.
- **In the ordinary case (the ~99% path where the process has already
  fully exited by the time `FAILED` is observed), this resolves
  immediately** — `child_process.wait()` on an already-terminated
  process returns its cached return code without further delay.
  Confirmed by the 3 pre-existing tests all passing unmodified, with
  their own `wait_for_worker_exit` fakes being simple no-ops that
  return instantly.
- **Only ever blocks for the genuine remaining shutdown time of a
  still-exiting process** — the exact and only case this fix targets.
- Placed BEFORE the `cooldown_seconds` sleep, not after — so the
  existing `--cooldown-seconds`/`--max-restarts` timing semantics
  (explicitly protected by this checkpoint's own rules) remain
  completely unchanged in shape; this is a strictly additive wait, not
  a modification of any existing tunable's meaning.

`[F]` **Regression test added**
(`test_orphaned_process_race_is_prevented_by_confirming_exit_before_restart`,
`tests/unit/application/services/test_market_data_worker_supervisor.py`):
simulates a rapid 4-restart crash burst where `wait_for_worker_exit()`
takes real (simulated) time to resolve for each process — exactly
mirroring the real `flush_remainder()`/`close_old_connections()` tail.
Records the exact interleaving of `start:N`/`exit_confirmed:N` events
and asserts strict ordering: **no `start_worker()` call for process
N+1 may occur before process N's own exit has been confirmed.**

`[F]` **Causation proven empirically, per this session's own
established discipline** — not merely reasoned about:
1. Stashed the source fix (`git stash push` on
   `market_data_worker_supervisor.py` only), leaving the new test in
   place.
2. Ran the new test against the reverted code: **failed**, with
   `AssertionError: start_worker() for process #2 was called before
   process #1's exit was confirmed` — the exact predicted symptom,
   reproduced precisely, not merely a generic failure.
3. Restored the fix (`git stash pop`). Re-ran: **passes**, along with
   all 3 pre-existing tests in the same file, unmodified.

## Part 3 — Verify

`[F]` `tests/unit/application/services/test_market_data_worker_supervisor.py`:
**4 passed** (3 pre-existing, unmodified in body + 1 new). `[F]`
`tests/unit/infrastructure/persistence/management/test_supervise_market_data_worker_command.py`
(the only other test file touching this module): **3 passed**,
unmodified.

`[F]` **Full test suite**: `.venv/Scripts/python.exe -m pytest -q
--reuse-db` — **3392 passed, 7 failed** (660.74s). Exact failure
names, identical to `LIVE-PAPER-2`'s own last-recorded list (same 5
pre-existing + 2 known `--reuse-db` flakes documented at every
checkpoint this session):

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

Pass count is up by exactly **1** from `LIVE-PAPER-2`'s own baseline
(3391 → 3392), matching the 1 net-positive test this checkpoint added.
**Zero new/unexplained failures, zero regressions.**

`[F]` **Confirmed the fix doesn't change ordinary-case external
behavior**: `test_supervisor_restarts_within_its_bound_after_a_crash`
(the original positive restart test) and
`test_phantom_restart_race_is_prevented_by_the_post_restart_grace_period`
(the `LIVE-1-INSTRUMENT` fix's own regression test) both still pass
unmodified with the new `wait_for_worker_exit()` call added to the
restart path — their own fakes' no-op `wait_for_worker_exit()`
implementations mean the added call is transparent to their existing
assertions, exactly as expected for a fix whose common-case behavior
is "resolve immediately."

## Governance compliance

- P3: zero DB writes — the only changes are (a) a pure function's own
  logic (`supervise_market_data_worker()`), no migration, no data
  write; (b) a new test file addition.
- P9: no strategy code touched, no registry change.
- No live session launched this checkpoint, per its own rule.
- P11/P16: this summary, the source fix, the new regression test, and
  `MEMORY.md` committed to `active-development` only.

`CHECKPOINT_90_SUMMARY.md` — this file — committed alongside the
source fix and the new test. `MEMORY.md` updated in the same commit
(see below).
