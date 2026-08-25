// frontend/src/common/api/systemApi.ts
//
// Checkpoint 64.80-F: typed wrapper around the already-existing,
// already-typed composed system-readiness endpoint
// (`GET /api/v1/system/readiness/`, registered in
// `infrastructure/api/urls.py` as `system-readiness` and backed by
// `system_readiness_view.system_readiness`).
//
// No backend code is added or changed by this module - the endpoint has
// existed since Checkpoint 50; it simply had no frontend consumer until
// the Application Dashboard needed it. Follows the same one-module-per-
// backend-domain convention as marketDataApi.ts / paperTradingApi.ts:
// generated OpenAPI contract types only, thin `apiGet` wrappers, no
// hand-duplicated response shapes and no bespoke fetch/auth logic.
import { apiGet } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

/** Checkpoint 50 Rule 10's ONE composed readiness answer. Deliberately
 * NOT re-derived in the frontend: `state`, `reasons`, and
 * `kill_switch_engaged` are read straight from the backend snapshot. */
export type SystemReadinessResponse = components["schemas"]["SystemReadinessResponse"];

export function getSystemReadiness(): Promise<SystemReadinessResponse> {
  return apiGet<SystemReadinessResponse>("/api/v1/system/readiness/");
}
