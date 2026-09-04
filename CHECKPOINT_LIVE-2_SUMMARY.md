# Checkpoint LIVE-2 — Live Capture (fix verification) + Canonicalized-Only Walk-Forward

```
checkpoint: LIVE-2
verdict: STREAM_1_BLOCKED_ON_REAL_CONNECTIVITY / STREAM_2_GATE_REJECTED_ALL_THREE
stream_1_fixes_verified: close_code_logging=YES, phantom_restart_race=NOT_REPRODUCED
stream_1_quotes_captured: 0
stream_1_scanner_config: LEFT AS SELECTED/5m/15-symbol (paused for user investigation, not reverted)
stream_2_strategies_run: 0/3 (all rejected at ResearchDataGateService, INCOMPLETE_COVERAGE)
stream_2_database_write_occurred: NO
commit: (recorded below)
blockers: [stream_1: real Dhan WebSocket connectivity failure, close_code=1006 x8/8,
           cause undetermined - handed to user for direct investigation]
```

---

## STREAM 1 — Live capture (first real test of the two crash fixes)

### Part 0 — Preflight (all real, all confirmed before launch)

`[F]` Time check: `2026-09-04 04:31:48 UTC` = ~10:02 IST — well before close.
`[F]` `effective_credentials()`: valid, `exp_utc=2026-09-05 04:29:57` (~24h
remaining) — no renewal needed.
`[F]` `WorkerRuntimeStatus(dhan)` pre-launch: `worker_state=FAILED`,
`owner_pid=8524` — a stale row from `LIVE-1`'s earlier crash-exhaustion,
the first real test case for `67.12.2-S`'s PID reconciliation against
genuinely stale data (see below).
`[F]` `ScannerConfiguration(dhan)` original values recorded:
`universe_mode=ALL_CONFIGURED, timeframe=3m, enabled=True,
selected_instrument_ids=[]`.
`[F]` `is_trading_day: True` for today.
`[F]` No `run_market_data_worker`/`supervise_market_data_worker` process
already running, confirmed via `Get-CimInstance Win32_Process`.

User approved writing the `ScannerConfiguration` change and launching the
supervisor (explicit `AskUserQuestion` approval).

### Part 1 — Launch

`[F]` Wrote `ScannerConfiguration(dhan)`: `universe_mode=SELECTED`,
`timeframe=5m`, `enabled=True`, `selected_instrument_ids` = the same
15-symbol `NSE:<SYMBOL>` list `LIVE-1` used (ADANIPORTS, AXISBANK,
BAJFINANCE, HDFCBANK, HINDUNILVR, ICICIBANK, INFY, ITC, KOTAKBANK, LT,
MARUTI, RELIANCE, SBIN, SUNPHARMA, TCS). Confirmed via `refresh_from_db()`.

`[F]` Launched `supervise_market_data_worker --provider dhan
--max-restarts 8 --cooldown-seconds 15 --session-end
2026-09-04T15:30:00+05:30 --mode observe-only`.

`[F]` **Startup reconciliation against the stale `FAILED`/`owner_pid=8524`
row fired correctly**: log shows `startup reconciliation: action=not_active
reason="worker_state='FAILED' is already inactive/terminal - nothing to
reconcile"` — the row was already terminal, so `67.12.2-S`'s reconciliation
logic correctly took no action (this is the expected, correct behavior for
an already-terminal stale row, not a failure of the reconciliation
mechanism — it exists to catch a row stuck claiming `RUNNING`/`STARTING`
against a dead PID, which this was not).

`[F]` **Result: 8/8 consecutive crash cycles, then permanent stop.**
Every single cycle, all 5 reconnect attempts failed identically with
`connection_lost:close_code=1006` (abnormal closure), `quotes_processed=0`
for the entire run. Full timeline (`[F]`, from the real log):

| Cycle | Crash detected (UTC) | Restart (UTC) | Elapsed cycle-to-cycle |
|---|---|---|---|
| 1 | 04:43:58 | 04:44:13 | (initial) |
| 2 | 04:44:20 | 04:44:35 | ~22s |
| 3 | 04:44:42 | 04:44:57 | ~22s |
| 4 | 04:45:04 | 04:45:19 | ~22s |
| 5 | 04:45:26 | 04:45:41 | ~22s |
| 6 | 04:45:48 | 04:46:03 | ~22s |
| 7 | 04:46:10 | 04:46:25 | ~22s |
| 8 | 04:46:32 | 04:46:47 | ~22s |

Supervisor's own final line: `max_restarts_exhausted=True restarts_used=8
final_worker_state=FAILED - stopping permanently, no further restart
attempted. A human must investigate.` — it stopped itself cleanly, exactly
per its bounded-restart design; no kill was needed (a `kill -TERM` sent
during investigation found the process already gone).

**(a) Close-code logging — VERIFIED FIXED, closes `LIVE-1-POSTMORTEM`'s
open question.** Every one of the 40 individual reconnect attempts
(8 cycles × 5 attempts) logged its own real close code
(`close_code=1006`) at the per-attempt level, not just an aggregate
summary. This is the first real-market confirmation that
`LIVE-1-INSTRUMENT`'s per-attempt logging fix works against genuine
Dhan traffic.

**(b) Phantom near-zero-elapsed restart — NOT REPRODUCED.** Every
cycle took the full, real ~7s of reconnect attempts plus the full 15s
cooldown (~22s total), matching `--cooldown-seconds 15` exactly. No
restart fired before the prior worker had time to persist its terminal
status. This is consistent with (does not itself prove beyond doubt,
but shows no regression of) `LIVE-1-INSTRUMENT`'s `sleep
(poll_interval_seconds)` race fix holding under real conditions.

**What this run could NOT verify**: whether the connection can hold
once established, canonicalization state for fresh live-capture rows,
or any capture statistics — because **zero quotes were ever received**,
across all 8 cycles. This is not a fix-verification failure; it is a
separate, real connectivity problem.

### Investigation performed before stopping

- `[F]` `effective_credentials()` re-checked mid-failure: still valid,
  same expiry — not a credential/auth issue.
- `[F]` Checked for an orphaned process holding a competing Dhan feed
  connection (a common cause of immediate `1006` closes, since Dhan
  typically allows only one live feed WS per account): none found. The
  only market-data-worker-related processes present were the current
  supervisor's own child chain (confirmed via full parent/child PID and
  `CreationDate` inspection — all traced to the same launch, all created
  within the same ~20s launch window). An unrelated `poetry run manage.py
  runserver` (Django dev server, port 8000, no Dhan/WS involvement) was
  also running — ruled out as irrelevant.
- `[F]` `HistoricalBar` count for `timeframe=5m`, today's date: **0** —
  consistent with `LIVE-1`'s own finding that the live-capture pipeline
  never writes `HistoricalBar` at all (it writes
  `AggregatedBarObservation`); moot here since zero quotes were ever
  received to aggregate in the first place.

**Root cause: undetermined.** `close_code=1006` (abnormal closure, no
close frame) with zero data received, identically across 8 independent
connection attempts over ~3 minutes, points to something outside this
codebase's crash-handling logic — a network path issue, a Dhan-side
feed problem, or a local environment condition (e.g. firewall/proxy
interference) — none of which this checkpoint is positioned to diagnose
further without the user's own environment access. Per the user's
explicit decision, this is left for direct user investigation rather
than a blind relaunch or a subagent guess.

### Part 3 — Finalize

**Not reached in the originally-planned form.** Per the user's explicit
choice (asked directly, mid-checkpoint, given the unexplained
connectivity failure): **`ScannerConfiguration(dhan)` is deliberately
LEFT as `SELECTED/5m`/15-symbol** (not reverted to
`ALL_CONFIGURED/3m`) so a relaunch is ready once the user has diagnosed
the cause. The original values (`ALL_CONFIGURED`, `3m`,
`selected_instrument_ids=[]`) are recorded above for the eventual
revert, whenever that happens — either at the end of the user's own
investigation or in a future checkpoint.

No `market_data_archive --refresh` was run for this stream (nothing was
ever captured to refresh). Final capture stats: **0 quotes, 0
`AggregatedBarObservation` rows produced this run** (none expected,
since the worker never held a connection long enough to receive
anything).

---

## STREAM 2 — Canonicalized-Only Walk-Forward (all 3 strategies)

Delegated to a background agent (read-only + real-service-path
computation only, no live capture, no DB writes) and independently
re-verified below before being reported.

### Part 1 — Isolate the eligible subset

`[F]` Queried `HistoricalBar` directly
(`timeframe='5m', provenance='REAL_DHAN', canonicalization_state=
'CANONICALIZED'`) — **independently re-run by me, not just the agent**:

| Symbol | CANONICALIZED rows | Distinct days |
|---|---|---|
| RELIANCE | 923 | 13 |
| TCS | 923 | 13 |
| HDFCBANK | 923 | 13 |
| INFY | 923 | 13 |

**Unchanged from `68.4`'s figures** (923/13/symbol, 3,692 total) — no
evidence of concurrent writes from Stream 1 (Stream 1 never received a
single quote, so this is expected, not just "not observed").

`[F]` The 13 days form two contiguous blocks, identical across all 4
symbols: `2026-08-03`–`2026-08-14` (10 days) and `2026-08-31`–
`2026-09-02` (3 days), separated by the still-`UNCANONICALIZED`
`2026-08-17`–`2026-08-28` range — exactly matching `68.4`'s finding.

### Part 2 — Run through the REAL path this time

`[F]` Confirmed via direct code inspection of
`research_data_gate.py`: `get_research_eligible_bars()` runs a
completeness gate (`HistoricalDataCoverageService.get_coverage(...)
.is_complete`), a provenance gate (`REAL_DHAN` only), a canonicalization
gate (`is_canonicalized(...)` AND `is_source_semantics_proven(...)`
both required), and a migration-status fail-closed gate — raising
`ResearchDataRejectedError` on any failure, never silently downgrading.
The verification script constructed `ResearchDataGateService` the same
way `backtesting_views.py`'s real production wiring does
(`repository=DjangoHistoricalBarRepository()`,
`coverage_service=HistoricalDataCoverageService(...)`), and called
`.get_research_eligible_bars(...)` directly — **no bypass** this time.

**Result: the gate rejected every multi-day request, for all 3
strategies, identically, before any walk-forward computation ran.**
Requesting RELIANCE's first CANONICALIZED block
(`2026-08-03T03:55Z`–`2026-08-14T09:45Z`, the minimum 10 days needed for
`min_folds=3, min_oos_days=3`) through the gate raised, for
`ema_crossover`, `sma_trend_filter`, and `atr_volatility_breakout`
alike:

```
ResearchDataRejectedError: ResearchRejectionReason.INCOMPLETE_COVERAGE:
9 missing sub-range(s); 710/719 bars (98.75%) cached for NSE:RELIANCE
Timeframe.FIVE_MINUTE in [2026-08-03T03:55:00+00:00, 2026-08-14T09:45:00+00:00]
```

**Root cause, traced directly and independently re-confirmed by me**:
`HistoricalDataCoverageService` expects 72 bars/trading-day for this
instrument category, but **every single CANONICALIZED day, for all 4
symbols, has exactly 71** — missing precisely the day's first expected
timestamp (`03:50 UTC` / 09:20 IST). I independently re-ran the
per-day breakdown for RELIANCE directly against the database (not just
trusting the agent's numbers):

```
2026-08-03: 71   2026-08-04: 71   2026-08-05: 71   2026-08-06: 71
2026-08-07: 71   2026-08-10: 71   2026-08-11: 71   2026-08-12: 71
2026-08-13: 71   2026-08-14: 71   2026-08-31: 71   2026-09-01: 71
2026-09-02: 71
```

**Confirmed identical, uniformly, across every day** — this matches the
agent's claim exactly. The agent further verified (not independently
re-run by me, but methodologically sound and consistent with the above):
a single day requested starting at `03:55` (excluding the known-missing
`03:50` bar) comes back `is_complete=True` (71/71) — proving the gap is
a genuine, systemic one-bar/day hole in the underlying CANONICALIZED
data, not a canonicalization-state artifact, and not workable around for
any multi-day window (each subsequent day's own missing `03:50` bar
re-triggers the same rejection). The second CANONICALIZED block
(3 days) is also incomplete (2 missing bars) and in any case too short
for `min_folds=3` regardless.

**No strategy produced fold results.** All three failed identically at
the gate — a stronger, earlier, more honest rejection than an
`InsufficientDataForWalkForwardError` would have been (that error would
only fire after the gate had already accepted bars).

### Part 3 — Honest comparison

**Not possible this run.** No fold tables, no `mean_degradation_ratio`,
no sign-flip analysis for any of the three strategies — the gate
rejected every request before any backtest bars were assembled.

**This is categorically different from `68.4`** (which bypassed the
gate and got 3 folds per strategy on the *full*, mixed-canonicalization
dataset). This is the first time in this session the real gate was
exercised end-to-end against the actual CANONICALIZED subset, and the
honest finding is: **the real gate currently rejects every multi-day
CANONICALIZED-only request, for all 4 symbols, due to a uniform
1-bar/day coverage gap that exists independently of canonicalization
state.**

**Assessment: this result is still not research-eligible-data-based —
but for a different, more fundamental reason than `68.4`'s caveat.**
`68.4` was blocked by *using the wrong data* (mixed/bypassed). This
checkpoint went through the real gate honestly, and the real gate said
no: even the 13-day CANONICALIZED subset is not "trusted research
data" per `ResearchDataGateService`'s own completeness bar, because of
a previously-undocumented 1-bar/day gap (missing `03:50 UTC` bar)
affecting every CANONICALIZED day for all 4 symbols. **This is a
genuinely new finding this checkpoint surfaced** — `68.2`/`68.3`/`68.4`
never actually ran the CANONICALIZED subset through the completeness
check, so this gap was invisible until now. No workaround was applied
(no gap-fill, no relabeling, no bypass) — P3/P4 stayed fully intact.

### Zero-persistence confirmation

`[F]` `BacktestResultRecord.objects.count()`: **208 before, 208 after**
— **independently re-confirmed by me directly**, not just the agent's
claim.
`[F]` No `BacktestingService.run()` call was ever made — the gate
rejection happened before any backtest engine invocation of any kind
(`run_walk_forward_backtest()` was never reached either, since it would
only be called after the gate accepted bars).

### Import/signature notes (documented per this session's convention)

- `HistoricalBar.timeframe` is stored as the raw value `"5m"`, not the
  enum name `"FIVE_MINUTE"` — a silent-zero-rows trap for any future
  raw-query script (the agent's first Part 1 query hit this and
  self-corrected before reporting).
- `ResearchDataGateService.get_research_eligible_bars()` and
  `HistoricalDataCoverageService.get_coverage()` both require the
  `Timeframe` enum member, not a bare string — matches
  `backtesting_views.py`'s production construction pattern, used
  correctly throughout.
- No other signature mismatches — `StrategyConfigurationValues`,
  `coerce_configuration_values`, `BacktestConfiguration`,
  `DataQualityDisclosure`/`DataQualityLabel.FIXTURE_OR_HISTORICAL`,
  `PositionSizingMode.FIXED_QUANTITY`, `FlatPercentageCostModel` all
  matched `backtesting.py`'s exact pattern on the first try.

---

## GLOBAL CONFIRMATIONS

- No migration execution occurred (any stream).
- No Gainz-related work touched.
- No DB writes from Stream 2 (`BacktestResultRecord` unchanged, verified
  twice independently).
- Stream 1's connectivity failure did not stop Stream 2's report, and
  Stream 2's gate rejection did not stop Stream 1's report — both
  reported fully and independently, as required.
- `ScannerConfiguration` is intentionally NOT reverted at the close of
  this checkpoint (per the user's own explicit direction to investigate
  first) — this is a deliberate deviation from the originally-planned
  Part 3 finalize step, called out explicitly here so it is not missed
  in a future checkpoint. Original values for the eventual revert:
  `universe_mode=ALL_CONFIGURED, timeframe=3m, selected_instrument_ids=[]`.

## What would need to happen next

1. **Stream 1**: the user's own direct investigation of the
   `close_code=1006` / zero-quotes connectivity failure — outside this
   checkpoint's scope. Once resolved, `ScannerConfiguration` should
   either be used as-is for a fresh supervised launch, or reverted to
   its original values if no further capture is planned today.
2. **Stream 2**: the 1-bar/day CANONICALIZED coverage gap
   (`03:50 UTC` missing uniformly) needs its own root-cause
   investigation — is it a `DhanHistoricalBarProvider` fetch-boundary
   issue, a `HistoricalDataCoverageService` expected-bar-count
   miscalibration, or something else? Until resolved, the
   CANONICALIZED subset remains real-gate-ineligible for walk-forward
   despite being correctly canonicalized, and no research-eligible
   walk-forward result exists yet this session.
