# CHECKPOINT FRONTEND-3 — Summary

Branch: `active-development` (frontend-only). This file now covers TWO
passes under the same `FRONTEND-3` name: the original pass (native
control contrast + dashboard scannability) and a later "Round 2" pass
(app-wide audit extension + strategy-selector toggle). Kept as one
file, in order, rather than one silently overwriting the other.

## Round 1 — Part 1 — Dark-mode native form control contrast (Settings)

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

## Round 1 — Part 2 — Paper Trading's two "Paper Account" sections

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

## Round 1 — Part 3 — Dashboard scannability

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

## Round 1 — Part 4 — Re-verify

- `npm run typecheck` — clean.
- `npm run build` — clean (94 modules, `dist/assets/index-*.css` 49.87 kB,
  `dist/assets/index-*.js` 373.72 kB gzip 99.06 kB).
- `npm test -- --run` — **360 passed** (34 test files), up from the
  359-test baseline by exactly the one new disclosure test added above.
  No regressions.

## Round 1 — Files touched

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

---

## Round 2 — App-Wide Audit + Strategy-Selector Toggle + Quick Wins

Scope: same audit/categorize/quick-win-only discipline as Round 1/
`FRONTEND-2`, extended to the 4 screens no prior screenshot script
covered (Configuration, Market Data, Live Scanner, Live Paper
Operations), plus the operator's one concrete request (strategy-
selector toggle). Read `docs/architecture/FRONTEND_DESIGN_SYSTEM.md`
first. Playwright/network-mocked testing only; no backend/API changes.

`FRONTEND-DATA-TABLES` had already landed before this pass started —
the Compare page and instrument picker were audited in their POST-fix
state (already paginated, already readable-labeled), not re-flagged
here.

### Round 2 — Part 1 — Audit

Extended `frontend/scripts/capture-design-audit-screenshots.mjs` with
`configuration` and `market-data` — the 2 previously-unaudited screens
whose generic mock fallback could render them correctly. **Live
Scanner and Live Paper Operations were deliberately NOT added to this
script** — each already has its own dedicated, more accurately-
fixtured screenshot script (`capture-live-ready-screenshots.mjs`,
`FRONTEND-LIVE-READY`), and this audit reuses those already-committed
screenshots rather than re-capturing them worse. 24 screenshots
re-captured (12 screens × 2 themes) in `frontend/docs/design-audit/`.

`[F]` Found and fixed a real mock bug while extending the script (not
glossed over): the "Market Data" screen (`LiveMarketDataMonitor.tsx`)
threw on load because `/api/v1/config/signals/` and
`/api/v1/config/market-data/instruments/` had no dedicated mock and
fell through to the generic `[]` fallback, which doesn't match either
endpoint's real object-shaped contract. Added both mocks with the real
shape; confirmed zero page errors on re-run.

**State clarity (loading/empty/error)**: every screen sampled handles
empty state honestly (e.g. Configuration: "No risk configuration
versions found for..."; Market Data: "No active signals... Strategies
are actively monitoring the selected universe - no qualifying signal
has been generated" — never a blank gap). No new gap found beyond what
Round 1/`FRONTEND-2` already recorded.

**Information density**:
- **Reports** — still the long, single-column stack of 7 card-grid
  sections `FRONTEND-2` already flagged (Category 2, unchanged,
  re-confirmed present in this pass's fresh screenshot — not
  re-fixed, still awaiting operator review).
- **Market Data (Active Signal Monitor)** — a NEW finding: its
  left-hand "Scanning Configuration" sidebar stacks 6 small filter
  dropdowns (Risk Status / Paper Status / Telegram Status / Discord
  Status / Sort / Rows Per Page), each with only 2-4 real options.
  This looks like the toggle pattern at first glance, but converting
  all 6 to segmented toggles in an already-narrow (~240px) sidebar
  column would very likely increase vertical scroll and reduce
  scannability, not improve it - each toggle needs more horizontal
  room per option than a compact `<select>`. Judgment call → Category
  2, not applied.
- **Dashboard**, **Paper Trading** — Round 1 already addressed the
  dashboard-length finding (collapsible disclosure) and investigated
  the Paper Trading "two panels" finding (found `DIFFERENT_CONCEPTS`,
  a labeling recommendation only). Not re-litigated here.

**Other low-friction-candidate dropdowns found** — grepped every
`<select>` in `frontend/src/features/*/*.tsx` and checked each one's
real option count:

| File | Field | Option count | Verdict |
|---|---|---|---|
| `StrategyConfigurationPage.tsx` | Strategy | 3 (today) | **Fixed this pass** — the operator's explicit request |
| `PaperTradingPage.tsx` | Side | 2 (`BUY`/`SELL`) | **Fixed this pass** |
| `PaperTradingPage.tsx` | Order Type | 4 | **Fixed this pass** |
| `PaperSessionPanel.tsx` | Strategy | 3 (today) | **Fixed this pass** |
| `PaperSessionPanel.tsx` | Timeframe | 5 | **Fixed this pass** |
| `LiveScannerConsole.tsx` | Timeframe | 6 (`TIMEFRAME_OPTIONS`) | Left as a dropdown - exceeds the 5-option threshold, `SegmentedToggle` would auto-fall-back to a `<select>` here anyway, so swapping the component would change nothing visible |
| `LiveMarketDataMonitor.tsx` | Risk/Paper/Telegram/Discord Status, Sort, Rows Per Page | 2-4 each, but 6 filters in a narrow sidebar | Category 2 (see above) - real density trade-off, not a mechanical win |

### Round 2 — Part 2 — Categorized findings

**Category 1 (quick win) — implemented this pass**:
1. Strategy-selector dropdown → segmented toggle
   (`StrategyConfigurationPage.tsx`), the operator's explicit request.
2. `PaperTradingPage.tsx`'s Side and Order Type dropdowns → segmented
   toggles.
3. `PaperSessionPanel.tsx`'s Strategy and Timeframe dropdowns →
   segmented toggles.
4. Fixed the "Market Data" screen's own screenshot-script mock gap
   (found while auditing, not a real app bug — it was the audit
   tooling's fixture that was incomplete, confirmed by checking the
   real endpoint contracts directly).

**Category 2 (design refinement) — documented, NOT implemented**:
- Reports screen information density (`FRONTEND-2`'s own finding,
  re-confirmed still present).
- Paper Trading's two "Paper Account" sections — Round 1's own
  `DIFFERENT_CONCEPTS` finding and labeling recommendation, still open.
- Market Data screen's 6-filter sidebar — real toggle-pattern
  candidates by option count, but converting them risks reducing
  density in an already-narrow column; needs an actual layout redesign
  decision (e.g. a horizontal filter bar above the results instead of
  a vertical sidebar), not a mechanical dropdown swap.
- Native form control theming in Settings — Round 1 already fixed the
  dark-mode contrast gap; not re-verified pixel-by-pixel this pass.

**Category 3 (structural) — not touched**:
- Primary navigation now spans 3 rows / 14 buttons at 1440px
  (`FRONTEND-2`'s own finding - one MORE button since that checkpoint,
  from the 4 screens now in nav; the wrapping issue is unchanged in
  kind, just marginally worse in degree). Still explicitly deferred,
  same as every FRONTEND checkpoint since `FRONTEND-2`.
- `react-router` adoption question — unchanged, still a recommendation
  only.

### Round 2 — Part 3 — Implementation

New shared component: `frontend/src/common/components/SegmentedToggle.tsx`
(~75 lines) — a real `role="radiogroup"`/`role="radio"` control (not a
styled `<div>` with `onClick`s, so keyboard/screen-reader behavior
matches a native radio group), with a `maxSegments` prop (default 5)
that **automatically falls back to a `<select>`** past that count. This
directly answers the checkpoint's own explicit question: "confirm the
component gracefully handles a FUTURE 4th/5th/6th strategy being
registered later" — yes, by construction, no follow-up change needed
when a 4th/5th strategy is registered; only at a 6th does it revert to
a dropdown automatically, and even then correctly (verified by a
dedicated test, see below).

Applied to 4 real call sites: `StrategyConfigurationPage.tsx` (Strategy),
`PaperTradingPage.tsx` (Side, Order Type), `PaperSessionPanel.tsx`
(Strategy, Timeframe). New CSS (`.segmented-toggle`/
`.segmented-toggle__segment[--selected]`) added to `styles.css`, reusing
existing `--color-accent`/`--color-on-accent`/`--color-surface-raised`
tokens - no new colors invented.

4 tests updated (select-based assertions → radio-based) and 2 new
tests added:
- `StrategyConfigurationPage.test.tsx`: confirms the toggle renders as
  a `radiogroup` with correct `aria-checked` states, and confirms the
  **auto-fallback to a dropdown past 5 options** with a 6-strategy
  fixture (proving the future-growth question above, not just
  asserting it in a comment).
- `PaperSessionPanel.test.tsx`: updated the existing "only offers
  strategies the backend registry actually reports" test for the new
  radiogroup markup (scoped via `within()` since the page now has 2
  radiogroups).

### Round 2 — Part 4 — Verification

- `npx tsc --noEmit`: clean, zero errors.
- `npx vitest run`: **34 files, 367 tests passing** (365 prior + 2 new).
- `styles.quality.test.ts`/`theme.quality.test.ts`: both pass (new CSS
  uses only existing tokens, no hardcoded colors).
- Screenshots re-captured and visually confirmed in both themes: the
  Strategy toggle reads clearly with a strong selected-state contrast
  in both `focus` (light) and `midnight` (dark).
- The user's own separately-running `app.bat` dev servers (5173/8000)
  were left untouched throughout — all screenshot testing used an
  isolated port (5198).

### Round 2 — `MEMORY.md` — confirmed updated

Appended (never rewritten), recording the audit extension, the mock-bug
fix, the categorized findings, and the 4 real call sites fixed.

### Round 2 — Governance compliance

- No backend/API change.
- Playwright/network-mocked testing only.
- Only Category 1 items implemented; Categories 2/3 are written
  recommendations, not applied, per the checkpoint's own explicit rule.
- Did not touch the Compare page or instrument picker beyond
  confirming their post-`FRONTEND-DATA-TABLES` state during the audit.
- P11/P16: this summary, `SegmentedToggle.tsx`, the 4 updated feature
  files, their test files, `styles.css`, the extended screenshot
  script, the re-captured screenshots, and `MEMORY.md` committed to
  `active-development` only.

### Note on this file's own history

An earlier tool call in this pass overwrote this file's Round 1
content via a blind `Write` instead of reading it first. Caught before
committing (`git status` showed the file as modified, not new, which
prompted checking `git show HEAD:...` for the pre-existing content) and
corrected by merging both rounds into this one file in order, so
neither round's record is lost.
