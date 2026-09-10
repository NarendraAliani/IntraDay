# CHECKPOINT-FRONTEND-8 (Watchlist-as-Universe Global + Final Grid-Density Sweep)

No filename collision — confirmed via `ls` before writing.

No backend changes — confirmed via `git status`. Part 1 calls only the
already-existing `GET /api/v1/config/watchlists/` (`listWatchlists()`)
read endpoint, unchanged.

## Part 1 — "Load from watchlist," added once at the shared component

**Found every real usage of the shared instrument picker** (not
guessed): `InstrumentPickerMulti`/`InstrumentPickerSingle`
(`common/components/InstrumentPicker.tsx`) are imported by 6 real
consumer files — `LiveScannerConsole.tsx`, `PaperTradingPage.tsx`
(single-instrument order entry), `WatchlistPage.tsx` (its own create/
edit form), `ScreenerPage.tsx`, `BacktestingWorkbenchPage.tsx`,
`HistoricalMarketDataCard.tsx`.

**Fixed once, at `InstrumentPickerMulti` only** — a new `WatchlistLoader`
sub-component, reusing the existing `listWatchlists()` read endpoint
(the exact mechanism `CHECKPOINT-WATCHLIST-A/B` already built, no new
backend call). Renders a `<select>` of the operator's own saved
watchlists plus an "Add to selection" button. **Deliberately NOT added
to `InstrumentPickerSingle`** — "load a watchlist's instruments" has no
sensible meaning for a picker that can only ever hold one instrument;
stated explicitly rather than silently omitted.

**Behavior decided and stated explicitly: ADDITIVE, not destructive.**
"Add to selection" unions the chosen watchlist's own `instrument_ids`
into the picker's CURRENT selection (a `Set`, so an already-selected
instrument is a no-op, never duplicated) — an operator can combine a
saved watchlist with a few extra manual picks in the same session, and
loading a watchlist never silently discards picks already made. This
is the correct default for a "load" convenience on a MULTI-select
picker (a destructive replace would be surprising and would make
combining watchlists impossible).

**Confirmed correct on every real consumer** (not just the component in
isolation): all 6 non-test consumer files' own existing test suites
(59 tests total across `WatchlistPage.test.tsx`,
`BacktestingWorkbenchPage.test.tsx`, `ScreenerPage.test.tsx`,
`HistoricalMarketDataCard.test.tsx`, `LiveScannerConsole.test.tsx`,
`PaperTradingPage.test.tsx`) pass unchanged after the shared-component
change, and real-browser Playwright screenshots (both themes) of
`BacktestingWorkbenchPage` and `WatchlistPage` confirm the control
renders and reads correctly in context, not only in the component's
own isolated test.

One pre-existing test needed a small, honest fix (not a production
bug): `WatchlistPage.test.tsx`'s own `getByText(/core/)` became
genuinely ambiguous once the shared picker's new watchlist dropdown
also renders "core" as an option — narrowed to
`getByRole("heading", { name: "core", level: 2 })`, which is what the
test actually meant to assert.

**New tests** (`InstrumentPicker.test.tsx`, 4 new — 16 total in that
file): offers saved watchlists and adds a chosen one's instruments;
additive behavior proven directly (an already-selected instrument
survives a watchlist load, no duplicate); no control shown when the
operator has no saved watchlists (never an empty/broken dropdown);
degrades honestly when the watchlists list fails to load (the rest of
the picker still works).

## Part 2 — Final, global grid-density sweep

### The operator's own named miss: `Backtesting`'s "Backtest Settings"

Confirmed by direct read, then by screenshot: `BacktestingWorkbenchPage.tsx`
hand-authors its own `<fieldset><legend>Backtest Settings</legend>`
with 8 `.strategy-config-page__field` divs (Timeframe/Start/End/
Initial Capital/Position Size Model/Quantity/Cost Model/Slippage) —
the EXACT single-column shape `CHECKPOINT-FRONTEND-6` fixed inside
`ParameterSchemaFields.tsx`, but hand-authored directly in this page
rather than routed through that shared component, so `FRONTEND-6`'s
fix never reached it. Fixed by wrapping those 8 fields in
`.parameter-grid` (the exact same reused class, not a new one). The
Universe field (`InstrumentPickerMulti` — wide, complex content with
its own search/checklist/pagination) stays OUTSIDE the grid, above
it, for the same reason `HistoricalMarketDataCard` stays outside
`Settings`' own grid.

### Genuinely exhaustive final sweep

Cross-checked the full nav (15 screens including Dashboard) against
`FRONTEND-6`'s and `FRONTEND-7`'s own audited-page lists to find the
gap, then screenshotted or directly read every remaining page:

- **`ConfigurationViewer`** — NOT a density gap: confirmed by reading
  the component, it is a WAI-ARIA tabbed interface (one narrow lookup
  panel visible at a time), not three stacked panels. Also confirmed
  by real-browser screenshot this checkpoint (crashed on generic mocks
  in `FRONTEND-6`/`-7`; built the real fixture shapes this time and it
  renders cleanly).
- **`ComparisonPage`** — screenshotted (crashed previously, fixed this
  time with a real `listBacktestResults` mock): two small, sequential
  selects (Strategy, then Sort by), genuinely compact, no real
  wasted-width problem.
- **`StrategyMonitorPage`** — a plain `<table>` (per-strategy status
  rows) — correctly excluded by the same "tables stay full-width"
  rule `FRONTEND-6` already established.
- Every other screen (`Dashboard`, `Screener`, `Reports`, `Market Data
  Archive`, `Watchlists`, the three Live-* pages, `Settings`, `Strategy
  Configuration`, `Paper Trading`) was already screenshotted and
  categorized by `FRONTEND-6`/`FRONTEND-7` — re-confirmed as still
  correct, not re-audited from scratch.

**No further Category 1 fixes found beyond `Backtesting`'s own
Backtest Settings panel and Part 1's watchlist-loader control** — the
sweep is complete for this checkpoint's own scope.

### Documentation strengthened (Part 2.3)

Extended `FRONTEND_DESIGN_SYSTEM.md`'s own "Density" section with:
the `CHECKPOINT-FRONTEND-7`/`-8` additions (what was fixed, and why
`ConfigurationViewer`/`ComparisonPage`/`StrategyMonitorPage` are
correctly NOT gridded); and a new, explicit subsection weighing
whether the `.parameter-grid`/`.page-summary-grid` pattern should
become a structurally-enforced wrapper COMPONENT rather than a CSS-
class convention.

**Considered and deliberately NOT built**, reasoning stated plainly:
this project's own established architecture is intentionally plain,
token-driven CSS with no component library (`FRONTEND_DESIGN_SYSTEM.md`'s
own pre-existing "CSS architecture" section). A wrapper component
whose only job is applying a CSS class would be the first
layout-only component in this codebase — every existing shared
component (`ParameterSchemaFields`, `InstrumentPicker`,
`CapabilityStatus`) exists because it carries real behavior, never
merely to wrap children in a styled `<div>`. The genuine, durable
enforcement point for STRATEGY PARAMETER panels specifically is
already architectural and was already true before this checkpoint:
`ParameterSchemaFields.tsx` is the one shared renderer every strategy
panel goes through, so a new strategy gets `.parameter-grid`
automatically with zero risk of a future author forgetting it. For
the OTHER case — a page's own hand-authored settings/summary panel,
where no such shared component exists to enforce anything
structurally — a clear, discoverable written rule (this document's
own "Density" section) is the correct, proportionate tool; a
component wrapper would not have prevented `Backtesting`'s own miss
this checkpoint fixed (a hand-authored fieldset, not a shared
component's fault) any more than the CSS-class rule would have, since
both require an author to apply them somewhere.

## Testing summary

- **Frontend**: `npm run typecheck` clean; `npx vitest run` → **392
  passed / 392** (37 files, up from 388 — the 4 new
  `InstrumentPicker.test.tsx` watchlist-loader tests). Real-browser
  Playwright screenshots (1280px both themes + 420px narrow check)
  confirm the Part 1 watchlist-loader control on `BacktestingWorkbenchPage`
  and `WatchlistPage`, and the Part 2 `Backtest Settings` grid fix, all
  collapsing cleanly to a single column at 420px with no manual
  breakpoint code.
- **Backend**: no backend file touched (confirmed via `git status`);
  targeted re-run of `test_watchlist_and_research_status_api.py`
  (7/7 passing) confirms the reused `listWatchlists()` endpoint is
  unaffected.

## Files touched

- `frontend/src/common/components/InstrumentPicker.tsx` — the shared
  "Load from watchlist" control.
- `frontend/src/common/components/InstrumentPicker.test.tsx` — 4 new
  tests.
- `frontend/src/features/backtesting/BacktestingWorkbenchPage.tsx` —
  Backtest Settings grid fix.
- `frontend/src/features/backtesting/WatchlistPage.test.tsx` — one
  test assertion narrowed (genuine new ambiguity, not a bug).
- `docs/architecture/FRONTEND_DESIGN_SYSTEM.md` — Part 2 findings and
  the component-vs-CSS-convention reasoning.

No backend production code changed. No strategy code changes, no
registry change, no live session launched.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
