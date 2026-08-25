# Task Report

## Milestone
Frontend product maturity — making the platform's real decision chain visible and honestly qualified, ahead of the next live milestone (Full NSE equity session + matching reference reconciliation).

## Checkpoint
64.80-F3 — Feature/Scanner/Strategy Correlation Experience (FRONTEND-ONLY).

## Classification
Frontend-only. Zero backend source changes, zero database/migration changes, zero live market activity. The Indian market is closed; nothing in this checkpoint contacted Dhan, started a worker, or placed an order.

## Objective
Create a frontend experience that makes the REAL relationship between market data, features, scanners, strategies, signals, paper trading and outcomes visible — using only what the existing backend/API contracts actually establish, and representing every missing or unexposed relationship honestly rather than inventing it.

## Correlation Audit

Phase 1 was a read-only investigation of `frontend/shared/generated_contracts/api-types.ts` (86 endpoints, 80 schemas), cross-checked against the actual Django views in `src/intraday/infrastructure/api/`, the strategy registry in `src/intraday/trading_engine/strategy_execution/`, the field registry in `src/intraday/signal_intelligence/feature_engine/field_registry.py`, and the signal→order lineage in `src/intraday/application/services/paper_signal_execution.py`.

| Source | Target | Status | Evidence | UI Exposure | Gap |
|---|---|---|---|---|---|
| Market Data | Features | FOUND | `GET /api/v1/config/strategy-engine/fields/` → `FieldDefinition.required_inputs` names the raw bar fields each derived feature consumes (RSI requires `close`; ATR requires `high`,`low`,`close`). `FieldDefinition.source` is `domain.market_data.contracts.Bar` for raw fields and `signal_intelligence.feature_engine` for derived ones. | Rendered as a FOUND chain link with the endpoint and field named inline. | None. |
| Features | Scanner | NOT APPLICABLE | `ScannerConfigurationState` exposes only `timeframe`, `universe_mode`, `universe_requested_count`, `universe_subscribed_count`, `strategy_ids`, `configuration_version`, `enabled`. No scanner-condition entity exists in the API contract or anywhere in `src/` (no `ScannerCondition` class). This platform's Scanner is a scan LOOP over universe × strategies; feature evaluation happens inside a Strategy. | Rendered as NOT APPLICABLE with the explanation that the relationship does not exist by design, and a pointer to the real Features→Strategy link. | None to close. Treating this as a missing link would misdescribe the architecture. |
| Features | Strategy | PARTIAL | `GET /api/v1/config/strategy-engine/strategies/{strategy_id}/schema/` → `ParameterDefinition.parameter_type === "FIELD_REFERENCE"` plus `field_category` publishes the field CATEGORY a parameter accepts. The chosen `field_id` lives in `StrategyConfigurationResponse.values`, typed `unknown`. The authoritative resolved list, `Strategy.required_features(config)` (`trading_engine/strategy_execution/strategy.py:30`), is exposed by NO endpoint — the string `required_features` does not appear anywhere in the generated contract. | Rendered as PARTIAL in "Other audited relationships". | Publish the resolved `required_features(config)` field_id list per active configuration. |
| Market Data | Scanner | FOUND | `ScannerConfigurationState.timeframe` / `universe_requested_count` / `universe_subscribed_count`, plus `WorkerRuntimeStatusResponse.subscribed_instrument_count`. | Rendered as FOUND. | None. |
| Scanner | Strategy | FOUND | `ScannerConfigurationState.strategy_ids` on `GET /api/v1/config/market-data/scanner-config/` declares exactly which strategies the scan loop runs. `ScannerProgressResponse.current_strategy` / `strategies_total` / `strategies_processed` show it in flight. | Rendered as a FOUND chain link. | None. |
| Scanner (run) | Signal | PARTIAL | `ScannerProgressResponse.signals_found` is an aggregate COUNT only. `SignalResponse` carries no scan-run identifier, so the count cannot be decomposed into the signals it counted. | Rendered as PARTIAL. | Carry a scan-run identifier onto `SignalResponse`. |
| Strategy | Signal | FOUND | `SignalResponse.strategy_id` on `GET /api/v1/config/signals/`; `SignalReportResponse.by_strategy` aggregates counts per strategy. | Rendered as a FOUND chain link. | None. |
| Features | Signal | NOT AVAILABLE | `SignalResponse.evidence.fields` is a list of `{label, value}` pairs authored by the strategy in its own display order (`SignalEvidenceRecordView.fields` is a tuple of `(label, value)` strings). Labels are free-text display strings, NOT `FieldDefinition.field_id` values — `field_id` does not appear in `SignalResponse` at all. No programmatic join exists. | Rendered as NOT AVAILABLE. | Emit `field_id` alongside each evidence label. |
| Signal | Paper Trade | PARTIAL | `PaperSessionSignal` carries `signal_id` together with `order_status` in one record, so signal→ORDER is exposed directly. `PaperOrderResponse.idempotency_key` IS the `signal_id` and `order_id` is `order-{signal_id}` for engine-generated orders (`paper_signal_execution.py:345-364`). But `PaperTradeResponse` has NO `signal_id` — only `order_ids` — so signal→TRADE is reachable only by joining through the order id. | Rendered as a PARTIAL chain link, stating exactly which half is exposed. | Expose `signal_id` on `PaperTradeResponse`. |
| Paper Trade | Outcome | FOUND | `PaperTradeResponse.realized_pnl`; `PaperSessionTrade.realized_net_pnl`; `DailySessionReportResponse.realized_pnl_total` / `unrealized_pnl_total` / `closed_positions`. | Rendered as a FOUND chain link. | None. |
| Paper Trade | Strategy VERSION | NOT FOUND | Searched every paper schema. `PaperTradeResponse`, `PaperOrderResponse`, `PaperPositionResponse` and `PaperSessionTrade` all carry `strategy_id` but NONE carries `specification_version`, `code_version` or `configuration_version`. `DailySessionReportResponse.configuration_version` is the SCANNER configuration version — a different concept. | Rendered as NOT FOUND. | Stamp the flattened strategy version onto paper orders and trades so P&L can be attributed to a configuration. |
| Strategy | Backtest Outcome | FOUND | `GET /api/v1/config/backtesting/strategies/{strategy_id}/results/` is keyed on `strategy_id` and returns `BacktestResult` with its own `trust_level` and `validation`. | Rendered as FOUND. | None. |
| Market Data | Outcome (archive-qualified) | NOT YET IMPLEMENTED | The daily archive is a MANAGEMENT COMMAND (`market_data_archive`). No archive or reconciliation schema exists in the generated contract. | Rendered as NOT YET IMPLEMENTED. | Expose archive completeness + reconciliation as a read-only API. |

Totals: **6 FOUND, 3 PARTIAL, 1 NOT FOUND, 1 NOT AVAILABLE, 1 NOT APPLICABLE, 1 NOT YET IMPLEMENTED.**

## Correlation Taxonomy

One closed vocabulary, defined once in `correlationModel.ts` and rendered verbatim as an on-screen legend:

- **FOUND** — the API contract exposes a field that directly joins these two things. Verified against the generated contract.
- **PARTIAL** — part of the relationship is exposed (an aggregate, a category, or an id needing an indirect join) but not the whole link.
- **NOT FOUND** — searched for in the contract; no field establishes it. A real traceability gap, not a UI omission.
- **NOT APPLICABLE** — the relationship does not exist in this platform's design. There is nothing for the backend to expose.
- **NOT AVAILABLE** — the relationship exists inside the backend but no HTTP endpoint publishes it.
- **NOT YET IMPLEMENTED** — the capability itself is not built, so no relationship can exist yet.

The UI states explicitly that availability is not correlation and correlation is not causal proof: "A FOUND status means the API exposes a join between two records. It does not claim the upstream stage caused the downstream outcome."

## Decision Pipeline
A reusable component, `frontend/src/features/correlation/DecisionPipeline.tsx`, rendering the seven-stage chain Market Data → Features → Scanner → Strategy → Signal → Paper Trade → Outcome as a semantic `<ol>`. Each stage shows an icon, label, stage ordinal, one-sentence summary, the real GET endpoints behind it, and a navigation action. Each connector carries the audited link's status badge, its relationship sentence, its API evidence, and its gap.

## Market Data
Stage 1. Bars/quotes for the subscribed universe. Backed by `market-data/bars/`, `market-data/quotes/`, `market-data/worker-status/`. Navigates to the existing Market Data screen.

## Features
Stage 2. The canonical field registry — raw Bar fields plus derived EQUITY indicators (SMA, EMA, ATR, RSI, ADX, +DI, -DI, Relative Volume, MACD histogram). Backed by `strategy-engine/fields/`. The UI states plainly that no options fields exist in this registry. Navigates to Strategy Configuration, where the field registry is actually rendered.

## Scanner
Stage 3. The scan loop over universe × timeframe × configured strategies. It holds no conditions of its own — stated explicitly, because assuming otherwise is the single most likely false correlation on this screen. Backed by `market-data/scanner-config/` and `market-data/live-paper-workbench/`. Navigates to Live Scanner.

## Strategy
Stage 4. Registered, versioned strategies with a parameter schema and saved configuration — where entry/exit conditions actually live. Backed by `strategy-engine/strategies/`, `.../schema/`, `strategy/{id}/active/`.

## Signal
Stage 5. Strategy-produced signals with direction, risk decision, trade plan and strategy-authored evidence. Backed by `config/signals/` and `reports/signals/`. Navigates to Reports (Signal Report) — the application has no standalone Signals screen, so no fake deep link was created.

## Paper Trading
Stage 6. Simulated execution only. Backed by `paper-trading/orders/`, `paper-trading/trades/`, `paper-trading/session/`. The stage text restates that nothing reaches a real exchange.

## Outcome
Stage 7. Realized/unrealized P&L and backtest results. Backed by `reports/daily-session/` and `backtesting/strategies/{id}/results/`.

## Dashboard Integration
`DecisionPipeline` is hosted at the foot of the existing Dashboard (`features/dashboard/DashboardPage.tsx`) as a "Decision Pipeline" section, placed after the status cards deliberately: the cards answer "what is happening now", the pipeline answers "how does this platform get from data to a decision, and which of those links are actually wired". The dashboard HOSTS the component; it does not own it — the component lives in `features/correlation/` so any other screen can reuse it.

## Drill-Down Navigation
This project has **no React Router** — verified. `App.tsx` holds one piece of screen state and switches on it (a documented convention since Checkpoint 9). The pipeline therefore drills down through that existing mechanism: a `PipelineDestination` closed union of screen ids that already exist, passed up via `onNavigate` and mapped to `setScreen` in `App.tsx`. A node with no real screen renders no control at all rather than a dead link. Pipeline actions were named "Go to …" rather than "Open …" so they do not collide with the dashboard cards' own accessible names (a duplicate-accessible-name defect caught by the existing `AppDashboardNavigation` test).

## Visual Identity
Reuses 64.80-F2's cerebral identity exactly: analytical surface tokens, precision connector rules, mono/tabular metrics for endpoints and pair labels, restrained status badges. Connectors are static 2px rules coloured by link status. No flashy flowchart, no `@keyframes`, no `infinite`, no `animation:` property — the same restraint the theme quality gate enforces.

## Icons
The EXISTING single icon system (`common/icons/Icon.tsx`) only. **No new icon was added and no second system created** — a test asserts neither the model nor the component contains a raw `<svg>`, and that the component imports both `Icon` and the shared `StatusBadge`. Status markers come from `StatusBadge`, which already maps tone → icon. No Unicode glyphs or emoji.

## Themes
The EXISTING theme system only. **No new CSS token was introduced** — the theme quality gate requires all four themes to define an identical token set, so a new token would have been a four-theme change. Every pipeline colour is a `var()` from the 64.80-F2 token set. A test renders the pipeline under all four themes (focus, midnight, obsidian, aurora) and asserts the structure and the status WORDS survive unchanged.

## Responsive
Desktop: `repeat(auto-fit, minmax(260px, 1fr))` horizontal flow. Below 1100px the same markup stacks to a single column and the connector rule rotates from horizontal (2px tall) to vertical (2px wide, 24px tall), indented so it never crosses a label. One markup tree serves both layouts — asserted by a test, so nothing is duplicated or hidden per breakpoint.

## Accessibility
The chain is an ordered list, so assistive technology receives the sequence without depending on visual position or arrows. Every relationship is announced as a full sentence ("Market Data supplies the raw bar fields that Features are computed from."), never as a glyph. Decorative icons and every connector rule are `aria-hidden`. The pipeline is a named region; every stage is a heading with its own accessible name. Every destination is a real `<button type="button">`, focusable in document order. Colour never carries state alone — the status WORD and its explanation are always rendered as text.

## API Usage
Read-only. The pipeline itself issues **no network requests at all** — it is a static, evidence-backed description of the contract, so it cannot fabricate a relationship from a runtime response. The endpoints it NAMES are the existing GET endpoints listed in the audit above; all are rendered verbatim with their HTTP verb so a reader can see they are reads.

## Backend Limitations
Documented as future backend/API requirements, not filled in:
1. `PaperTradeResponse` carries no `signal_id` — signal→trade needs a client-side id join.
2. No paper schema carries a strategy version — realized P&L cannot be attributed to a configuration.
3. `required_features(config)` is not exposed — a feature cannot be traced to every strategy that consumes it.
4. Signal evidence labels are free text, not `field_id` — evidence cannot be joined to the field registry.
5. `SignalResponse` carries no scan-run id — an aggregate `signals_found` cannot be decomposed.
6. No archive/reconciliation HTTP API exists (carried forward from 64.80-F).

## Testing Level
FULL FRONTEND REGRESSION (escalated).

## Tests Run
- New: `src/features/correlation/correlationModel.test.ts` (40 tests) and `src/features/correlation/DecisionPipeline.test.tsx` (32 tests) — **72 new tests, all passing**.
- Full frontend regression: `npx vitest run` → **350 tests across 32 files, all passing**.
- CSS/theme quality gates: `styles.quality.test.ts` + `theme.quality.test.ts` → 20 passing.

`correlationModel.test.ts` is the honesty gate: it reads the checked-in generated contract as text and asserts that every field cited as evidence for a FOUND/PARTIAL link genuinely EXISTS in it, and — symmetrically — that every field claimed MISSING is genuinely ABSENT (e.g. `PaperTradeResponse` must not contain `signal_id`; the contract must not contain `required_features`). A future link asserting an unexposed correlation fails the build.

Phase 13's required coverage is met in full: pipeline renders; FOUND/PARTIAL/NOT AVAILABLE/NOT FOUND (and NOT APPLICABLE/NOT YET IMPLEMENTED) each render correctly; no false correlation is displayed (the rendered edge set must equal the audited edge set exactly, and each card's badges must equal exactly that link's status); theme switching preserves the pipeline; icons render through the common system; keyboard navigation works; stacked layout stays readable; navigation destinations fire with the right screen id; no Gainz control appears; no NSE_FNO/OptionQuote/OI/IV/Greeks UI is introduced.

## Tests Skipped
Backend pytest, mypy and lint-imports — deliberately not run, because no backend source was modified. Running them would only re-measure carried-forward 64.43–64.80-F2 state.

## Escalation Decision
Escalated to full frontend regression, and it was warranted. This checkpoint modified the **dashboard shell host** (`DashboardPage.tsx`), the **application shell** (`App.tsx`), the **shared stylesheet** (`styles.css`), and consumed the **shared theme + icon + StatusBadge foundation**. That is exactly the escalation criterion. It paid for itself immediately: the regression caught a real defect the targeted tests could not — the pipeline's navigation buttons duplicated the dashboard cards' accessible names, breaking `AppDashboardNavigation.test.tsx`. That was a genuine accessibility problem (two identically-named buttons on one screen), fixed by renaming the pipeline's actions rather than by weakening a prior checkpoint's test.

## Frontend Build
`npm run build` — PASS. 94 modules transformed; `dist/assets/index-*.css` 48.42 kB (gzip 8.83 kB), `dist/assets/index-*.js` 366.28 kB (gzip 97.43 kB). Built in 982ms.

## Type Check
`npx tsc --noEmit` — PASS, zero errors. (`npm run build` runs `tsc -b` first and also passed.)

## CSS Quality
PASS. No hex/rgba literal outside `:root`; no duplicate rule blocks; responsive `@media` rule present; focus-visible preserved; no inline `style={{ }}` anywhere; no raw `<svg>` outside the icon module; no emoji. No new theme token was added, so all four themes remain token-identical.

## Backend Changes
**NONE.** No file under `src/`, `trading_engine/`, `application/`, `domain/`, `config/`, `signal_intelligence/` or `research/` was created, edited or deleted by this checkpoint. The backend diff visible in `git status` is entirely carried-forward, uncommitted 64.43–64.80-F2 work that pre-existed this session.

## Database Changes
**NONE.** No migration created, no model touched, no query executed.

## Live Market Activity
**NONE.** Dhan was not contacted. No worker was started. No credentials were read or modified. No order was placed. The Indian market is closed. The new component performs no network I/O whatsoever.

## Research Readiness
Unchanged — **NOT READY**. Still gated on full NSE session validation, independent candle authority, and reconciliation evidence. This checkpoint did not touch the research-readiness gate and did not claim progress on it.

## Gainz Status
**DISABLED / future scope, unchanged.** No Gainz activation control was added. The pipeline contains no Gainz node and no Gainz text at all — asserted by two tests.

## BacktestTrustLevel
Unchanged. No backtest code, cost model, validation path or trust-level computation was touched.

## Remaining Correlation Gaps
1. Signal → Paper Trade requires a client-side id join (no `signal_id` on `PaperTradeResponse`).
2. Realized P&L cannot be attributed to a strategy VERSION.
3. Feature → Strategy is category-level only; `required_features()` is unexposed.
4. Signal evidence cannot be machine-joined to the field registry.
5. Individual signals cannot be attributed to a scan run.
6. Archive completeness cannot qualify an outcome (no HTTP API).
7. The pipeline is a contract-level description; it does not yet render LIVE instance-level chains (e.g. "this specific signal produced this specific trade"). Doing so honestly requires gaps 1 and 2 to be closed first.
8. Carried forward from 64.80-F2: ~40 individual feature pages still contain their own inline Unicode markers and are not yet migrated to the icon system.

## Blockers
No blocker to this checkpoint's own scope. The blocker to deepening the correlation experience is backend/API exposure (gaps 1–6), which is deliberately out of scope for a frontend-only checkpoint and was NOT worked around by adding backend code.

## Next Product Milestone
**FULL NSE EQUITY SESSION + MATCHING REFERENCE RECONCILIATION** — unchanged.

## Performance Ranking

| Dimension | Previous (64.80-F2) | Current (64.80-F3) | Change | Evidence | Remaining Gap |
|---|---|---|---|---|---|
| Correlation Visibility | None — no screen described the decision chain | A 7-stage Decision Pipeline with 13 audited relationships, each with status + evidence | Major improvement | `DecisionPipeline.tsx`; 72 new tests | Contract-level only, not instance-level |
| Feature Traceability | Field registry visible on Strategy Config only | Feature stage + Features→Strategy PARTIAL + Features→Signal NOT AVAILABLE, each with cited evidence | Improved, honestly bounded | Audit rows 3, 8 | `required_features()` unexposed |
| Scanner Traceability | Scanner config visible; relationships implicit | Scanner→Strategy FOUND, Market Data→Scanner FOUND, Scanner run→Signal PARTIAL, Features→Scanner NOT APPLICABLE | Improved | `ScannerConfigurationState.strategy_ids` | No scan-run id on signals |
| Strategy Traceability | Strategy list/schema/config screens | Strategy stage linked upstream to Scanner and downstream to Signal and Backtest, all FOUND | Improved | Audit rows 5, 7, 12 | Version→outcome attribution absent |
| Signal Traceability | Signal report in Reports | Strategy→Signal FOUND; Signal→Paper Trade PARTIAL with the exposed half named precisely | Improved | `SignalResponse.strategy_id`; `PaperSessionSignal` | No `signal_id` on trades |
| Paper Trading Traceability | Paper Trading screen | Signal→Order exposed; Order→Trade via `order_ids`; Trade→Strategy VERSION marked NOT FOUND | Improved + a real gap surfaced | Audit rows 9, 11 | Version stamping |
| Outcome Traceability | P&L on paper/report screens | Paper Trade→Outcome FOUND; Strategy→Backtest FOUND; archive-qualified outcome NOT YET IMPLEMENTED | Improved | Audit rows 10, 12, 13 | No archive API |
| Dashboard UX | 8 status cards in 3 groups | Same cards plus a "how this platform decides" section | Improved | `DashboardPage.tsx` | — |
| Navigation | Card-level entry points | Pipeline nodes drill into 6 existing screens through the existing mechanism; duplicate accessible names eliminated | Improved | `App.tsx` `onNavigate`; regression fix | No Signals screen exists |
| Accessibility | Icon system, focus states, theme control | Ordered-list sequence, full-sentence relationships, named region, aria-hidden connectors, keyboard-reachable destinations | Improved | 5 accessibility tests | — |
| Visual Consistency | 4-theme token system + one icon system | Reused exactly; zero new tokens, zero new icons, zero second systems | Maintained | Theme/icon quality gates pass | — |
| Testing | 278 frontend tests | 350 frontend tests (+72) | Improved | `npx vitest run` | — |
| Performance | 366 kB JS / 48 kB CSS bundle | Effectively unchanged (static component, no network I/O, no runtime data) | Neutral | `npm run build` | — |
| Security | No live controls; read-only screens | Unchanged; pipeline is read-only, issues no requests, exposes no credentials | Maintained | No API calls in component | — |

## Final Product Gate

**A. Can the user see the complete decision pipeline?** YES — all seven stages, Market Data through Outcome, on the Dashboard.

**B. Are existing correlations represented accurately?** YES — each of the 6 FOUND links names the exact endpoint and schema field, re-asserted against the generated contract by an automated test.

**C. Are missing correlations explicitly identified?** YES — 1 NOT FOUND, 3 PARTIAL, each stating what is missing and what backend work would close it.

**D. Are unavailable API relationships shown honestly?** YES — 1 NOT AVAILABLE, 1 NOT YET IMPLEMENTED, 1 NOT APPLICABLE, each with its reason.

**E. Can the user navigate from a node to an existing related screen?** YES — six real destinations through the project's existing navigation mechanism; nodes without a screen render no control.

**F. Are scanner/strategy relationships clearly distinguishable from merely co-existing features?** YES — Scanner→Strategy is FOUND because `strategy_ids` declares it; Features→Scanner is NOT APPLICABLE because no scanner-condition entity exists. Co-existence is never drawn as a link.

**G. Can a feature be traced to a scanner where the actual backend relationship exists?** NOT APPLICABLE — no such backend relationship exists; the UI says so rather than inventing one. The real feature relationship (Features→Strategy) is shown as PARTIAL.

**H. Can a scanner be traced to a strategy where the actual relationship exists?** YES — FOUND via `ScannerConfigurationState.strategy_ids` and `ScannerProgressResponse.current_strategy`.

**I. Can a strategy be traced to signals where the actual relationship exists?** YES — FOUND via `SignalResponse.strategy_id` and `SignalReportResponse.by_strategy`.

**J. Can signals be traced to Paper Trading where the actual relationship exists?** PARTIALLY, and it is labelled PARTIAL — signal→order is exposed (`PaperSessionSignal.signal_id` + `order_status`; `idempotency_key` is the signal id); signal→trade requires an order-id join because `PaperTradeResponse` has no `signal_id`.

**K. Are future/unimplemented relationships clearly marked?** YES — NOT YET IMPLEMENTED for archive-qualified outcomes, with the prerequisite stated.

**L. Was any false correlation invented?** **NO.** Every rendered edge comes from the audited model; a test asserts the rendered edge set equals the audited edge set exactly, and the contract-reading test would fail on any FOUND claim citing a field that does not exist.

**M. Was Gainz activated?** **NO.** No Gainz node, no Gainz control, no Gainz text in the new UI.

**N. Was NSE_FNO modified?** **NO.** No OI/IV/Greeks/OptionChain/OptionQuote/OptionBar UI introduced; asserted by tests in both new test files.

**O. Was Dhan contacted?** **NO.** No live API call, no worker start, no credential access.

**P. Was BacktestTrustLevel changed?** **NO.**

**Q. Is the next live milestone still FULL NSE EQUITY SESSION + MATCHING REFERENCE RECONCILIATION?** **YES.**

---

### Git Safety

No commit, no push, no destructive git command was run.

**Files created/modified by 64.80-F3:**
- `frontend/src/features/correlation/correlationModel.ts` (new)
- `frontend/src/features/correlation/DecisionPipeline.tsx` (new)
- `frontend/src/features/correlation/correlationModel.test.ts` (new)
- `frontend/src/features/correlation/DecisionPipeline.test.tsx` (new)
- `frontend/src/features/dashboard/DashboardPage.tsx` (modified — hosts the pipeline, adds optional `onNavigate`)
- `frontend/src/app/App.tsx` (modified — wires `onNavigate` to the existing screen state)
- `frontend/src/app/styles.css` (modified — appended the Decision Pipeline block; no existing rule altered)

**Carried forward from 64.43–64.80-F2, untouched by this checkpoint:** all backend changes under `src/intraday/**` (Dhan worker, instrument master, packet decoder, persistence models, worker runtime status), `docs/**`, `config/**`, `domain/**`, and the frontend work from 64.80-F/F2 (`frontend/src/app/theme/`, `frontend/src/common/icons/`, `frontend/src/features/dashboard/` scaffolding, `MarketDataArchivePage`, `systemApi.ts`).

`git log -3 --oneline`: `3bd7a09 CheckPoint 64.69`, `ab2dc04 Checkpoint 64.42`, `b576008 CHECKPOINT 64.33` — unchanged; nothing was committed.
