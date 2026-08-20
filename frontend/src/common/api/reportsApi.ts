// frontend/src/common/api/reportsApi.ts
//
// Checkpoint 64.15: the FIRST typed frontend client for the report
// endpoints wired in Checkpoint 64.10 (`reports_views.py`) - mirrors
// marketDataApi.ts's own established pattern (generated OpenAPI
// contract types only, thin fetch wrapper). Previously only consumed
// as a catalogue placeholder (ReportsOverviewPage.tsx never called the
// real endpoint) - the Live Paper Operations Console (64.15) is the
// first screen to actually read `DailySessionReportResponse`, reusing
// it for the Paper Execution + Communication KPI panels rather than
// re-deriving those counts client-side from the signal list.
import { apiGet } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type DailySessionReportResponse = components["schemas"]["DailySessionReportResponse"];

export function getDailySessionReport(): Promise<DailySessionReportResponse> {
  return apiGet<DailySessionReportResponse>("/api/v1/config/reports/daily-session/");
}
