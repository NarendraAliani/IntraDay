// frontend/src/common/api/configApi.ts
//
// Checkpoint 9: typed wrappers around the Checkpoint 8 configuration API
// (/api/v1/config/...). Each function returns the array of persisted
// versions for a given identity, which includes `is_active` per version -
// there is deliberately no separate "list" vs "active" call here, since the
// list endpoint already carries the active/historical distinction the
// Configuration Viewer needs.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type RiskConfigurationResponse = components["schemas"]["RiskConfigurationResponse"];
export type UniverseResponse = components["schemas"]["UniverseResponse"];
export type StrategyVersionResponse = components["schemas"]["StrategyVersionResponse"];

/** All persisted versions of a risk configuration, active flag included. */
export function listRiskConfigurationVersions(
  configurationId: string,
): Promise<RiskConfigurationResponse[]> {
  return apiGet<RiskConfigurationResponse[]>(
    `/api/v1/config/risk/${encodeURIComponent(configurationId)}/`,
  );
}

/** All persisted versions of a universe, active flag included. */
export function listUniverseVersions(universeId: string): Promise<UniverseResponse[]> {
  return apiGet<UniverseResponse[]>(`/api/v1/config/universe/${encodeURIComponent(universeId)}/`);
}

/** All persisted versions of a strategy, active flag included. */
export function listStrategyVersions(strategyId: string): Promise<StrategyVersionResponse[]> {
  return apiGet<StrategyVersionResponse[]>(
    `/api/v1/config/strategy/${encodeURIComponent(strategyId)}/`,
  );
}

/**
 * Activate a specific persisted risk-configuration version (Checkpoint 8's
 * `POST /api/v1/config/risk/{configuration_id}/{version}/activate/`).
 * Backend-authoritative and idempotent - activating an already-active
 * version simply re-confirms it. Never mutates local state directly; the
 * caller must treat the returned record (or a follow-up
 * `listRiskConfigurationVersions` call) as the source of truth for what
 * is actually active.
 */
export function activateRiskConfigurationVersion(
  configurationId: string,
  version: string,
): Promise<RiskConfigurationResponse> {
  return apiPost<RiskConfigurationResponse>(
    `/api/v1/config/risk/${encodeURIComponent(configurationId)}/${encodeURIComponent(version)}/activate/`,
  );
}
