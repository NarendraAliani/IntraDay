# Checkpoint 67.12.2-E — Corrected Live-Window Retry

```
checkpoint: 67.12.2-E
verdict: PARTIAL_SESSION_CAPTURED (capture in progress at time of this write; see Addendum)
part0_credential_check: effective_credentials() exp=2026-09-03 06:49:34 UTC, iat=2026-09-02 06:49:34 UTC, correct source used: YES
part0_time_remaining_at_start: 131.0 minutes
capture_window: 2026-09-02 07:52:xx UTC (~13:22 IST) to ~09:59:30 UTC (~15:29:30 IST, scheduled clean stop)
bars_captured_1m: in progress at write time (44 AggregatedBarObservation rows within first minute; final count in Addendum)
archive_cell_status: PARTIAL_SESSION_CAPTURE (pending final refresh at stop)
commit: (this file; final commit follows stop + archive refresh)
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

## D. Addendum — final outcome (completed after market close)

*This section is filled in once the scheduled stop and archive refresh
have actually run; see the follow-up commit on `active-development` for
final bar counts, `PARTIAL_SESSION_CAPTURE` archive status per symbol,
and restoration of the original `ALL_CONFIGURED`/`3m` scanner
configuration.*

## E. Recommendation for tomorrow's full session

1. Today's corrected check proves the operational fix: always resolve
   Dhan credentials via `effective_credentials()` (DB-first, `.env`
   fallback), never by decoding `.env` directly — that is now the
   standard pre-check for any future live-capture checkpoint.
2. `run_market_data_worker` has no direct CLI symbol/timeframe scoping;
   every future scoped capture will need the same
   `ScannerConfiguration`-row approach used here (and the same
   before/after restore discipline), or a small, explicit CLI addition if
   this becomes a recurring need.
3. Tomorrow remains the correct target for the full §65.13 procedure
   (full session, 15-symbol watchlist, `ONE_MINUTE`), now unblocked by
   today's corrected credential-check finding.

---

**STOP after this checkpoint's capture window ends. No other checkpoint
proceeds today beyond the scheduled clean stop and archive refresh
already in progress.**
