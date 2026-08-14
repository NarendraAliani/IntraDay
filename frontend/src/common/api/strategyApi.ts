// frontend/src/common/api/strategyApi.ts
//
// Checkpoint 26: typed wrappers around the strategy-engine API
// (/api/v1/config/strategy-engine/...), mirroring settingsApi.ts's own
// established pattern - generated OpenAPI contract types only, thin
// fetch wrappers, no hand-duplicated response shapes. This module is
// the ONLY place the frontend talks to the field registry / strategy
// registry / parameter schema / configuration endpoints - the dynamic
// dropdowns and generic renderer (StrategyConfigurationPage.tsx)
// consume it exclusively, never a hardcoded option list.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type FieldDefinition = components["schemas"]["FieldDefinition"];
export type StrategySummary = components["schemas"]["StrategySummary"];
export type StrategySchema = components["schemas"]["StrategySchema"];
export type ParameterDefinition = components["schemas"]["ParameterDefinition"];
export type StrategyConfigurationSaveRequest =
  components["schemas"]["StrategyConfigurationSaveRequest"];
export type StrategyConfigurationResponse =
  components["schemas"]["StrategyConfigurationResponse"];

export function getFieldRegistry(): Promise<FieldDefinition[]> {
  return apiGet<FieldDefinition[]>("/api/v1/config/strategy-engine/fields/");
}

export function listStrategies(): Promise<StrategySummary[]> {
  return apiGet<StrategySummary[]>("/api/v1/config/strategy-engine/strategies/");
}

export function getStrategySchema(strategyId: string): Promise<StrategySchema> {
  return apiGet<StrategySchema>(`/api/v1/config/strategy-engine/strategies/${strategyId}/schema/`);
}

export function listConfigurations(
  strategyId: string,
): Promise<StrategyConfigurationResponse[]> {
  return apiGet<StrategyConfigurationResponse[]>(
    `/api/v1/config/strategy-engine/strategies/${strategyId}/configurations/`,
  );
}

export function getConfiguration(
  strategyId: string,
  specificationVersion: string,
  codeVersion: string,
  configurationVersion: string,
): Promise<StrategyConfigurationResponse> {
  return apiGet<StrategyConfigurationResponse>(
    `/api/v1/config/strategy-engine/strategies/${strategyId}/configurations/` +
      `${specificationVersion}/${codeVersion}/${configurationVersion}/`,
  );
}

export function saveConfiguration(
  strategyId: string,
  body: StrategyConfigurationSaveRequest,
): Promise<StrategyConfigurationResponse> {
  return apiPost<StrategyConfigurationResponse>(
    `/api/v1/config/strategy-engine/strategies/${strategyId}/configurations/save/`,
    body,
  );
}
