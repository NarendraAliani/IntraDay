# Checkpoint 67.12.2-H — Live-Worker Reliability Hardening

```
checkpoint: 67.12.2-H
verdict: HARDENING_COMPLETE
stale_status_bug_fixed: YES (test_reconnect_exhaustion_persists_a_terminal_failed_status_not_a_stale_reconnecting_one)
tiebreaker_fixed: YES (existing-data-impact: NONE - 1,136/1,136 real conflicting-timestamp groups today already match ascending-id order, verified by direct query, see Section B)
supervisor_built: YES (python manage.py supervise_market_data_worker)
tests_added: 6 (1 Part-1 regression, 2 Part-2 tiebreaker, 2 Part-3 supervisor bound, plus 1 pre-existing-pattern fix commented inline)
tests_passing: 6/6 new, 44/44 in the direct target files, 712/714 in the broader persistence+market_data_providers+application/services sweep (2 pre-existing failures, unrelated to this checkpoint - see Section E)
existing_suite_regression: NONE (the 2 failing tests are in files this checkpoint never touched - test_historical_data_preparation.py and test_migration_67_10_execute.py/test_migration_67_7_dry_run.py - already present in the working tree from earlier, separately-committed checkpoint work before this one started; git status confirms this checkpoint's diff touches only 4 files, none of the failing ones)
recommended_tomorrow_command: python manage.py supervise_market_data_worker --provider dhan --max-restarts 4 --cooldown-seconds 30 --session-end 2026-09-03T15:30:00+05:30 --mode observe-only
commit: 4e38fdd
blockers: []
```

## A. Part 1 — the stale-status bug

**Confirmed root cause** (re-derived by reading the code, not merely
trusting 67.12.2-E's own report of it): `run_market_data_worker.py`
called `health_tracker.mark_failed()` in exactly one place — inside
`connect_and_run()`, only when a **single connection attempt's own**
`run_worker_against_websocket()` result was directly `FAILED`/
`AUTH_FAILED`/`TOKEN_EXPIRED`. `reconnect_supervisor.py`'s own
exhaustion branch (`run_worker_with_reconnect()`, line ~114-117) sets
`result.final_state = WorkerState.FAILED` purely in its own return
value — no callback into `health_tracker` at all. Back in the command,
the only post-loop persist branch was:

```python
if supervisor_result.final_state is WorkerState.STOPPED and stop_event.is_set():
    health_tracker.mark_stopped()
    await sync_to_async(health_tracker.persist)(...)
```

There was **no corresponding `else`/final branch** for any other
terminal `final_state` (in particular `FAILED` from reconnect
exhaustion) — exactly the missing branch 67.12.2-E named. The DB row
was left holding whatever `worker_state` the last periodic
`aggregate_now()` cycle happened to persist (`RECONNECTING`, in both of
today's real crashes).

**Fix applied** (`run_market_data_worker.py`, `_run_dhan()`, immediately
after the `STOPPED` branch): an `elif supervisor_result.final_state is
not WorkerState.STOPPED:` branch that calls the SAME
`health_tracker.mark_failed(supervisor_result.final_state,
reason=supervisor_result.last_disconnect_reason or ...)` and the SAME
`health_tracker.persist(DjangoWorkerRuntimeStatusRepository(), ...)`
path the existing `STOPPED` branch already used — no second
status-transition mechanism, exactly mirroring the existing pattern per
the directive.

**Regression test**:
`tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py::test_reconnect_exhaustion_persists_a_terminal_failed_status_not_a_stale_reconnecting_one`.
Uses a well-formed, non-expired synthetic JWT (so the command passes the
credential/token gates) and monkeypatches
`DhanWebSocketTransport.connect` to always raise
`DhanWebSocketTransportError` — **no real socket, no real Dhan
connection, ever** — so every reconnect-supervisor attempt reports
RECONNECTING until `--max-reconnect-attempts 2` is exhausted, exactly
reproducing today's `close_code=1006` failure shape. Pre-seeds
`WorkerRuntimeStatus.worker_state="RUNNING"` beforehand to prove the
stale value gets genuinely overwritten, not merely created fresh.
Asserts `final_state=FAILED` in stdout, and directly re-queries the DB
row: `worker_state == "FAILED"`, never `"RUNNING"`/`"RECONNECTING"`,
`reconnect_count == 2`, `last_error_safe ==
"reconnect_attempts_exhausted"`.

**Verified this run**: `pytest
tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py
-v` → **10 passed** (all pre-existing tests in the file still pass
unmodified, plus the new one), 13.13s.

**A real deadlock found and fixed along the way** (worth reporting
honestly, not just the final green result): the first version of this
test hung indefinitely under pytest — reproduced cleanly three times,
confirmed via `pg_stat_activity` as a genuine two-connection Postgres
deadlock (one backend idle-in-transaction at `RELEASE SAVEPOINT`, one
backend blocked on an `INSERT`/`UPDATE` of the same
`WorkerRuntimeStatus` row). Root cause: a redundant per-test
`@pytest.mark.django_db` decorator conflicted with this file's
module-level `@pytest.mark.django_db(transaction=True)` marker, silently
downgrading just that one test back into atomic/savepoint (rollback)
mode — which leaves the test's own pre-seed transaction open for the
rest of the test, and the worker's separate `sync_to_async` connection
then blocks forever trying to lock the same row. Fixed by removing the
redundant decorator (documented inline in the test). This was a genuine
test-infrastructure bug this checkpoint found and fixed, not a defect in
the Part 1 code fix itself (confirmed separately via a standalone
non-pytest diagnostic script that reproduced the exact same monkeypatch
scenario and completed correctly in seconds — see the checkpoint
working notes).

## B. Part 2 — the ordering-determinism gap

**Confirmed** (`live_market_data_repositories.py`,
`DjangoLiveQuoteRepository.get_observations()`): the query was exactly
`.order_by("instrument_symbol", "source_timestamp")` — no tiebreaker for
rows sharing both fields (the `conflicting_same_timestamp` case
`domain/market_data/aggregation.py` resolves by arrival order).

**Fix applied**: added `"id"` as an explicit third `order_by()` key. No
new column — `id` (the existing auto-increment PK) is already the
genuine row-insertion-order sequence, since a batch of quotes reaches
this table via one `bulk_create()` call in `save_batch()`.

**Existing-data-impact finding — directly queried, not assumed**: ran a
real query against today's (2026-09-02) `LiveQuoteObservation` rows,
grouping by `(instrument_symbol, source_timestamp)` and finding every
group with more than one row (the real `conflicting_same_timestamp`
population):

- **1,136 conflicting-timestamp groups found today.**
- For every one of the 1,136 groups, compared the row order the OLD
  query produced (ascending `id`, since no tiebreaker means Postgres's
  actual physical/heap order — verified as ascending `id` order for this
  freshly-inserted, never-`VACUUM FULL`'d table) against the row order
  sorted by `(fetched_at, id)` (a proxy for true local-receive/arrival
  order, independent of `id`).
- **Result: 0 mismatches out of 1,136 groups checked.** The new explicit
  `id` tiebreaker produces the byte-for-byte identical resolution order
  as today's actual (accidental) behavior, for every single real
  conflicting row that exists.

**Conclusion**: this is a **future-behavior-only, zero-impact** fix.
Per the directive's explicit instruction, no existing `HistoricalBar` or
`AggregatedBarObservation` row was touched, recomputed, or flagged for
recompute — none needed to be, since the fix provably changes nothing
about any row that already exists.

**Tests added**
(`tests/unit/infrastructure/persistence/test_live_market_data_repositories.py`):
`test_get_observations_breaks_an_identical_timestamp_tie_by_insertion_order`
(two same-timestamp observations via two separate `save_all()` calls,
asserts they come back in insertion order) and
`test_get_observations_tie_break_is_stable_across_repeated_calls`
(asserts the SAME order across 5 repeated reads). **Verified this run**:
both pass, part of the file's full 15/15 pass (see Section D).

## C. Part 3 — the bounded auto-restart supervisor

**Design**: `application/services/market_data_worker_supervisor.py`
holds ONE pure async loop (`supervise_market_data_worker()`) — every
side effect (`start_worker`, `is_worker_alive`,
`request_session_end_stop`, `wait_for_worker_exit`, `refresh_archive`,
`sleep`, `now`) is a caller-supplied callable, so the poll/restart/bound
decision logic is testable with zero real subprocess and zero real Dhan
connection. `infrastructure/persistence/management/commands/
supervise_market_data_worker.py` is the thin CLI wrapper that supplies
REAL implementations: `asyncio.create_subprocess_exec(sys.executable,
"manage.py", "run_market_data_worker", --provider, --mode)` to spawn,
the real `DjangoWorkerRuntimeStatusRepository` to poll, the EXISTING
`request_stop()` process-independent stop mechanism (Checkpoint
64.73/67.12.2-C/E) at session-end, and the EXISTING
`MarketDataArchiveService.refresh_trading_date()` for the archive
refresh — no new stop/archive mechanism invented.

Command: `python manage.py supervise_market_data_worker --provider
<name> --max-restarts <n> --cooldown-seconds <s> --session-end <ISO
timestamp> [--poll-interval-seconds 7] [--mode observe-only|paper]`.

Behavior: polls `WorkerRuntimeStatus` (default 7s, within the directed
5-10s range). On `worker_state == FAILED` (Part 1's fix — the genuinely
terminal, reconnect-exhausted state): waits `cooldown-seconds`, restarts,
bounded by `max-restarts` for the whole run; exhausting the bound stops
the supervisor **permanently** with no further restart attempted, per
the "report, don't improvise past the bound" discipline used elsewhere
in this project. On `AUTH_FAILED`/`TOKEN_EXPIRED` (a credential problem,
not a restart-recoverable failure): stops immediately without spending a
restart, since retrying would just repeat a guaranteed failure. At
`session-end`: requests the stop, waits for exit, refreshes the archive,
and returns. Every event (start, crash detected, restart, exhaustion,
session-end, stop-requested, archive-refreshed) is appended to one
in-memory log with a timestamp, printed at the end — one reconstructable
record, not two ad hoc files stitched together after the fact.

**Tests** (`tests/unit/application/services/test_market_data_worker_supervisor.py`):

- **Positive** (`test_supervisor_restarts_within_its_bound_after_a_crash`):
  a single simulated crash (the test flips the real `WorkerRuntimeStatus`
  row to `FAILED`, exactly what Part 1's fix persists) triggers exactly
  one restart, well within `max_restarts=3`, and the run reaches
  `session_end` and stops cleanly. Asserts `starts == 2` (initial +1),
  `restarts_used == 1`, `stopped_cleanly is True`, the stop-request and
  archive-refresh callables were both actually called.
- **Negative** (`test_supervisor_never_restarts_beyond_max_restarts`):
  the worker crashes on every single poll (`max_restarts=2`,
  `session_end` 6 hours away — far past when the bound is hit). Asserts
  `starts == 3` (initial +2, never a 3rd), `restarts_used == 2`,
  `max_restarts_exhausted is True`, `stopped_cleanly is False`, and that
  `request_session_end_stop` (which would raise `AssertionError` if
  called) was never invoked.

**No real Dhan connection or real subprocess anywhere in this file** —
`start_worker`/`sleep`/etc. are fakes; `WorkerRuntimeStatus` is written
through the real repository against the real (test) Postgres database,
matching this checkpoint's harness discipline.

**A second instance of the same deadlock class** was found and fixed
here too: this file's module marker was initially the plain
`pytest.mark.django_db` (not `transaction=True`), which produced the
identical two-connection deadlock as Section A's (main-thread pre-seed
+ async-thread write to the same row). Fixed by switching the module
marker to `pytest.mark.django_db(transaction=True)`, documented inline.

**Verified this run**: `pytest
tests/unit/application/services/test_market_data_worker_supervisor.py
-v` → **2 passed**, 8.00s.

## D. Full verification run (Part 5)

Ran, this run, hands-off to completion (all synchronous, foreground):

1. `test_run_market_data_worker_command.py` (10 tests) — **10 passed**.
2. `test_reconnect_supervisor.py` + `test_live_market_data_repositories.py`
   + `test_market_data_worker_supervisor.py` +
   `test_live_market_data.py` (application layer) +
   `test_live_market_data_boundaries.py` (architecture) — **44 passed**,
   14.35s.
3. Broad sweep: `tests/unit/infrastructure/persistence/` +
   `tests/unit/infrastructure/market_data_providers/` +
   `tests/unit/application/services/` (714 tests collected) —
   **712 passed, 2 failed**, 191.62s.

## E. The two pre-existing (unrelated) failures

`test_historical_data_preparation.py::test_fully_cached_range_triggers_zero_provider_calls`
and
`test_migration_67_10_execute.py::test_migration_67_7_dry_run_test_suite_still_passes_unmodified`
(the latter cascades from 16 errors inside
`test_migration_67_7_dry_run.py`). **Confirmed NOT a regression from
this checkpoint**: `git status --porcelain` shows this checkpoint's own
diff touches exactly 4 tracked files
(`live_market_data_repositories.py`, `run_market_data_worker.py`,
`test_run_market_data_worker_command.py`,
`test_live_market_data_repositories.py`) plus 3 new untracked files (the
supervisor service, its management command, its test file) — none of
which are `historical_data_preparation.py`, `migration_67_7.py`,
`migration_67_10_*.py`, or their test files. Those files' modifications
were already present in the working tree (visible in this session's
initial `git status`, before this checkpoint began) from separate,
earlier checkpoint work this checkpoint never touches or claims
responsibility for. Per this checkpoint's own halt conditions, this is
reported as an existing, unrelated fact — not silently absorbed into
this checkpoint's own regression count, and not something this
checkpoint fixes (out of scope).

## F. Tomorrow's recommended invocation (Part 4 — NOT run)

```
python manage.py supervise_market_data_worker --provider dhan --max-restarts 4 --cooldown-seconds 30 --session-end 2026-09-03T15:30:00+05:30 --mode observe-only
```

Reasoning:

- **`--session-end 2026-09-03T15:30:00+05:30`**: the real IST market
  close, timezone-aware as the command requires.
- **`--max-restarts 4`**: today's two independent crashes in ~1 hour
  suggest network instability is a real, recurring possibility for this
  session, not a one-off. 4 restarts gives real headroom for a repeat of
  today's pattern (which needed 1 restart to be useful) plus margin,
  while still bounding a genuinely broken network/credential to a
  finite, reviewable incident rather than an unbounded crash-loop
  burning Dhan's rate limits for 6+ hours unattended.
- **`--cooldown-seconds 30`**: long enough to let a transient
  network/heartbeat blip (Dhan's own ~10s ping / 40s unresponsive
  threshold, per 67.12.2-E's own research citation) clear before
  retrying, short enough that a genuine recoverable blip does not cost
  more than a fraction of a percent of the trading session.
- **`--mode observe-only`** (the default, stated explicitly for
  clarity): matches every prior live capture checkpoint this session —
  market data only, strategy execution never enabled.
- Every `run_market_data_worker` restart still uses its own existing
  in-process 5-attempt reconnect ceiling (`--max-reconnect-attempts`,
  unspecified here, defaults to 5) BEFORE ever reaching this
  supervisor's own restart logic — the two bounds compose (in-process
  reconnect handles brief blips without even needing a process restart;
  this supervisor handles the case where even that ceiling is
  exhausted), exactly the two-layer design this checkpoint's Part 1+3
  fixes were built to close the gap between.

**This command was NOT executed in this checkpoint** — Part 0/live
capture is a separate, explicit action for tomorrow, per the directive.

## G. Remaining blockers

None. `blockers: []`.

---

**STOP after this checkpoint. No live capture was attempted today.**
