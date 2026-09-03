# CHECKPOINT FRONTEND-5 — Complete the Icon Audit (remaining files + final sweep)

Scope: close the two files FRONTEND-4 explicitly flagged as "not yet audited to the
same depth" (`BacktestingWorkbenchPage.tsx`, `HistoricalMarketDataCard.tsx`), fix the
one stray `✕ Not Satisfied` glyph on `ReportsOverviewPage.tsx` that FRONTEND-4 found
but correctly left alone, and do one final whole-`src/` sweep for any remaining raw
status glyphs. No navigation/router change. No new `IconName`. No production
trading/data logic touched. No Dhan network call (screenshot capture uses the
existing Playwright network-mocking script from FRONTEND-2 — no real Django server).

## Part 1 — the two previously-unaudited files

### `frontend/src/features/backtesting/BacktestingWorkbenchPage.tsx` — genuine gap, fixed

Found 9 color-only `badge--ok` / `badge--pending` sites, none of which had an icon
(this file predates FRONTEND-4's `badgeIconName()` helper entirely). All 9 now use
`<Icon name={badgeIconName(...)} />`, reusing the existing helper — no new mapping
logic introduced:

1. `VERIFIED COST MODEL` (`badge--ok`) — cost-model help text
2. `MODEL ASSUMPTION` (`badge--pending`) — cost-model help text
3. `ENGINE VALIDATION: VERIFIED` (`badge--ok`) — `EngineValidationIndicator`
4. Trust level badge (`badge--pending`, dynamic text) — results panel
5. Cost model identity badge (`badge--ok`/`badge--pending`, dynamic) — results panel
6. Data quality badge (`badge--ok`/`badge--pending`, dynamic) — results panel
7. `READY` (`badge--ok`) / `FETCH REQUIRED` (`badge--pending`) — readiness table
8. `DATABASE ONLY` (`badge--ok`) — scan-source stat
9. Historical run status badge (`badge--ok`/`badge--pending`, dynamic) — progress panel

Import added: `badgeIconName` from `common/components/statusIcon`, `Icon` from
`common/icons/Icon` — same imports FRONTEND-4 used elsewhere, no new module.

### `frontend/src/features/settings/HistoricalMarketDataCard.tsx` — already clean

Searched for `badge--`/status-class usage: **none exists in this file.** Its progress
status is rendered as plain `<strong>{progress.status}</strong>` text (no badge
class, no color-only signal to accompany). There was nothing to fix — confirmed by
direct search, not assumed clean.

## Part 2 — Reports page glyph fix (scoped to exactly one change)

`frontend/src/features/reports/ReportsOverviewPage.tsx`: the `NOT_SATISFIED` entry in
`CONDITION_LABEL` used to read `"✕ Not Satisfied"` (a raw Unicode glyph, informally
carrying the "failed condition" meaning inside the same badge that already carries
`badge--danger`). Changed to:

- `CONDITION_LABEL.NOT_SATISFIED` → `"Not Satisfied"` (glyph removed from the string)
- The rendering `<span>` now conditionally prepends `<Icon name="error" />` only when
  `condition.status === "NOT_SATISFIED"`.

**`SATISFIED` (`"✓ Satisfied"`) and `BLOCKED` (`"⊘ Blocked"`) were deliberately left
untouched** — they were not named in the checkpoint directive, and the directive is
explicit that this is the only permitted change on this page. Confirmed via diff that
no other line in this file changed: layout, card structure, and density are
byte-identical apart from the two edits above (label map + one `<span>` body). Reports'
broader redesign remains its own separate, deferred task.

## Part 3 — final whole-`src/` sweep

Searched all of `frontend/src` for `[●◐○✕✓✗✔✖⊘⚠]` (the glyphs named in the directive
plus adjacent lookalikes). Three files matched:

| File | Match | Classification |
|---|---|---|
| `features/reports/ReportsOverviewPage.tsx` | `"✓ Satisfied"` (SATISFIED label) | **INTENTIONALLY NOT FIXED THIS CHECKPOINT** — a genuine status glyph, but explicitly out of scope: the checkpoint directive named only the `✕ Not Satisfied` glyph and prohibited any other change to this page. Left for Reports' own future, deliberate pass. |
| `features/reports/ReportsOverviewPage.tsx` | `"⊘ Blocked"` (BLOCKED label) | **INTENTIONALLY NOT FIXED THIS CHECKPOINT** — same reasoning as above. |
| `features/reports/ReportsOverviewPage.tsx` | `✕` in the new code comment documenting this fix | `INTENTIONALLY_NOT_A_STATUS_ICON` — prose, not rendered UI. |
| `features/correlation/DecisionPipeline.test.tsx:274` | `/[●○✓✗⚠→]/u` inside a `not.toMatch()` assertion | `INTENTIONALLY_NOT_A_STATUS_ICON` — a test regex asserting these glyphs are *absent* from rendered output; not itself a UI glyph. |
| `app/theme/theme.quality.test.ts:156` | `/[●○◐✕✖✓✔⚠⚙]/u` inside a `banned` regex, gated to a fixed list of shell/dashboard/shared-component files | `ALREADY_COVERED` — this is FRONTEND-4/64.80-F2's own existing enforcement test; it already gates the shell, dashboard, and the four shared status components (`ActiveBadge`, `ConnectionStatusBadge`, `CapabilityStatus`, `StatusBadge`/`dashboardModel`) against exactly these glyphs. Its own comment (lines 138–145) honestly records that ~40 further feature-page files were a known, named remaining gap, not silently claimed clean — this checkpoint closes 2 of those (the ones FRONTEND-4 flagged) and reports the rest below. |

**No other match anywhere else in `src/`.** No emoji found (the existing
`theme.quality.test.ts` "no source file anywhere contains emoji" test remains
passing).

**Honest scope note on completeness:** this sweep covers the specific glyph set named
in the directive (`●`, `◐`, `○`, `✕`, `✓`, plus `✗`/`✔`/`✖`/`⊘`/`⚠` as "similar"
lookalikes) across the whole `src/` tree via a single regex grep, which is a
reasonably strong signal but not a semantic proof that zero informal status
indicators of any other kind exist (e.g. a colored dot rendered via CSS `::before`
content, or a differently-coded arrow/checkmark character not in this character
class). I did not find evidence of either of those in this pass, but I did not
exhaustively enumerate every CSS file's `content:` properties, which was outside
what Part 3 asked for (Unicode glyphs used as informal *icons in markup*, not CSS
pseudo-content). Flagging this rather than implying total certainty.

## Part 4 — re-verification

- `npm run typecheck` — clean, no errors.
- `npm run build` — clean (`tsc -b && vite build` succeeded, 95 modules transformed).
- `npm test -- --run` — **34 test files, 360 tests, all passing.** No test asserted
  the old `"✕ Not Satisfied"` text, so no test assertion needed updating (confirmed
  by grep for `"Not Satisfied"` across `*.test.ts(x)` before running — zero matches).
- Screenshots re-captured via `scripts/capture-design-audit-screenshots.mjs`
  (FRONTEND-2's Playwright script, network-layer API mocking only, dev server on
  `:5173`, no real Django/Dhan call) for Reports and Backtesting, both themes
  (`docs/design-audit/reports-{light,dark}.png`,
  `docs/design-audit/backtesting-{light,dark}.png`), viewed directly:
  - **Reports (light/dark):** `Not Satisfied` rows (conditions 3 and 6) now render
    the real `error` icon (red circle-with-slash mark) instead of the raw `✕`
    character; `Satisfied` rows unchanged; card grid, table layout, and density are
    unchanged from before — confirming the fix is genuinely scoped to only that one
    glyph.
  - **Backtesting (light/dark):** the script's default capture only reaches the
    "Discover" list view (it drives the real nav but does not click into
    Configure/Backtest), so the 9 badge icon changes — which live in the
    Configure/Results views and the Historical Data Readiness panel — are not
    visible in these particular screenshots. The Discover view itself is
    pixel-unchanged (as expected: nothing on it was touched). The badge/icon
    rendering in the Configure and Results views is instead confirmed by the 21
    passing `BacktestingWorkbenchPage.test.tsx` tests, including
    "runs a backtest and renders KPIs, charts, data-quality disclosure, and the
    trade ledger" and "polls real backend progress after starting a historical
    run", both of which render through the exact JSX paths that were edited.

## Files changed

- `frontend/src/features/backtesting/BacktestingWorkbenchPage.tsx` — 9 badge sites
  now use `badgeIconName()` + `Icon`.
- `frontend/src/features/reports/ReportsOverviewPage.tsx` — one glyph replaced with
  the real `error` icon, nothing else touched.
- `frontend/src/features/settings/HistoricalMarketDataCard.tsx` — audited, no change
  (no badge classes present).

## Blockers

None.

## What remains explicitly deferred (unchanged from FRONTEND-4)

- Reports page density/layout redesign.
- Reports page's `✓ Satisfied` / `⊘ Blocked` glyphs (only `✕ Not Satisfied` was
  in scope this checkpoint).
- Navigation/router restructuring (Category 3).

Per the checkpoint directive: this closes the icon-consistency thread. No further
icon-audit checkpoint should run until explicitly requested.
