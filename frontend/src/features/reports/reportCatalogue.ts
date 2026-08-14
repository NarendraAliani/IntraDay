// frontend/src/features/reports/reportCatalogue.ts
//
// Checkpoint 32 Part 7/8/11: frontend presentation data mirroring the
// backend's authoritative `REPORT_CATALOGUE`
// (src/intraday/application/reporting/contracts.py). This file is a
// presentation-layer MIRROR, not a second source of truth for backend
// logic - if the backend catalogue changes, this file must be updated
// to match (no automated sync exists yet; both sides are covered by
// tests asserting exactly 10 report types / exactly this shape).
import type { CapabilityState } from "../../common/components/CapabilityStatus";

export interface ReportCatalogueEntry {
  reportType: string;
  title: string;
  status: CapabilityState;
  purpose: string;
  uiSurface: string;
}

export const REPORT_CATALOGUE: ReportCatalogueEntry[] = [
  {
    reportType: "BACKTEST_REPORT",
    title: "Backtest Report",
    status: "AVAILABLE",
    purpose: "One backtest run's full result set - configuration, trades, costs, equity, validation.",
    uiSurface: "Backtesting Workbench",
  },
  {
    reportType: "BACKTEST_COMPARISON_REPORT",
    title: "Backtest Comparison Report",
    status: "AVAILABLE",
    purpose: "Side-by-side comparison of two or more backtest results.",
    uiSurface: "Comparison page",
  },
  {
    reportType: "STRATEGY_RESEARCH_REPORT",
    title: "Strategy Research Report",
    status: "PARTIAL",
    purpose: "Overall research status across every backtest run against a strategy.",
    uiSurface: "Strategy Monitor page (single-run only today)",
  },
  {
    reportType: "MARKET_DATA_QUALITY_REPORT",
    title: "Market Data Quality Report",
    status: "AVAILABLE",
    purpose: "TRADING_GRADE_BAR six-condition classification, evidence, and current status.",
    uiSurface: "Reports Overview page (this page)",
  },
  {
    reportType: "SIGNAL_REPORT",
    title: "Signal Report",
    status: "NOT_YET_IMPLEMENTED",
    purpose: "Generated/verified signals and their theoretical outcomes for a period.",
    uiSurface: "Not yet surfaced",
  },
  {
    reportType: "PORTFOLIO_REPORT",
    title: "Portfolio Report",
    status: "PARTIAL",
    purpose: "Multi-instrument portfolio backtest attribution and aggregate P&L.",
    uiSurface: "Not yet surfaced as a dedicated view",
  },
  {
    reportType: "RISK_REPORT",
    title: "Risk Report",
    status: "NOT_YET_IMPLEMENTED",
    purpose: "Risk-engine exposure/limit-utilization reporting.",
    uiSurface: "Not yet surfaced",
  },
  {
    reportType: "PRODUCTION_REPORT",
    title: "Production Report",
    status: "PLANNED",
    purpose: "Live production reconciliation/P&L summaries.",
    uiSurface: "Not yet surfaced",
  },
  {
    reportType: "AUDIT_REPORT",
    title: "Audit Report",
    status: "PARTIAL",
    purpose: "Human-readable presentation of the existing audit trail.",
    uiSurface: "Not yet surfaced as a dedicated report (raw audit API exists)",
  },
  {
    reportType: "SYSTEM_HEALTH_REPORT",
    title: "System Health Report",
    status: "PARTIAL",
    purpose: "Aggregate operational health across subsystems.",
    uiSurface: "Not yet surfaced as a dedicated report (Market Data Monitor covers one subsystem)",
  },
];
