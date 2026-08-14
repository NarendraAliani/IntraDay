// frontend/src/common/api/killSwitchApi.ts
//
// Checkpoint 34 Part 11/15: typed wrappers around the kill-switch API
// (/api/v1/config/kill-switch/...), mirroring marketDataApi.ts's own
// established pattern - generated OpenAPI contract types only, thin
// fetch wrappers.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type KillSwitchStatusResponse = components["schemas"]["KillSwitchStatusResponse"];

export function getKillSwitchStatus(): Promise<KillSwitchStatusResponse> {
  return apiGet("/api/v1/config/kill-switch/");
}

export function engageKillSwitch(reason: string): Promise<KillSwitchStatusResponse> {
  return apiPost("/api/v1/config/kill-switch/engage/", { reason });
}

export function resetKillSwitch(): Promise<KillSwitchStatusResponse> {
  return apiPost("/api/v1/config/kill-switch/reset/");
}
