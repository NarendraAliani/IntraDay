# CHECKPOINT-SCANNER-B — Read-Only API + Minimal UI (Historical mode only)

Scope: Phase B of `SCANNER_BUILDER_ROADMAP.md`, built on
`CHECKPOINT-SCANNER-A`'s pure logic. Historical mode only — no
live-worker dependency, no rule persistence.

```
backend endpoint: POST /api/v1/config/screening/evaluate/ - read-only,
            synchronous, rule + instrument universe + date range in,
            matches out
honest labeling: every instrument routed through the REAL
            ResearchDataGateService first - a ResearchDataRejectedError
            becomes its own NOT_GATE_VERIFIED status with the gate's
            own real detail, never silently folded into NO_MATCH
architecture boundary: test_adhoc_screening_boundary.py extended to
            cover the new view + contracts files (still 4 tests, now
            scanning 4 files instead of 2)
frontend: new ScreenerPage.tsx under its own features/screening/
            directory, wired into the existing "Research" nav group,
            reusing InstrumentPickerMulti + the FIELD_REFERENCE
            dropdown pattern - zero new component library
screenshots: real Playwright/Chromium, both themes (Focus/light,
            Midnight/dark), verified legible and consistent - found
            and fixed a real Vite/Playwright gotcha along the way
            (networkidle never resolves against Vite's own HMR
            WebSocket)
tests_new: 7 backend API tests + 6 frontend vitest tests = 13
full_backend_suite: 3419 passed / 7 failed - identical failure set to
            CHECKPOINT-SCANNER-A, +7 net passing tests, zero new
            failures
full_frontend_suite: 373 passed (367 pre-existing + 6 new),
            typecheck clean, CSS quality gate clean
commit: (recorded below)
```

## Part 0 — Pre-flight

`[F]` Confirmed via `ls`/`git status`: `CHECKPOINT_SCANNER-B_SUMMARY.md`
did not already exist. Git tree was clean apart from the deliberately-
uncommitted `SCANNER_BUILDER_ROADMAP.md` before this checkpoint's own
edits began.

## Backend

`[F]` **Studied the exact precedent before writing anything**:
`historical_backtesting_views.py`'s own `coverage_preview_view` —
a read-only, synchronous POST endpoint that never persists, never
dispatches a background task. This project's screening universe (4-6
symbols) makes the async-task-plus-polling shape
`create_historical_backtest_run_view` needs genuinely unnecessary here
— documented directly in the new view's own docstring, not assumed.

`[F]` **New wire contracts** (`application/contracts/screening.py`):
`ScreeningEvaluateRequestSerializer`/`ScreeningEvaluateResponseSerializer`,
mirroring `CoveragePreviewRequestSerializer`'s own established shape.
`comparison` travels as a plain string on the wire — the view parses it
as a `Decimal` if it looks numeric, otherwise passes it through
unchanged, exactly matching `evaluate_condition()`'s own two-case-plus-
categorical-fallback resolution (Checkpoint-Scanner-A).

`[F]` **New view** (`infrastructure/api/screening_views.py`,
`evaluate_screening_rule_view`): for every requested instrument, calls
the REAL `ResearchDataGateService.get_research_eligible_bars()` first
— the SAME trusted-data gate every backtest/research consumer in this
project already relies on, never a screening-specific reimplementation
of "is this data trustworthy." A `ResearchDataRejectedError` becomes
its own `NOT_GATE_VERIFIED` status carrying the gate's own real
rejection reason/detail; only instruments that pass the gate ever reach
`AdhocScreeningService.screen()` — called EXACTLY as Checkpoint-Scanner-A
designed it (`bars_by_instrument` supplied by the caller, no signature
change).

`[F]` **Route wired** at `/screening/evaluate/`
(`config_api:screening-evaluate`), confirmed resolving via
`django.urls.reverse()` directly.

`[F]` **Architecture-boundary test extended**
(`test_adhoc_screening_boundary.py`): `SCREENING_FILES` now scans 4
files (was 2) — the new view and its own contracts, alongside the
Phase A domain/service files. All 4 existing tests still pass,
confirming the new backend files also carry zero imports of
`Strategy`/`StrategyRegistry`/`StrategyExecutionCoordinator`/
`PaperBroker`/`ScannerConfiguration`.

`[F]` **7 new API tests**
(`tests/unit/infrastructure/api/test_screening_api.py`), real
PostgreSQL fixtures (`@requires_postgres`), real gate, never mocked:
a matched instrument with its evidence trail, a genuine no-match, an
instrument with zero bars reporting `NOT_GATE_VERIFIED` with a real
`INCOMPLETE_COVERAGE` detail (the honest-labeling requirement, proven
not just claimed), a mixed universe reporting each instrument
independently, an `OR` combinator with a field-vs-field condition,
unauthenticated rejection, and invalid-operator 400. `[F]` Fixture
bars are built at the EXACT close-timestamps
`HistoricalDataCoverageService._expected_timestamps()` itself computes
(never a guessed/approximate schedule) — confirmed directly rather
than assumed, so the gate genuinely accepts them.

## Frontend

`[F]` **Read `docs/architecture/FRONTEND_DESIGN_SYSTEM.md` first**, per
this checkpoint's own instruction (the project's own "frontend-design
skill" — no dedicated Skill-tool entry exists for this codebase's own
frontend conventions, so the equivalent, already-established doc was
used). Confirmed: no CSS framework, no component library, plain
token-driven CSS, `.form-grid`/`.form-row`/`.market-data-monitor__table`/
`.table-scroll`/`.badge--*` as the established reusable idioms — the
new page reuses every one of these, adding only two small, token-driven
page-level layout rules (`--space-*` tokens, no hardcoded literals).

`[F]` **New page** (`features/screening/ScreenerPage.tsx`), a genuinely
new, standalone directory per the roadmap's own explicit architecture-
boundary instruction — never embedded inside
`StrategyConfigurationPage`/`BacktestingWorkbenchPage`/the Live Paper
Operations Console. Reuses `InstrumentPickerMulti` (instrument
selection) and the SAME `FieldDefinition[]`-driven `<select>` pattern
`ParameterSchemaFields.tsx`'s own `FIELD_REFERENCE` case established
(a new small `ConditionRow` component, since a screening condition
needs a field pick PLUS an operator PLUS a comparison value — a shape
`ParameterControl` itself doesn't have, not force-fit into it).
Clearly labeled **"Historical mode"** — checked directly (a dedicated
test asserts the word "live"/"real-time" never appears anywhere on the
page).

`[F]` **API client** (`common/api/screeningApi.ts`), mirroring
`backtestingApi.ts`'s own established pattern — generated OpenAPI
types only, one thin `apiPost` wrapper.

`[F]` **OpenAPI contract regenerated**: `manage.py spectacular` →
`openapi.json` (gitignored, build artifact) →
`openapi-typescript` → `shared/generated_contracts/api-types.ts`
(tracked, committed) — confirmed the new `Screening*` types appear
correctly before writing a single line of the API client against them.

`[F]` **Added to navigation**: `App.tsx`'s existing `NAV_GROUPS`
"Research" group (`FRONTEND-4`'s own established grouping) gained one
new item, `Screener` — no new nav pattern invented, the existing
`<details>`/`<summary>` dropdown mechanism handles it identically to
every other Research entry.

`[F]` **6 new vitest tests** (`ScreenerPage.test.tsx`), network-mocked
(`vi.stubGlobal("fetch", ...)`, the established pattern) — confirms
"Historical mode" labeling, confirms NO mention anywhere of
`live`/`real-time`/`Buy`/`Sell`/`Place Order`/`Submit Paper Order`/
`Signal` (the roadmap's own architecture-boundary spirit, checked in
the UI's own copy, not just imports), a matched result's evidence
trail rendering, the honest `NOT_GATE_VERIFIED` label rendering
distinctly from a no-match, Run staying disabled until the form is
genuinely complete, and adding/removing condition rows with the
AND/OR combinator appearing only once there are 2+ conditions.

## Real-browser screenshots — both themes

`[F]` **A real Vite/Playwright gotcha found and fixed along the way**:
`page.goto(url, { waitUntil: "networkidle" })` never resolved, because
Vite's dev server keeps its own HMR WebSocket connection open
indefinitely — a well-known but easy-to-hit interaction, not obvious
until diagnosed directly (console/pageerror capture, then a debug
screenshot showing an empty `<div id="root">` with zero rendered
content). Fixed by waiting on `"load"` plus a concrete DOM element
(`nav`) instead.

`[F]` **A second real issue found**: the initial screenshot attempt
crashed with `Cannot read properties of undefined (reading 'length')`
inside `DashboardPage` — the landing screen, which must mount
successfully before any navigation can happen, needs its own 4 status
endpoints (`/market-data/session/`, `/market-data/health/`,
`/market-data/worker-status/`, `/system/readiness/`) mocked with real
response shapes (matching `AppDashboardNavigation.test.tsx`'s own
established fixtures) — a generic empty-object fallback mock was not
enough.

`[F]` Both screenshots (1280×900, full-page) captured successfully
against a real Chromium instance with every `/api/` call intercepted
client-side (no real backend contacted) — **Focus (light)** and
**Midnight (dark)** — both legible, consistent typography/spacing,
badges reading correctly (green `Matched`, grey `No match`, amber
`Not verified`) in both themes, the Research nav dropdown showing the
new `Screener` entry correctly positioned. Deleted the temporary script
and PNG files afterward (not committed — a one-off verification
artifact, not a repo asset) and terminated only the dev-server process
this checkpoint itself launched (confirmed by port, `netstat`/`taskkill`
targeting PID `11500` on `127.0.0.1:5174` specifically — the operator's
own pre-existing dev server on port `5173` was never touched).

## Testing — full results

`[F]` **Backend**: `tests/unit/infrastructure/api/test_screening_api.py`
— **7 passed**. `tests/unit/architecture/test_adhoc_screening_boundary.py`
— **4 passed** (now covering 4 files). `[F]` **Full backend suite**:
`.venv/Scripts/python.exe -m pytest -q --reuse-db` — **3419 passed, 7
failed** (675.09s). Exact failure names, identical to
`CHECKPOINT-SCANNER-A`'s own list (same 5 pre-existing + 2 known
`--reuse-db` flakes):

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

Pass count up by exactly **7** (3412 → 3419), matching the 7 new API
tests. **Zero new/unexplained failures.**

`[F]` **Frontend**: `npx tsc -b` — clean, zero errors. `npx vitest run`
— **373 passed** (367 pre-existing, unmodified + 6 new), including
`styles.quality.test.ts` (8 checks: no inline styles, no hardcoded
colors outside `:root`, no duplicate rule blocks — confirmed the new
`.screener-page`/`.screener-page__condition-row` CSS stays within the
existing token discipline) and `theme.quality.test.ts` (13 checks,
unaffected since no new theme tokens were needed — every color the
new page uses is an existing shared token via `.badge--*`/
`.market-data-monitor__table`).

## New baseline, stated plainly

- The read-only screening endpoint and its minimal UI are real,
  tested, and genuinely decoupled from `Strategy`/`PaperBroker`/
  `ScannerConfiguration` — mechanically proven at 3 layers (Phase A's
  own pure-logic boundary test, this phase's extension of it to the
  API layer, and this phase's own frontend copy-content check).
- Historical mode only, as scoped — the honest data-coverage labeling
  this checkpoint's own explicit requirement demanded is real,
  end-to-end tested (not just claimed): a genuinely uncovered
  instrument is reported `NOT_GATE_VERIFIED` with the SAME real gate
  detail every other research consumer in this project already relies
  on, never silently downgraded to a false `NO_MATCH`.
- Phase C (Live mode, `AggregatedBarObservation`) and Phase D (saved
  rules) remain explicitly out of this checkpoint's own scope, per the
  roadmap's own sequencing — not attempted here.

## Governance compliance

- P3: the only new persistence-adjacent surface is the new, read-only
  `screening_views.py`'s own call to the existing, unchanged
  `ResearchDataGateService`/`DjangoHistoricalBarRepository` — zero
  writes, zero new tables, zero rule persistence.
- P9: no strategy code touched, no registry change — mechanically
  proven (architecture-boundary test, extended this checkpoint) and
  visually proven (the frontend copy-content test).
- No live session launched, per this checkpoint's own rule.
- P11/P16: this summary, the new backend/frontend files, the
  regenerated OpenAPI types, and `MEMORY.md` committed to
  `active-development` only. `openapi.json` (the intermediate schema
  file `api-types.ts` is generated from) remains correctly gitignored,
  regenerated on demand rather than committed.

`CHECKPOINT_SCANNER-B_SUMMARY.md` — this file — committed alongside
the code and tests. `MEMORY.md` updated in the same commit (see
below). `SCANNER_BUILDER_ROADMAP.md` remains deliberately uncommitted,
per its own originating convention.
