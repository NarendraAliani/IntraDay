# Checkpoint LIVE-1 — Today's Real Supervised Session (Finalized Post-Close)

```
checkpoint: LIVE-1
verdict: PARTIAL
crash_occurred: YES (5 times total — 1 initial + 4 restarts, all reconnect_attempts_exhausted)
restart_exercised_live: YES (4/4, exactly as designed, then correctly stopped permanently on exhaustion)
config_restored: RESTORED_EXACTLY (re-confirmed field-by-field after market close: ALL_CONFIGURED/3m/())
config_lifecycle_gap_still_open: YES (confirmed — the supervisor's own run never reached its --session-end handling at all, since it stopped hours earlier on restart-exhaustion; ScannerConfiguration restoration was performed manually by this checkpoint both times, exactly as 67.12.2-I's design note flagged: the supervisor owns process lifecycle, not config lifecycle)
bars_captured_5m_total: 135 CLOSED AggregatedBarObservation rows (9 per symbol, 15 symbols — see Section D) — 0 new HistoricalBar rows (a real structural finding, unchanged after market close)
provenance_confirmed: NOT_APPLICABLE (no HistoricalBar rows exist to check provenance on)
canonicalization_confirmed: NOT_APPLICABLE (same reason)
commit: (recorded below)
blockers: [live-capture pipeline never writes to HistoricalBar — only the separate REST backfill path does; network instability far exceeded the 4-restart budget chosen for today]
```

**Note on this finalization pass**: the supervisor actually stopped
permanently at **07:40:51 UTC (~13:10 IST)**, hours before market
close, on exhausting `--max-restarts`. Part 4 (archive refresh,
`ScannerConfiguration` restoration) was already performed at that time
— this pass re-verifies everything fresh now that the trading day has
genuinely elapsed (checked 10:17:19 UTC / 15:47 IST, past the ~15:40
IST close), and re-runs the archive refresh once more since a cell's
status legitimately differs before vs. after the session actually
ends (`IN_PROGRESS`/`session_not_closed` earlier today →
`PARTIAL`/`missing_bars` now that the day is over). No new capture
happened between the two checks — nothing was running, confirmed via
process check.

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

`[F]` `market_data_archive --refresh` re-run **after market close**
(10:17 UTC / 15:47 IST): 15 cells refreshed, status now correctly
**`PARTIAL`** for all 15 symbols (`reason=missing_bars:66`, or `:63`
for the four CAS-shortened symbols HDFCBANK/INFY/RELIANCE/TCS) — an
honest final status, not the earlier `IN_PROGRESS`/`session_not_closed`
that applied while the trading day was still technically open.
`closed=9/75` (`9/72` for the CAS-shortened four),
`reconciliation=NOT_RECONCILED` for every cell — none silently
upgraded, both before and after this re-check.

`[F]` **135 `AggregatedBarObservation` rows with `status=CLOSED`**
exist for today at `timeframe=5m` — confirmed again post-close,
unchanged from the mid-session count (nothing captured between the
supervisor's 07:40 UTC stop and this final check, as expected — no
process was running). Exactly **9 closed bars for every one of the 15
symbols**:

```
ADANIPORTS 9  AXISBANK 9  BAJFINANCE 9  HDFCBANK 9  HINDUNILVR 9
ICICIBANK 9   INFY 9      ITC 9         KOTAKBANK 9  LT 9
MARUTI 9      RELIANCE 9  SBIN 9        SUNPHARMA 9  TCS 9
```

`[F]` **`HistoricalBar` count for `timeframe=5m`, today's date: 0** —
re-checked directly after market close, still zero, unchanged. This is
the single most important finding of this checkpoint, and it changes
what "success" means for today: **the live WebSocket capture pipeline
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

`[F]` **Credential state, re-checked post-close**: `effective_credentials()`
still resolves successfully, `exp_utc=2026-09-04 06:38:27`, still
valid (~14.8 hours remaining from this check). Today's crashes,
restarts, and the permanent stop on exhaustion left the credential
itself completely unaffected — it was never the cause of any of
today's failures (`last_error_safe` was `reconnect_attempts_exhausted`
throughout, never `TOKEN_EXPIRED`/`AUTH_FAILED`) and remains usable for
a future attempt without needing another renewal right now.

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

## F. One recommended next step

**Do not attempt a real backtest against today's captured data** — it
would either be pointed at `AggregatedBarObservation` directly (a
different table than what `BacktestingService`/`ResearchDataGateService`
actually read, per 67.12.2-L) or fail outright for lack of any eligible
`HistoricalBar` rows, proving nothing new. The single most valuable
next checkpoint is a **small, dedicated, explicitly-scoped one that
traces exactly where a "promote closed live bars into `HistoricalBar`"
step would need to live** — likely somewhere in
`BarAggregationService`'s own closed-bar handling, or as a separate
periodic promotion job — and proposes (not necessarily implements
immediately) the correct provenance/canonicalization stamping for
that path, reusing the same `REAL_DHAN`/`CANONICALIZED` machinery
`DhanHistoricalBarProvider` already uses, rather than inventing a
second one. Separately, and less urgently: revisit the supervisor's
`--max-restarts`/`--cooldown-seconds` defaults given today's real
evidence (5 crashes, two near-instant re-failures, budget exhausted in
42 minutes) before the next live attempt.
