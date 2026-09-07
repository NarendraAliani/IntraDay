# Checkpoint LIVE-2-FINALIZE — End-of-Day Close-Out

```
checkpoint: LIVE-2-FINALIZE
verdict: STALE_PREMISE — RECONCILED AGAINST THE REAL LIVE-2 RUN (2026-09-04)
premise_mismatch: directive assumed "market closed today, ~15:40 IST same day
                   as the LIVE-2 run"; this checkpoint was issued on
                   2026-09-07, a trading day, at ~12:25 IST — market was
                   OPEN at issue time, three days after LIVE-2 actually ran.
close_code_logged: 40/40 reconnect attempts (100%) — LIVE-1-POSTMORTEM's
                    open question is CLOSED, confirmed.
phantom_restart_recurred: NO — 0/8 crash-to-restart gaps under 15.0s.
quotes_captured: 0 (all 8 cycles, close_code=1006, connectivity failure)
canonicalization_of_live_rows: MOOT — 0 HistoricalBar rows written (no
                                quotes were ever received to write).
stream_2_status: already completed and reported in CHECKPOINT_LIVE-2_SUMMARY.md
                  — not re-run here, per this checkpoint's own rule.
backtestresultrecord_count: 208 before LIVE-2, 208 now — unchanged.
full_test_suite: 3240 passed / 5 failed / 3245 total — all 5 failures
                  pre-existing, unrelated to LIVE-2 (confirmed via
                  git status --short = clean; zero source files touched
                  by LIVE-2, LIVE-2-FINALIZE, or the interim MEMORY.md
                  commit).
commit: (recorded below)
```

---

## Premise correction (read this first)

This checkpoint's directive opens: *"Market (including CAS) has
closed for today... run after market + CAS close, ~15:40 IST."* That
premise does not match reality at the time this checkpoint was
issued: **today is 2026-09-07, a confirmed trading day, and the
directive arrived at ~12:25 IST — while the market was still open.**
`LIVE-2`'s actual live-capture attempt happened three days earlier, on
**2026-09-04**.

Rather than fabricate a same-day close for a market session that
hasn't ended, or silently substitute today's (still-open, untouched)
session for `LIVE-2`'s, this checkpoint reconciles honestly against
**the real `LIVE-2` run's actual data from 2026-09-04** — re-verifying
the underlying log and database facts directly rather than trusting
`CHECKPOINT_LIVE-2_SUMMARY.md`'s own prose. No new capture and no new
walk-forward run were performed today, per this checkpoint's own
rules.

`ScannerConfiguration(dhan)` remains in the state `LIVE-2` deliberately
left it in (`SELECTED`/`5m`/15-symbol, not reverted to
`ALL_CONFIGURED`/`3m`) — unchanged since 2026-09-04, confirmed `[F]`
directly. No action was taken on it here, since Part 3's global rules
prohibit any new capture/config change in this checkpoint.

---

## PART 1 — Stream 1 (live capture) close-out

`[F]` **The supervisor is not running now**, and was not stopped
externally — it **stopped itself, permanently, on its own**, on
2026-09-04 at `04:46:54 UTC` (~10:16:54 IST), per its own bounded
`--max-restarts 8` design: `max_restarts_exhausted=True
restarts_used=8 final_worker_state=FAILED - stopping permanently, no
further restart attempted. A human must investigate.` Confirmed via
direct re-read of the real supervisor log
(`live2_supervisor.log`, preserved in the scratchpad) and via
`Get-CimInstance Win32_Process` today showing no
`run_market_data_worker`/`supervise_market_data_worker` process alive.

`[F]` **Final tally, re-counted directly from the log, not from
memory of the earlier report**:
- **8 total crashes**, **8 total restarts** (`grep -c
  "crash_detected"` = 8, `grep -c "worker_restarted"` = 8).
- **40/40 reconnect attempts had a logged close code** (`grep -c
  "close_code="` = 40, matching `5 attempts × 8 cycles` exactly) — a
  **100% hit rate**. Every single one was `close_code=1006`
  (abnormal closure, no close frame).
- **One permanent-stop event**: `max_restarts_exhausted` at
  `04:46:54 UTC` on 2026-09-04, reason `reconnect_attempts_exhausted`
  on the 8th and final cycle — the restart budget itself, not a
  separate failure mode.

`[F]` **Phantom near-zero-elapsed restart: did NOT recur, 0/8 times.**
Re-measured every `crash_detected → worker_restarted` gap directly
from the real timestamps in the log:

| Cycle | crash_detected (UTC) | worker_restarted (UTC) | Gap |
|---|---|---|---|
| 1 | 04:43:58.808 | 04:44:13.825 | 15.02s |
| 2 | 04:44:20.824 | 04:44:35.845 | 15.02s |
| 3 | 04:44:42.860 | 04:44:57.861 | 15.00s |
| 4 | 04:45:04.864 | 04:45:19.872 | 15.01s |
| 5 | 04:45:26.885 | 04:45:41.900 | 15.02s |
| 6 | 04:45:48.915 | 04:46:03.941 | 15.03s |
| 7 | 04:46:10.954 | 04:46:25.964 | 15.01s |
| 8 | 04:46:32.970 | 04:46:47.970 | 15.00s |

Every gap equals the configured `--cooldown-seconds 15` almost
exactly (15.00–15.03s) — no restart ever fired early. This is the
strongest evidence yet, across 8 independent real cycles, that
`LIVE-1-INSTRUMENT`'s `sleep(poll_interval_seconds)` race fix holds.

`[F]` **`HistoricalBar` count for `timeframe=5m`, 2026-09-04: 0**
(re-queried directly today). `[F]` **`AggregatedBarObservation` count
for `timeframe=5m`, `trading_date=2026-09-04`: 0** (re-queried
directly today, by both total and per-status/per-symbol breakdown —
all empty). Both are consistent with the log's own
`quotes_processed=0` for all 8 cycles: the connection never held long
enough to receive a single quote, so nothing existed to aggregate or
write anywhere.

`[F]` **Canonicalization state of today's fresh live-capture rows: N/A
— there are no rows to have a state.** This closes `LIVE-2`'s own open
question, but not with a positive answer: the question "does live
capture also canonicalize at write time, like the REST backfill path
does?" cannot be answered from 2026-09-04's run, because zero rows
were ever written by the live-capture path that day. This remains
genuinely untested, not confirmed either way.

`[F]` **Archive status for 2026-09-04**: re-ran `market_data_archive
--refresh --date 2026-09-04` directly just now — `refreshed 0 archive
cell(s)`, final status `NOT_OBSERVED`, `symbols=0`. Not `PARTIAL` or
`COMPLETE` — `NOT_OBSERVED` is the correct, honest state for a day
with literally zero captured data.

---

## PART 2 — Stream 2 (canonicalized walk-forward) close-out

**Stream 2 already completed on 2026-09-04, inside `LIVE-2` itself —
not re-run here, per this checkpoint's own rule.** Referencing that
result rather than repeating it:

`CHECKPOINT_LIVE-2_SUMMARY.md`'s Stream 2 section found that, for the
first time this session, walk-forward was run through the real
`ResearchDataGateService` (no bypass) against the CANONICALIZED
subset (RELIANCE/TCS/HDFCBANK/INFY, 923 rows / 13 days each). **The
gate rejected all 3 strategies identically** (`ema_crossover`,
`sma_trend_filter`, `atr_volatility_breakout`), before any
walk-forward computation ran, due to a uniform 1-bar/day coverage gap
(missing the `03:50 UTC`/09:20 IST bar on every CANONICALIZED day, all
4 symbols) — a newly surfaced finding, not previously documented.
**No fold results, no `mean_degradation_ratio`, for any strategy.**

This is confirmed still accurate today: `[F]` re-queried
`HistoricalBar` directly just now for the same filter
(`timeframe='5m', provenance='REAL_DHAN',
canonicalization_state='CANONICALIZED'`) — nothing has changed since
`LIVE-2` (unsurprising, since Stream 1's zero-quote failure means no
new rows of any kind were written on 2026-09-04, and no further
capture has run since).

**What would unblock it next time**: root-causing the uniform 1-bar/
day gap itself — is it a `DhanHistoricalBarProvider` fetch-boundary
issue, a `HistoricalDataCoverageService` expected-bar-count
miscalibration (72 expected vs. 71 actually ever fetched), or
something else? This is explicitly unresolved and was not
investigated further in `LIVE-2` or here, per both checkpoints'
scope.

---

## PART 3 — Zero-persistence / zero-drift confirmation

`[F]` **`BacktestResultRecord.objects.count()`: 208, unchanged.**
This matches the count recorded both before and after `LIVE-2`'s own
Stream 2 run — re-confirmed directly today, not assumed.

`[F]` **`git status --short`: clean** at the moment this checkpoint's
investigation began (before writing this file) — no unexpected source
diff. The only files this checkpoint and its immediate predecessors
added were `CHECKPOINT_LIVE-2_SUMMARY.md` (already committed as
`65843e9`) and, in between, `MEMORY.md` (a conversation-history
bootstrap requested mid-session, unrelated to `LIVE-2`'s own scope,
already committed as `a70d11d`) — both accounted for, neither a
source-code change.

`[F]` **Full test suite: 3240 passed / 5 failed / 3245 total**, run
just now (`pytest -q`, full suite, 729.14s). The 5 failures:

- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
- `tests/unit/architecture/test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
- `tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
- `tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**These are pre-existing, not a regression from today's work.**
Confirmed two ways: (1) `git status --short` was clean before this
checkpoint began any work, and neither `LIVE-2` nor
`LIVE-2-FINALIZE` nor the interim `MEMORY.md` commit touched a single
source file (`src/`, `tests/`) — only `.md` files at repo root; (2)
these exact test names are referenced in earlier checkpoint summaries
from well before today (`67.12.2-S`, `67.12.2-U`, `68.2`), indicating
they are already-known, pre-existing failures in this codebase's
current state, not something introduced by any work in this
conversation.

**Caveat, stated plainly**: this run's total (3245) does not match
the `750`-total figure quoted as "the established baseline" in
`67.12.2-V` (the most recent full-suite number found in this
conversation's own summaries). That earlier figure almost certainly
reflected a narrower test scope/selection at that time, not the same
"whole repository" invocation used here — no attempt was made to
reconcile the two counts, since doing so is outside this checkpoint's
scope and would require re-deriving what `67.12.2-V`'s exact `pytest`
invocation actually targeted. Flagging this rather than silently
treating either number as authoritative.

---

## PART 4 — One paragraph for the operator

Today (2026-09-07) nothing new happened — this checkpoint's own
premise ("market just closed") didn't match reality, so instead of
guessing I went back and closed out `LIVE-2`'s actual results from
2026-09-04. The good news: both of the crash-handling fixes you asked
me to verify live really do work — every single one of 40 real
reconnect attempts logged its actual failure reason, and the
"restarted too soon" bug never happened once across 8 real crash
cycles. The bad news: the connection itself never once succeeded that
day — all 8 attempts failed with the same abnormal-closure code and
zero market data was ever received, so there's still no live-captured
data to show, and whether live capture gets automatically
"canonicalized" (like fresh backfilled data does) remains genuinely
unanswered, not just unconfirmed. Separately, the canonicalized-data
walk-forward test also came back empty-handed: going through the real
data-quality gate this time (instead of around it) revealed that even
the "good" canonicalized data is missing one bar every single day,
so nothing passes the gate yet. Nothing was written to the database
today, and the test suite shows no new breakage from any of this. The
single most useful next action would be figuring out why that
WebSocket connection keeps getting slammed shut — but I'm not
starting that automatically; it's your call when you're ready.
