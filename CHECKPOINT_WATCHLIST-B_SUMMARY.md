# CHECKPOINT-WATCHLIST-B — Minimal UI (columns, sparkline, mode badge)

Phase B of `WATCHLIST_REDESIGN_ROADMAP.md`, built on
`CHECKPOINT-WATCHLIST-A`'s read-only market-data endpoint. Frontend
only — no backend changes were needed or made.

## What was built

- **`WatchlistPage.tsx`** rewritten — the old comma-separated
  instrument-id string is replaced with a real table per watchlist:
  **Symbol, Price, Change %, Volume, Sparkline, As of**, sourced from
  `GET .../watchlists/<name>/market-data/`. The create/save/delete form
  is unchanged. Each watchlist fetches its own market data
  independently (`WatchlistMarketDataSection`), so one watchlist's
  fetch failure never blocks another's table from rendering.
- **`common/components/Sparkline.tsx`** — new, small, inline-SVG
  component following `EquityChart.tsx`'s own `buildPath()` idiom
  exactly (a simpler, axis-less, single-series variant) — no new
  charting dependency, confirmed against `package.json` before
  building. Rising/falling gets a distinct color class, but that's a
  supplementary cue only — the row's own `change_percent` text already
  carries the same fact in words, matching the app's "color is never
  the sole signal" rule.
- **Mode badge**: reuses `ScreenerPage.tsx`'s own `.badge--historical`
  class verbatim for "Historical mode," and `.badge--active` (already
  used for "Matched" elsewhere) for a new "Live mode" label —
  deliberately the same visual language, not a new one.
- **Honest labeling in the UI**:
  - A `NOT_GATE_VERIFIED` instrument shows a `.badge--pending` "Not
    verified" badge (title = the real `coverage_detail`) in place of
    the sparkline, and every other cell renders a plain `—`, never a
    blank or fabricated value.
  - `volume_basis` is rendered as an explicit inline label
    (`(session-to-date)` / `(full day)`) next to the number — never
    silently conflated, per the roadmap's own explicit rule.
  - A row whose price fell back to the historical close even though
    the page-level envelope is `LIVE` (no fresh quote for that one
    symbol) gets its own small `"last close (no live quote)"` note —
    proven directly in both a Vitest test and the real-browser
    screenshot below.
  - `is_stale` renders a `.badge--pending` "Stale" badge next to the
    as-of label when true.
- **Table conventions reused, not reinvented**: `.table-scroll` +
  `.market-data-monitor__table`, `<th scope="col">`, matching
  `FRONTEND_DATA_TABLES`'s own established pattern — this table is
  legible at the app's existing scale, no new unpaginated-list problem
  introduced.
- New CSS: `.sparkline*` (in `styles.css`, colors sourced from the
  existing `--color-success-border`/`--color-danger-border` tokens,
  already theme-safe across all four themes — no new hex literal
  added), `.watchlist-page__change--positive/negative`,
  `.watchlist-page__cell-muted`, `.watchlist-page__price-note`,
  `.watchlist-page__section*`.

## A real, small gap found and fixed (per the RULES: "stop and report
rather than expanding scope unilaterally" — this one was genuinely
small and directly blocking, so it was fixed in place)

`theme.quality.test.ts`'s own "no component authors a raw `<svg>`
outside the single icon module" gate previously allowlisted only
`EquityChart.tsx` by name. `Sparkline.tsx` is the same kind of
exception (a DATA rendering, not an icon) — the allowlist was extended
to a small, named `DATA_CHART_FILES` list covering both, rather than
weakening the gate itself. No backend change was needed anywhere.

## Testing

- **`WatchlistPage.test.tsx`** (rewritten, 6 tests, all passing):
  gate-verified table renders real price/change/volume/sparkline/as-of
  values; a `NOT_GATE_VERIFIED` instrument is labeled plainly with no
  fabricated values; Historical mode is the correct default with no
  `Live mode` badge present; a `LIVE` envelope shows the Live mode
  badge, the session-to-date volume label, AND the honest
  historical-fallback note on the one row with no live quote; the
  existing save-watchlist and no-free-text-instrument tests are
  unchanged in intent, updated only for the new market-data mock.
- **`Sparkline.test.tsx`** (new, 4 tests): renders a rising trend line
  with the `sparkline--up` class from real close values; a falling
  series gets `sparkline--down`; an empty series renders a plain dash,
  never a fabricated flat line; a single-point series also renders a
  dash (not enough data to draw a trend).
- **Full frontend suite**: `npm run typecheck` clean;
  `npx vitest run` → **380 passed / 380** (36 test files, including the
  extended `theme.quality.test.ts` and unchanged `styles.quality.test.ts`
  gates), zero regressions.
- **Playwright screenshots (both themes)**, real Chromium, network-
  mocked (`watchlist_screenshots.mjs`, scratchpad, not a repo file):
  one watchlist with a gate-verified + a `NOT_GATE_VERIFIED` instrument
  mixed together (Historical mode), and one watchlist in Live mode with
  one instrument on a genuinely live quote and one that honestly fell
  back to its historical close. Verified visually in both Focus
  (light) and Midnight (dark) themes — table, badges, sparklines, and
  every honest-labeling note render correctly and legibly in both.
- **Backend**: confirmed directly, not assumed — no backend file was
  touched this checkpoint (`git status` shows only `frontend/` and the
  two roadmap `.md` files as changes); reran
  `tests/unit/infrastructure/api/test_watchlist_market_data_api.py`
  and `test_watchlist_and_research_status_api.py` directly (14/14
  passing) to confirm no incidental effect.

## RULES compliance

- No backend changes — confirmed directly via `git status` and a
  targeted backend re-run, not assumed.
- No live session launched, no strategy code changes, no registry
  change.
- Reused `ScreenerPage.tsx`'s established mode-badge visual language
  verbatim rather than inventing a new one.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
