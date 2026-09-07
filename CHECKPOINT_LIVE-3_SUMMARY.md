# Checkpoint LIVE-3 — Diagnose WebSocket Connectivity Failure + Coverage-Gap Root Cause

```
checkpoint: LIVE-3
verdict: STREAM_1_ROOT_CAUSE_FOUND_AND_FIXED (a real bug, distinct from
         the original close_code=1006 symptom) / STREAM_2_HIGH_CONFIDENCE_
         ROOT_CAUSE_REPORTED_NO_FIX (read-only scope)
stream_1_original_1006_failure: NOT a code bug — connectivity itself works
         (proven live: 10,243 + 10,052 real quotes received across two
         separate multi-minute streams today); 2026-09-04's 8/8 zero-quote
         failure was transient, cause not further determinable after the
         fact.
stream_1_new_bug_found_and_fixed: YES — SynchronousOnlyOperation crash in
         request_session_end_stop(), reproduced live, fixed narrowly,
         regression test proves causation (fails on reverted code, passes
         on fixed code).
stream_1_quotes_captured_today: 10,243 + 10,052 = 20,295 real quotes across
         two worker lifetimes within one ~22-minute supervised window.
stream_1_historicalbar_writes: 0 (live capture still architecturally never
         writes HistoricalBar — LIVE-1's finding still holds; the
         canonicalization question remains structurally moot, not failed).
stream_2_root_cause: HIGH-CONFIDENCE INFERENCE — DhanHistoricalBarProvider
         fetch-boundary issue (from_time widening insufficient), NOT a
         HistoricalDataCoverageService miscalibration. No fix applied
         (read-only stream, per its own scope).
tests: 212 passed / 0 failed (scoped sweep: supervisor + worker-supervisor
       + market-data-provider test directories, all touched/adjacent code).
backtestresultrecord_count: 208 before, 208 after — unchanged (Stream 2
         read-only; Stream 1 doesn't touch this table).
commit: (recorded below)
```

---

## STREAM 1 — Why did every single reconnect get `close_code=1006`?

### Part 1 — Diagnosis, in likelihood order

**1. Credential validity at connect time — RULED OUT, re-derived
precisely.** `[F]` Re-decoded the real JWT directly (not just calling
`effective_credentials()`'s summary): on 2026-09-04, at the moment of
`LIVE-2`'s failure (`04:43:58`–`04:46:54 UTC`), the token's `exp` was
`2026-09-05 04:29:57 UTC` — **~23.75 hours of validity remaining at
connect time**, nowhere near expiry. Today's token, checked directly:
`iat=2026-09-07 06:40:22 UTC`, `exp=2026-09-08 06:40:22 UTC` — also
comfortably valid. Not the cause on either day.

**2. Subscription payload correctness — RULED OUT, by direct
reproduction.** `[F]` Built a minimal diagnostic script
(`diag_ws.py`, scratchpad, not committed) that constructs the **exact
same** URI shape (`wss://api-feed.dhan.co?version=2&token=...
&clientId=...&authType=2`) and the **exact same** subscribe payload
shape (`{"RequestCode": 15, "InstrumentCount": 1, "InstrumentList":
[{"ExchangeSegment": "NSE_EQ", "SecurityId": "2885"}]}`) that
production code sends (`_build_subscribe_messages()` in
`run_market_data_worker.py`), reusing the real
`DhanWebSocketTransport` class directly (not reimplemented). **Ran it
against the real Dhan endpoint just now: connected in 116ms, subscribe
accepted, 5 real packets received in under 4 seconds.** The payload
shape is valid; not the cause.

**3. Rate limiting / competing connections — RULED OUT.** `[F]`
`Get-CimInstance Win32_Process` before launch found no
`run_market_data_worker`/`supervise_market_data_worker` process of any
kind already running (only my own diagnostic query self-matching the
filter). No other process could have been holding a connection slot.

**4. Network/firewall/proxy — RULED OUT for today, by direct positive
evidence.** `[F]` The same diagnostic script, and later the full
supervised worker, both connected and streamed real data successfully
today with zero handshake issues. Whatever the local network path is,
it works.

**5. A recent code change — RULED OUT as an explanation; `close_code=
1006` is a long-standing, already-documented failure MODE, not a
newly introduced bug.** `[F]` Re-read `CHECKPOINT_LIVE-1-POSTMORTEM
_SUMMARY.md` directly: `LIVE-1` (2026-09-03) **did** receive real
quotes — three separate runs streamed for 6m53s to 24m2s each before
eventually exhausting the in-process 5-reconnect ceiling and dying.
`[F]` `git log -S"exact signature this checkpoint's own live Dhan
connection attempt produced"` traced the close-code-logging feature
itself to commit `0f075e4` (`LIVE-1-INSTRUMENT`, 2026-09-03), whose
own commit message cites "the postmortem's real close_code=1006
citation" as its motivating example — **`close_code=1006` was already
the observed failure signature on 2026-09-03, before `LIVE-2` ever
ran.** This directly distinguishes "newly broken" from "always this
fragile": it is the latter, and today's own successful ~22-minute
capture (below) confirms the fragility is intermittent, not
permanent.

**Conclusion for the original symptom**: `LIVE-2`'s 8/8 zero-quote
failure on 2026-09-04 was very likely a transient condition (Dhan-side
or environment-specific to that day/window) — not a defect in this
codebase's credential handling, subscription payload, connection
management, or network path, all four of which were re-tested
directly today and found working. **The exact cause of 2026-09-04's
specific failure cannot be determined after the fact** — no Dhan-side
status/incident log is available to this environment, and the
condition did not reproduce today. Reported plainly as unresolved,
not forced to a false conclusion.

### Part 2 — Real test window: connectivity confirmed working, AND a genuinely new bug found

Since market was live, launched `supervise_market_data_worker
--max-restarts 4 --cooldown-seconds 15 --session-end
2026-09-07T13:14:00+05:30 --mode observe-only` — an ~18-minute window,
same 15-symbol watchlist as `LIVE-1`/`LIVE-2`.

`[F]` **Real quotes flowed immediately and substantially**: two
separate worker lifetimes (the first exhausted its own in-process
5-reconnect ceiling after a multi-minute stream and was restarted by
the supervisor, matching `LIVE-1`'s exact known pattern) processed
**10,243** and **10,052** real quotes respectively — **20,295 total**
— aggregating 60 bars/symbol and promoting 135 bars to
`TRADING_GRADE_BAR` on each. Zero decode failures, zero rejected
packets, across both lifetimes.

`[F]` **A genuinely new bug surfaced at session-end** — not the
`close_code=1006` symptom this checkpoint set out to diagnose, but a
real, independent defect: at `13:14:31 IST`, the supervisor's own
`request_session_end_stop()` closure called
`WorkerRuntimeStatusRepository.request_stop()` (a synchronous Django
ORM write) **directly from an async function**, triggering Django's
own `SynchronousOnlyOperation` guard and **crashing the entire
supervisor process uncaught** — the worker was never asked to stop
cleanly, and the supervisor never produced a final `SupervisorResult`
or archive refresh. Full traceback captured in
`live3_supervisor.log` (scratchpad, not committed — the source of
truth for this checkpoint's log-based findings).

**Fixed narrowly** — `src/intraday/infrastructure/persistence
/management/commands/supervise_market_data_worker.py`: wrapped the
call in `asyncio.to_thread(...)`, exactly matching the pattern its
sibling closure `refresh_archive()` already uses two lines below (that
one already wraps its own sync call correctly — this was the one
inconsistent call site, not a systemic issue). No other file touched;
no refactor beyond the one call site.

`[F]` **Causation proven empirically**, not just asserted: added
`test_session_end_stop_does_not_crash_with_synchronousonlyoperation`
(the real core supervisor loop runs to a past `--session-end`, with
only the subprocess spawn stubbed — not the whole loop, unlike the two
pre-existing tests in this file), then `git stash`ed the fix and
re-ran that one test against the reverted code: it failed with the
**exact same** `SynchronousOnlyOperation` traceback captured live.
Restored the fix (`git stash pop`) and confirmed it passes again.

`[F]` **Scoped regression sweep**: `tests/unit/infrastructure
/persistence/management/`, `tests/unit/application/services
/test_market_data_worker_supervisor.py`, and `tests/unit
/infrastructure/market_data_providers/` — **212 passed, 0 failed**.

`[F]` **Residual, self-healing, not hand-patched**:
`WorkerRuntimeStatus(dhan)` was left claiming `worker_state=RUNNING,
owner_pid=14992` after the crash (the crash happened before any clean
stop status could be written). Confirmed directly (`Get-Process -Id
14992` → not found) that this PID is genuinely dead — a stale row.
Per `67.12.2-S`'s own PID-verified reconciliation design, this
self-heals automatically the next time either `run_market_data_worker`
or `supervise_market_data_worker` starts up; it was deliberately left
as-is rather than manually edited, consistent with "the established
mechanism handles this, don't hand-patch around it."

**A related observability gap, noted but NOT fixed (out of this
checkpoint's narrow-fix scope)**: the supervisor's own internal
restart-history log entries (`crash_detected`, `worker_restarted`,
etc.) are only ever flushed to stdout in one batch, by `_report()`,
after `asyncio.run()` returns normally. Because this run's process
crashed uncaught mid-loop, `_report()` never ran, and every one of
those internal log lines was silently lost — invisible in
`live3_supervisor.log` even though the restarts genuinely happened
(confirmed indirectly via 4 "Starting market-data worker" launch
lines and 2 "Worker finished" completion lines). This is a real,
separate hardening opportunity (incremental/streaming log flush
instead of batch-at-completion) — reported here for a future
checkpoint's own decision, not fixed now.

`[F]` **Canonicalization state of any new rows — still structurally
moot, not answered positively or negatively.** `HistoricalBar` count
for `timeframe=5m`, 2026-09-07: **0** — unchanged from `LIVE-2`'s
finding. The live-capture pipeline still has no code path that writes
to `HistoricalBar` at all (it writes `AggregatedBarObservation` only —
confirmed **60** rows for today, 45 `CLOSED` / 15 `FORMING`, real
quote counts 453–1,174 per symbol). This is not a new finding, just a
re-confirmation that the question `LIVE-2` left open cannot be
answered by any live-capture run under the current architecture,
regardless of connectivity success.

`market_data_archive --refresh --date 2026-09-07` run directly:
`status=IN_PROGRESS reason=session_not_closed` for all 15 symbols
(correct and expected — today's actual full trading session had not
ended at the time of this checkpoint; only an ~18-minute test window
was run, not a full-day capture).

---

## STREAM 2 — Root-cause the uniform 1-bar/day coverage gap (read-only)

Delegated to a background agent (strictly read-only: no DB writes, no
`HistoricalDataCoverageService`/strategy-logic changes, no Dhan network
call, per its own scope) and independently re-verified below before
being reported.

### Findings, independently re-checked

`[F]` **Fetch-boundary logic**
(`historical_provider.py:261-305`, `_provider_request_envelope()`):
widens the request's `from_time` by exactly one bar-duration
(`canonical_start - one_bar`) before sending it to Dhan; `to_time` is
sent **unwidened** — a prior widening attempt there was tested and
explicitly disproven by its own predecessor checkpoint (66.7), per the
function's own docstring, which I read directly.

`[F]` **Expected-bar-count logic**
(`historical_data_coverage.py:64-113` →
`CasAwareSession.expected_continuous_bar_timestamps()`,
`contracts.py:203-221`): generates 72 timestamps from
`continuous_trading_open + bar_duration` (09:20 IST) through
`continuous_trading_close` (15:15 IST) at 5-minute steps — a
straightforward, correctly-derived count from the real 09:15–15:15
IST CAS-era session, **not** a hardcoded or miscalibrated constant.

`[F]` **Independently re-derived, RELIANCE/2026-08-04**: queried
`HistoricalBar` directly myself (not just trusting the agent) —
**71 rows**, first bar `2026-08-04T03:55:00+00:00` (09:25 IST), last
bar `09:45 UTC` (15:15 IST), every 5-minute slot present in between.
Confirmed `2026-08-04T03:50:00+00:00` (09:20 IST — the expected
*first* bar) is genuinely absent. All 71 rows share `ingested_at =
2026-09-03 13:54:37 UTC` (a single batch insert).

`[F]` **The fix-timing fact that makes this a real, still-open bug,
not a stale finding**: `git log -1 8f29502` → `2026-09-02 12:57:00
+0530` — the commit bundling the `from_time`-widening fix (Checkpoints
66.6/66.7/66.8) **predates** this data's ingestion
(`2026-09-03 13:54:37 UTC` = `2026-09-03 19:24:37 IST`) by over 6
hours. **The fix was already active when this data was fetched, and
the first bar is still missing.**

`[F]` **OPEN-vs-CLOSE semantics**: `source_timestamp_semantics='OPEN'`
confirmed directly on every row for this day (matches
`_DHAN_INTRADAY_TIMESTAMP_SEMANTICS` in `historical_provider.py:66`).
A raw Dhan candle labeled `09:15` (bucket `[09:15,09:20)`) becomes
canonical CLOSE-labeled `09:20` IST after the `+interval` shift — so
`09:20 IST` genuinely is the correct *first* expected canonical bar,
not a labeling-convention artifact. The coverage service's expectation
is correct; the underlying raw data for that one bucket is what's
missing.

### Root cause — HIGH-CONFIDENCE INFERENCE, not fully confirmable without a live diagnostic (out of this stream's read-only/P6 scope)

The provider's own `_provider_request_envelope()` docstring
(`historical_provider.py:278-296`) already documents, from its own
prior investigation, that widening `to_time` by one bar had **zero**
demonstrated effect on Dhan's response — and separately names the
exact hypothesis this stream's evidence converges on: Dhan's raw
candle timestamps may be OPEN-of-interval, and the boundary comparison
against `fromDate` may be **exclusive**, not inclusive. If so,
requesting `fromDate = canonical_start - one_bar` (=09:15 IST, exactly
equal to the raw candle's own bucket-start label) would still exclude
that candle — recovering it would require widening by *more* than one
full bar. **This is the most probable explanation consistent with all
evidence gathered**, but confirming it would require an authorized
live Dhan diagnostic call varying the exact `fromDate` boundary, which
is outside this stream's own strictly read-only scope. Reported as a
high-confidence root cause, not a certainty — **no fix was proposed or
applied**, per Stream 2's own explicit rules.

---

## GLOBAL CONFIRMATIONS

- No migration execution. No Gainz work.
- `BacktestResultRecord.objects.count()`: **208 before, 208 after** —
  unchanged, re-confirmed directly.
- Stream 1's fix touches only
  `supervise_market_data_worker.py` (one call site) and its own test
  file — `HistoricalDataCoverageService` and all strategy logic
  (P9) remain untouched by either stream.
- `git status --short`: clean at the time of writing this summary,
  beyond the two commits this checkpoint itself made.
- Stream 1's real test window did produce real database writes
  (`AggregatedBarObservation`, `WorkerRuntimeStatus`) — expected and
  intended, exactly as the checkpoint's own global rules anticipated
  ("No DB writes beyond what Stream 1's short real-test window
  naturally produces").
