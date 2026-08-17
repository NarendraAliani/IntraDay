# Task Report

## Checkpoint

Checkpoint 62.x — Wiring Readiness Gate + Active Signal Monitor UI.
(Checkpoint 63 was explicitly NOT started, per instruction.)

## Wiring Readiness Result

The signal pipeline built in the immediately preceding sub-task
(`SignalRecord` / `DjangoSignalRepository` / `GET /api/v1/config/signals/`,
committed as `7aa0e19`) was mostly sufficient, but two real gaps were found
and closed while actually wiring the UI against it — not left as cosmetic
front-end-only workarounds:

1. **Missing `timeframe`/`direction` filters.** `list_signals()` only
   supported `strategy_id`/`instrument_id`. The UI's timeframe control had
   no backend filter to bind to. Added `timeframe`/`direction` query
   params end-to-end: `DjangoSignalRepository.list_signals()` →
   `signal_views.list_signals()` → `signalApi.ts`.
2. **Ugly persisted timeframe value.** `_maybe_record_signal()` stored
   `str(signal.timeframe)` → `"Timeframe.ONE_MINUTE"` instead of
   `signal.timeframe.value` → `"1m"`, making the new filter useless for a
   `"1m"`/`"5m"`-style dropdown. Fixed at the `_maybe_record_signal()` call
   site only; `derive_signal_id()`'s own `str()`-based identity hash
   (elsewhere in the same file) was deliberately left untouched, since
   changing it would alter existing signal IDs. Covered by a new test:
   `test_recorded_timeframe_is_the_clean_enum_value_not_its_repr`.

## Signal Pipeline Verified

`test_a_flat_bar_series_with_no_signal_records_nothing` proves the core
QUOTE ≠ SIGNAL invariant: a normal market-data update that produces no
qualifying strategy signal creates zero `SignalRecord` rows. The frontend
table renders only `listSignals()` results — it never reads
`getCurrentQuotes()`/`getRecentBars()` into the primary table; those are
demoted to a collapsed, secondary "Market Data Health" diagnostic section.

## Timeframe / Strategy / Universe Wiring

All three controls are real server-side query parameters, verified by
test, not client-side filters over a pre-fetched array:

- **Timeframe** — `<select>` bound to `listSignals({ timeframe })`.
  Test: `"changing the timeframe control re-requests signals with the new
  timeframe"` asserts the actual outgoing fetch URL contains
  `timeframe=15m` after changing the control.
- **Strategy** — sourced from the real `listStrategies()` registry (only
  `ema_crossover`, `sma_trend_filter`, `atr_volatility_breakout` exist;
  none of the old mock names are used). When exactly one strategy is
  selected, `strategy_id` is sent as a real filter; the API only supports
  a single-value filter, so "all selected" (the default) sends none.
- **Universe** — radio (`All Stocks` / `Selected`) + checklist sourced
  from `getCurrentQuotes()`'s observed instruments (never a hard-coded
  `HDFCBANK/RELIANCE/INFY/TCS` list). Single-selection maps to
  `instrument_id`.

## API Contract

`GET /api/v1/config/signals/` — `page`, `page_size`, `strategy_id`,
`instrument_id`, `timeframe`, `direction`. Regenerated
`shared/generated_contracts/api-types.ts` via `npm run generate:api`
after this session's backend changes; `SignalResponse`/`SignalListResponse`
were already present from the prior sub-task's commit.

### Field honesty classification

| Field | Status |
|---|---|
| strategy_id, instrument_id, direction, price, timeframe, signal_timestamp | REAL AND AVAILABLE |
| risk_status, risk_reason, order_status | REAL AND AVAILABLE |
| Entry price | REAL AND AVAILABLE (= `price`) |
| Stop loss / targets / trailing SL | NOT CURRENTLY AVAILABLE — UI shows "Not available from the current signal contract", never invented |
| Explanation ("why this signal?") | NOT CURRENTLY AVAILABLE — same explicit fallback; details panel is structured (`dl`/`dt`/`dd`) so a future `explanation` field can slot in without a rewrite |

## Frontend Implementation

`frontend/src/features/market-data/LiveMarketDataMonitor.tsx` rewritten
(file path/export retained to avoid touching `App.tsx` routing).
FO-Scanner-style structure: header, sticky sidebar (Scanning
Configuration: timeframe select, universe radio+checklist, strategy
checkboxes, honest "Scan Source" note), main workspace (5 summary cards,
signal table with server-side pagination, signal details panel, collapsed
Market Data Health diagnostics retaining the original Checkpoint 23 UI
verbatim). New `frontend/src/common/api/signalApi.ts` typed wrapper.
~250 lines of new CSS in `frontend/src/app/styles.css`, entirely reusing
existing design tokens (no second design system), with a `900px`
responsive breakpoint collapsing the two-column layout to one.

Zero-signal state shows: "No active signals. Timeframe: 5m. Universe: All
Stocks. Strategies are actively monitoring the selected universe — no
qualifying signal has been generated." — never a market-data row.

No order-placement control exists anywhere on this screen (no Buy/Sell/
Execute button, no quantity input, no submit-order form) — verified by a
dedicated test, not just a design intent.

## Tests Added / Executed

- Backend: 2 new tests in `test_paper_signal_execution_signal_recording.py`
  (now 5 tests in that file); full backend suite: **1225 passed**, 0
  failed (`poetry run pytest -q`).
- Frontend: `LiveMarketDataMonitor.test.tsx` fully rewritten, 8 tests,
  covering: honest empty state, real signal rendering (never a
  market-data row), real strategy names, honest "not available" notes,
  diagnostics collapsed-by-default, no order-placement controls, safe
  error message on load failure, and real (not cosmetic) timeframe
  wiring. Full frontend suite: **102 passed**, 0 failed
  (`npx vitest run`, re-run twice for stability).
- Quality gates: `ruff format --check`, `ruff check`, `mypy` (253 files,
  clean), `lint-imports` (6/6 contracts kept), `manage.py check`,
  `makemigrations --check --dry-run` (no changes), `spectacular
  --fail-on-warn` (clean) — all passing.
- Production build: `npm run build` (`tsc -b && vite build`) succeeds
  cleanly (249 kB JS / 21 kB CSS, gzipped 71 kB / 4 kB).

### Two real test bugs found and fixed while stabilizing (not race conditions)

1. An ambiguity, not a race: `getByText(/All Stocks/i)` matched both the
   sidebar radio label and the empty-state message — `"Found multiple
   elements"`. Fixed by matching the full empty-state sentence in one
   query.
2. A genuine component race: the auto-select-all-strategies effect
   (firing once `listStrategies()` resolves) changes `activeStrategyFilter`,
   which re-triggers `loadSignals`'s effect and reset `signalState` back
   to `{ phase: "loading" }` — unmounting a previously-rendered "Details"
   button mid-interaction under CPU contention (visible only when running
   the full test suite in parallel, not in file isolation). Fixed at the
   root in the component: `loadSignals` now only sets `phase: "loading"`
   on a genuine first load, not on every background refetch triggered by
   a filter change — so a signal already on screen never disappears
   because of an unrelated internal reload.

## Visual Verification

**Not performed as pixel-rendered screenshots** — no browser/screenshot
tool is available in this session. Verification instead relied on: (a)
the component's actual DOM structure asserted by 8 targeted RTL tests
(empty state, populated table, details panel, collapsed/expanded
diagnostics, absence of order controls), (b) a successful `vite build`
confirming no build-time errors, and (c) manual review of the new CSS
against the existing token system and the `900px` responsive breakpoint.
This is a real gap against the user's Phase 18 requirement to inspect
actual rendered states (desktop/tablet/mobile, dark/light, loading/error/
empty, long names, large counts) — disclosed honestly rather than claimed.

## Real / Missing / Deferred Capabilities

- REAL NOW: signal persistence, listing, pagination, timeframe/strategy/
  instrument filtering, risk status, order status.
- MISSING (by honest design, not oversight): stop loss, targets, trailing
  stop, and a structured "why this signal" explanation — none exist in
  the current `Signal` domain contract; inventing them in the UI was
  explicitly forbidden by the user and was not done.
- DEFERRED: true browser-rendered visual verification (no tool available
  this session); signal freshness/staleness indicators beyond the
  existing market-data health section; duplicate-signal suppression UI
  (backend already dedupes via `signal_id`, but the UI does not yet
  surface "this signal was already seen" explicitly beyond showing it
  once).

## Research Findings (brief — full literature review not separately re-run this sub-task)

Carried over from the prior audit: ALREADY IMPLEMENTED — signal identity/
dedup (`derive_signal_id`), server-side pagination, filterable listing.
NEEDED NOW (addressed this sub-task) — real filter wiring, honest empty/
missing-field states. FUTURE ENHANCEMENT — explainability payload,
confidence scoring, alerting/notification hooks, staleness badges on
individual signal rows (today staleness is only shown at the aggregate
market-data-health level).

## Production Risks

- No browser-based visual QA was performed this session (see above) —
  layout bugs at specific breakpoints or in dark mode cannot be ruled out
  from code review alone.
- The single-value-only filter limitation on `strategy_id`/`instrument_id`
  means selecting 2+ (but not all) strategies or instruments currently
  falls back to "no filter" (shows all) rather than an OR-filter — this
  is a real, disclosed limitation of the current API, not a UI bug.

## Performance Ranking

Not separately re-benchmarked this sub-task (no new hot paths were
added — signal filtering is a single indexed Django ORM `.filter()` call
per new parameter).

## Honest Final Conclusion

**IS THE ACTIVE SIGNAL MONITOR NOW WIRED TO REAL SIGNAL DATA?**
**YES.** The primary table renders exclusively from
`GET /api/v1/config/signals/`, backed by `SignalRecord` rows that are
only ever created when `PaperSignalExecutionService.evaluate_and_submit()`
genuinely produces a signal — proven by
`test_a_flat_bar_series_with_no_signal_records_nothing`. Market data
(quotes/bars) is demoted to a collapsed, clearly-labeled secondary
diagnostic section and never feeds the primary table.

**DO THE TIMEFRAME, STOCK UNIVERSE AND STRATEGY CONTROLS ACTUALLY AFFECT
THE SCAN?**
**YES**, with one disclosed limitation. Timeframe always maps to a real
query parameter. Strategy and universe map to real query parameters when
narrowed to exactly one selection; because `list_signals()` only accepts
single-value `strategy_id`/`instrument_id` filters, selecting a subset
larger than one currently has no server-side effect (falls back to
showing all) — this is an honest API limitation, not a cosmetic control,
and is documented above rather than hidden.

Full regression is green (1225 backend + 102 frontend tests), the
production build succeeds, and all quality gates pass. The one
acknowledged gap is browser-rendered visual verification, which this
session's toolset could not perform.
