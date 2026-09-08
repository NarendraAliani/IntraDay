# FRONTEND-DATA-TABLES — Summary

Scope: two concrete, screenshot-confirmed usability problems — the
shared instrument picker and the Compare (Strategy Comparison) page.
Read `docs/architecture/FRONTEND_DESIGN_SYSTEM.md` first, per
established discipline. No backend/API changes; Playwright/
network-mocked testing only.

## Part 1 — Scope confirmed directly, not assumed

- **Instrument picker**: genuinely ONE shared component,
  `frontend/src/common/components/InstrumentPicker.tsx`
  (`InstrumentPickerMulti`/`InstrumentPickerSingle`), reused verbatim
  by 4 real call sites: `LiveScannerConsole.tsx`, `PaperTradingPage.tsx`,
  `HistoricalMarketDataCard.tsx`, and `WatchlistPage.tsx`. One fix
  covers all 4. The flat-checkbox problem is specific to
  `InstrumentPickerMulti` (the checkbox variant) — `InstrumentPickerSingle`
  uses a native `<select>`, which browsers already handle natively at
  scale, so it was left untouched.
- **Compare page**: `frontend/src/features/backtesting/ComparisonPage.tsx`.
- **Real row counts, checked directly** (`[F]`): `BacktestResultRecord.objects.count()`
  = **208 total**, grouped by strategy: `ema_crossover` **139**,
  `atr_volatility_breakout` 34, `sma_trend_filter` 27,
  `gainz_compatible_research` 8. Confirms the "100+" figure for at
  least one strategy in the Compare page's own dropdown. The
  instrument list's ~8,558 figure is taken as given from the
  screenshot review (re-deriving it would require a live Dhan call,
  prohibited by P6 in a read/fix checkpoint).
- **Existing pattern found and reused**: `BacktestingWorkbenchPage.tsx`'s
  `TradeTable` already implements client-side pagination (filter →
  slice → Previous/Next + "Page X of Y"). No virtualization library or
  general-purpose table framework existed or was needed — extracted
  the SAME idiom into one small shared component
  (`frontend/src/common/components/Pagination.tsx`, ~45 lines: a
  `<Pagination>` control plus a `paginate()` slicing helper) instead of
  inventing a second pattern or over-engineering a data-grid.

## Part 2 — Instrument picker fixed

`InstrumentPickerMulti` now paginates its checklist at **100/page**
(the picker's own data is already fully fetched client-side; 100/page
avoids rendering all ~8,558 checkboxes at once while keeping each page
substantial). Search and exchange filtering both reset to page 1.
"Select All" is unchanged in behavior — it still selects every
FILTERED instrument across all pages, not just the visible page — and
now says so explicitly ("Select All still applies to all N, not just
this page") so pagination never makes the button look narrower than it
is. Applied once, in the shared component — all 4 call sites benefit
identically, confirmed by the existing `InstrumentPicker.test.tsx`
suite still passing plus 2 new tests proving the paginated count and
the cross-page "Select All" behavior.

## Part 3 — Compare page fixed

- **Pagination**: the raw results list (not just the post-selection
  comparison table) is now paginated at 20/page, matching the
  established idiom.
- **Sort**: a new "Sort list by" control (Newest first / Oldest first /
  Instrument / Timeframe) orders the raw list before selection —
  distinct from the existing "Sort comparison table by" (renamed for
  clarity) which still orders the selected-results comparison table by
  metric. All fields used (`generated_at`, `configuration.instrument_id`,
  `configuration.timeframe`) are already present in the existing API
  response (`to_json_dict()`, `research/backtesting/serialization.py`)
  — no new backend field.
- **Readable label**: each result now shows
  `<instrument> · <timeframe> · <generated date/time>` as the primary
  label, with the backtest ID (first 12 chars) and configuration
  version as secondary, monospace, smaller text — the full ID is still
  available via a `title` tooltip. The raw hash is no longer the
  primary identifier.
- **Grouping by strategy**: considered, not implemented — the results
  list is already scoped to exactly one strategy at a time via the
  existing "Strategy" dropdown (`listBacktestResults(selectedStrategyId)`
  is called per-strategy), so the flat list never actually mixes
  strategies together in the first place. Adding a second grouping
  layer inside an already-single-strategy list would add complexity
  without a real problem to solve.

## Part 4 — Verification

- **Screenshots**: `frontend/scripts/capture-data-tables-screenshots.mjs`
  (same throwaway-script pattern as prior FRONTEND checkpoints),
  4 screenshots in `frontend/docs/design-audit/data-tables/` (both
  themes): the Live Scanner instrument picker showing 150 fixture
  instruments paginated at 100/page ("150 matches", "Page 1 of 2"),
  and the Compare page showing 45 fixture results paginated at 20/page
  ("45 results", "Page 1 of 3") with readable labels. **A real mock bug
  was found and fixed while building the capture script itself** (not
  glossed over): the fixture instruments used `symbol`/`company_name`
  instead of the real `InstrumentSummary` contract's `display_name`,
  which made the picker's own `.localeCompare()` sort throw — caught
  silently by the component's existing try/catch and shown as "Unable
  to load the instrument list." Root-caused directly (not worked
  around) by comparing against the real generated contract type.
- **Full suite**: `npx vitest run` — **34 files, 365 tests passing**
  (361 prior + 4 new: 2 pagination tests in `InstrumentPicker.test.tsx`,
  2 in `ComparisonPage.test.tsx`), including `styles.quality.test.ts`/
  `theme.quality.test.ts` gates.
- `npm run typecheck`: clean, zero errors.
- The user's own separately-running `app.bat` dev servers (port
  5173/8000) were left running throughout — all screenshot testing used
  an isolated port (5199) started and stopped by this checkpoint only.

## `MEMORY.md` — confirmed updated

Appended (never rewritten), recording the scope confirmation, the
shared `Pagination` component, both fixes, and verification results.

## Governance compliance

- No backend/API change — every field used was already returned by
  existing endpoints.
- Playwright/network-mocked testing only; no real backend/Dhan
  dependency.
- Scope held to exactly the two named components plus the one new
  shared `Pagination.tsx` helper both needed — no navigation, Reports
  layout, or other deferred item touched.
- P11/P16: this summary, the CSS/component changes, the new
  `Pagination.tsx`, the screenshot script and its output, and
  `MEMORY.md` committed to `active-development` only.
