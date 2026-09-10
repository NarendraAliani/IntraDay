# CHECKPOINT-FRONTEND-7 (Live-* Density Audit + Watchlist-Driven Paper Trading)

No filename collision this time — confirmed via `ls` before writing.

## Part 1 — Live-* pages density audit (the honest gap FRONTEND-6 deferred)

Built realistic fixture shapes for all three pages by reusing the
real, already-established fixture patterns from each page's own
`.test.tsx` file (`LiveScannerConsole.test.tsx`,
`LivePaperOperationsConsole.test.tsx`, `LiveMarketDataMonitor.test.tsx`)
— never invented from scratch — and screenshotted all three at 1280px,
both themes.

**Findings, confirmed by rendered screenshot, not source-level
grep alone:**

- **`LiveScannerConsole.tsx` — a genuine, real density gap found and
  fixed.** Three independent, orthogonal fieldsets (`Scan Universe`,
  `Strategies`, `Notification Channels` — none reads another's value)
  stacked full-width, each a boxed panel with a legend/hint/inputs,
  leaving substantial unused width per panel — the same shape
  `CHECKPOINT-FRONTEND-6` fixed on `Settings`. Fixed by wrapping the
  three fieldsets in `.page-summary-grid` (`FRONTEND-6`'s own reusable
  class, reused directly per its own documented guidance — no new
  class invented). `Timeframe` (a single field, not a fieldset) stays
  above the grid, unchanged. `Desired Configuration`/`Effective
  Configuration` were already gridded via the pre-existing
  `.live-scanner__state-grid` — confirmed still correct, untouched.
- **`LivePaperOperationsConsole.tsx` — already fully compliant, no fix
  needed.** Confirmed by screenshot: the 10-item readiness checklist
  already grids 3-up, `Desired`/`Effective Configuration` already sit
  side by side, `Paper Execution Summary`'s 7 KPI tiles and the
  `Telegram`/`Discord` communication summaries already grid correctly.
  This page's own internal grid classes (found via `grep` in
  `FRONTEND-6`, now confirmed by actually rendering them) genuinely do
  handle its density adequately — the source-level note that
  triggered this audit turned out not to indicate a real gap here.
- **`LiveMarketDataMonitor.tsx` — already fully compliant, no fix
  needed.** A different, equally legitimate layout: a narrow sidebar
  filter panel (`Scanning Configuration` — a naturally vertical list
  of filters, the accepted convention for a filter sidebar, not a
  density problem) beside a wide content area whose own 5 status tiles
  already grid correctly. Not a form-panel-with-wasted-space pattern
  at all.

**Verification:** real-browser Playwright screenshots at 1280px (both
themes) and 420px (narrow-viewport collapse, `LiveScannerConsole`
only, since it's the only page changed) confirm the fix and its
graceful collapse to a single column with no manual breakpoint code —
`repeat(auto-fit, minmax(...))`'s own native behavior, matching
`FRONTEND-6`'s established pattern exactly. `LiveScannerConsole.tsx`'s
own 3 existing test files (20 tests total) all pass unchanged — the
DOM content and source order are untouched, only the CSS layout of an
existing wrapper changed. Full frontend suite: `npm run typecheck`
clean, `npx vitest run` → **388 passed / 388**.

## Part 2 — Watchlist-driven paper trading: investigated, confirmed
already working end-to-end

**Direct answer to the checkpoint's own question: yes, this already
works end-to-end — no fix was needed, and none was built.**

Traced the real code, not assumed:

1. **`LiveScannerConsole.tsx`'s own "Watchlist" radio** (confirmed
   directly in the Part 1 screenshot) sets `universeMode="WATCHLIST"`
   and a `selected_watchlist_name`, persisted via the existing
   `ScannerConfiguration` save path — no new UI needed, it already
   exists.
2. **`resolve_scanner_universe()`** (`infrastructure/market_data_
   providers/dhan/scanner_universe.py`) already has a real `WATCHLIST`
   branch: `watchlist_repository.get(config.selected_watchlist_name,
   config.requested_by)` — the SAME `WatchlistRepository` Protocol
   `CHECKPOINT-WATCHLIST-A`/`B` already built on, reused verbatim, no
   parallel mechanism. Already unit-tested directly
   (`test_scanner_universe.py`: `test_watchlist_mode_resolves_the_
   named_watchlists_symbols`, `test_watchlist_mode_with_an_invalid_
   or_missing_watchlist_resolves_to_nothing`).
3. **`run_market_data_worker.py`'s real Dhan-connect path** calls
   `resolve_scanner_universe(desired, watchlist_repository=...)` once,
   at connection/subscribe time, feeding the SAME resolved instrument
   list into `_QuoteSink`'s subscribe messages and downstream
   aggregation — identical code path for every `universe_mode`, no
   WATCHLIST-specific branch anywhere downstream of this resolution.
4. **Multi-strategy fan-out already works, uniformly, for every
   mode.** `_QuoteSink.aggregate_now()` reads `strategy_ids =
   desired.selected_strategy_ids or (self._strategy_id,)` —
   mode-agnostic — then loops `for strategy_id in strategy_ids:
   promote_bars_and_trigger_signals(aggregation, ..., strategy_id=
   strategy_id)`, calling the real, shared, already-tested pipeline
   function once per selected strategy against the SAME aggregated
   bars. No special-casing for `WATCHLIST` mode anywhere in this loop.
5. **Configuration uses each strategy's own real schema defaults**
   (`_configuration_values_for()`, `signal_pipeline_runtime.py`) —
   the exact same mechanism for every universe mode, including
   `WATCHLIST`. **Honest, separately-flagged, NOT a watchlist-specific
   gap** (out of this checkpoint's own scope to fix, and not
   requested): live scanning never uses a named/saved preset
   configuration for ANY mode — only schema defaults, always. This is
   a pre-existing, general limitation unrelated to watchlist parity.
6. **The one real, uniform caveat, already honestly labeled in the
   UI** (confirmed in the Part 1 screenshot's own copy): a universe
   change (including a `WATCHLIST` edit) only takes effect on the
   worker's next Dhan reconnect — Dhan's WebSocket protocol has no
   verified per-instrument unsubscribe. This applies identically to
   `ALL_CONFIGURED`/`SELECTED`/`WATCHLIST` — not a watchlist-specific
   gap, already documented in-page.

### The real, end-to-end test (per the checkpoint's own literal scenario)

`tests/unit/infrastructure/api/test_checkpoint_frontend_7_watchlist_scanning.py`
(new) — composes ONLY real, already-existing, already-tested functions
(`WatchlistService`/`DjangoWatchlistRepository`,
`resolve_scanner_universe()`, `promote_bars_and_trigger_signals()`) in
exactly the shape the real worker's own `_QuoteSink.aggregate_now()`
uses at its real call site — never a duplicate composition invented
for this test alone:

- **`test_watchlist_mode_resolves_the_real_saved_watchlists_own_
  instruments`**: saves a real watchlist via the REAL
  `WatchlistService`/`DjangoWatchlistRepository` (not a fake this
  time), resolves it through `resolve_scanner_universe()` in
  `WATCHLIST` mode, confirms it reaches exactly RELIANCE + TCS.
- **`test_watchlist_driven_scan_evaluates_every_selected_strategy_
  against_every_watchlist_instrument`**: the full scenario — saves a
  watchlist (RELIANCE + TCS), resolves it via real `WATCHLIST` mode,
  selects 2 of the 3 registered strategies (`ema_crossover`,
  `atr_volatility_breakout`), builds one real
  `BarAggregationResult` shared across both strategies (mirroring the
  real worker's own "one scan = one aggregate cycle across every
  desired strategy" shape), runs one scan cycle by calling
  `promote_bars_and_trigger_signals()` once per selected strategy
  (the real per-strategy loop shape), and lets the REAL
  `run_active_loop_tick → PaperSignalExecutionService →
  StrategyExecutionCoordinator → strategy.evaluate()` chain execute
  (not faked — spies on each strategy's own bound `evaluate()` method,
  matching this repo's own established `test_checkpoint_78_real_
  evaluate_receives_non_empty_config_never_a_keyerror` precedent).
  Confirms: both selected strategies' real `evaluate()` were each
  called exactly against RELIANCE and TCS (never a third instrument,
  never fewer than both); the THIRD, unselected strategy
  (`sma_trend_filter`) was never touched; total active-loop
  invocations = 4 (2 strategies × 2 instruments), matching one genuine
  scan cycle.

Both tests pass. **No production code was changed for Part 2** — the
RULES' own explicit instruction ("if Part 2 finds the feature already
fully works, say so plainly — don't manufacture a fix for something
that isn't broken") is followed exactly.

## Testing summary

- **Frontend**: `npm run typecheck` clean; `npx vitest run` → 388/388
  passing (37 files), including `LiveScannerConsole.tsx`'s own 3 test
  files (20 tests) unaffected by the Part 1 layout change. Real-browser
  Playwright screenshots (1280px both themes + 420px) confirm the Part
  1 fix and its narrow-viewport collapse.
- **Backend**: `poetry run pytest tests/unit -q` → **5 failed / 3414
  passed** — the exact same 5 pre-existing, unrelated failures every
  prior checkpoint's own baseline has had
  (`test_checkpoint_64_52_database_first_backtest.py` ×2,
  `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`,
  `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`,
  `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`)
  — 3414 (up from 3412) confirms the 2 new Part 2 tests are counted and
  passing; no regression.

## Files touched

- `frontend/src/features/market-data/LiveScannerConsole.tsx` — Part 1
  grid wrapper (layout only, no behavior change).
- `tests/unit/infrastructure/api/test_checkpoint_frontend_7_watchlist_scanning.py`
  — new, Part 2's own end-to-end proof.

No backend production code changed. No strategy code changes, no
registry change, no live session launched (test-level proof only, per
the RULES).

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
