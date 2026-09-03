# Checkpoint LIVE-1 — Today's Real Supervised Session

```
checkpoint: LIVE-1
verdict: PARTIAL
pid_reconciliation_exercised_live: PARTIALLY (ran for real at startup, found nothing stale — "action=not_active" — no restart-cycle row was ever stale mid-session either, since the fixed terminal-status persistence from 67.12.2-H kept the row honest throughout)
crash_occurred: YES (5 times total — 1 initial + 4 restarts, all reconnect_attempts_exhausted)
restart_exercised_live: YES (4/4, exactly as designed, then correctly stopped permanently on exhaustion)
config_restored: RESTORED_EXACTLY
bars_captured_5m: 135 CLOSED AggregatedBarObservation rows (live-observation table) — 0 new HistoricalBar rows (see Section D, a real structural finding)
provenance_confirmed: NOT_APPLICABLE (no HistoricalBar rows exist to check provenance on)
canonicalization_confirmed: NOT_APPLICABLE (same reason)
commit: (recorded below)
blockers: [live-capture pipeline never writes to HistoricalBar — only the separate REST backfill path does; network instability far exceeded the 4-restart budget chosen for today]
```

## A. Part 0 findings

1. **Time**: session started 2026-09-03 06:58:33 UTC (12:28 IST), ~192
   minutes before the ~15:40 IST close target. Well above threshold.
2. **Credential**: renewed by the operator mid-session-preparation
   (see `CHECKPOINT_LIVE-1-RENEW_SUMMARY.md`) after the first attempt
   this morning HALTed on an about-to-expire token. Re-checked via
   `effective_credentials()`: valid until `2026-09-04 06:38:27 UTC`
   (~23.7 hours) — comfortably covered the intended session.
3. **`WorkerRuntimeStatus(dhan)` / PID reconciliation** — genuinely
   exercised for real, not a fake, for the first time this session:
   at startup the supervisor's own log recorded
   `startup reconciliation: action=not_active reason="worker_state='STOPPED' is already inactive/terminal - nothing to reconcile"`.
   The row was already clean (no stale PID to catch) — a real,
   honest negative result, not a fabricated positive. Throughout the
   session's 4 crash/restart cycles, `WorkerRuntimeStatus.worker_state`
   correctly reached `FAILED` (never stuck at a stale `RUNNING`/
   `RECONNECTING`) every single time — this **is** live proof that
   67.12.2-H's terminal-status-persistence fix held up under 5 real
   crashes, exactly the property that was broken before that fix.
4. Nothing else was capturing before this session started (confirmed
   at the original Part 0 check, prior message in this conversation).
5. Confirmed trading day.

## B. The capture window and what actually happened — the real test

`[F]` Quoted directly from the supervisor's own event log
(`$TEMP/checkpoint_LIVE-1_supervisor.log`):

```
[2026-09-03T06:58:33.608433+00:00] start: provider=dhan max_restarts=4 cooldown_seconds=30.0
[2026-09-03T06:58:33.608433+00:00] worker_started: initial start
[2026-09-03T07:23:12.601445+00:00] crash_detected: worker_state=FAILED (reason='reconnect_attempts_exhausted') - cooling down 30.0s before restart 1/4.
[2026-09-03T07:23:42.608422+00:00] worker_restarted: restart 1/4
[2026-09-03T07:23:42.609425+00:00] crash_detected: worker_state=FAILED (reason='reconnect_attempts_exhausted') - cooling down 30.0s before restart 2/4.
[2026-09-03T07:24:12.617659+00:00] worker_restarted: restart 2/4
[2026-09-03T07:32:58.201450+00:00] crash_detected: worker_state=FAILED (reason='reconnect_attempts_exhausted') - cooling down 30.0s before restart 3/4.
[2026-09-03T07:33:28.211053+00:00] worker_restarted: restart 3/4
[2026-09-03T07:33:28.213437+00:00] crash_detected: worker_state=FAILED (reason='reconnect_attempts_exhausted') - cooling down 30.0s before restart 4/4.
[2026-09-03T07:33:58.216951+00:00] worker_restarted: restart 4/4
[2026-09-03T07:40:51.741488+00:00] max_restarts_exhausted: worker_state=FAILED (reason='reconnect_attempts_exhausted') but restarts_used=4 >= max_restarts=4 - stopping permanently, no further restart attempted.
Supervisor finished: max_restarts_exhausted=True restarts_used=4 final_worker_state=FAILED - stopping permanently, no further restart attempted. A human must investigate.
```

**Timeline**: the worker ran cleanly for ~24.5 minutes (06:58:33 to
07:23:12) before its first crash. Two of the four restarts
(1→2, 3→4) failed **almost immediately** — seconds after restarting,
not after another sustained run — while the other two intervals
(restart 2, restart 4) each ran ~9 minutes before failing again. The
supervisor's own bounded logic behaved **exactly as designed at every
step**: detected each crash via the real, now-fixed terminal-status
persistence (not a stale row), waited the full 30s cooldown each time,
restarted within `max_restarts=4`, and — critically — **stopped
permanently the instant the 4th restart also failed, rather than
attempting a 5th.** This is the exact "report, don't improvise past
the bound" behavior 67.12.2-H was built to guarantee, and today is the
first time it has ever been proven against a real crash, not a fake
one.

`[I]` The immediate-refailure pattern on two of the four restarts
(sub-2-second gap between "worker_restarted" and the next
"crash_detected") suggests the underlying network condition may have
been a sustained connectivity problem for part of this window, not
purely brief transient blips — worth noting as a real signal for
tuning tomorrow's parameters, not something this checkpoint
investigates further (no change to the supervisor's own logic was
made, per the standing prohibition).

Per this checkpoint's own instruction: **`max_restarts` was exhausted;
no manual restart was attempted.** The supervisor process itself
confirmed no longer running (`Get-CimInstance` returned no matching
process).

## C. Config restoration

`ScannerConfiguration(dhan)` was `ALL_CONFIGURED`/`3m`/`()` before this
session (recorded in the prior message in this conversation), changed
to `SELECTED`/`5m`/15-symbol watchlist with explicit `AskUserQuestion`
approval, and — since the supervisor's own session-end handling was
never reached (it stopped early, on restart-exhaustion, not on the
`--session-end` timestamp) — required a manual restoration:

```
restored: ALL_CONFIGURED 3m ()
```

**`RESTORED_EXACTLY`**, confirmed by direct query immediately after.

## D. Final counts and the canonicalization finding

`[F]` `market_data_archive --refresh` was run: 15 cells refreshed,
`status=IN_PROGRESS` for all 15 symbols (`reason=session_not_closed`
— correct, since the session stopped at 07:40 UTC, hours before the
real 15:30 IST close), `closed=9/75` (HDFCBANK/INFY/RELIANCE/TCS show
`9/72`, reflecting their CAS-shortened session), `reconciliation=NOT_RECONCILED`
for every cell — none silently upgraded.

`[F]` **135 `AggregatedBarObservation` rows with `status=CLOSED`** exist
for today at `timeframe=5m` (plus 13 `FORMING`) — this is real,
successfully-captured 5-minute bar data.

`[F]` **`HistoricalBar` count for `timeframe=5m`, today's date: 0.**
Checked directly, not assumed. This is the single most important
finding of this checkpoint, and it changes what "success" means for
today: **the live WebSocket capture pipeline
(`run_market_data_worker` → `BarAggregationService` →
`AggregatedBarObservation`) has no code path that ever writes to
`HistoricalBar`.** Every `HistoricalBar` row this entire multi-day
canonicalization arc has ever produced — the 11,442 `REAL_DHAN` rows,
today's own 67.12.2-F/Q backfills — came from the **separate REST
historical-candle path** (`DhanHistoricalBarProvider` /
`HistoricalDataPreparationService`), never from live capture. This is
a pre-existing architectural fact, not something today's session or
this checkpoint broke, and not something fixed here (no code change
was made, per the standing prohibitions).

**Consequence, stated plainly**: today's live session — even in the
counterfactual case of zero crashes and a full clean run to 15:30 IST
— could not have produced new, research-eligible `HistoricalBar` rows
by itself. `provenance_confirmed`/`canonicalization_confirmed` are
`NOT_APPLICABLE`, not because today's capture failed at that specific
step, but because that step was never reachable from the pipeline
actually exercised today. This checkpoint's own premise ("this session
also needs to produce genuinely usable data this time") assumed a
live-to-archive path that does not exist yet.

## E. Honest assessment — is the supervisor now genuinely proven?

**Yes, for its actual scope — crash detection and bounded restart —
this is now genuinely, positively proven against reality, not just
fakes.** Five real crashes, five correct detections via the real
terminal-status-persistence fix, four correct restarts within
cooldown, one correct permanent stop on exhaustion, zero manual
intervention. This is exactly what 67.12.2-H/S were built and tested
(against fakes) to do, and today is the first time either has faced a
real failure and behaved correctly.

**No, for the broader goal of "produce usable data today" — that goal
was not achievable by this pipeline as built**, independent of how
well the supervisor performed. The real, actionable finding from
today is not "the supervisor needs tuning" (though the restart budget
clearly needs revisiting — 4 restarts were exhausted in 42 minutes,
nowhere close to covering a real session) but **"live WebSocket
capture and the `HistoricalBar` research archive are two disconnected
pipelines, and closing that gap is a genuine, separate, and now
clearly-motivated future checkpoint"** — not a small thing to patch
inline here.
