# CHECKPOINT-BACKTEST-PDF-B — "Download PDF" Button (frontend)

No filename collision — confirmed via `ls` before writing.

No backend changes — confirmed via `git status` (frontend files only).
Phase A's endpoint (`GET /backtesting/results/<backtest_id>/report/`)
is consumed exactly as it already exists.

## What was built

- **`common/api/client.ts`** — new `apiGetBlob(path): Promise<Blob>`.
  This project had **no existing binary-file-download pattern**
  (confirmed via `grep` for `createObjectURL`/`Blob(`/`download=` —
  zero matches anywhere in the frontend before this checkpoint), so a
  new, minimal one was built, reusing `performRequest()`'s own
  request-construction and `credentials: "include"` handling exactly.
  A non-2xx response is still routed through the SAME
  `ApiRequestError`/`ApiNetworkError` handling every other verb
  uses — the backend's own error responses stay JSON even on an
  endpoint whose success response is binary.
- **`common/api/backtestingApi.ts`** — new
  `getBacktestResultReportPdf(backtestId, runId?)`, calling Phase A's
  endpoint with an optional `?run_id=` query param.
- **`BacktestingWorkbenchPage.tsx`** — a new `DownloadPdfReportButton`
  sub-component, rendered inside `BacktestResultsPanel` (so it's
  visible on BOTH call sites: the single-instrument "Run Backtest"
  flow AND each expanded instrument inside a multi-instrument
  historical run's own "Results by Instrument" list) — placed directly
  under the "Results" heading, above the existing disclaimers.
  - **`run_id` reuses existing state, no new tracking added**: the
    single-instrument flow never had a `run_id` (and never should —
    it's genuinely not part of any multi-instrument run) so it's
    simply omitted there; the multi-instrument flow already tracks
    `progress.run_id` (from `HistoricalBacktestRunProgress`, already
    fetched for the progress-polling UI) — threaded down through
    `PerInstrumentResults` → `BacktestResultsPanel` as a new,
    optional `runId` prop, never a second piece of state.
  - **Triggers a real browser download**: a standard blob-download
    approach (`URL.createObjectURL` + a programmatic `<a download>`
    click + `URL.revokeObjectURL`), filename
    `backtest-<backtest_id>-report.pdf` — matching the task's own
    example naming exactly.
  - **Loading state**: the button's own label becomes "Generating…"
    and is disabled while the request is in flight — a genuine
    in-flight state (reportlab's own multi-page-with-charts generation
    is not instant), not a fixed-duration fake spinner.
  - **Error state**: a failed request (network error, 404, etc.)
    renders via the SAME shared `ErrorState` component every other
    failure on this page already uses — never a silent no-op; the
    button re-enables so the operator can retry.

## Design-system conventions followed

- Button placement/styling: a plain, unclassed `<button>` (this
  project's own global `button` rule, matching every other action
  button on this page — "Run Backtest," "Check Data Readiness,"
  etc.) — no bespoke button style invented.
- `.backtest-results__pdf-export` (new, `app/styles.css`) is a
  one-line spacing wrapper only — no new visual language.
- **Density/grid rule** (`FRONTEND_DESIGN_SYSTEM.md`): confirmed not
  applicable here — a single button plus its own conditional error
  message is not a form panel or a set of independent summary
  sections; there is nothing to grid.

## Testing

- **`BacktestingWorkbenchPage.test.tsx`** — 4 new tests (25 total,
  all passing):
  - The button appears once a single-instrument result exists, and
    the request is made with **no** `run_id` in the URL.
  - A **"Generating…"** loading state while the request is in flight
    (a controlled, never-resolving `fetch` mock proves the button
    stays disabled until the request genuinely completes).
  - An **honest error message** on a failed request (a mocked 404) —
    the real error text appears on screen, and the button re-enables.
  - The **multi-instrument** flow (reusing this file's own existing
    "drill into a completed historical run" test setup) — confirms
    the request URL includes `?run_id=run-1`, the exact `run_id` the
    page's own progress polling already tracked.
  - One real fix made while writing these tests: `vi.stubGlobal("URL",
    {...URL, createObjectURL: ...})` silently breaks `URL` as a
    constructor in jsdom (spreading a class copies no methods) —
    switched to directly assigning `URL.createObjectURL`/
    `revokeObjectURL` on the real global instead, which is what
    actually works.
- **Real-browser Playwright screenshots (both themes)**, network-
  mocked: confirm the "Download PDF Report" button renders correctly,
  in context, directly under "Results," in both Focus (light) and
  Midnight (dark) themes.
- **Full frontend suite**: `npm run typecheck` clean;
  `npx vitest run` → **396 passed / 396** (37 files) on a clean
  rerun. One transient failure (`ScreenerPage.test.tsx`, unrelated —
  this checkpoint never touches that file) appeared on an earlier run
  amid the full suite and was confirmed NOT a regression: it passed
  standalone and passed again on a full clean rerun.
- **Backend**: confirmed unaffected directly via `git status` (only
  frontend files changed) — no backend suite re-run needed, per the
  RULES' own "No backend changes — Phase A's endpoint is already
  complete."

## RULES compliance

- No backend changes — confirmed via `git status`.
- No strategy code changes, no registry change, no live session
  launched.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
