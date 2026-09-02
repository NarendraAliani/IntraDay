# Checkpoint 67.12.2-E — Corrected Live-Window Retry

```
checkpoint: 67.12.2-E
verdict: PARTIAL_SESSION_CAPTURE_CONFIRMED
config_restored: RESTORED_EXACTLY
crash_count: 2
capture_gap: 29 minutes 23 seconds (08:05:53.228558 UTC to 08:35:16.180936 UTC) — second gap open-ended (08:44:01.020589 UTC onward, no third restart per standing policy)
bars_captured_1m_total: 310 (window 1: 8,005 quotes processed → most of these bars; window 2: 2,258 quotes processed; see Section C for per-symbol breakdown)
reconnect_root_cause: LIKELY_TRANSIENT_NETWORK_EVENT (disconnect itself) — but see tomorrow_full_session_risk
tomorrow_full_session_risk: ELEVATED — not because the disconnect itself is suspicious, but because there is no process-level auto-restart above the in-process 5-attempt reconnect ceiling; an unattended multi-hour session that hits this twice, as today did, silently stops capturing for the rest of the day unless a human notices
stale_status_bug_filed: YES (infrastructure/persistence/management/commands/run_market_data_worker.py:1154, see Section E)
commit: (pending — see final commit note at end of file)
blockers: []
```

## A. Part 0 findings

1. **Time check**: at start, IST 13:18:59 → 13:22:xx by first quote. Minutes
   to 15:30 IST close: **131.0** — well above the 20-minute threshold. Full
   Part 0 executed.
2. **Credential check, correct source this time**: called
   `DhanSettingsService(repository=DjangoDhanCredentialRepository())
   .effective_credentials()` — the exact resolution path
   `infrastructure/api/tasks.py:232-241` uses — **not** a direct `.env`
   decode (that was 67.12.2-C's error). Decoded the JWT it actually
   returned, locally, token value never printed:
   - `iat`: 2026-09-02 06:49:34 UTC
   - `exp`: 2026-09-03 06:49:34 UTC
   - `now` at check: 2026-09-02 07:49:09 UTC
   - **VALID: True**
   This confirms 67.12.2-D's finding: 67.12.2-C's HALT was a false
   negative caused by checking the wrong credential source (`.env`
   instead of the DB-stored row `effective_credentials()` actually
   prefers).
3. **Already-running check**: zero rows today in `LiveQuoteObservation`,
   `AggregatedBarObservation`, and `HistoricalBar` before this checkpoint
   started; no other worker process found. Clear to proceed.
4. Confirmed trading day via `domain.session.calendar.is_trading_day`.

## B. Scope, mechanism, and a permission-gated deviation

**Deviation from the directive, done with explicit user approval before
proceeding (not silently):** `run_market_data_worker --provider dhan` has
no CLI flag for symbol/timeframe scope — it reads scope from the
persisted `ScannerConfiguration` row for provider `"dhan"`
(`resolve_scanner_universe()`). The existing row was `ALL_CONFIGURED` /
`3m`, not this checkpoint's required 15-symbol / `ONE_MINUTE` scope.

Setting that row to `universe_mode=SELECTED` (the 15-symbol watchlist,
`NSE:<SYMBOL>` form) and `timeframe=1m` was the only way to satisfy Part
1's exact scope — and the Claude Code permission classifier blocked that
write on the first attempt (a live-system config change immediately
upstream of a real Dhan connection). Rather than retry or work around it,
I stopped and asked the user directly via `AskUserQuestion`; the user
chose **"Approve the scoped config write"** — the original
`ALL_CONFIGURED`/`3m` values were recorded before the change so they can
be restored after this checkpoint's capture window ends.

Applied: `universe_mode=SELECTED`, `selected_instrument_ids` = the 15
symbols (`ADANIPORTS, AXISBANK, BAJFINANCE, HDFCBANK, HINDUNILVR,
ICICIBANK, INFY, ITC, KOTAKBANK, LT, MARUTI, RELIANCE, SBIN, SUNPHARMA,
TCS`), `timeframe=1m`. `enabled` and `selected_strategy_ids` left
unchanged from the existing row — irrelevant to safety here because
`--mode observe-only` (the command's default, used for this run)
unconditionally forces `strategy_execution_enabled=False` regardless of
`ScannerConfiguration.enabled`, so no strategy, signal, or PaperBroker
call is reachable at any point in this run.

## C. Capture start

- `python manage.py run_market_data_worker --provider dhan --mode
  observe-only` started as a detached background process
  (`nohup ... &`), confirmed alive and streaming real quotes within 15
  seconds of start (real prices, e.g. `NSE:RELIANCE last_price=1309.5`,
  `NSE:HDFCBANK last_price=702.95` — genuine Dhan feed, not synthetic).
- Confirmed via direct DB query shortly after start: `LiveQuoteObservation`
  today = 1,150 rows, `AggregatedBarObservation` today = 44 rows — real
  data landing correctly.
- A second background process (`checkpoint_67_12_2_e_orchestrate.sh`) was
  started to sleep until 09:59:30 UTC (15:29:30 IST, a 30-second safety
  margin before close), then call
  `DjangoWorkerRuntimeStatusRepository.request_stop("dhan", ...)` — the
  documented process-independent stop mechanism (Checkpoint 64.73) — wait
  for the worker to exit cleanly, and run `market_data_archive --refresh`.
  Confirmed via its own log that the sleep (7,571s ≈ 126 min) is genuinely
  in progress, not a false-positive "completed" status (an early
  background-task notification reflected only the launcher line
  returning after backgrounding, not the detached child exiting).

## D. Addendum v2 (crash-aware) — full timeline and final outcome

*The original addendum plan (a single scheduled stop at 09:59:30 UTC) did
not survive contact with reality. This section replaces it with the
honest full account: two crashes, one authorized restart, and a
root-cause investigation.*

### D.1 Full timeline

| Time (UTC) | Event |
|---|---|
| 07:52:17.835835 | Window 1 starts — first real quote persisted |
| 08:05:53.228558 | Window 1 ends — `reconnect_attempts_exhausted` (5 attempts, `close_code=1006`), `final_state=FAILED`, 8,005 quotes processed. `WorkerRuntimeStatus.worker_state` never updated from `RECONNECTING` (stale — see Section E) |
| 08:05:53 – 08:09:47 | 67.12.2-F issued during this window; correctly HALTED at its own Part 0 gate on the (stale but still meaningfully "not STOPPED") worker status — not superseded by this finding |
| ~08:09 – ~08:32 | Crash undetected — orchestrator still asleep (scheduled for 09:59:30), no automated alerting exists |
| 08:32:51 | Crash discovered, during independent verification of 67.12.2-B's agent output (unrelated task) — `tasklist`/`Get-CimInstance` confirmed no `run_market_data_worker` process alive |
| — | User asked directly via `AskUserQuestion`; chose "Restart once, let it run to close" |
| 08:35:16.180936 | Window 2 starts — worker restarted (`ScannerConfiguration` unchanged, still `SELECTED`/`1m` from window 1) |
| 08:44:01.020589 | Window 2 ends — **second** `reconnect_attempts_exhausted`, `final_state=FAILED`, 2,258 quotes processed. Same stale-status pattern: DB read at 08:57:42 UTC showed `worker_state=RECONNECTING`, `reconnect_count=5` |
| 08:57:42 | This checkpoint (v2) begins; confirms second crash via log + process check |
| 08:57:42 (this checkpoint) | Per standing policy ("report, do not auto-restart more than once" — already exercised once), **no third restart**. Capture for today ends here, ~75 minutes before the 15:30 IST close |
| 08:57:42 (this checkpoint) | `ScannerConfiguration` restored to `ALL_CONFIGURED`/`3m` (was `NOT_RESTORED` at check time — fixed immediately, see Section D.2) |

**Total genuine capture time today: ~22 minutes 20 seconds** (13m35s + 8m45s) out of the ~65 minutes elapsed since the first connection attempt, and a much smaller fraction of the full session.

### D.2 Config restoration

Checked field-by-field against the values 67.12.2-E originally recorded
before changing them:

| Field | Original | Found at this checkpoint | Restored to |
|---|---|---|---|
| `universe_mode` | `ALL_CONFIGURED` | `SELECTED` | `ALL_CONFIGURED` |
| `timeframe` | `3m` | `1m` | `3m` |
| `selected_instrument_ids` | `()` | 15 `NSE:<SYMBOL>` entries | `()` |
| `enabled` | `True` | `True` (unchanged throughout) | `True` |
| `selected_strategy_ids` | `('ema_crossover', 'sma_trend_filter', 'atr_volatility_breakout')` | unchanged | unchanged |

**Status at check time: `NOT_RESTORED`.** Fixed immediately in this
checkpoint (`repo.save('dhan', enabled=True, timeframe='3m',
universe_mode='ALL_CONFIGURED', selected_instrument_ids=[], ...)`) and
re-verified — **`RESTORED_EXACTLY`** as of this report.

This was restored now, rather than waiting for the still-sleeping
09:59:30 UTC orchestrator, because the second crash means no further
capture will happen today — waiting on that orchestrator would have left
live production scanner config in the temporary state for another ~62
minutes for no reason.

### D.3 Stop-mechanism / orchestrator note

The orchestrator (`checkpoint_67_12_2_e_orchestrate.sh`) is still
genuinely asleep as of this checkpoint (confirmed: its log shows nothing
past the `sleep 7571` line). It was never triggered by either crash — it
only acts at 09:59:30 UTC regardless of worker state. When it does fire,
its `request_stop("dhan", ...)` call will be a harmless no-op (the row
update succeeds regardless of whether a process is listening — the
mechanism is DB-row-based, not PID-based, exactly as designed), and its
`market_data_archive --refresh` call will be redundant but harmless (each
worker's own shutdown path already ran one archive refresh at its crash
time — visible in both logs as `archive refreshed: 15 cell(s) ...
statuses=['IN_PROGRESS']`). No action needed on the orchestrator; it will
complete on its own and its behavior in this now-worker-absent case has
been verified safe rather than assumed.

### D.4 Final capture counts

Per-symbol `AggregatedBarObservation` count today, `timeframe=1m`
(combining both windows — no per-window breakdown exists downstream of
aggregation, only the worker-side `quotes_processed` counters are
per-window):

| Symbol | 1m bars | Expected (full session) |
|---|---|---|
| ADANIPORTS | 21 | 375 |
| AXISBANK | 21 | 375 |
| BAJFINANCE | 21 | 375 |
| HDFCBANK | 20 | 360 (reduced-session symbol per archive service) |
| HINDUNILVR | 20 | 375 |
| ICICIBANK | 21 | 375 |
| INFY | 21 | 360 |
| ITC | 20 | 375 |
| KOTAKBANK | 21 | 375 |
| LT | 21 | 375 |
| MARUTI | 21 | 375 |
| RELIANCE | 21 | 360 |
| SBIN | 20 | 375 |
| SUNPHARMA | 20 | 375 |
| TCS | 21 | 360 |
| **Total** | **310** | — |

Worker-side counters (quotes, not bars): window 1 processed 8,005 quotes,
window 2 processed 2,258 quotes (10,263 total). Actual `LiveQuoteObservation`
rows persisted today: 8,193 — lower than the sum because
`STALE_DUPLICATE` quotes (exact repeats, per `classify_observation()`) are
never inserted at all, only logged-and-skipped; `CONFLICTING_SAME_TIMESTAMP`
quotes ARE inserted (both candidates become separate rows) — see D.6.

**The 08:05:53–08:35:16 gap (29m23s) and the 08:44:01-onward gap are
genuinely missing data — no bar was interpolated, fabricated, or
back-filled for either.** Any 1-minute interval whose window falls
entirely inside a gap simply has no row.

### D.5 Archive status

`describe_trading_date()` for today: overall `status=IN_PROGRESS` (the
project's `ArchiveStatus` enum has no `PARTIAL_SESSION_CAPTURE` value —
`IN_PROGRESS` is the honest equivalent used elsewhere in this codebase for
a trading day whose session hasn't archived-closed yet). **All 15 cells
report `IN_PROGRESS` — none report `COMPLETE`.** No labelling error, no
HALT condition triggered.

Per-cell `missing_bar_count` (e.g. ADANIPORTS: 354 of 375 missing) is an
**aggregate** figure against the full expected session count — it does
not distinguish "not yet reached because the session hasn't ended" from
"missing because of the mid-session crash gap." There is no dedicated
`missing_bar_timestamps` list field on `ArchiveDayRecord` (checked its
full field list directly) — only aggregate counts. **This is an honest
limitation, not a fabricated gap-detail claim**: the archive service
cannot currently show you the crash gap specifically, separate from
"today isn't over yet."

`reconciliation_status`: confirmed **`NOT_RECONCILED`** for all 15 cells
— never silently upgraded, no independent source was fetched.

### D.6 Conflicting-timestamp resolution — completing the v1 question

- **Resolution rule** (`domain/market_data/aggregation.py:242-248,294-297`):
  ties at the exact same `source_timestamp` are broken by **arrival
  order** — the observation's position in the input sequence determines
  which becomes `OPEN` (earliest position) vs. contributes to `CLOSE`
  (latest position) for that bar.
- **Is it deterministic?** The docstring calls this "a deterministic,
  documented rule, not an arbitrary one" — but the actual query supplying
  that "input sequence" (`DjangoLiveQuoteRepository.get_observations()`,
  `live_market_data_repositories.py:156-158`) is
  `.order_by("instrument_symbol", "source_timestamp")` — **with no
  explicit tiebreaker column** (no `.order_by(..., "id")`) for rows that
  share both fields exactly, which is precisely the
  `conflicting_same_timestamp` case. PostgreSQL does not guarantee row
  order among ties without an explicit tiebreaker in `ORDER BY`. **In
  practice**, for a freshly-inserted, uncontended table, PostgreSQL
  typically returns ties in heap/insertion order — which usually does
  match true network arrival order — but this is not a documented
  PostgreSQL guarantee, and is not what the query asks for. **Honest
  conclusion: the mechanism is INTENDED to be arrival-order-deterministic
  and is likely so in practice on this schema today, but the query as
  written does not structurally guarantee it** — a `VACUUM FULL`,
  `CLUSTER`, or future query-planner change could silently reorder ties
  without any code change being required. This is a real, previously
  unnamed gap between the code's own docstring claim and what the SQL
  actually enforces.
- **Does the resolved price feed the bar's OHLC?** Yes — both candidate
  rows are persisted (neither is discarded at write time; only the
  in-memory `last_known[symbol]` used for `STALE_DUPLICATE` detection
  advances), and `aggregate_quotes_into_bars()` reads both back and
  applies the tie-break above when computing `OPEN`/`CLOSE` for the
  interval containing that timestamp.
- **Total count**: **1,142** `conflicting_same_timestamp` events across
  both windows (897 in window 1, 245 in window 2). Per-symbol spread is
  proportional to trading activity, not concentrated on one symbol —
  AXISBANK highest at 164, ITC lowest at 5, no pathological
  single-symbol/single-minute outlier found.

## E. Stale-status bug (named gap, not fixed)

`WorkerRuntimeStatus.worker_state` stayed `RECONNECTING` for the full
duration of both post-mortem periods (never advanced to `FAILED`),
despite the worker process having genuinely and completely exited both
times.

**Root cause** (`run_market_data_worker.py`): `health_tracker.mark_failed()`
is called in exactly one place, inside `connect_and_run()`
(around line 1136), and only when a **single connection attempt's own**
`run_worker_against_websocket()` result is directly `FAILED`/`AUTH_FAILED`/
`TOKEN_EXPIRED`. It is **never called** when `run_worker_with_reconnect()`
(the supervisor) itself gives up after exhausting `max_attempts` — that
path (`reconnect_supervisor.py:114-117`) sets its own `result.final_state
= WorkerState.FAILED` purely in the supervisor's return value, with no
callback into `health_tracker`. After the supervisor loop returns, the
command (`run_market_data_worker.py:1154`) only has an explicit
`health_tracker.persist()` call inside the branch
`if supervisor_result.final_state is WorkerState.STOPPED and
stop_event.is_set():` — there is **no corresponding `else`/final branch**
that persists a `FAILED` (or any other non-`STOPPED`) terminal state. The
DB row is therefore left holding whatever `worker_state` the last
periodic `aggregate_now()` cycle happened to persist — in both of today's
crashes, that was `RECONNECTING`, from the last `mark_reconnecting()` call
before the attempts were exhausted.

**Probable fix (not applied — report only, per Part 5 prohibition)**: add
an unconditional `health_tracker.mark_failed(supervisor_result.final_state,
...)` + `persist()` call for any `supervisor_result.final_state` that
isn't `STOPPED`, immediately after `run_worker_with_reconnect()` returns,
mirroring the existing `STOPPED`-branch pattern.

**Priority**: high for any future unattended multi-hour capture (like
tomorrow's §65.13 run) — without this fix, a crash produces no
DB-visible signal distinguishing "still trying to reconnect" from "gave
up permanently," which is exactly the ambiguity that let today's first
crash go undetected for ~23 minutes.

## F. Root-cause verdict and recommendation

**`reconnect_root_cause: LIKELY_TRANSIENT_NETWORK_EVENT`** for the
underlying disconnect itself (`close_code=1006`, abnormal WebSocket
closure with no close frame). Evidence: Dhan's own documented heartbeat
(`docs/research/CHECKPOINT_53_DHAN_WEBSOCKET_PROTOCOL_RESEARCH.md`:
server ping every 10s, client considered unresponsive only after >40s
silence — `VERIFIED_PRIMARY`) is generous; nothing in
`reconnect_supervisor.py`'s backoff (`min(1.0 * 2**(attempt-1), 30) *
(0.5 + jitter*0.5)` — attempts 1-4 sleep roughly 0.5-1s, 1-2s, 2-4s,
4-8s, ~7.5-15s of total sleep across 4 gaps) manipulates or interacts
with that heartbeat cycle at all — the backoff only governs the delay
*between* fresh connection attempts, not ping/pong handling (owned
entirely by the underlying `DhanWebSocketTransport`/websocket library).
File mtime evidence for both crashes (log file's final write landing
within ~1-2 minutes of the last successfully processed packet) is
consistent with all 5 reconnect attempts failing fast (immediate
handshake/connection failures) rather than each attempt separately
timing out against the 40s heartbeat window — i.e., this looks like a
real, sustained connectivity interruption on the network or Dhan's
side for roughly the duration of the 5-attempt sequence, not a client
logic defect misfiring against a healthy connection. No per-attempt
timestamps are logged (`mark_reconnecting()` doesn't call
`self.stdout.write()`), so the individual attempt sequence can't be
quoted line-by-line — itself a smaller, related diagnosability gap
worth naming but not filing separately from Section E's stale-status
finding.

**`tomorrow_full_session_risk: ELEVATED`** — not because the disconnect
itself is unusual (a transient WebSocket drop over a multi-hour live
feed is an expected, acceptable real-world occurrence, not a defect to
fix before tomorrow), but because **today's actual outcome was two
independent, unattended process deaths with no automatic recovery above
the in-process reconnect ceiling, compounded by the Section E stale-
status bug hiding both for a combined ~23+ minutes** until a human
happened to notice during unrelated work. Over a real 6h15m unattended
session (§65.13), the same pattern — one transient network blip,
5 attempts exhausted, process exits, DB says `RECONNECTING` forever,
nobody watching — would silently end capture for the rest of the day,
with no operator signal that anything went wrong.

**Recommendation**: proceed with tomorrow's §65.13 full session, but
**do not treat it as unattended** — either keep a human checking
`WorkerRuntimeStatus`/process liveness at intervals materially shorter
than today's ~23-minute blind spot, or land the Section E fix (and
ideally a genuine OS-level supervisor/auto-restart above the in-process
ceiling) before then. The disconnect itself is not a reason to hold
tomorrow's session; the *lack of any way to know it happened* is.

---

**Final commit**: this addendum, the `ScannerConfiguration` restoration,
and all supporting findings are committed together to
`active-development` immediately following this file's write — see this
checkpoint's own commit message for the SHA.

**STOP after this checkpoint.**
