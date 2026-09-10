# CHECKPOINT-FRONTEND-6 (Screen-Density Audit + Grid-Layout Fixes + Design Rule)

**Naming note, flagged explicitly (this repo's third such collision)**:
`CHECKPOINT_FRONTEND-6_SUMMARY.md` already exists at the repo root from
an **earlier, unrelated** checkpoint (a glyph-guarantee/icon-migration
durability sweep). This checkpoint's own directive reused the
identifier "CHECKPOINT-FRONTEND-6" for a different topic. Per the
standing "check before writing to any file that might already exist"
discipline (which this checkpoint's own directive explicitly
anticipated - "this repo has had filename collisions before"), the
existing file was **not overwritten**; this summary is written to
`CHECKPOINT_FRONTEND-6_DENSITY-AUDIT_SUMMARY.md` instead.

No backend changes. Every field/value/validation behavior unchanged -
layout only.

## Part 1 — Audit findings (screenshots at 1280px, both named pages
confirmed directly)

- **`Strategy Configuration`'s Parameters panel** — confirmed exactly
  as the operator reported: ATR Volatility Breakout's 7 parameters
  rendered in one long column, roughly half the panel's own width
  left empty.
- **`Paper Trading`** — confirmed two genuinely independent,
  similarly-shaped summary sections (`Kill Switch`, `Live Paper
  Trading Account`) stacked full-width one after another, exactly the
  pattern named.
- **`Settings`** — a THIRD instance of the same pattern, found beyond
  the two named pages: the Dhan/Telegram/Discord connection-status
  cards (each holding only 2 narrow fields) stacked full-width in
  `.settings-page__cards`, leaving most of each card's own width
  empty.
- **Pages already compliant, confirmed by screenshot** — `Dashboard`
  (`.dashboard__grid`), `Backtesting` (its own 3-column strategy-card
  grid), `Reports` (its own `Report Catalogue` grid), `Screener` (a
  rule-builder row, not a form panel — appropriately compact).
- **Pages NOT verified by screenshot this checkpoint** — `Live
  Scanner`, `Live Paper Operations Console`, `Live Market Data
  Monitor`, `Comparison`, `Configuration Viewer` all require page-
  specific fixture shapes beyond a generic mock (each crashed against
  a generic mock with a real `TypeError`, not a layout problem) —
  reproducing their exact response contracts was judged disproportionate
  to this checkpoint's effort budget. **Source-level confirmation
  only**: `grep` confirms all three Live-* pages already use SOME grid
  class internally (`.live-paper-console__check-grid`,
  `.signal-monitor__details-grid`, `.live-scanner__state-grid`), but
  whether their SECTION-level stacking (10-12 `<section>`s each) could
  also benefit from `.page-summary-grid` was **not verified visually**
  — stated honestly as a gap, not silently skipped. A future checkpoint
  with the bandwidth to build the fuller live-market-data mock fixture
  set should audit these three specifically.
- **Watchlists** — already redesigned in `CHECKPOINT-WATCHLIST-B`
  (its own table-based layout is not a single-column form panel; not
  re-audited here).

## Part 2 — Categorization

### Category 1 (quick win — implemented)

1. `ParameterSchemaFields.tsx`'s own field list → `.parameter-grid`
   (`repeat(auto-fit, minmax(240px, 1fr))`). Applies to **both**
   consumers (`Strategy Configuration` and the `Backtest Workbench`)
   and **every** strategy (current 3, and any future one), since it's
   a property of the one shared renderer, not a per-strategy fix.
2. `PaperTradingPage.tsx`'s `Kill Switch` + `Live Paper Trading
   Account` sections → wrapped in `.page-summary-grid`
   (`repeat(auto-fit, minmax(320px, 1fr))`).
3. `SettingsPage.tsx`'s Dhan/Telegram/Discord connection cards →
   also wrapped in `.page-summary-grid` — a genuine Part-1 finding
   beyond the two named pages, fixed with the exact same safe,
   low-risk pattern.

### Category 2 (genuine improvement, deferred with a precise
description)

- **`PaperSessionPanel`'s own "Replay Session Account" KPI block** —
  a real independent-summary candidate by CONTENT (the operator's own
  third named example), but structurally it is a subsection (an
  `<h3>`) nested deep inside one much larger `<section>` (session
  setup form + 3 tables + controls), not its own top-level page
  section. Grouping it with `Paper Trading`'s Kill Switch/Live Paper
  Trading Account sections would require first restructuring
  `PaperSessionPanel` into multiple top-level `<section>`s — a larger
  change than this checkpoint's safe-quick-win bar. Documented here,
  and in `FRONTEND_DESIGN_SYSTEM.md`'s own new rule section, as a
  precise, named, deferred item for operator review.
- **`Settings`' individual card internal fields** (e.g. Client ID +
  Access Token within one Dhan card) could additionally go 2-up WITHIN
  each card — checked visually after the section-level grid fix (see
  Part 5's screenshot) and judged already adequately resolved by the
  section-level grid alone (each card is now ~400px wide instead of
  ~1050px, and 2 narrow fields read comfortably in a single column at
  that width) — not implemented as a separate change, but named here
  in case a future reviewer disagrees once real credential values are
  present.
- **Live Scanner / Live Paper Operations Console / Live Market Data
  Monitor's own section-level stacking** (10–12 sections each) — not
  visually audited this checkpoint (see Part 1's honest gap above);
  deferred pending a proper fixture build for these pages' own
  endpoints.

### Category 3 (structural/risky — correctly excluded, not merely
deferred)

- Paper Orders / Positions / Trades / Signals tables, and the
  Screener's own results table — genuinely sequential, table-heavy
  content; explicitly named as an EXEMPTION in the new design rule
  (`FRONTEND_DESIGN_SYSTEM.md`), not a gap to fix later.
- `Submit Paper Order` and the Screener's own rule-builder section —
  primary action forms, not passive summary panels; excluded by the
  same rule's own reasoning (a form section is not squeezed beside an
  unrelated section, even though its own fields already use
  `.form-grid` internally).

## Part 3 — Implementation details

- `ParameterSchemaFields.tsx`: the bare `<>...</>` fragment wrapping
  each parameter's field div is now `<div className="parameter-grid">`.
  Source order — and therefore tab order and screen-reader reading
  order — is **completely unchanged**; this is a CSS-only reflow
  (`display: grid`, not a DOM reorder).
- `.parameter-grid > .strategy-config-page__field { margin-bottom:
  var(--space-4); }` — a SCOPED override (not a change to the global
  `.strategy-config-page__field` rule, which `WatchlistPage.tsx` also
  reuses for its own, ungridded "Watchlist name" field) so the
  existing per-field bottom margin isn't doubled by the grid's own
  `gap`.
- `.page-summary-grid` (new, general-purpose, `app/styles.css`) —
  reused verbatim by both `PaperTradingPage.tsx` and
  `SettingsPage.tsx`, rather than each page inventing its own grid
  wrapper class.
- `HistoricalMarketDataCard` deliberately stays OUTSIDE
  `SettingsPage.tsx`'s new grid — it is a different kind of content
  (a multi-instrument/timeframe fetch tool), not a peer "connection
  status" card; putting a much taller card into an `auto-fit` grid row
  with three short cards would have looked wrong (grid rows
  align-stretch by default).
- No breakpoint/media query needed anywhere — `repeat(auto-fit,
  minmax(...))` collapses to one column automatically once the
  container narrows below `2 × minmax-floor`, verified directly at a
  420px viewport for both fixes (see Part 5).

## Part 4 — The design rule, documented durably

New section **"Density: responsive grid by default (Checkpoint
FRONTEND-6)"** added to `docs/architecture/FRONTEND_DESIGN_SYSTEM.md`,
placed before "Deferred / explicitly out of scope" so it's discoverable
alongside every other standing convention. States the rule explicitly,
gives the exact CSS pattern for both `.parameter-grid` and
`.page-summary-grid`, names where each is implemented, and — just as
important — names what is deliberately NOT gridded and why (tables,
primary action forms, `HistoricalMarketDataCard`, and the deferred
`PaperSessionPanel` case), so a future checkpoint building a new
strategy's parameter panel or a new page follows the rule without
rediscovering this reasoning, and without over-applying it to content
that genuinely needs to stay single-column.

## Part 5 — Verification

- **Playwright screenshots (1280px)**, network-mocked, confirmed
  visually: `Strategy Configuration`'s 7 ATR parameters now flow into
  a 3-column grid filling the panel's own width; `Settings`' three
  connection cards now sit 2-up (Dhan/Telegram top row, Discord below)
  with `Historical Market Data` correctly staying full-width below;
  `Paper Trading`'s Kill Switch and Live Paper Trading Account now sit
  side by side.
- **Playwright screenshots (420px, narrow-viewport check)**: both
  fixes collapse cleanly to a single column with zero manual
  breakpoint code — `auto-fit`/`minmax()`'s own native behavior.
- **Full frontend suite**: `npm run typecheck` clean twice (before and
  after implementation); `npx vitest run` → **388 passed / 388** (37
  test files) on a clean rerun. One transient failure
  (`AppDashboardNavigation.test.tsx`, 2 tests) appeared on a single run
  amid the full suite and was confirmed NOT a regression: it passed
  standalone (5/5) and passed again on a full clean rerun (388/388) —
  pre-existing test-order flakiness, not caused by this checkpoint's
  CSS-only changes (no test in that file touches any file this
  checkpoint modified).
- **Backend**: no backend file touched — confirmed directly via `git
  status`, not assumed; no backend suite re-run needed.

## RULES compliance

- No backend changes — confirmed via `git status`.
- Every existing field/value/validation behavior unchanged — layout-
  only change, proven by source-order-unchanged reasoning above and
  the unaffected full test suite.
- Part 1 findings beyond the two named pages (`Settings`) were found,
  reported, AND fixed (Category 1, same safe pattern); findings judged
  too large for this checkpoint (Live-* pages' section-level stacking,
  `PaperSessionPanel`'s own Replay Session Account) are reported
  honestly rather than silently skipped.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
