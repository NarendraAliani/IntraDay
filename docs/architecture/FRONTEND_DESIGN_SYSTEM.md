# Frontend Design System

Checkpoint 35 Part 10/11. A system-wide CSS/UX audit of the entire
frontend (not only Paper Trading), and the resulting design-token/
component/responsive/accessibility conventions. Extends the existing
stylesheet (`frontend/src/app/styles.css`, Checkpoint 9 onward) rather
than replacing it — every finding below states what was fixed this
checkpoint and what remains an honest, named gap.

## Audit method

A full pass over every file in `frontend/src/app/`, `frontend/src/common/`,
and `frontend/src/features/`, plus the single shared stylesheet. No
visual/browser screenshot testing was performed — browser automation
remains genuinely unavailable in this environment (re-confirmed this
checkpoint, same as every prior checkpoint since Checkpoint 27; `import
playwright` fails, no `node_modules/.bin/playwright`). This audit is a
structural/code-level audit (component inventory, CSS token review, a
machine-checkable CSS quality gate), not a rendered-pixel review — that
distinction is stated explicitly, not glossed over.

## Headline finding

**Before this checkpoint, `styles.css` contained zero `@media` rules.**
The entire frontend — 9 screens, every table, every form, the primary
navigation bar — was desktop-only. This is the single most consequential
finding of the audit, and the one this checkpoint prioritized fixing at
the token/base level (global responsive rules that every page inherits
automatically) over rebuilding every individual page's layout.

## Design tokens

`:root` in `styles.css` is the single source of truth. Checkpoint 9's
original 11 color tokens are unchanged; Checkpoint 35 added:

| Category | Tokens | Status before this checkpoint |
|---|---|---|
| Warning/info/danger/success | `--color-warning-*`, `--color-info-*`, `--color-danger-*` (aliases existing error tokens), `--color-success-*` (aliases existing active tokens) | Missing — `.badge--pending` used raw hex (`#fff8e1`/`#b98900`/`#8a6600`) |
| Paper/live safety | `--color-paper-bg`/`--color-paper-border`/`--color-paper-text` | Missing entirely — no visual language existed for "this is simulated" distinct from success/danger |
| Neutral accent fixes | `--color-on-accent`, `--color-overlay`, `--color-equity-line` | Missing — 9 hardcoded hex/rgba literals existed across the file (found and fixed by the new CSS quality gate, see below) |
| Spacing | `--space-1` … `--space-8` (4px base unit) | Missing — every component hand-wrote its own rem values |
| Typography | `--font-size-xs` … `--font-size-2xl`, line-heights | Missing |
| Radius/shadow | `--radius-sm/md/pill`, `--shadow-sm/md/lg` | Partially ad hoc (radius values like `4px`/`8px`/`999px` repeated as literals) |
| Focus ring | `--focus-ring`, `--focus-ring-color` | **Missing entirely — no visible focus state existed anywhere in the app before this checkpoint** (a genuine accessibility gap, see below) |
| Motion | `--transition-fast/base`, plus a global `prefers-reduced-motion` rule | Missing |
| Z-index | `--z-nav/dropdown/modal/toast` | Missing (not yet consumed by any component — reserved for the Modal/Dialog work named in "Deferred," so future overlay components don't invent ad hoc z-index values) |
| Layout | `--page-max-width` (960px, unchanged), `--page-max-width-wide` (1200px, reserved for a future wide-table screen) | Partial (hardcoded `960px` literal) |

## Typography hierarchy

Page titles (`<h1>`), section titles (`<h2>`, used consistently inside
`.capability-status-section`), card titles (`.capability-status__title`,
`.paper-trading__kpi span`), body text, small/help text
(`.capability-status__description`, `font-size: var(--font-size-sm)`),
table text, and badges now share the same type-scale tokens. No new
heading levels or a `<h3>`-as-card-title convention was introduced this
checkpoint — the existing hierarchy was audited and found structurally
consistent; only the *values* (rem literals) were tokenized.

## Layout

- **Page max-width**: 960px (`--page-max-width`), consistent across
  every screen via the shared `main` element — no page overrides it.
- **Cards**: `.capability-status`, `.paper-trading__kpi`,
  `.market-data-monitor__card` all share the same
  surface/border/radius/padding recipe (`var(--color-surface)`,
  `var(--color-border)`, `var(--radius-md)`) — audited for consistency,
  no divergent card style found needing a fix.
- **Grids**: `.capability-status-grid`, `.paper-trading__kpis`,
  `.form-grid` all use the same `repeat(auto-fit, minmax(...))` pattern
  — a genuinely consistent grid idiom already existed before this
  checkpoint (Checkpoint 32's own `capability-status-grid`), reused
  for the new Paper Trading page rather than inventing a new one.
- **Forms**: `.form-grid`/`.form-row` are NEW this checkpoint,
  consolidating what was previously bespoke, unlabeled `<div>`/`<input>`
  markup in `LiveMarketDataMonitor.tsx` and `PaperTradingPage.tsx` into
  one reusable pattern.
- **Tables**: every `<table>` uses the shared `.market-data-monitor__table`
  class (established Checkpoint 23, reused — never duplicated — by
  Paper Trading's order/trade/position tables this checkpoint). Wide
  tables are wrapped in the new `.table-scroll` utility so the table
  scrolls horizontally inside itself, never the page body.
- **Navigation**: `.app-shell__nav` now wraps (`flex-wrap: wrap`) and
  the header stacks vertically below 640px — previously it would
  overflow with 10 nav items on a narrow viewport.

## Responsive strategy

Two global breakpoints, applied at the base/token level so every page
inherits them without per-page media queries:

- **768px** (tablet): reduced page padding.
- **480px** (mobile): further-reduced padding, smaller `<h1>` size.
- **640px** (nav-specific): header switches from row to column layout,
  nav wraps below the title/sign-out row.

**Explicitly tested viewport widths** (via component-level assertions
and manual DOM/CSS reasoning, not a rendered browser — see "Audit
method" above): the breakpoint values themselves target common device
class boundaries (mobile ≤480px, tablet ≤768px, laptop/desktop
>768px) — a standard three-tier strategy, not a fourth "laptop-specific"
breakpoint, since no page content in this app currently needs a
distinct laptop-only layout.

**What remains unaddressed (honest gap, not fixed this checkpoint):**
per-page responsive review of `BacktestingWorkbenchPage.tsx`,
`ComparisonPage.tsx`, and other pre-existing screens' own dense KPI
grids/tables at exactly 480px was not individually verified — the
global base rules apply, but a genuinely thorough per-page mobile
audit (verifying no specific table or KPI grid still overflows at
exactly 375px, a common phone width) was not performed given this
checkpoint's time constraints. This is a named, deferred item, not a
claimed-complete one.

## Interaction states

- **Focus**: a global `:focus-visible` rule (visible box-shadow ring)
  now applies to every `a`/`button`/`input`/`select`/`textarea`/
  `[tabindex]` element — **this did not exist anywhere before this
  checkpoint**, a genuine WCAG 2.4.7 gap now closed at the base level.
- **Disabled**: existing `:disabled` styles (opacity reduction,
  `cursor: not-allowed`) were audited and found already present on
  every button that has a disabled state (`login-form button[type=submit]:disabled`,
  `.dialog__actions button:disabled`) — no new disabled-state work was
  needed.
- **Hover**: present on the buttons that had it before this checkpoint
  (`.activate-button:hover`); not audited for 100% coverage across
  every interactive element - a named remaining gap.
- **Loading/Error**: unified via the existing `LoadingState`/`ErrorState`
  shared components (Checkpoint 9/23) — reused by every new Paper
  Trading section, never reimplemented.

## Accessibility

- Every form input in the new Paper Trading order-entry form uses a
  real `<label>` wrapping its control (not a placeholder-as-label
  anti-pattern).
- Table headers use `<th scope="col">` throughout (existing convention,
  reused).
- Status changes on order submission use `role="status"`/`role="alert"`
  (existing convention from `KillSwitchService`'s frontend wiring,
  reused for the order-submission result message).
- Color is never the sole signal for status — every badge pairs a
  color with an icon (`●`/`◐`/`○`/`✕`) and text, unchanged discipline
  since Checkpoint 9's `ActiveBadge`.
- **Not verified this checkpoint**: actual color-contrast ratios
  (WCAG AA 4.5:1) were not measured with a contrast-checking tool —
  the token palette was chosen to visually read as sufficiently
  distinct, but this is a named gap, not a verified pass.
- **Not verified this checkpoint**: full keyboard-only navigation
  walkthrough (tab order across the entire app) — the new
  `:focus-visible` rule makes focus visible wherever it lands, but an
  end-to-end tab-order audit was not performed (would require browser
  automation, unavailable).

## Paper vs. Live visual conventions

- `--color-paper-*` tokens are deliberately a distinct hue (indigo)
  from both `--color-success-*` (green) and `--color-danger-*` (red),
  so a "this is simulated" signal can never be misread as "succeeded"
  or "failed."
- Every paper-trading-operational page states **PAPER MODE** in a
  visible callout at the top.
- Every currently-unavailable live capability is labeled
  **"LIVE TRADING — NOT AVAILABLE"** via the shared `CapabilityStatus`
  component, never a bare "Coming Soon."
- No button anywhere in the app says a bare, ambiguous "Submit Order,"
  "Execute," "Buy," or "Sell" — the one order-entry action reads
  **"Submit Paper Order"** (Part 13's own explicit example).

## CSS architecture

- **No CSS framework was introduced.** The existing plain-CSS,
  token-driven approach (Checkpoint 9's own original decision) was
  judged still appropriate for this app's size (9 screens, one shared
  stylesheet) — introducing Tailwind/a component library now would be
  a larger architectural change than this checkpoint's mandate,
  and Part 10 itself warns against "blindly introduc[ing] a CSS
  framework."
- **No inline `style={{...}}` usage exists anywhere in the frontend**
  (verified by the new CSS quality gate, `styles.quality.test.ts`).
- **No duplicate CSS rule blocks** (verified mechanically).
- **9 hardcoded color literals were found and fixed** this checkpoint
  (6× `#fff`, 1× `#2f7d4f`, 2× a stale, INCORRECT hex fallback on
  `var(--color-error-border, #b3261e)` that didn't even match the real
  token value `#c0392b` — a genuine bug the audit caught, not just a
  style nit).
- **CSS quality gate** (`frontend/src/app/styles.quality.test.ts`, Part
  19): 8 automated checks - no duplicate `:root` token names, no
  hardcoded hex/rgba outside `:root`, no duplicate rule blocks, at
  least one responsive rule exists, a visible focus state exists, and
  no component uses inline styles. Runs as a normal `vitest` test
  (same toolchain, zero new tooling dependency beyond `@types/node`
  for the file-reading utility itself).

## Design system components (Part 11)

Reused/standardized, not duplicated (no `ButtonV2`/`CardV2` was
created):

| Component | Status |
|---|---|
| Button | Standardized via shared classes (`.app-shell__header button`, form buttons) - no dedicated `<Button>` React component exists; a future checkpoint could extract one, not done here (see Deferred). |
| Input/Select/Textarea | Standardized this checkpoint via `.form-grid`/`.form-row` shared classes. |
| Checkbox/Radio | Not audited this checkpoint - `ComparisonPage.tsx`'s `.comparison-page__checkbox` is the only existing usage; left unchanged. |
| Card | `.capability-status`, `.paper-trading__kpi`, `.market-data-monitor__card` share one recipe, audited consistent. |
| Badge | `CapabilityStatus`'s badge classes + `.badge--*` shared across every screen - added `.badge--info`/`.badge--paper` this checkpoint. |
| Alert / Callout | `.callout--warn` (existing, Checkpoint 27) reused for the PAPER MODE banner - no new callout variant needed. |
| Table | `.market-data-monitor__table` reused everywhere; `.table-scroll` wrapper added this checkpoint. |
| Modal / Dialog | `.dialog`/`.dialog-backdrop` (existing, unaudited beyond the color-token fix) - not extended this checkpoint. |
| Tabs | Does not exist anywhere in this app - not needed yet (9 screens use top-level nav, not in-page tabs). |
| Navigation | `.app-shell__nav` - made responsive this checkpoint. |
| Loading / Empty / Error State | `LoadingState`/`EmptyState`/`ErrorState` (existing shared components, Checkpoint 9/23) - reused unchanged. |
| Capability Status | `CapabilityStatus` (Checkpoint 32) - the ONE placeholder mechanism, reused (not duplicated) for every new Paper Trading capability card this checkpoint. |
| Status Indicator | The icon+text+color badge pattern (`●`/`◐`/`○`/`✕`) - audited consistent across Market Data, Reports, and now Paper Trading. |

## Deferred / explicitly out of scope

A dedicated `<Button>`/`<Input>` React component library (classes are
standardized; component extraction is a larger refactor than this
checkpoint's scope), per-page mobile-width verification below 480px,
measured color-contrast ratios, full keyboard tab-order walkthrough,
a Tabs component (not yet needed), checkbox/radio standardization.
