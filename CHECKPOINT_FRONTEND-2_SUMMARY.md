# CHECKPOINT FRONTEND-2 — Visual/UX Audit with Screenshots

Date: 2026-09-02
Scope: frontend-only visual/UX audit. No production trading/data logic touched. No real Dhan network call. No Django database row created or touched.

## 1. What was captured

All 10 screens named in the directive, in both the "focus" (light) and "midnight" (dark) themes — 20 screenshots total, all captured successfully with no crashed or blank captures:

- `dashboard-{light,dark}.png`
- `market-data-archive-{light,dark}.png`
- `settings-{light,dark}.png`
- `strategies-{light,dark}.png`
- `backtesting-{light,dark}.png`
- `comparison-{light,dark}.png`
- `watchlists-{light,dark}.png`
- `strategy-monitor-{light,dark}.png`
- `paper-trading-{light,dark}.png`
- `reports-{light,dark}.png`

Saved at `frontend/docs/design-audit/*.png` (1440×900 viewport, full-page screenshots — several pages are long, e.g. dashboard renders ~6800px tall).

Several screens (`strategy-monitor`, parts of `watchlists`/`backtesting`) rendered a genuine empty or minimal state because the mocked backend intentionally returns empty lists for endpoints not explicitly given richer fixture data — this is the same "first-time user" state a real, freshly-provisioned backend would show, and is captured as-is per the checkpoint directive rather than invented.

## 2. Auth / mock-data approach used, and why

**Chosen approach: network-layer interception, no real Django server, no Django `User` row created.**

The directive offered two options: (a) create a Django auth `User` in `CONFIGURATION_OPERATOR_GROUP` and log in against a real running `manage.py runserver`, or (b) intercept the auth check at the network layer. Option (b) was chosen because it is strictly safer and simpler for a pure frontend visual task:

- No Django process needs to run at all, so there is no path — accidental or otherwise — to a real `HistoricalBar`/migration table even existing in the loop.
- No database row of any kind (harmless or not) is created, sidestepping any judgment call about "harmless."
- Playwright's `page.route()` can intercept every request to the backend origin (`http://127.0.0.1:8000/**`) and fulfill it locally; the real backend is never contacted, matching the "no Dhan network call, no external network call" prohibition trivially (there is no network call to intercept, Dhan or otherwise).

Only the Vite dev server (`npm run dev`, port 5173) was started. `GET /api/v1/auth/session/` is mocked to return `is_authenticated: true` for a clearly-labelled `design-audit-mock-user`, which is visible in every screenshot ("Signed in as design-audit-mock-user") so nobody could mistake it for a real account.

All other backend endpoints used by the 10 screens are mocked with response shapes copied from the project's own generated OpenAPI contract types (`shared/generated_contracts/api-types.ts`) and, where one already existed, the project's own test fixtures (`src/features/dashboard/dashboardFixtures.ts`). Endpoints without a specific fixture return a well-formed empty array/object rather than an invented "success" payload, so an empty-state screen is only ever a genuine empty state, not a fabricated one.

## 3. Capture tooling

`frontend/scripts/capture-design-audit-screenshots.mjs` — a throwaway Playwright script, not a permanent E2E suite. Adds `playwright` as a new frontend devDependency (`npm install -D playwright`, `npx playwright install chromium` — Chromium binary only, per the directive). Run manually with `npm run dev` already up:

```
node scripts/capture-design-audit-screenshots.mjs
```

It drives one browser, opens a fresh page/context per screenshot (found to be materially more reliable than reusing one page across 20 reloads/navigations, which crashed the renderer under repeated HMR churn during development of the script), sets the theme via the real mechanism (`localStorage["intraday.ui.theme.v1"]`, the same key `src/app/theme/themeStorage.ts` reads — confirmed by reading that file rather than guessing), navigates through the real `App.tsx` navigation buttons, and takes a full-page screenshot.

## 4. Findings

### Category 1 — Quick wins (applied this checkpoint)

1. **`LiveScannerConsole.tsx` inline-style debt (the item FRONTEND-1 explicitly deferred).** Four `style={{ marginLeft: "0.5rem" }}` usages on badge `<span>`s replaced with a new `.badge--inline` CSS class in `src/app/styles.css`, using the existing `--space-2` (`0.5rem`) spacing token rather than a hand-typed value. Applied at:
   - the "Not currently selectable" strategy badge,
   - the notification channel "Configured"/"Not configured" badge,
   - the notification channel "Enabled"/"Disabled" badge,
   - the scanner progress "STALE" badge.

   Confirmed `styles.quality.test.ts`'s "no inline style=" guard now passes (it was the one known-failing check going into this checkpoint) and the file has zero remaining `style={{` usages.

No other changes met the "safe, mechanical, existing-tokens-only, no subjective call" bar strictly enough to apply automatically this checkpoint — everything else below is a written recommendation only, per Part 4 / the STOP instruction.

### Category 2 — Design refinements (recommendation only, not applied)

- **Paper Trading screen has two parallel, overlapping sections.** `paper-trading-light.png`/`-dark.png` show a "Paper Trading Session (Deterministic Replay)" block (with its own "Paper Account" stat group) immediately followed later on the same page by a second, differently-styled "Paper Account" heading with its own stat tiles ("Available Capital (Paper)", "Utilized Margin (Paper)", "Open Positions"), then separate "Paper Orders"/"Paper Positions"/"Paper Trades" headings duplicating "Open Paper Positions"/"Closed Paper Trades" above them. This reads as two components stacked rather than one coherent screen — worth consolidating or at minimum visually separating with a clearer section boundary so a trader scanning the page doesn't have to reconcile two "Paper Account" panels.
- **Reports screen information density.** `reports-light.png` is a very long, single-column stack of card grids (Report Catalogue, Market Data Quality Report, Report Export, Research, Market Data, Trading, Notifications — 7 major sections). Each card is a reasonable size but the page as a whole asks for a lot of scrolling to get an overview; a denser, more scannable layout (e.g. a persistent status-legend or a filter/summary bar at top) would suit a "state of the platform" reference page better than a long scroll.
- **Dashboard screen length/density.** `dashboard-light.png`/`-dark.png` is extremely long (~6800px) with a large "Decision Pipeline"/"Other audited relationships" documentation-style section taking up most of the page below the actual live status cards. The live-status cards (Market Status, Data Provider, Worker Status, System Readiness, Today's Market Data, Archive & Reconciliation, Paper Trading, Research Readiness, Gainz) are all in the first ~1400px and are the part a trader glancing at the dashboard actually needs "at a glance" — the audit/evidence narrative below is valuable documentation but competes with the live-status purpose of a dashboard landing screen. Consider collapsing the evidence/relationship narrative behind a disclosure control, or moving it to a dedicated "Evidence" screen, so the dashboard itself stays a fast, scannable status view.
- **Badge/status-pill color consistency check.** Every screen sampled does use the existing `--color-active-*`/`--color-error-*` (`badge--danger`)/`--color-historical-*` tokens consistently — no screen was found inventing its own ad hoc color for a status pill. This is a positive finding, not an issue, but is worth stating explicitly since it was one of the checklist items: no action needed here.
- **Native form control theming in Settings.** The `Fetch & Save` button, the `Timeframes` fieldset border, and the native `<input type="date">` controls on the Settings screen keep essentially the same visual weight in both themes (the fieldset border in particular is barely visible against the dark background at `theme=midnight`). Worth a pass to confirm every native-control border on this screen resolves to a token with sufficient dark-mode contrast, rather than inheriting only `color-scheme` from the browser.

### Category 3 — Structural suggestions (recommendation only, not implemented)

- **Primary navigation is now 14 buttons (10 audited screens + Configuration, Live Scanner, Live Paper Operations, Market Data) wrapping across three rows** at a 1440px viewport (visible at the top of every screenshot). This was a reasonable "no framework" choice at 3 screens (Checkpoint 22) and is still workable at this size, but a proper sidebar/grouped-navigation pattern (e.g. grouping into Discover/Configure/Backtest/Review sections, collapsible) would scale better as more screens are added and would reduce the header's vertical footprint on every single screen (currently ~250px of every capture is chrome before any page content starts). This is exactly the kind of structural navigation change the directive says to report, not build.
- **Introducing `react-router` (or continuing to explicitly avoid it) is now a decision worth revisiting on its own merits** given 10+ screens and growing — not because the current state-switch pattern is broken (it isn't; every screen renders correctly), but because deep-linking to a specific screen, browser back/forward, and the navigation-crowding issue above would all be natural side benefits. Recommendation only.

## 5. Build/typecheck/test status after the quick-win fix

Ran after the `LiveScannerConsole.tsx`/`styles.css` change, before any screenshot tooling was added (screenshot tooling and scripts do not touch `src/`):

- `npm run build` — clean.
- `npm run typecheck` — clean, no errors.
- `npm test -- --run` — **34 test files, 359 tests, all passed**, including `styles.quality.test.ts` (8/8, the previously-failing inline-style guard now passes).

No regression introduced.

## 6. Screenshot location

`frontend/docs/design-audit/` — 20 PNG files, named `<screen-id>-<light|dark>.png`, committed to `active-development`.

## 7. Commit

Committed to `active-development` (no push, no merge to `main`) — see the commit named in the final summary message for this checkpoint.

## 8. Explicit STOP

Per the directive: only Category 1 (quick wins) was implemented. Categories 2 and 3 above are written recommendations only and wait for explicit review/approval before any further frontend checkpoint acts on them.
