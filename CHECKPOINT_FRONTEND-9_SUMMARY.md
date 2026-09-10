# CHECKPOINT-FRONTEND-9 — Fix On-Screen IST Bug + Broader Timezone Sweep

No filename collision — confirmed via `ls` before writing.

## Issue 1 — the confirmed bug, fixed

`BacktestingWorkbenchPage.tsx`'s own Trade Ledger called
`new Date(trade.entry_timestamp).toLocaleString()`/
`.toLocaleString()` with **no `timeZone` option** — rendering the
VIEWER'S browser-local time, not IST, for a real trade timestamp.
Fixed with a new `formatIstTimestamp()` helper reusing the EXACT same
`toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })` pattern
`CHECKPOINT-BACKTEST-PDF-D`'s own recon cited as already correct
elsewhere (`LiveMarketDataMonitor.tsx`/`LiveScannerConsole.tsx`) — not
a new convention.

**Confirmed identical to the PDF's own corrected IST times**, both by
real Vitest coverage (see Testing) and by a real Playwright screenshot
in context: the same known conversion (`2026-01-02T04:00:00Z` →
`09:30:00`, `...T04:10:00Z` → `09:40:00`) now renders identically in
both the on-screen Trade Ledger and the downloaded PDF (Trade #
`ema_crossover-1`, `2/1/2026, 9:30:00 am` / `9:40:00 am` — visible in
`docs/design-audit/backtesting-trade-ledger-ist-{light,dark}.png`).

## Issue 2 — broader sweep, same class of bug

Grepped the ENTIRE `frontend/src` for `toLocaleString`,
`toLocaleTimeString`, `toLocaleDateString`, and `new Date(` — not
relying on memory of which files were already checked. Every hit,
categorized honestly:

### Fixed (genuine IST-relevant real moments, same bug class)

| File | What | Fix |
|---|---|---|
| `BacktestingWorkbenchPage.tsx` | Trade Ledger Entry/Exit time | Issue 1, above |
| `dashboardModel.ts::formatTimestamp()` | Market session open/close/square-off, market-data health `last_success_at`/`last_packet_at`/`last_bar_at` (shared, used across `DashboardPage.tsx`) | Bare `toLocaleString()` → `Asia/Kolkata` |
| `ComparisonPage.tsx::formatGeneratedAt()` | A backtest's own `generated_at` | `toLocaleString("en-IN", {dateStyle, timeStyle})` had no `timeZone` → added |
| `StrategyConfigurationPage.tsx` | Saved configuration's `created_at` | Bare `toLocaleString()` → `Asia/Kolkata` |
| `EquityChart.tsx` (`EquityCurveChart`/`DrawdownChart`) | Chart axis-label/tooltip timestamps from real bar data | Bare `toLocaleString()` → `Asia/Kolkata` |
| `StrategyVersionPanel.tsx`/`RiskConfigurationPanel.tsx`/`UniversePanel.tsx` | Each version record's own `created_at` | `toLocaleString("en-IN")` — **"en-IN" alone is a LOCALE, not a timezone**; the same bug class, one degree more subtle. All three fixed to add `timeZone: "Asia/Kolkata"`. |
| `DhanSettingsCard.tsx` | Dhan access-token `Expires at`/`Expired at` | Bare `toLocaleString()` → `Asia/Kolkata` |
| `PaperTradingPage.tsx` | Order `created_at`, trade `closed_at` | `toLocaleString("en-IN")`, same "locale ≠ timezone" gap → `Asia/Kolkata` added |
| `PaperSessionPanel.tsx` | Replay signal `bar_timestamp` | `toLocaleString("en-IN")`, same gap → `Asia/Kolkata` added |

**A real, non-obvious finding surfaced by this sweep**: several of
these (`StrategyVersionPanel.tsx`, `RiskConfigurationPanel.tsx`,
`UniversePanel.tsx`, `PaperTradingPage.tsx`, `PaperSessionPanel.tsx`)
already passed `"en-IN"` as the locale argument — which controls
number/date FORMAT (12-hour clock, DD/MM/YYYY, ₹-style grouping), NOT
the timezone used for the underlying instant. This is the exact same
bug class as the bare-`toLocaleString()` case, just one layer more
subtle (it looks locale-correct at a glance), and would have been
missed by a narrower grep for only bare `toLocaleString()` with zero
arguments — this is why the sweep searched for every
`toLocaleString`/`toLocaleTimeString`/`toLocaleDateString` call and
inspected each one's actual options, not just the ones with no
arguments at all.

### Correctly left alone (genuinely not IST-relevant, or already correct)

| File | What | Why no fix |
|---|---|---|
| `LiveMarketDataMonitor.tsx`/`LiveScannerConsole.tsx`/`LivePaperOperationsConsole.tsx` | Their own `formatTimestamp()` | Already `toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })` — the pattern this whole checkpoint propagates, confirmed still correct, untouched. |
| `BacktestingWorkbenchPage.tsx` `scanned_bars`/`cache_hits`/`cache_misses` | `.toLocaleString()` on plain **numbers** | Thousands-separator formatting, not a timestamp — no timezone concept applies. |
| `PaperSessionPanel.tsx::formatAmount` (`Number(value).toLocaleString("en-IN", {...})`) | Currency (₹) formatting | A number, not a timestamp. |
| `LiveMarketDataMonitor.tsx:902` (`Date.now() - new Date(...).getTime()`) | Elapsed-seconds freshness calc | A duration (milliseconds difference), never rendered as a wall-clock time — no timezone concept applies. |
| `LivePaperOperationsConsole.tsx::workbenchUpdatedAt` | `new Date()` fed into `formatSecondsAgo()` | Purely relative ("N seconds ago") — genuinely locale/timezone-neutral by design. |
| `HistoricalMarketDataCard.tsx`/`ScreenerPage.tsx`/`BacktestingWorkbenchPage.tsx` own `new Date().toISOString().slice(0, 10)` | Default form-field date, `start`/`end` ISO conversion for API payloads | Never rendered to the operator as a formatted timestamp — internal form-state/API-payload plumbing only. |

No case was force-converted to IST where it didn't need one — the
RULES' own "don't over-apply" instruction was checked against each
hit individually, not applied as a blanket sweep.

## Issue 3 — re-check for other small, deferred items

Re-read `MEMORY.md` and every checkpoint summary from
`CHECKPOINT-BACKTEST-PDF-A` through `-D` and `CHECKPOINT-FRONTEND-5`
through `-8` for any other honestly-flagged-but-deferred item.

- **`CHECKPOINT-FRONTEND-6`'s own Category 2 items** (3 named):
  (1) `LiveScannerConsole`/`LivePaperOperationsConsole`/
  `LiveMarketDataMonitor`'s own section-level stacking — **already
  fully resolved in `CHECKPOINT-FRONTEND-7`** (confirmed by reading
  its own summary: one real fix made to `LiveScannerConsole.tsx`, the
  other two confirmed already-compliant by screenshot). Nothing left
  to do.
  (2) `Settings`' individual card internal fields going 2-up — already
  explicitly judged adequately resolved by the section-level grid
  alone in `FRONTEND-6`'s own summary, not a pending item.
  (3) **`PaperSessionPanel`'s own "Replay Session Account" KPI block**
  — still genuinely open, and still correctly deferred: it is a real
  independent-summary candidate by content, but structurally nested
  deep inside one large section (setup form + 3 tables), so grouping
  it properly would require first restructuring `PaperSessionPanel`
  into multiple top-level sections — a genuinely larger, riskier
  change than this checkpoint's own "genuinely small and safe" bar.
  Named again here, left deferred, not touched.
- **`CHECKPOINT-BACKTEST-PDF-C`'s own PDF generation scaling note**
  (async generation for a much larger instrument universe) — an
  explicitly-named FUTURE concern at a scale this project doesn't
  operate at today (its own real universes are 4-6 symbols); correctly
  stays deferred, out of this checkpoint's own frontend-only scope
  regardless.
- **`CHECKPOINT-BACKTEST-PDF-D`'s own flagged item** — the on-screen
  IST bug — is exactly this checkpoint's own Issue 1, now fixed.

No other genuinely small, safe, previously-deferred item was found.

## Testing

- **Vitest, direct (not just visual) proof the fix holds regardless of
  system timezone**: both `BacktestingWorkbenchPage.test.tsx` and
  `dashboardModel.test.ts` gained a new test that sets
  `process.env.TZ = "America/New_York"` for the assertion, then
  confirms the rendered/returned text is still the correct IST
  conversion (`2026-01-02T04:00:00Z` → `09:30`) — if the old bare-
  `toLocaleString()` bug were still present, these tests would render
  a New York time instead and fail.
- **Real Playwright/Chromium screenshots, both themes**
  (`frontend/docs/design-audit/backtesting-trade-ledger-ist-{light,dark}.png`,
  captured via the new, disposable
  `frontend/scripts/capture-frontend-9-screenshots.mjs`, reusing the
  same network-mocked convention as the prior capture scripts) — a
  real backtest run rendered end-to-end shows Trade #1's own Entry/Exit
  as `2/1/2026, 9:30:00 am` / `9:40:00 am`, the correct IST conversion,
  in context, in both themes.
- Full frontend suite: **398/398 passing** (up from 396 — exactly the
  2 new tests), `tsc --noEmit` clean.
- Backend unaffected, confirmed via `git status` — no backend file was
  touched by Issues 1/2 (both are frontend-only, per the RULES).

## RULES compliance

- Only genuine timezone-display bugs were fixed — each of the 9 fixed
  call sites represents a real, IST-relevant moment (a trade, a
  session boundary, a token expiry, a created-at record); every
  correctly-left-alone case (number formatting, elapsed-time/relative
  labels, internal form-state plumbing) was checked individually and
  is documented above with its own reasoning, not silently skipped.
- No backend changes made for Issues 1/2 (confirmed via `git status`).
- No strategy code changes, no registry change, no live session
  launched.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
