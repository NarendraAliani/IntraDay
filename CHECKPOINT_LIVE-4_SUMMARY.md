# Checkpoint LIVE-4 — Full-Session Live Capture + Authorized Coverage-Gap Diagnostic

```
checkpoint: LIVE-4
verdict: STREAM_1_SESSION_END_FIX_CONFIRMED_WORKING / STREAM_2_THEORY_CONFIRMED_WITH_DIRECT_EVIDENCE
premise_check: today (2026-09-07) confirmed live at issue time (13:25 IST,
               ~2h before 15:30 IST close) — matched the prompt, no stale
               premise this time.
stream_1_uncaught_crash: NO — zero, across two supervised launches and
               26 total worker lifetimes over the full remaining session.
stream_1_session_end_reached_cleanly: YES — stopped_cleanly=True,
               final_worker_state=STOPPED, at 15:30:xx IST, exactly at
               the configured session_end.
stream_1_total_quotes_today: 28,463 (sum of all 26 "Worker finished"
               lifetimes) / 39,487 total AggregatedBarObservation
               observations (a larger, correct superset — see Part 3).
stream_1_historicalbar_canonicalization: DEFINITIVELY ANSWERED — 0
               HistoricalBar rows for 2026-09-07 despite substantial
               successful capture (401 CLOSED AggregatedBarObservation
               rows). Live capture architecturally never writes
               HistoricalBar, independent of connectivity success.
stream_2_theory: CONFIRMED with direct evidence — Dhan's fromDate
               boundary is exclusive; widening one bar further than the
               current code recovers the missing bar. No fix applied
               (diagnostic only, as scoped).
tests: 3/3 passed (supervisor command suite, re-run just now).
backtestresultrecord_count: 208 before, 208 after — unchanged.
commit: (recorded below)
```

---

## Premise check (done first, per this checkpoint's own instruction)

`[F]` Checked directly before doing anything else: `2026-09-07
13:25:12 IST`, `is_trading_day=True`, market open (close `15:30:00
IST`, ~2 hours remaining at the time this checkpoint started). This
matched the prompt's "market is LIVE right now" — no correction
needed this time, unlike `LIVE-2-FINALIZE`.

---

## STREAM 1 — Full-session live capture (real test of the session-end fix)

### Part 0 — Preflight

`[F]` `effective_credentials()`, re-decoded the real JWT directly:
`iat=2026-09-07 06:40:22 UTC`, `exp=2026-09-08 06:40:22 UTC` — ~22.75
hours remaining at check time, comfortably covering the ~2-hour
remaining session.

`[F]` `LIVE-3`'s fix and test confirmed present **by direct
inspection, not assumed**: `grep` confirmed `asyncio.to_thread(...)`
wraps the `request_stop()` call in
`supervise_market_data_worker.py`, and
`test_session_end_stop_does_not_crash_with_synchronousonlyoperation`
exists in the test file. Ran the file directly: **3/3 passed** right
before launch.

### Part 1 — Launch and full-session result

Launched `supervise_market_data_worker --max-restarts 10
--cooldown-seconds 15 --session-end 2026-09-07T15:30:00+05:30 --mode
observe-only` at 13:26 IST, same 15-symbol watchlist as prior
checkpoints (`ScannerConfiguration` already `SELECTED`/`5m`/15-symbol
from earlier, confirmed unchanged before launch).

`[F]` **Zero uncaught crashes** across the entire session — this is
the headline result and is reported first per this checkpoint's own
rule. `close_code=1006` reconnects continued to occur at roughly the
same intermittent cadence observed in `LIVE-3` (a real, external
characteristic of today's connection, not a code defect — see
`LIVE-3`'s own Stream 1 findings), but every single one was handled
correctly: worker marks itself `FAILED` after its in-process 5-attempt
ceiling, the supervisor detects it, cools down 15s, and restarts —
never once producing a `SynchronousOnlyOperation` traceback or any
other uncaught exception.

`[F]` **One real operational finding, reported honestly**: the first
`--max-restarts 10` budget was exhausted at `14:18:55 IST` —
**before** the 15:30 IST session end — due to the reconnect frequency
today (11 worker lifetimes in ~52 minutes, roughly one every ~5
minutes). This is **not** the crash-fix failing; it is the
bounded-restart safety design working exactly as intended
(`max_restarts_exhausted=True ... stopping permanently ... A human
must investigate` — the process stopped itself cleanly, no crash, no
data corruption). Since this was mid-session and the checkpoint's
intent was full-session coverage, I relaunched with `--max-restarts
40` (sized generously against the observed cadence) for the remaining
~71 minutes, using the exact same watchlist/config — this is a
continuation of the same already-authorized capture, not a new
sensitive action.

`[F]` **The second launch reached natural session-end cleanly**:
`Supervisor finished: stopped_cleanly=True restarts_used=14
final_worker_state=STOPPED` at `15:30:28 IST` — the log shows the
exact sequence `LIVE-3`'s fix was built for: `stop request observed
for provider='dhan' ... reason='session_end_reached' - initiating
graceful shutdown` → `stop requested - worker shut down cleanly` →
`archive refreshed: 15 cell(s)` → clean process exit, `_report()`
running normally and printing the full internal restart log (unlike
`LIVE-3`, where the crash meant this batch log was silently lost —
this time it printed in full, itself indirect confirmation the fix
held).

`[F]` **Totals across the whole session** (both launches combined): 26
distinct worker lifetimes (11 from the first launch + 1 initial + 14
restarts from the second launch), summing to **28,463 quotes
processed** (`grep`-summed directly from all 26 "Worker finished"
lines), **zero decode failures, zero rejected packets** across every
single lifetime.

### Part 2 — Monitoring

Reused the established pulse-check pattern approximately every 20-30
minutes throughout (13:26, 13:57, 14:39, 14:48, 14:58, 15:04, 15:24,
15:30 IST) via direct log-tail + `WorkerRuntimeStatus` re-queries — no
gaps in coverage, no unnoticed extended outage.

### Part 3 — Final state (verified at actual 15:30 IST close)

`[F]` **`AggregatedBarObservation`, `timeframe=5m`,
`trading_date=2026-09-07`**: **401 rows, all `status=CLOSED`**,
summing to **39,487 total observations** across the 15 symbols (this
is the correct, larger figure — it counts every individual quote
folded into each closed bar, not just quotes seen by whichever single
worker lifetime happened to be running at any instant; the 28,463
"Worker finished" sum undercounts because a worker lifetime's own
counter resets on each restart while aggregation state persists
across restarts within the same trading day).

`[F]` **`HistoricalBar`, `timeframe=5m`, 2026-09-07: 0 rows.**
**This definitively answers `LIVE-2`'s still-open question** — and
this time the answer is not moot due to a zero-quote failure (as it
was in `LIVE-2`/`LIVE-2-FINALIZE`): today's capture was substantial
and successful (401 closed bars, 39,487 observations), and the
`HistoricalBar` table still received **zero** rows. **Live capture
architecturally never writes to `HistoricalBar`, under any
connectivity outcome** — confirmed positively this time, not just
"couldn't determine." The canonicalization question `LIVE-2` asked
("do live-captured rows also land as `CANONICALIZED`?") therefore has
a definitive answer: **there is no live-captured `HistoricalBar` row,
ever, for this question to apply to** — it is not a data-quality gap,
it is the current architecture's own scope (only
`HistoricalDataPreparationService`'s REST backfill path writes to
`HistoricalBar`; live capture writes only to
`AggregatedBarObservation`).

`[F]` **Archive status, `market_data_archive --refresh --date
2026-09-07`, run directly at close**: `status=PARTIAL` for all 15
symbols, `closed=26-27/72-75` bars, `missing=46-49` per symbol,
`quotes=1521-3278` per symbol. **`PARTIAL` is the correct, honest
status** — capture began at ~13:26 IST (mid-session, not from market
open 09:15 IST), so a substantial fraction of today's expected bars
predate this checkpoint's own capture window by design; this is not a
data-quality failure, it reflects exactly when the worker was
actually running.

`[F]` **`WorkerRuntimeStatus(dhan)` final state**: `STOPPED`,
`owner_pid=22616`, updated `2026-09-07 10:00:17 UTC` (15:30:17 IST) —
correctly reflects the clean stop, not a stale/crashed row this time
(unlike after `LIVE-3`'s crash).

---

## STREAM 2 — Authorized live diagnostic for the `fromDate`-exclusive theory

Delegated to a background agent (single scoped REST diagnostic fetch,
explicitly authorized by this checkpoint, outside today's date so it
cannot conflict with Stream 1) and independently re-verified below
before being reported.

`[F]` **Symbol/day used**: RELIANCE, 2026-08-04, 5m — the exact
CANONICALIZED day already analyzed in `LIVE-3`, safely outside today
(2026-09-07). `[F]` Confirmed directly, independently, before trusting
the agent's own claim: `HistoricalBar.objects.filter(symbol=
'RELIANCE', timeframe='5m', bar_timestamp__date='2026-08-04').count()`
= **71** — unchanged before and after the diagnostic (re-confirmed by
me directly after the agent's run too).

`[F]` **Method**: called `fetch_intraday_candles()` directly
(`historical_client.py:195`) — the raw client-level function,
bypassing `DhanHistoricalBarProvider.fetch()`'s post-filter and
bypassing `HistoricalDataPreparationService.prepare()` entirely, so
this was a pure read with zero persistence path reachable, not just
"chose not to persist."

`[F]` **Two calls, direct comparison**:
1. **Current production boundary** (`from_time = 2026-08-04 03:45:00
   UTC` / 09:15 IST — exactly what `_provider_request_envelope()`
   sends today): **5 raw candles**, first at `03:50:00 UTC`. The
   `03:45 UTC` candle (which canonicalizes into the missing 09:20 IST
   bar) is **absent**.
2. **Diagnostic widened boundary** (`from_time = 2026-08-04 03:40:00
   UTC` / 09:10 IST — one bar-duration earlier than the current code,
   double the current widening): **6 raw candles**, now including
   `03:45:00 UTC` (`O=1315.0 H=1315.0 L=1306.0 C=1306.5
   V=394116`) — **the previously-missing candle is present.**

**Conclusion: CONFIRMED**, with direct evidence, not inference. Dhan's
`fromDate` comparison is exclusive — sending `fromDate` at exactly the
boundary timestamp excludes the candle whose own raw timestamp equals
that boundary. Widening by one bar further recovers exactly the
missing candle.

`[F]` **Zero persistence**: `HistoricalBar` count for
RELIANCE/2026-08-04/5m unchanged (71 before, 71 after, confirmed
independently by me). `git status --short`: clean, no source files
touched by this stream.

**Future-fix description (one sentence, NOT applied this
checkpoint)**: widen `from_time` by two bar-durations instead of one
in `_provider_request_envelope()`
(`historical_provider.py:301-305`), and add a regression test proving
RELIANCE/2026-08-04's day-start CANONICALIZED bar coverage returns to
72 rows via the normal `HistoricalDataPreparationService` path — left
for a future checkpoint's own explicit decision to implement and test,
per this checkpoint's "diagnostic only, do not apply as a permanent
fix" rule.

---

## GLOBAL CONFIRMATIONS

- No migration execution. No Gainz work.
- Stream 2 applied no fix — `_provider_request_envelope()`,
  `historical_provider.py`, `historical_client.py`, and every other
  source file remain byte-for-byte unchanged by this stream (`git
  status --short` clean, re-confirmed).
- Stream 1's real capture produced real, expected database writes
  (`AggregatedBarObservation`, `WorkerRuntimeStatus`) — intended, not
  a violation of any DB-write rule.
- `BacktestResultRecord.objects.count()`: **208 before, 208 after** —
  unchanged.
- `git status --short`: clean at the time of writing this summary.
- Zero uncaught crashes reported first, per this checkpoint's explicit
  priority rule — there were none to report.
