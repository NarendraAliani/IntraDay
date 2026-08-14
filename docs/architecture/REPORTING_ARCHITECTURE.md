# Reporting Architecture

Checkpoint 32 Part 7-14. Establishes the reporting foundation: one
shared report-metadata contract, the report catalogue, and the first
two reports built on top of it (Backtest Report, Market Data Quality
Report). Does not fabricate functionality for report types that have
no underlying data yet.

## What already existed vs. what this checkpoint added

`reports/`, `reports/backtests/`, `reports/production/`,
`reports/research/`, and `research/research_reports/` (repo-root
directories, distinct from `src/intraday/research/`) were pre-existing
Checkpoint-1/2 **output-artifact** placeholders — directories reserved
for generated, human-readable report *files*, never containing
business logic. This checkpoint did not add source code to them; they
remain what Checkpoint 2 defined them as. Report *logic* (metadata
assembly, the catalogue, status mapping) lives in
`src/intraday/application/reporting/` — the application layer, per
`.importlinter` contract 3 ("Application -> bounded contexts -> domain
layering"), which already permits the application layer to read from
and compose multiple bounded contexts (`research.backtesting`,
`domain.market_data`, etc.) — exactly what assembling a report from
existing data is. No new bounded context, no new `.importlinter`
contract entry was needed.

## The shared contract: `ReportMetadata`

`application/reporting/contracts.py`. One frozen dataclass, reused by
every report type — never a report-type-specific metadata subclass:

```
report_id, report_type, title, generated_at, generated_by,
data_source, data_identity, strategy_identity, timeframe,
instrument_universe, trust_level, quality_status, report_status,
version, period_start, period_end
```

`trust_level` reuses `research.backtesting.contracts.BacktestTrustLevel`
verbatim. `quality_status` reuses `DataQualityLabel` verbatim. Neither
is a new, competing enum — Part 13's explicit instruction ("do not
invent status names if an existing canonical trust model already
exists").

## Report-type status vs. report-instance trust/quality — two different questions

`ReportStatus` (`AVAILABLE`/`PARTIAL`/`PLANNED`/`BLOCKED`/
`NOT_YET_IMPLEMENTED`/`RESEARCH_ONLY`) describes whether a report
**type** is buildable at all today — a property of the catalogue entry,
not of any one report instance. `trust_level`/`quality_status` on a
`ReportMetadata` instance describe the **data** a specific report was
built from. A `BACKTEST_REPORT` is always `ReportStatus.AVAILABLE`
(the report type works), but any individual instance's `trust_level`
is still whatever the underlying `BacktestResult` says (always `POC`
today) — these never collapse into one "passed" indicator (Part 9's
explicit requirement).

## The report catalogue

`REPORT_CATALOGUE` (`application/reporting/contracts.py`) — exactly the
ten report types Part 8 names, each with `purpose`/`owner`/
`required_data`/`future_data_dependencies`/`ui_surface`. This is the
single, authoritative list — the frontend's
`features/reports/reportCatalogue.ts` is a presentation-layer mirror of
it (not a competing source of truth for backend logic; both sides are
covered by tests asserting exactly 10 entries).

| Report Type | Status | Owner |
|---|---|---|
| BACKTEST_REPORT | AVAILABLE | research.backtesting |
| BACKTEST_COMPARISON_REPORT | AVAILABLE | research.backtesting |
| STRATEGY_RESEARCH_REPORT | PARTIAL | research.backtesting |
| MARKET_DATA_QUALITY_REPORT | AVAILABLE | control_plane.market_data_health / domain.market_data |
| SIGNAL_REPORT | NOT_YET_IMPLEMENTED | signal_intelligence |
| PORTFOLIO_REPORT | PARTIAL | research.backtesting |
| RISK_REPORT | NOT_YET_IMPLEMENTED | trading_engine.risk_engine |
| PRODUCTION_REPORT | PLANNED | control_plane.reconciliation / domain.trade |
| AUDIT_REPORT | PARTIAL | control_plane / domain.audit |
| SYSTEM_HEALTH_REPORT | PARTIAL | control_plane.market_data_health |

## Backtest Report

`application/reporting/backtest_report.py::build_backtest_report_metadata()`
maps an existing `BacktestResult` into `ReportMetadata` — pure
assembly, no new computation. `report_id` = `backtest_id` (the
existing deterministic hash). `trust_level` is copied verbatim, never
raised — proven by
`test_backtest_report_metadata_cannot_become_research_ready_automatically`.

The existing Backtest Workbench UI (Checkpoints 27-30) already presents
the full structure Part 9 asks for (Executive Summary via KPIs,
Run Identity, Strategy, Data Identity, Configuration, Execution
Assumptions, Trade Summary, Gross/Net P&L, Costs, Win Rate, Profit
Factor, Drawdown, MFE/MAE, Equity Curve, Trade Table, Validation
Status, Trust Level, Caveats via the "not a promise" callout) — this
checkpoint did not rebuild that UI, only formalized its underlying
metadata contract.

## Market Data Quality Report

`application/reporting/market_data_quality_report.py`. Structures
Checkpoint 31's `TRADING_GRADE_BAR_VALIDATION.md` findings as queryable
data: `TradingGradeBarCondition` (one per acceptance condition, with
`ConditionStatus` — `SATISFIED`/`PARTIALLY_SATISFIED`/`NOT_SATISFIED`/
`BLOCKED` — and its evidence string), plus `current_classification`
(`BarQualityGrade`, reused from `domain.market_data.aggregation`,
never a new classification enum).

`current_classification` only becomes `TRADING_GRADE_BAR` when **all
six** conditions are `SATISFIED` — never a partial-progress inference.
Proven by `test_market_data_quality_report_stays_sample_bar_with_partial_conditions`.

This module does not re-verify anything live — it structures the
already-established Checkpoint 31 evidence. A future checkpoint that
re-runs live verification updates the `CONDITIONS` tuple, never
silently flips a status without new evidence.

## Frontend mirror

`features/reports/marketDataQualityReport.ts` and
`reportCatalogue.ts` are static, code-embedded presentation mirrors of
the backend contracts above — the same pattern Checkpoint 31 already
established for `DataQualityBanner` (a property of the codebase at a
given commit, not a per-request live value). `ReportsOverviewPage.tsx`
renders both, plus the capability registry (see
`PLACEHOLDER_AND_FEATURE_STATE_ARCHITECTURE.md`).

## Export policy

No PDF/CSV/JSON export exists. `Export PDF`/`Export CSV`/`Export JSON`
are shown as `PLANNED` capability cards on the Reports page — no
document-generation framework was introduced (Part 12's explicit "do
not introduce a new document-generation framework without
architectural justification"; the underlying data is already available
via the existing results API for a future export endpoint to read).

## Deferred / explicitly out of scope

Report persistence (a `ReportRecord` model), a report-generation
service/scheduler, PDF/CSV/JSON export implementation, `SIGNAL_REPORT`/
`RISK_REPORT` (no underlying data exists for either yet — risk_engine
remains empty scaffolding, signal reports have no assembler),
`PRODUCTION_REPORT` (no live trading exists).
