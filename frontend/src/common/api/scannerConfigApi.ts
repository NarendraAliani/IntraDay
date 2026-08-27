// frontend/src/common/api/scannerConfigApi.ts
//
// Checkpoint 64.5: typed wrappers around the live scanner control-plane
// API (/api/v1/config/market-data/scanner-config/...), mirroring
// strategyApi.ts's own established pattern - generated OpenAPI contract
// types only, no hand-duplicated response shapes. This is the ONLY
// place the frontend writes the DESIRED scanner configuration or reads
// the combined desired/effective state - the Live Scanner console
// consumes it exclusively, never a second endpoint invented because
// the UI came later than the backend.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type ScannerConfigurationState = components["schemas"]["ScannerConfigurationState"];
export type ScannerConfigurationResponse = components["schemas"]["ScannerConfigurationResponse"];
export type ScannerConfigurationUpdateRequest =
  components["schemas"]["ScannerConfigurationUpdateRequest"];
// Checkpoint 64.93: the notification-channel registry row - reused
// verbatim from the generated contract, never a hand-written shape.
export type NotificationChannel = components["schemas"]["NotificationChannel"];

export function getScannerConfiguration(): Promise<ScannerConfigurationResponse> {
  return apiGet<ScannerConfigurationResponse>("/api/v1/config/market-data/scanner-config/");
}

export function updateScannerConfiguration(
  body: ScannerConfigurationUpdateRequest,
): Promise<ScannerConfigurationResponse> {
  return apiPost<ScannerConfigurationResponse>(
    "/api/v1/config/market-data/scanner-config/update/",
    body,
  );
}

// Checkpoint 64.93 Part D: the registry-driven notification-channel
// list - the multi-select renders from this, never a hardcoded
// Telegram/Discord pair.
export function listNotificationChannels(): Promise<NotificationChannel[]> {
  return apiGet<NotificationChannel[]>("/api/v1/config/notifications/channels/");
}
