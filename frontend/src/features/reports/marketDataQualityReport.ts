// frontend/src/features/reports/marketDataQualityReport.ts
//
// Checkpoint 32 Part 10/11: frontend presentation mirror of the
// backend's `build_market_data_quality_report()`
// (src/intraday/application/reporting/market_data_quality_report.py),
// itself a structured form of Checkpoint 31's real, evidence-based
// TRADING_GRADE_BAR findings - not fabricated for this page. Static,
// code-embedded (same pattern as Checkpoint 31's DataQualityBanner)
// since this describes a property of the engine/pipeline at a given
// commit, not a per-request live value.
export type ConditionStatus = "SATISFIED" | "NOT_SATISFIED" | "BLOCKED";

export interface TradingGradeBarCondition {
  ordinal: number;
  description: string;
  status: ConditionStatus;
  evidence: string;
}

export const TRADING_GRADE_BAR_CONDITIONS: TradingGradeBarCondition[] = [
  {
    ordinal: 1,
    description: "Same-day intraday availability verified",
    status: "SATISFIED",
    evidence: "Live POST /v2/charts/intraday call (HDFCBANK, 2026-08-14) returned 360 real same-day 1-minute candles.",
  },
  {
    ordinal: 2,
    description: "Exact timestamp/timezone verified",
    status: "SATISFIED",
    evidence: "First candle epoch equals exactly 09:15:00 IST - this project's own market-open convention.",
  },
  {
    ordinal: 3,
    description: "Candle authority/provenance sufficiently trusted",
    status: "NOT_SATISFIED",
    evidence: "Only one independent (Google Finance) cross-check point performed.",
  },
  {
    ordinal: 4,
    description: "WebSocket live ingestion implemented and validated",
    status: "BLOCKED",
    evidence: "No persistent-process infrastructure exists outside Docker (Docker permanently deferred).",
  },
  {
    ordinal: 5,
    description: "Historical/reconciliation gap recovery implemented and validated",
    status: "BLOCKED",
    evidence: "Contingent on condition 4.",
  },
  {
    ordinal: 6,
    description: "One full trading session independently validated against a trusted price source",
    status: "NOT_SATISFIED",
    evidence: "Only a single-instrument, single-timestamp comparison performed, not a full session.",
  },
];

export const CONDITIONS_PASSED = TRADING_GRADE_BAR_CONDITIONS.filter(
  (c) => c.status === "SATISFIED",
).length;
export const CONDITIONS_TOTAL = TRADING_GRADE_BAR_CONDITIONS.length;
export const CURRENT_CLASSIFICATION: "SAMPLE_BAR" | "TRADING_GRADE_BAR" =
  CONDITIONS_PASSED === CONDITIONS_TOTAL ? "TRADING_GRADE_BAR" : "SAMPLE_BAR";
