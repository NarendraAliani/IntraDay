# Checkpoint LIVE-1-INSTRUMENT — Close-Code Logging + Phantom-Restart Investigation

```
checkpoint: LIVE-1-INSTRUMENT
verdict: BOTH_FIXED
close_code_logging_added: YES
phantom_restart_confirmed_as_race: YES
phantom_restart_fixed: YES
tests_added: 2
full_sweep_result: 283/283
commit: (recorded after commit, see below)
blockers: []
```

## A. Per-attempt close-code logging

`[F]` Read `run_market_data_worker.py::_run_dhan`'s `connect_and_run()` closure.
`health_tracker.mark_reconnecting()` was already being called on both the
`connect_failed` branch and the mid-stream-disconnect branch, and the
mid-stream branch already built a `reason` string containing
`result.last_close_code` (from `websocket_transport.py`'s `close_code`
property, Checkpoint 64.23). But neither call site ever wrote anything to
`self.stdout` — only the final aggregate line at the bottom of `_run_dhan`
(`reconnect_count=... attempts=... last_disconnect_reason=...`) was ever
printed. This is exactly the gap the postmortem found: the data existed
in-process, per attempt, but was never logged per attempt.

**Fix** (`src/intraday/infrastructure/persistence/management/commands/run_market_data_worker.py`):
added one `self.stdout.write(self.style.WARNING(...))` call immediately
after each of the two `health_tracker.mark_reconnecting()` call sites,
printing `reconnect attempt #<n>: <reason>` — where `<reason>` includes
`connection_lost:close_code=<code>` for a real mid-stream disconnect, or
`connect_failed:<repr>` for a failed connection attempt. `#<n>` comes from
`health_tracker.reconnect_count`, which increments inside `mark_reconnecting()`
itself, so it is always in sync with the real attempt number.

**Test** (`tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py::test_each_reconnect_attempt_logs_its_own_distinct_close_code`):
patches `DhanWebSocketTransport.connect/send_json_text/close` to no-ops and
`run_worker_against_websocket` (in the command module's own namespace) to
return three results in sequence — `RECONNECTING` with `last_close_code=1006`,
`RECONNECTING` with `last_close_code=1011`, then a clean `STOPPED` — and
asserts the stdout capture contains BOTH per-attempt lines with their
DISTINCT close codes (`close_code=1006` for attempt #1, `close_code=1011`
for attempt #2), and that no spurious third "reconnect attempt" line
appears for the clean stop. `[F]` Ran directly: **passed**.

## B. Phantom-restart investigation — confirmed as a genuine race

`[F]` Read `supervise_market_data_worker`'s loop
(`src/intraday/application/services/market_data_worker_supervisor.py`).
On detecting `worker_state == FAILED` (the `_RESTART_ON` branch), the
loop:
1. logs `crash_detected`,
2. `await sleep(cooldown_seconds)`,
3. increments `restarts_used`,
4. `await start_worker()` (spawns the real subprocess — `asyncio.create_subprocess_exec` returns as soon as the OS has launched the process, with NO guarantee the new process has done anything yet),
5. logs `worker_restarted`,
6. **`continue`** — jumps straight back to the top of the `while True:` loop.

At the top of the loop, after the `session_end` check, the very next
statement is an unconditional `status = await sync_to_async(status_repository.get)(provider)`
— with **no sleep at all** between `worker_restarted` and this poll. The
`poll_interval_seconds` sleep only happens in the separate "healthy state"
branch at the bottom of the loop, which this path never reaches before
its next poll.

`[F]` Cross-checked `run_market_data_worker.py::_run_dhan`: it runs PID-verified
reconciliation, `mark_owner`, reads `ScannerConfiguration`, fetches
credentials, evaluates the token lifecycle, resolves instruments — several
real `await sync_to_async(...)` DB/IO round-trips — before its first
`health_tracker.persist()` ever overwrites the `WorkerRuntimeStatus` row.
`[F]` Also checked `worker_status_reconciliation.py`: `_ACTIVE_CLAIM_STATES
= {RUNNING, RECONNECTING, CONNECTING}` deliberately excludes `FAILED` —
by design, a terminal FAILED row is left byte-for-byte untouched by
reconciliation, since 67.12.2-S's own docstring reasons "correcting them
would not change anything an existing gate reads." That reasoning holds
for the reconciliation checkpoint's own purpose, but it means nothing
clears the stale FAILED row on the new process's behalf either — the new
process must overwrite it itself, and that takes real time.

**Proof, not just reasoning**: wrote
`tests/unit/application/services/test_market_data_worker_supervisor.py::test_phantom_restart_race_is_prevented_by_the_post_restart_grace_period`
(originally written and RUN against the pre-fix code with the assertion
`restart_events[0].at == crash_events[1].at` — a real fake-clock timestamp
comparison, not a guess). `[F]` **That version of the test PASSED against
the unmodified loop** — a `crash_detected` fired at the exact same
simulated instant as the preceding `worker_restarted`, with zero elapsed
time and zero intervening sleep, precisely the shape the postmortem's real
1-2ms gaps showed. This is a **CONFIRMED FACT**, independently re-derived
this run, not an inference: the race is real.

## C. The fix

`src/intraday/application/services/market_data_worker_supervisor.py`: added
`await sleep(poll_interval_seconds)` immediately after the `worker_restarted`
log line, before the `continue` that returns to the top of the loop. This
gives the newly-spawned process one full poll interval's worth of real time
to overwrite its own `WorkerRuntimeStatus` row before the supervisor reads
it again.

This is safe and in scope:
- Reuses the loop's own existing `poll_interval_seconds` — no new tunable,
  no change to `--max-restarts`, `--cooldown-seconds`, or any restart-bound
  logic (the explicit prohibition).
- Does not touch `reconcile_worker_runtime_status` or its `_ACTIVE_CLAIM_STATES`
  set (checked whether 67.12.2-S's mechanism could be extended instead —
  it deliberately does not touch terminal states by design, and extending
  it to treat FAILED as "possibly stale" would blur the very distinction
  that checkpoint built; a grace period in the polling loop is the more
  targeted, lower-risk fix, per the directive's own first-listed option).
- Does not weaken crash detection for a genuinely-repeating failure — it
  only delays the NEXT poll by one interval after a restart, exactly the
  same delay a normal "worker running fine" cycle already tolerates.

**Test updated to prove the fix**: the same test now simulates the real
process finishing its startup (writing `RUNNING`) DURING the new
grace-period sleep — exactly the timing a real, slightly-delayed subprocess
startup would have — and asserts exactly ONE `crash_detected` and exactly
ONE `worker_restarted` occur, with `restarts_used == 1` and a clean stop.
`[F]` Ran directly: **passed**.

## D. Final sweep

`[F]` Ran directly, all passed, zero failures/errors:

| Suite | Result |
|---|---|
| `test_market_data_worker_supervisor.py` (incl. both new tests here) | pass |
| `test_worker_status_reconciliation.py` | pass |
| `test_run_market_data_worker_command.py` (incl. new close-code test) | pass |
| `test_supervise_market_data_worker_command.py` | pass |
| `infrastructure/market_data_providers/dhan/` (transport, async worker) | pass |
| `test_live_market_data_boundaries.py` | pass |
| Combined total for the above | **167/167** |
| research checkpoints 64.55/64.56/64.63/64.64/64.71/64.78 | 116/116 |
| **Grand total** | **283/283** |

No regressions. 2 new tests added (one per part), both independently run
and confirmed passing.

## E. Readiness for the next live session

Both real gaps the postmortem named are closed:

1. A future live session's log will now contain a `reconnect attempt #N:
   connection_lost:close_code=<real code>` (or `connect_failed:<repr>`)
   line for **every individual reconnect attempt**, not only the final
   aggregate summary — the one piece of evidence the postmortem said was
   missing and that blocked a real verdict on the underlying disconnect
   cause.
2. The near-instantaneous "phantom" restart pattern is confirmed as a real
   stale-status-read race (not reasoned about, reproduced with a real
   timestamp proof) and is now fixed with a grace period — so a future
   session's restart count and `crash_detected` log will reflect **only
   genuine** disconnects, not detection artifacts, giving an accurate
   crash count to reason from.

No live Dhan connection was attempted at any point in this checkpoint.
