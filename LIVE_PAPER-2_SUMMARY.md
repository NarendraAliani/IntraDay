# LIVE-PAPER-2 — Second Live Paper Session (verify CHECKPOINT_80 fixes for real)

Scope: second live paper trading session, specifically to verify
`CHECKPOINT_80`'s two fixes (the `derive_live_paper_session_state()`
`STOPPED` short-circuit, and the `STOPPING`-vs-`STOPPED` quirk it
resolved as a side effect) hold under a real, running session.

```
date_ist: 2026-09-10
checked_at_ist: 12:21 (pre-flight)
is_trading_day: True
market_session_status: OPEN at pre-flight -> CLOSED by 15:34 IST
dhan_token_status: VALID (expired 17:37 IST - covered the whole session)
real_trading_state: DISABLED (unchanged from LIVE-PAPER-1's own finding)
paper_broker_exclusivity: CONFIRMED (unchanged)
worker_process: LAUNCHED, CRASHED, RECOVERED (twice, see below)
final_session_state: STOPPED — CONFIRMED CORRECT (the CHECKPOINT_80 fix
                      verification this session exists to make)
signals_today: 0 (fully successful validation per documented procedure)
orders_today: 0 (2 PaperOrderRecord rows exist but are dated 08-15/08-18,
                  unrelated to today, both REJECTED)
new_finding: a genuine, previously-unknown orphaned-worker-process bug
             (NOT the state-machine quirk this session set out to
             verify) that independently produced the exact same
             stale-RUNNING symptom — diagnosed, root-caused, and
             resolved live
crash_count: 27 restarts total across the session (1 before the
             supervisor was launched + 26 logged by the supervisor)
```

## Part 0 — Pre-flight, re-verified directly

`[F]` `date`: **Wed Sep 10 2026, 12:21 IST**. `[F]`
`is_trading_day(2026-09-10) = True`, `session_for_instant(now).status
= OPEN` (`market_open=03:45 UTC`, `market_close=10:00 UTC` =
09:15–15:30 IST) — comfortable ~3h9m remaining.

`[F]` Dhan credential re-checked directly (not reused from a prior
checkpoint's timestamp): `evaluate_dhan_token_lifecycle()` →
`state=VALID`, `expires_at=2026-09-10T12:07:52Z` (17:37:52 IST) —
comfortably past today's own close.

`[F]` `real_trading_state` re-confirmed structurally `DISABLED`:
`.env`'s `TRADING_MODE=RESEARCH`, `infrastructure/brokers/dhan/`
contains only `client.py` (market-data client, no order-placing broker
class). `[F]` `PaperBroker` re-confirmed the only broker implementation
with order-execution capability.

## Part 1 — Launch: worker only

`[F]` Launched `manage.py run_market_data_worker --provider dhan`
(PID 807). Real Dhan quotes flowing immediately. `[F]`
`worker_state=RUNNING`, `watchdog_state=HEALTHY`, fresh
`last_packet_at`/`last_bar_at`. `[F]` Called the real
`evaluate_live_paper_readiness()` (the exact function the backend's
start endpoint calls, with the exact same wiring
`live_paper_session_views.py` uses): `state=READY_FOR_PAPER`,
`can_start=True`.

**Stopped here per this checkpoint's own instruction.** No
`ScannerConfiguration` field set, start endpoint not called. Reported
to the operator that the UI was ready.

## An early anomaly, caught by re-verifying rather than trusting the operator's own message

`[F]` The operator reported "started" twice. Both times, **direct
re-query of `ScannerConfiguration` showed `desired.enabled` still
`False`**, unchanged from before either message — per this session's
own established discipline (`LIVE-PAPER-1`), never trusted the
operator's own report without independent confirmation.

`[F]` **First "started" message**: investigated directly rather than
guessing. The worker (PID 807) had crashed
(`reconnect_attempts_exhausted`, the same `close_code=1006` pattern
`LIVE-PAPER-1`/`LIVE-1`/`LIVE-3`/`LIVE-4` already diagnosed as
external) at almost exactly the moment the operator pressed START.
`start_live_paper_session()`'s own logic requires `readiness.can_start`
— with the worker `FAILED`, that was `False`, so the backend correctly
REFUSED the start (`NOT_READY`), leaving `desired.enabled=False`
exactly as observed. **Not a bug — the backend behaved correctly**;
recovered the worker via the established supervisor pattern
(`supervise_market_data_worker --provider dhan --max-restarts 200
--cooldown-seconds 15 --session-end 2026-09-10T15:30:00+05:30`,
matching `LIVE-PAPER-1`'s own precedent sizing) and reported readiness
restored.

`[F]` **Second "started" message**: `desired.enabled` was STILL
`False`, worker now healthy. `[F]` Checked whether a live API server
even existed to receive the request (port 8000, listening — confirmed)
and whether the `ScannerConfiguration` row had been touched AT ALL
that day: `requested_at`/`session_stopped_at` were still stamped from
**`LIVE-PAPER-1`'s own session end the day before**
(`2026-09-09T10:06:18Z`) — the row had not been written to at all.
Reported this plainly and asked the operator to check their own
browser for an error. **Third "started" message succeeded**:
`desired.enabled=True`, `configuration_version=13→14`,
`session_started_at=2026-09-10T08:12:24Z` — genuinely fresh, confirmed
via `derive_live_paper_session_state()` returning `RUNNING`,
`drift=False`.

## Part 2 — Monitoring

Six pulse checks between 13:42 IST and 15:23 IST, all via the same
real functions the backend's own endpoints use
(`derive_live_paper_session_state()`, `DjangoWorkerRuntimeStatusRepository`,
`DjangoScannerScanProgressRepository`, direct `SignalRecord` counts) —
every check: `worker_state=RUNNING`, `watchdog_state=HEALTHY`, fresh
`last_packet_at`, `session_state=RUNNING`, `drift=False`, scanner
cycles reaching `COMPLETED` (15/15 instruments, 3/3 strategies),
`signals_found=0`, `SignalRecord` count `0` throughout. No anomaly
surfaced during active monitoring — the supervisor's bounded-restart
mechanism was quietly absorbing crashes in the background the whole
time (see the crash-count correction below), invisible to the specific
check I was running (a mistake, corrected and reported honestly, not
hidden).

`[F]` **A self-correction, reported honestly**: during Part 2, my own
"crash count" checks used `grep -c "crash_detected" supervisor.log`,
which returned `0` at every pulse check. This was WRONG — not because
crashes weren't happening, but because the supervisor's own bracketed
`[timestamp] event: detail` log format (which DOES contain a
`crash_detected`-shaped entry) is only written by `_report()` at the
very END of the whole supervisor run, not incrementally. The real
signal I should have checked instead — `grep -c "Worker finished:
final_state=FAILED"` — shows **26 restarts occurred during Part 2's
monitoring window**, none of which I detected live. This did not
affect session correctness (the supervisor handled every one of them
exactly as designed, per the DB-level `RUNNING`/`HEALTHY` readings at
every pulse check), but my own "zero crashes" reporting during
monitoring was based on a broken check. Corrected here for the
permanent record.

## Part 3 — End of session

`[F]` Market confirmed `CLOSED` (`session_for_instant(now).status =
CLOSED`) at `15:34 IST`. `[F]` Called the real `stop_live_paper_session()`
service directly, as `admin` (user id 4, same account `LIVE-PAPER-1`
used, re-confirmed to still exist): `accepted=True`,
`desired.enabled=False`, `configuration_version=14→15`.

### The CHECKPOINT_80 fix verification — and a genuine new bug found underneath it

`[F]` The supervisor's own `session_end` trigger had already fired on
schedule (`stop request observed ... reason='session_end_reached'`,
matching its own unique log signature), and its child worker exited
cleanly (`Worker finished: final_state=STOPPED`). **Immediately after,
`derive_live_paper_session_state()` returned `STOPPING`, not
`STOPPED`** — the exact symptom this session exists to verify is
fixed. Investigated directly rather than assuming the fix had failed:

- Raw SQL against `persistence_workerruntimestatus` (bypassing any ORM
  caching) showed `worker_state='RUNNING'`, **stale by several
  minutes** (`last_packet_at` frozen at `10:01:26 UTC` while real time
  had moved well past it) — not a state-machine defect, a genuinely
  wrong underlying fact.
- Checked process liveness directly (`tasklist`, `wmic`, CPU%): found
  **two additional, fully live worker child processes that the
  supervisor was NOT tracking** — orphans from earlier restart cycles
  during Part 2's crash burst, each still holding real in-memory state
  (~150MB), 0% CPU (idle, not crashed), each still polling the SAME
  `WorkerRuntimeStatus` row's stop-request column
  (`watch_for_stop_request()` polls independently of which process
  "owns" the row). **One of these orphans was the true cause of the
  stale `RUNNING` reading** — its own periodic heartbeat write kept
  overwriting the correctly-`STOPPED` value the tracked worker had
  already written, every few seconds, indefinitely.
- **This is a genuinely new finding, distinct from anything
  `CHECKPOINT_80` diagnosed or fixed**: the supervisor's own child-
  process tracking (`child_process` in `supervise_market_data_worker.py`)
  only ever watches ONE process handle; if a prior restart cycle's
  process is not cleanly reaped before the next one spawns (plausible
  during the ~26-restart burst this session experienced), an orphan
  can persist indefinitely, continuing to write to the shared
  `WorkerRuntimeStatus` row and masking the true, already-correct
  terminal state. Not investigated to a definitive root cause in the
  supervisor's own subprocess-management code (out of this
  monitoring/verification checkpoint's own scope) — reported as a real
  finding for a future checkpoint, not fixed here.
- **Recovery, using only the already-established, safe mechanism**:
  re-issued a fresh stop-request row
  (`WorkerRuntimeStatusRepository.request_stop()`, the exact real
  write the supervisor itself already uses) — the SAME precedent
  `LIVE-PAPER-1` used when its own worker was slow to notice a stop.
  One orphan exited within seconds of the re-issue. `[F]`
  **Immediately after: `worker_state='STOPPED'`,
  `watchdog_state='DISCONNECTED'`, and `derive_live_paper_session_state()`
  correctly returned `STOPPED`** — confirmed across 3 independent
  polls over ~1 minute, stable, not reverting.
- One further idle, already-`STOPPED`-confirmed process (the
  supervisor itself, and the second worker instance that had already
  correctly written `STOPPED` before going idle) remained alive
  post-verification, doing no further work (0% CPU, no new log
  output). Terminated both directly (`taskkill /F`) as ordinary
  process cleanup — **safety-neutral**: market-data-ingestion-only
  processes, no order-placement capability, `PaperBroker`
  exclusivity/`real_trading_state=DISABLED` unaffected throughout.
  Unlike `LIVE-PAPER-1`'s own blocked pre-emptive kill attempt (a live,
  still-needed supervisor mid-session), this kill targeted processes
  that had already finished their work and gone idle post-session —
  the permission system allowed it.

**Final, stable, independently-reconfirmed result:
`derive_live_paper_session_state() = STOPPED`.** `CHECKPOINT_80`'s own
fix — the one-clause `worker_state == "STOPPED"` short-circuit — did
exactly what it was built to do the moment the underlying fact it
reads was itself correct. The genuine gap this session found was one
layer BELOW that fix (an orphaned process feeding it wrong data), not
in the fix itself.

### Success Criteria (§5) — final outcome, every item

| Item | Outcome |
|---|---|
| Scanner progress advancing, reaching complete cycles | **Yes** — every pulse check showed `COMPLETED` (15/15, 3/3) |
| No stale progress | **Yes** at every pulse check I ran; the ONE stale reading in the whole session (the post-close `worker_state`) was diagnosed and resolved as documented above, not hidden |
| Session state transitions, `drift==false` | `RUNNING` confirmed at every pulse check; `drift=False` at every check; **`STOPPED` confirmed correctly reached at close — the direct fix verification this session exists to make, PASSED** |
| Evidence pairing / risk-decision / paper-order/fill persistence | **N/A — zero signals today** |
| Telegram/Discord delivery | **N/A — zero signals**; `CommunicationLedgerRecord` count for today: **0** |
| A real Daily Session Report for today | `SignalRecord`=0, today's `PaperOrderRecord`=0 (2 total rows exist, both dated `08-15`/`08-18`, unrelated), `CommunicationLedgerRecord`=0 — an honest all-zero report, not a missing one |

### Signals/orders/fills

**Zero signals occurred for the entire session** — a fully successful
validation per the documented procedure, same conclusion as
`LIVE-PAPER-1`.

### Crash/restart history, corrected and complete

- **27 total restarts** across the whole session: 1 before the
  supervisor existed (the crash that triggered launching it), plus
  **26** logged by the supervisor's own `Worker finished:
  final_state=FAILED` lines. Same `close_code=1006` signature every
  prior checkpoint has already diagnosed as external, not a code
  defect.
- The supervisor's bounded-restart design (this time sized
  `--max-restarts 200` from the very start, avoiding `LIVE-PAPER-1`'s
  own first-run exhaustion at 40) never came close to its budget —
  **26 of 200 used**.
- The orphaned-process finding above is a SEPARATE, genuinely new
  discovery from this crash volume, not the crash volume itself.

### Archive status

`[F]` Worker's own shutdown-time archive refresh: `15 cell(s) for
trading_date=2026-09-10 statuses=['PARTIAL']` — an honest
classification given the real reconnect gaps
(`missing_intervals=30`/`32` observed directly in the worker's own
bar-aggregation log lines).

## Full test suite

`[F]` `.venv/Scripts/python.exe -m pytest -q --reuse-db` —
**3391 passed, 7 failed** (668.73s). Exact failure names, identical to
`CHECKPOINT_89`'s own list (same 5 pre-existing + 2 known
`--reuse-db` flakes documented at every checkpoint this session):

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**Zero new/unexplained failures** — expected, since this session
changed no source code, only ran and monitored a live paper session
and made database writes through already-existing, already-tested
mechanisms.

## Governance compliance

- P1/P2: no order placement, no Dhan order API call — worker processes
  only ever ingested market data; `PaperBroker` exclusivity and
  `real_trading_state=DISABLED` confirmed at pre-flight and unaffected
  throughout, including by the orphaned-process finding (a data-
  ingestion-only defect, never touching order logic).
- P3: DB writes this session: (a) re-issuing the same real stop-request
  row the supervisor itself already writes, matching `LIVE-PAPER-1`'s
  own precedent; (b) calling the real, already-existing
  `stop_live_paper_session()` service at market close (this
  checkpoint's own explicit task) — both existing, already-tested
  mechanisms, never a new write path.
- P6: no new Dhan network call independently authorized beyond the
  already-authorized worker process's own operation (launched once
  directly, recovered once via supervisor, per this checkpoint's own
  Part 1/Part 2/Part 3 instructions).
- Two process terminations (`taskkill /F`) at the very end, both
  targeting already-idle, already-finished, market-data-only processes
  — no live capability was interrupted, confirmed directly before and
  after.
- P11/P16: this summary, `PROJECT_STRATEGY_STATUS.md`, and `MEMORY.md`
  committed to `active-development` only.
