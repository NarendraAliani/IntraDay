# CHECKPOINT FRONTEND-3 — Summary

Branch: `active-development` (frontend-only). Scope: Part 1 contrast fix,
Part 2 investigation, Part 3 dashboard scannability, Part 4 re-verify.
Out of scope, untouched: Reports-page density, Category 3 (nav/router).

## Part 1 — Dark-mode native form control contrast (Settings)

**Confirmed via `docs/design-audit/settings-dark.png` (FRONTEND-2's own
capture) before changing anything**: the "Timeframes" fieldset border was
barely visible against the card background, and the "Fetch & Save"
button rendered with unreadable low-contrast text — both because no
component in the codebase applied any styling to plain `<input>`,
`<select>`, `<button>`, or `<fieldset>` elements; they fell back to full
browser UA chrome, which has no knowledge of this app's theme tokens.
`<input type="date">` similarly rendered as stock browser chrome.

**Fix** (token-based, no new colors invented):
- `src/app/styles.css`: added a base rule for
  `input:not([type=checkbox]):not([type=radio]), select, textarea, button`
  using `var(--color-surface)`, `var(--color-text)`, and
  `var(--color-border-strong)`; a global `fieldset`/`legend` rule using
  the same tokens; disabled-button and cursor styling. Any more specific
  class selector elsewhere in the file still wins on specificity, so no
  existing styled control changed.
- `src/app/theme/theme.css`: added `color-scheme: light` to the `focus`
  theme and `color-scheme: dark` to `midnight`/`obsidian`/`aurora`, so
  native chrome (date-picker calendar icon, spinners) also renders
  correctly per theme, in addition to the token-based border/background
  fix (not relying on `color-scheme` alone, per the directive).

**Re-captured and visually confirmed**: `docs/design-audit/settings-dark.png`
was overwritten via a Playwright re-capture reusing FRONTEND-2's mocking
approach (network-layer mocks, real dev server, no backend, no DB writes,
no Dhan call). Looking at the new screenshot: the Timeframes fieldset now
has a clearly visible border, the date inputs render as themed dark
fields with legible white-on-dark text, and "Fetch & Save" is now a
clearly bordered, legible button. `styles.quality.test.ts` and
`theme.quality.test.ts` (20 tests) still pass — no hex/rgba leaked
outside `:root`, every theme still defines the full canonical token set.

## Part 2 — Paper Trading's two "Paper Account" sections

**Read in full**: `src/features/paper-trading/PaperTradingPage.tsx` and
`src/features/paper-trading/PaperSessionPanel.tsx`.

**Finding: `DIFFERENT_CONCEPTS`.**

- The first "Paper Account" lives inside `PaperSessionPanel`'s "Paper
  Trading Session (Deterministic Replay)" block. It is sourced from
  `getPaperSession()` → `GET /api/v1/config/paper-trading/session/`,
  reading `session.account` — fields `starting_capital`,
  `available_capital`, `equity`, `realized_pnl`, `unrealized_pnl`,
  `total_pnl`, `drawdown`. This is the account state of one specific
  deterministic-replay backtest session (start/pause/resume/stop/reset,
  tied to a `replay_date`/`replay_cursor`).
- The second "Paper Account" lives inside `PaperTradingPage` itself
  ("Paper Account" heading, `funds-heading`). It is sourced from
  `getPaperFunds()` → `GET /api/v1/config/paper-trading/funds/` —
  fields `available_balance`, `utilized_margin` — plus
  `getPaperPositions()` for the "Open Positions" count. This is the
  live/operational paper-trading account: real submitted paper orders
  via `submitPaperOrder()`, independent of any replay session.

These are two distinct backend endpoints backing two distinct concepts
(a replay-session's simulated account vs. the platform's standing paper
account used for manually submitted paper orders), not the same data
rendered twice. **No merge was made**, per the directive.

**Recommendation (not implemented — reported for review, since it
changes how financially meaningful information is read):**
- Rename the first section's heading from "Paper Account" to something
  that names what it is, e.g. **"Replay Session Account (Simulated)"**
  or **"Deterministic Replay — Paper Account"**.
- Rename the second section's heading from "Paper Account" to something
  that distinguishes it as the standing/live paper-trading account, e.g.
  **"Live Paper Trading Account"** or **"Standing Paper Account"** — note
  "Live" here must stay unambiguous that it means "currently active
  paper trading," never confusable with real trading, consistent with
  this page's existing PAPER MODE safety language.
- Consider a one-line explanatory sub-caption under each heading (e.g.
  "Tracks only this replay session's simulated fills" vs. "Tracks all
  manually submitted paper orders on this platform") so a user does not
  have to infer the distinction from context.
- This is a copy/labeling change only — no data flow, endpoint, or
  component structure change is implied.

## Part 3 — Dashboard scannability

**Confirmed the boundary** via `docs/design-audit/dashboard-light.png`
and by reading `src/features/dashboard/DashboardPage.tsx`: the
live-status card groups (Market Status, System & Data Health [Data
Provider / Worker Status / System Readiness], Market Data & Archive
[Today's Market Data / Archive & Reconciliation], Simulation & Research
[Paper Trading / Research Readiness / Gainz]) end at line 521, and
`<DecisionPipeline onNavigate={onNavigate} />` (which renders "Market
Data to Outcome" plus "Other audited relationships" plus the status-key
legend) begins immediately after at line 529 — confirmed in the original
screenshot as a ~1400px-tall status view followed by several thousand
more pixels of evidence/narrative content.

**Change**: wrapped `<DecisionPipeline>` in a native
`<details className="dashboard__evidence-disclosure">` /
`<summary>Evidence &amp; Audited Relationships — click to expand</summary>`
element, collapsed by default (no `open` attribute). `src/app/styles.css`
adds matching token-based styling (border, background, a `▸`/`▾`
disclosure-triangle marker driven by the `[open]` attribute selector).
Nothing was deleted: the entire `DecisionPipeline` subtree is still
rendered in the DOM at all times — a `<details>` element hides content
visually via the UA, it does not unmount it — so it remains fully
reachable, keyboard-operable, and present for anyone who expands it or
uses in-page find.

**Behaviorally confirmed, not just read from JSX**:
- `docs/design-audit/dashboard-light.png` and `dashboard-dark.png`
  (re-captured) now show the page ending in a single collapsed
  "▸ Evidence & Audited Relationships — click to expand" row right after
  the Gainz card, in both themes — the live-status cards are now visible
  in well under 1400px, no scrolling through documentation required.
- `docs/design-audit/dashboard-light-evidence-expanded.png` was captured
  via a real Playwright click on the summary element; the screenshot
  confirms the full "Market Data to Outcome" pipeline stages, "Other
  audited relationships" cross-checks, and the "What each status means"
  legend all render exactly as before, just below the now-open
  disclosure.
- A new test was added,
  `DashboardPage — rendering and market/system state > collapses the
  evidence/audited-relationships section by default and expands it on
  click"` (in `src/features/dashboard/DashboardPage.test.tsx`), which
  asserts: the `<details>` has no `open` attribute on initial render; the
  Decision Pipeline's own heading ("Market Data to Outcome") is present
  in the DOM even while collapsed (proving no content deletion); and
  clicking the summary sets the `open` attribute.

## Part 4 — Re-verify

- `npm run typecheck` — clean.
- `npm run build` — clean (94 modules, `dist/assets/index-*.css` 49.87 kB,
  `dist/assets/index-*.js` 373.72 kB gzip 99.06 kB).
- `npm test -- --run` — **360 passed** (34 test files), up from the
  359-test baseline by exactly the one new disclosure test added above.
  No regressions.

## Files touched

- `src/app/styles.css` — native control base tokens, fieldset/legend
  tokens, `.dashboard__evidence-disclosure` styling.
- `src/app/theme/theme.css` — `color-scheme` per theme.
- `src/features/dashboard/DashboardPage.tsx` — `<details>`/`<summary>`
  wrap around `<DecisionPipeline>`.
- `src/features/dashboard/DashboardPage.test.tsx` — new disclosure test.
- `docs/design-audit/settings-dark.png` — re-captured (overwritten).
- `docs/design-audit/dashboard-light.png`,
  `docs/design-audit/dashboard-dark.png` — re-captured (overwritten).
- `docs/design-audit/dashboard-light-evidence-expanded.png` — new,
  behavioral confirmation of the expand interaction.

No production trading/data logic touched. No Dhan network call made
(all screenshots use the same Playwright network-layer mock as
FRONTEND-2, no real backend, no DB writes). Reports page and
navigation/router structure were not touched.
