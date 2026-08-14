// frontend/src/common/api/settingsApi.ts
//
// Checkpoint 22: typed wrappers around the operational provider-settings
// API (/api/v1/config/settings/...), mirroring configApi.ts's own
// established pattern (real generated OpenAPI types, thin fetch
// wrappers, no hand-duplicated response shapes).
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type DhanSettingsResponse = components["schemas"]["DhanSettingsResponse"];
export type DhanSettingsSaveRequest = components["schemas"]["DhanSettingsSaveRequest"];
export type TelegramSettingsResponse = components["schemas"]["TelegramSettingsResponse"];
export type TelegramSettingsSaveRequest = components["schemas"]["TelegramSettingsSaveRequest"];
export type DiscordSettingsResponse = components["schemas"]["DiscordSettingsResponse"];
export type DiscordSettingsSaveRequest = components["schemas"]["DiscordSettingsSaveRequest"];
export type ConnectionStatusResponse = components["schemas"]["ConnectionStatusResponse"];

export type ProviderId = "dhan" | "telegram" | "discord";

export function getDhanSettings(): Promise<DhanSettingsResponse> {
  return apiGet<DhanSettingsResponse>("/api/v1/config/settings/dhan/");
}

export function saveDhanSettings(body: DhanSettingsSaveRequest): Promise<DhanSettingsResponse> {
  return apiPost<DhanSettingsResponse>("/api/v1/config/settings/dhan/save/", body);
}

export function testDhanConnection(): Promise<ConnectionStatusResponse> {
  return apiPost<ConnectionStatusResponse>("/api/v1/config/settings/dhan/test/");
}

export function getTelegramSettings(): Promise<TelegramSettingsResponse> {
  return apiGet<TelegramSettingsResponse>("/api/v1/config/settings/telegram/");
}

export function saveTelegramSettings(
  body: TelegramSettingsSaveRequest,
): Promise<TelegramSettingsResponse> {
  return apiPost<TelegramSettingsResponse>("/api/v1/config/settings/telegram/save/", body);
}

export function testTelegramConnection(): Promise<ConnectionStatusResponse> {
  return apiPost<ConnectionStatusResponse>("/api/v1/config/settings/telegram/test/");
}

export function getDiscordSettings(): Promise<DiscordSettingsResponse> {
  return apiGet<DiscordSettingsResponse>("/api/v1/config/settings/discord/");
}

export function saveDiscordSettings(
  body: DiscordSettingsSaveRequest,
): Promise<DiscordSettingsResponse> {
  return apiPost<DiscordSettingsResponse>("/api/v1/config/settings/discord/save/", body);
}

export function testDiscordConnection(): Promise<ConnectionStatusResponse> {
  return apiPost<ConnectionStatusResponse>("/api/v1/config/settings/discord/test/");
}

/** Last-recorded status only - never performs a live check itself. */
export function getProviderStatus(provider: ProviderId): Promise<ConnectionStatusResponse> {
  return apiGet<ConnectionStatusResponse>(
    `/api/v1/config/settings/${encodeURIComponent(provider)}/status/`,
  );
}
