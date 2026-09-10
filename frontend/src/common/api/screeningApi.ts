// frontend/src/common/api/screeningApi.ts
//
// CHECKPOINT-SCANNER-B, Phase B of SCANNER_BUILDER_ROADMAP.md: typed
// wrapper around the read-only, Historical-mode-only screening
// endpoint (/api/v1/config/screening/evaluate/), mirroring
// backtestingApi.ts's own established pattern - generated OpenAPI
// contract types only, one thin fetch wrapper, no rule persistence
// (Phase D's own concern).
import { apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type ScreeningConditionRequest = components["schemas"]["ScreeningConditionRequest"];
export type ScreeningEvaluateRequest = components["schemas"]["ScreeningEvaluateRequest"];
export type ScreeningEvaluateResponse = components["schemas"]["ScreeningEvaluateResponse"];
export type ScreeningInstrumentResult = components["schemas"]["ScreeningInstrumentResult"];

export function evaluateScreeningRule(
  body: ScreeningEvaluateRequest,
): Promise<ScreeningEvaluateResponse> {
  return apiPost<ScreeningEvaluateResponse>("/api/v1/config/screening/evaluate/", body);
}
