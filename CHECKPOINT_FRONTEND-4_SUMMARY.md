# CHECKPOINT FRONTEND-4 — Summary

Branch: `active-development`. This file covers TWO passes under the
same `FRONTEND-4` name: Round 1 (paper-account labeling fix + icon
audit for color-only status) and Round 2 (Reports density + navigation
restructuring). Kept as one file, in order, rather than one silently
overwriting the other — same discipline established for
`CHECKPOINT_FRONTEND-3_SUMMARY.md`.

---

## Round 1 — Paper-Account Labeling Fix + Icon Audit for Color-Only Status

Frontend-only. No backend, no navigation/router, no Reports-page
change (explicitly out of scope for this round). Continuation of
`FRONTEND-3`'s accessibility thread (contrast fix, disclosure
control) — this round's thread is "no status conveyed by color alone."

### Round 1 — Part 1 — Paper-Account labeling fix (implemented)

Applied `FRONTEND-3`'s own approved recommendation, copy-only, no data
flow / endpoint / component-structure change:

- `src/features/paper-trading/PaperSessionPanel.tsx`: heading renamed
  `Paper Account` → **"Replay Session Account (Simulated)"**, with a new
  sub-caption: *"Tracks only this replay session's simulated fills — not
  the standing Live Paper Trading account used elsewhere in the app."*
  (reads `session.account` from `GET /api/v1/config/paper-trading/session/`).
- `src/features/paper-trading/PaperTradingPage.tsx`: heading renamed
  `Paper Account` → **"Live Paper Trading Account"**, with a new
  sub-caption: *"Tracks all manually submitted paper orders on this
  platform — a standing account, distinct from any single replay
  session's simulated account. Still paper only: no order here ever
  reaches a real exchange."* (reads the separate `PaperFundsResponse` /
  `getPaperFunds()` fetch).
- Both sub-captions reuse the existing `signal-monitor__hint` CSS class
  (no new class invented; `paper-trading__hint` does not exist in
  `styles.css`, so the established hint style was reused instead).
- Confirmed no change to any API call, response type, or component tree
  shape — `git diff` on both files is text/JSX-only.
- Visually confirmed via re-captured screenshots (see Part 5): both
  headings and captions are legible in both Focus (light) and Midnight
  (dark) theme, and remain visually distinct from each other.

### Round 1 — Part 2 — Icon system audit

#### 2.1 `src/common/icons/Icon.tsx` — full `IconName` set (19 names, unchanged)

`dashboard`, `market`, `archive`, `paper-trading`, `research`,
`system-health`, `settings`, `security`, `gainz`, `refresh`, `warning`,
`success`, `error`, `info`, `navigation`, `theme`, `check`,
`chevron-down`, `signal`.

One closed grammar: 24×24 viewBox, stroke-only, `currentColor`, 1.5
stroke width, round caps/joins, no fills, no npm dependency (hand-authored
inline SVG, documented rationale in the file's own header comment).
Decorative by default (`aria-hidden`), promotable to `role="img"` via a
`label` prop.

#### 2.2 Where `<Icon>` is already used (before this checkpoint)

Nav/section headers across `DashboardPage.tsx` (all fully icon-paired,
including every `StatusBadge`/`TONE_ICON_NAME` status site — this page
was already done in a prior checkpoint, Phase 8/17), the three shared
status components below, and scattered action-button icons
(`View Market Data`, `Open Paper Trading`, etc.) — all decorative pairings
with adjacent text, not status-color pairings.

#### 2.3 Shared status components — already had an icon slot, already used it

`ActiveBadge.tsx`, `ConnectionStatusBadge.tsx`, `CapabilityStatus.tsx` all
already render `<Icon name={...}/>` next to their badge text (added in
Checkpoint 64.80-F2 Phase 8, predating this checkpoint). **No gap found
here** — these were confirmed, not fixed.

#### 2.4 Color-only status sites found (no icon, color/class carried extra
meaning beyond the text already shown, or a raw Unicode glyph stood in
for a real icon) — the actual gaps this checkpoint closed:

| File | Site | Before |
|---|---|---|
| `LiveMarketDataMonitor.tsx` | `WorkerStatusCard` watchdog badge (HEALTHY/DEGRADED/STALE/DISCONNECTED/FAILED) | class only |
| `LiveMarketDataMonitor.tsx` | `renderChannelBadge` / communication-history table channel badges | class only |
| `LiveMarketDataMonitor.tsx` | Live Paper Readiness badge | Unicode `●`/no real icon |
| `LiveMarketDataMonitor.tsx` | `HEALTH_ICONS` (Connection Health badge, ×2 render sites) | raw Unicode glyphs (`●`/`◐`/`○`/`✕`) — a second, competing icon system |
| `LiveMarketDataMonitor.tsx` | `DataQualityBanner` SAMPLE_BAR badge | Unicode `◐` |
| `LiveMarketDataMonitor.tsx` | Signal table `direction` (BULLISH/BEARISH) and `risk_status` (APPROVED/REJECTED) badges | class only |
| `LiveMarketDataMonitor.tsx` | Quote `is_stale` / bar `status` badges | Unicode `●`/`◐` |
| `LivePaperOperationsConsole.tsx` | Readiness-checklist item badges (`CHECK_STATE_CLASS`) | class only |
| `LivePaperOperationsConsole.tsx` | Session-state badge + timeline "current step" marker | class only / no marker at all |
| `LivePaperOperationsConsole.tsx` | Live Paper Readiness badge | Unicode `●` |
| `LivePaperOperationsConsole.tsx` | Scanner-progress status badge, drift badge, STALE badge | class only |
| `LiveScannerConsole.tsx` | Effective-configuration status badge (EFFECTIVE/APPLYING/DEGRADED/STOPPED) | class only |
| `LiveScannerConsole.tsx` | Notification-channel `configured`/`enabled` inline badges | class only |
| `LiveScannerConsole.tsx` | Readiness badge (READY TO SCAN / NOT READY) | Unicode `●` |
| `DhanSettingsCard.tsx` | `TokenStateBadge` (VALID/EXPIRING_SOON/EXPIRED/…) | class only, **no icon at all** |
| `PaperSessionPanel.tsx` | Session `STATUS_BADGE` (RUNNING/PAUSED/STOPPED/…) | class only |
| `PaperSessionPanel.tsx` / `PaperTradingPage.tsx` | "PAPER TRADING — NOT LIVE" / "PAPER MODE" banners | Unicode `◐` |
| `PaperTradingPage.tsx` | Paper-order table status badge | class only |
| `StrategyMonitorPage.tsx` | Research status badge (RESEARCH_ACTIVE/PAUSED/DISABLED) | class only |

**Explicitly left untouched (out of scope / not a genuine gap):**
- `ReportsOverviewPage.tsx` — Reports page is prohibited from any change
  this round (still had its own `✕ Not Satisfied` Unicode glyph;
  flagged for a future checkpoint — closed by Round 2 below, though
  Round 2's own scope was layout/density, not this glyph specifically;
  see Round 2's Part 3).
- `LivePaperOperationsConsole.tsx` safety-strip badges ("Execution Mode:
  PAPER" / "Real Trading: DISABLED" / "Broker Execution: PAPER ONLY") —
  the file's own existing comment states these are deliberately
  text-only-by-design safety labels, not a status badge in the audited
  sense; left as-is rather than second-guessing a documented decision.
- `InstrumentPicker.tsx` static warning badges ("INDEX SELECTION
  UNAVAILABLE", "OBSERVED INSTRUMENTS ONLY") — single fixed banners, not
  part of a varying status set; borderline, but adding an icon here would
  be closer to decoration than fixing a color-only ambiguity, so left
  alone under the no-decorative-stuffing prohibition.
- `BacktestingWorkbenchPage.tsx` `badge--ok`/`badge--pending` sites,
  `HistoricalMarketDataCard.tsx` static badges — outside the checkpoint's
  named priority areas (worker/session health, readiness checklists,
  Settings/Strategy/Watchlist generic badges); not touched to keep the
  diff scoped to what was asked. **Honestly flagged as an area not yet
  audited to the same depth**, not confirmed clean.

### Round 1 — Part 3 — Gap check before adding anything new

Every color-only site above maps cleanly onto an **existing** `IconName`:
`success` (active/ready/healthy/valid/approved/bullish), `warning`
(pending/degraded/stale/drift/expiring), `error` (danger/failed/blocked/
expired/rejected/bearish), `info` (historical/neutral/not-configured/no
attempt), `check` (timeline "current step" marker), `paper-trading`
(paper-mode banners). **No new `IconName` was added** — the existing 19
covered every genuine gap found.

A new small helper, `src/common/components/statusIcon.ts`
(`badgeIconName(badgeClass) → IconName`), was added purely to keep the
`badge--active → success` / `badge--danger → error` / `badge--pending →
warning` / `badge--historical → info` mapping in ONE place instead of
re-deriving it per file — this is refactor scaffolding, not a new icon.

### Round 1 — Part 4 — Applied

All sites in the table above now render `<Icon name={...}/>` immediately
before the badge/status text, reusing `badgeIconName()` wherever the
badge class is already the source of truth, or an inline ternary where
the underlying boolean/enum was clearer than re-deriving the class
mapping (e.g. `signal.direction === "BULLISH" ? "success" : "error"`).
Raw Unicode glyphs (`●`/`◐`/`○`/`✕`) that were substituting for icons
were replaced by the real closed icon system rather than left standing
next to the new SVGs as a second, inconsistent icon language.

Confidence note, honestly stated: most of these sites already carried
the status in a visible text word (e.g. "READY", "STALE", "RUNNING") —
so strictly speaking color was never the *only* signal. The icon pairing
here follows the project's own established convention (`ActiveBadge`
etc. do this even with text present) for faster at-a-glance scanning
under time pressure, per this checkpoint's stated rationale — not because
each site was independently unreadable without it. The handful of sites
that had literally nothing but color (`TokenStateBadge` before this
checkpoint, the timeline "current step" highlight) are the ones with the
strongest, least-arguable case.

### Round 1 — Part 5 — Verification

- `npm run typecheck` — clean (`tsc --noEmit`, no errors).
- `npm run build` — clean (`tsc -b && vite build`, 95 modules, no
  warnings beyond normal bundle-size report).
- `npm test -- --run` — **360/360 passed**, 34 test files. Six tests in
  `LiveMarketDataMonitor.test.tsx` and `LiveScannerConsole*.test.tsx`
  initially failed because they asserted the literal Unicode-glyph text
  (`"● READY"`, `"● BLOCKED"`, `"● READY TO SCAN"`, `"● NOT READY"`) that
  this checkpoint replaced with a real `<Icon>` + plain text — updated
  those assertions to the new plain-text content (`"READY"`, `"BLOCKED"`,
  `"READY TO SCAN"`, `"NOT READY"`); no other test needed changes,
  confirming the icon additions are additive to markup rather than a
  breaking rewrite.
- Re-captured Dashboard, Settings, and Paper Trading (both themes) with
  `scripts/capture-design-audit-screenshots.mjs` (same network-mocked
  Playwright approach FRONTEND-2 built — dev server on :5173, no real
  Django server, no DB writes, no Dhan call). Actually viewed all six
  images:
  - **Paper Trading** (light + dark): both new headings — "Replay
    Session Account (Simulated)" and "Live Paper Trading Account" — and
    their sub-captions render legibly, visually distinct sections, in
    both themes.
  - **Dashboard** (light + dark): all `StatusBadge` sites (Market
    Status, Worker Status, System Readiness, Today's Market Data,
    Research Readiness, Gainz) already show icon + text + color
    together — confirms this page's prior-checkpoint work is intact and
    unbroken by this checkpoint's changes.
  - **Settings** (light + dark): Dhan `Token status` badge now shows a
    paired error icon (red circle-X) instead of a bare color chip;
    layout/contrast unaffected in either theme.

### Round 1 — Commit

Committed to `active-development`. No push, no merge to `main`.

---

## Round 2 — Reports Density + Navigation Restructuring

Scope: the two Category 2/3 items deferred since `FRONTEND-2`/`3`
(Reports page density, 14-button nav wrapping), now explicitly
authorized. Read `docs/architecture/FRONTEND_DESIGN_SYSTEM.md` first.
Playwright/network-mocked testing only; no backend/API changes.

### Round 2 — Part 1 — Audit

Re-captured all 12 generic-mock screens fresh (`frontend/scripts/
capture-design-audit-screenshots.mjs`, both themes, 24 images) —
confirmed the nav had grown to 14 items across 3 wrapped rows since
`FRONTEND-2` first flagged it (Live Paper Operations, Strategy
Monitor, and others added since).

### Round 2 — Part 2 — Navigation restructuring (implemented)

**Grouped into 5 top-level entries**: Dashboard (standalone, the
landing screen) + 4 dropdown groups —

- **Live Operations**: Live Scanner, Live Paper Operations, Market Data
- **Research**: Strategies, Backtesting, Compare, Watchlists
- **System Setup**: Configuration, Settings, Strategy Monitor
- **Trading Record**: Paper Trading, Reports, Market Data Archive

(Adjusted the user's own suggested "Configuration" group label to
"System Setup" — see the real collision this avoided, below.)

**Implementation**: reused the SAME native `<details>`/`<summary>`
disclosure idiom the Dashboard's own evidence section (`FRONTEND-3`)
already established, rather than building a new dropdown/menu
component — `frontend/src/app/App.tsx`'s `NAV_GROUPS` array, rendered
as one `<details className="nav-group">` per group inside the
existing `<nav aria-label="Primary">`. The group containing the
currently active screen auto-opens (`open={containsActive ||
undefined}`) so the operator always sees where they are. Every
existing `Screen` id, route, and button label is unchanged — this is
purely a rendering/grouping change.

**Two real bugs found and fixed while verifying with a real browser
(Playwright), neither caught by the jsdom-based unit test suite**:

1. **Naming collision**: the user's own suggested "Configuration"
   group label collided with the "Configuration" screen's own item
   inside it — both exposed as `role="group"`/`role="button"`-
   adjacent elements sharing one accessible name in Chromium. Fixed
   by renaming the group to "System Setup" (the screen's own label is
   untouched).
2. **`<details>` is `role="group"`, not `role="button"`** — Chromium
   folds the `<summary>` text into the GROUP's own accessible name; a
   closed `<details>`'s content is also excluded from the
   accessibility tree entirely (not merely visually hidden). Neither
   fact is obvious from the DOM alone, and jsdom's `getByRole`/click
   handling in `@testing-library/react` does not enforce either
   behavior, so the existing unit tests (below) never caught it — only
   driving a real browser did. This governs how any future Playwright/
   e2e navigation script must locate a group (open by its own visible
   text, not by role or by searching for an item inside it before
   opening).

**Confirmed no existing test broke** — `App.test.tsx` and
`AppDashboardNavigation.test.tsx` (the two files with real nav-button
clicks, including one that iterates `Dashboard`/`Market Data`/`Market
Data Archive`/`Paper Trading`/`Backtesting` and asserts each is inside
`nav[aria-label="Primary"]`) **both pass unmodified** — jsdom doesn't
enforce visibility on `fireEvent.click`, so a button inside a closed
`<details>` remains clickable and DOM-contained in that test
environment, and the grouped structure is transparent to those
assertions. **Keyboard operability confirmed directly** (not assumed):
`Tab` from the Dashboard button lands on the first group's `<summary>`,
and `Enter` toggles it open — native, no custom key handling needed.

### Round 2 — Part 3 — Reports page density (implemented)

**Wrapped every major section in a collapsible `<details>`** (same
established idiom, `ReportSection` helper component in
`ReportsOverviewPage.tsx`) instead of building a new ARIA tabs pattern
— `FRONTEND_DESIGN_SYSTEM.md`'s own Deferred list already named Tabs
as "not yet needed," so reusing the disclosure pattern already proven
elsewhere in this app is the lower-risk option the checkpoint asked
for. **Report Catalogue** and **Market Data Quality Report** (the two
sections an operator most likely opens Reports FOR) stay **open by
default**; **Report Export**, **Research**, **Market Data**,
**Trading**, and **Notifications** start collapsed. Every existing
badge, table, and piece of content is unchanged and fully present in
the DOM — only whether each section is expanded by default changed.
Visually: the page now shows 2 open sections + 5 one-line collapsed
headers at rest, instead of one continuous scroll of 7 full sections.

### Round 2 — Part 4 — Categorized, not implemented

Nothing new surfaced that warranted deferral beyond what was already
authorized — both threads stayed within their described, low-risk
scope. No Category 2/3 items to report from this round.

### Round 2 — Part 5 — Verification

- `npx tsc --noEmit`: clean.
- `npx vitest run`: **34 files, 367 tests passing** — zero test files
  needed updating for either restructuring (confirmed both bugs above
  via direct, hand-written Playwright reproduction scripts, not via
  the unit suite, which structurally cannot see them).
- `styles.quality.test.ts`/`theme.quality.test.ts`: both pass (new CSS
  for `.nav-group`/`.reports-overview__section` uses only existing
  tokens — 2 stray fallback literals, `rgba(0,0,0,0.15)` and a
  redundant `--space-1` fallback, were caught by the quality gate
  during development and removed in favor of the real, already-
  defined tokens).
- 24 screenshots re-captured (both themes) and visually confirmed: nav
  fits in one row at 1440px (was 3 wrapped rows), Reports page is a
  fraction of its previous scroll length.

### Round 2 — `MEMORY.md` update — confirmed made

Appended (never rewritten), recording both restructurings, the two
real Playwright-only bugs found, and verification results.

### Round 2 — Governance compliance

- No backend/API change.
- Every existing route/page remains reachable — confirmed directly via
  the re-captured screenshots and the unmodified passing nav tests,
  not assumed.
- Playwright/network-mocked testing only; no real backend/Dhan
  dependency.
- P11/P16: this summary, `App.tsx`, `ReportsOverviewPage.tsx`,
  `styles.css`, the updated screenshot script, the re-captured
  screenshots, and `MEMORY.md` committed to `active-development` only.

### Note on this file's own history

This pass's own first tool call would have overwritten Round 1's
content via a blind `Write`. Caught before committing (`git status`
showed the file as modified, not new, matching the exact same
`CHECKPOINT_FRONTEND-3_SUMMARY.md` incident earlier this session) and
corrected by merging both rounds into this one file in order.
