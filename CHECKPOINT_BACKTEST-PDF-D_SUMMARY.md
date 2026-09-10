# CHECKPOINT-BACKTEST-PDF-D — Timezone Fix + Header Redesign + Scan-Count Investigation + Backtesting Page UX + Config Viewer Recon

No filename collision — confirmed via `ls` before writing.

## Issue 1 — PDF times now converted to IST

**Root cause confirmed**: `backtest_pdf_report.py` parsed every ISO
timestamp (`Bar`/trade timestamps are always UTC per this project's
own established convention) and rendered it directly, with no
conversion — a genuine presentation-boundary bug, exactly the
operator's own finding.

**Fix**: reused the SAME `Asia/Kolkata` offset this project already
uses at every other presentation boundary (`calendar.py::
INDIA_STANDARD_TIME`, `historical_client.py::_INDIA_STANDARD_TIME`,
the frontend's own `LiveMarketDataMonitor.tsx`/`LiveScannerConsole.tsx`
`toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })` pattern) — not
a new convention. Every rendered timestamp is now converted: Trade
Ledger Entry/Exit Time, the "Generated" line, and the Configuration
date range. A new `_parse_ist()`/`_format_ist_datetime()` pair does
the conversion; `_split_timestamp()` (Trade Ledger rows) now converts
too.

**A real, honest finding along the way, not fixed (out of this
checkpoint's own scope)**: the on-screen Trade Ledger
(`BacktestingWorkbenchPage.tsx:969-970`) was PRESUMED to already show
IST correctly — it does not. It calls bare
`new Date(...).toLocaleString()` with no `timeZone` option, which
renders the VIEWER'S OWN BROWSER-LOCAL time, not necessarily IST. This
is a real, separate, pre-existing frontend gap named here honestly
(not silently glossed over), but left unfixed — this checkpoint's own
scope is the PDF, and a frontend fix would need its own verification
pass. Flagged for the user's own prioritization.

**Verified**: a real UTC→IST conversion test (`04:00:00Z` → `09:30:00`
IST), a Generated/date-range conversion test, and a UTC-calendar-date-
boundary test (`19:15:00Z` → next-day `00:45:00` IST, proving the DATE
converts too, not just the time) — all real `pypdf` text extraction,
not string manipulation.

## Issue 2 — Divider page replaced with a running header banner

The old full per-instrument DIVIDER PAGE (confirmed by the operator:
wasted a whole page for one line of text) is now a running header
BANNER ("Instrument N of M — <symbol>") rendered at the TOP of that
instrument's own first content page (`_build_instrument_story()`'s new
`running_header` parameter) — the combined file stays exactly as
navigable (the banner is still a single-glance visual break, still
carries the instrument's own symbol) without the wasted page.

**Page-count math re-verified honestly, not assumed**: a combined
2-instrument, 1-trade-each file is now **9 pages** (1 index + 4 + 4),
down from PDF-C's own 11 (1 index + 5 + 5, the "5" including the old
divider page). `test_checkpoint_backtest_pdf_a.py`'s own hardcoded `11`
and `test_checkpoint_backtest_pdf_c.py`'s own hardcoded `17` (3-
instrument case) were both updated to the new correct counts (`9` and
`14` respectively) with an explanatory comment — a legitimate
consequence of this checkpoint's own documented change, not a
regression papered over.

## Issue 3 — Investigation: 12 stocks selected, only 2 reports shown

**Read-only investigation, real evidence from this project's own dev
database** (not a guess, not a synthetic test fixture) — queried
`BacktestRun` rows with `total_instruments > 2` directly:

```
44dc088b-... PARTIAL  12 total, 12 completed, 2 result_backtest_ids, 10 failed_instruments
```

**Finding: scenario (a) — a real, expected data-availability limit,
not a bug.** All 12 instruments WERE genuinely attempted
(`completed_instruments == 12`, confirming
`HistoricalBacktestRunOrchestrator.run()` — `historical_backtest_run.py:118-255`
— iterates every `snapshot.instrument_ids`, wrapped in a broad
`except Exception` so one bad instrument never aborts the run). 10
failed for real, honestly-reported reasons, each recorded in
`failed_instruments` with its own exact cause:
- 1 (`NSE:FIXTURE01`): "no verified Dhan security_id... not present in
  the current scrip master" (the deterministic test fixture is not a
  real, tradeable Dhan instrument — expected).
- 9 (`ADANIENSOL`/`ADANIENT`/`ADANIGREEN`/`ADANIPORTS`/`ADANIPOWER`/
  `SBIN`/`HEROMOTOCO`/`TVSMOTOR`/`MARUTI`): `INCOMPLETE_COVERAGE` —
  96.17%/96.67% of bars cached, genuinely missing sub-ranges, and this
  project's own data-integrity policy REJECTS a partial range rather
  than silently gap-filling it ("rejected, never gap-filled" — the
  correct, conservative behavior, not a bug).

**Corroborating evidence**: other real runs in the same table with
FULL coverage (13/13, 6/6 instruments) show `COMPLETED` with **0**
failed_instruments — confirming the mechanism genuinely succeeds when
data is actually complete, and only rejects when it genuinely isn't.

**Already correctly surfaced to the operator, confirmed by reading the
component directly**: `BacktestingWorkbenchPage.tsx:1353-1372` already
renders an `role="alert"` box — "Incomplete data — the following
instruments were skipped:" — listing every `failed_instruments` entry
with its own exact reason, whenever the panel is in the "done" state.
**No code fix made** — none was warranted; this is honest, already-
surfaced, expected behavior, not a defect.

## Issue 4 — Strategy Backtesting page: workflow clarity + grid alignment

**Workflow mechanism traced directly, not assumed**: both "Run
Backtest" (`backtesting_views.py`) and "Prepare Data & Start Backtest"
(`historical_backtest_run.py`) use the exact SAME DB-first coverage/
fetch/persist pipeline before scanning (confirmed by reading both -
`backtesting_views.py`'s own header comment explicitly documents this
unification). The real difference is scope and synchronicity, not data
handling: "Run Backtest" is exactly one instrument, synchronous, result
in the same request; "Prepare Data & Start Backtest" is one-to-many
instruments, an async background job with live progress polling and a
separate report per instrument. **On-page copy rewritten** (both the
Backtest Settings help text and the Historical Data Readiness panel's
own intro paragraph) to state this explicitly, reusing this project's
own existing `.strategy-config-page__help-text` pattern, not a new
style.

**Grid re-audit, confirmed and one real gap fixed**:
- `CHECKPOINT-FRONTEND-8`'s own "Backtest Settings" `.parameter-grid`
  fix is still correctly applied (`BacktestingWorkbenchPage.tsx:339` -
  confirmed by reading the source and by a real rendered screenshot).
- **A real, previously-missed gap found**: the Historical Data
  Readiness panel's own `.historical-run__config` (Start Date/End Date)
  used a fixed `grid-template-columns: 2fr 1fr 1fr` for only TWO
  fields — leaving a dead, permanently-empty third column at every
  viewport width, unlike every other grid on this project (which uses
  the `repeat(auto-fit, minmax(...))` idiom, per
  `FRONTEND_DESIGN_SYSTEM.md`'s own "Density" section). Fixed to
  `repeat(auto-fit, minmax(200px, 1fr))`, and the now-redundant manual
  640px media-query override (the responsive pattern collapses on its
  own) was removed. Verified via a real Playwright screenshot, both
  themes — the two date fields now fill the row evenly with no dead
  space.

## Issue 5 — Recon: Configuration Viewer

**Traced directly, file:line cited, not guessed.** All three tabs
(Risk Configuration/Universe/Strategy Version) are genuinely
functional — real reads AND real writes:
- `RiskConfigurationPanel.tsx` reads persisted `RiskConfiguration`
  versions and can genuinely `activate()` one (a real API POST, a real
  DB write, confirmed re-fetching fresh state from the backend
  afterward - `RiskConfigurationPanel.tsx:89-105`).
- `UniversePanel.tsx`/`StrategyVersionPanel.tsx` are the same
  versioned-record pattern for `UniverseVersion`/`StrategyVersion`.

**The honest, concrete finding**: NONE of these tabs' "active version"
state is consumed anywhere in the live/paper trading pipeline or the
backtest engine:
- `paper_trading_runtime.py:74-82` uses a hard-coded
  `DEFAULT_RISK_LIMITS` constant, with its own comment stating
  explicitly: "Deliberately conservative defaults for a proving-ground
  paper account - not sourced from any operator-configurable settings
  screen yet (a named gap, see PAPER_TRADING_ARCHITECTURE.md)."
  Activating a different Risk Configuration version on this page has
  **zero effect** on paper trading's actual enforced limits.
- Grepped every call site of `StrategyVersionService.get_active()`/
  `UniverseService.get_active()`/`RiskConfigurationService.get_active()`
  across the codebase: each is called ONLY from that same
  feature's own `*_views.py` (the API this page itself reads) — never
  from `historical_backtest_run.py`, `backtesting_views.py`, or any
  live/scanner orchestrator. A backtest's strategy version and
  instrument universe are chosen directly, per-request, on the
  Strategy Backtesting/Scanner pages — never looked up as an "active"
  version from these tables.

**Conclusion, stated precisely rather than as a binary**: this is
neither "complete but underexplained" nor "vestigial" in the usual
sense — it is a genuinely functional, real, audited versioned-
configuration store (a real feature, worth keeping), but its
activation has **no observable effect** anywhere outside itself. This
is exactly the kind of distinction the operator needed and didn't have.

**Fix made (low-risk, text-only, per the RULES)**: rewrote the page's
own subtitle (`ConfigurationViewer.tsx`) to state this precisely:
activating a version here is a real, recorded database write, but does
NOT change what live/paper trading or a backtest actually uses, naming
each real place those ARE actually decided instead. No logic change.

## Testing

- **`tests/unit/infrastructure/api/test_checkpoint_backtest_pdf_d.py`**
  (new, 6 tests): IST conversion (trade times, Generated/date-range,
  a UTC-midnight-crossing case), the running-header page-count math,
  a single-instrument no-running-header check, and one real end-to-end
  HTTP test confirming the fix is wired into the live endpoint.
- `test_checkpoint_backtest_pdf_a.py`/`test_checkpoint_backtest_pdf_c.py`:
  page-count assertions updated (9 and 14 respectively) — a legitimate
  consequence of Issue 2's own documented change, not a regression.
- All PDF test files together: **18/18 passing**
  (`test_checkpoint_backtest_pdf_a/c/d.py` - PDF-B has no PDF-generation
  tests of its own, it tests the frontend button only).
- Frontend: full suite **396/396 passing**, `tsc --noEmit` clean.
- Real Playwright/Chromium screenshots, both themes
  (`frontend/docs/design-audit/backtesting-configure-pdf-d-{light,dark}.png`,
  captured via the new, disposable
  `frontend/scripts/capture-backtest-pdf-d-screenshots.mjs`, same
  network-mocked convention as `capture-design-audit-screenshots.mjs`)
  — confirm the rewritten help text and the fixed date-range grid both
  render correctly and legibly in both themes.
- Full backend suite: `poetry run pytest tests/unit -q` → **5 failed /
  3432 passed** (up from 3426 — exactly the 6 new PDF-D tests) — the
  exact same 5 pre-existing, unrelated failures as every prior
  checkpoint's own baseline; no regression.

## RULES compliance

- Issues 3 and 5 were investigated FIRST, with real evidence (a real
  database query for Issue 3, real file:line source tracing for Issue
  5) before any conclusion was drawn or any code touched.
- Issue 3: no code fix made — the real finding is that the existing
  behavior (attempt all, honestly report per-instrument failures,
  already surfaced on-screen) is correct, not a bug.
- Issue 5: only a low-risk, text-only on-page description was added;
  no logic change, per the RULES' own "propose, or implement if
  clearly low-risk" guidance.
- No strategy code changes, no registry change, no live session
  launched.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
