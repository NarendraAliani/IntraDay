// frontend/src/common/api/marketDataSyncApi.ts
//
// Typed wrappers around the manual historical-market-data-sync API
// (/api/v1/config/market-data/sync-runs/) - the Settings page's "fetch
// real Dhan data into the database" trigger. Mirrors
// backtestingApi.ts's own createHistoricalBacktestRun/
// getHistoricalBacktestRunProgress pattern exactly for the analogous
// resource.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type MarketDataSyncRunRequest = components["schemas"]["MarketDataSyncRunRequest"];
export type MarketDataSyncRunCreated = components["schemas"]["MarketDataSyncRunCreated"];
export type MarketDataSyncRunProgress = components["schemas"]["MarketDataSyncRunProgress"];

export function createMarketDataSyncRun(
  body: MarketDataSyncRunRequest,
): Promise<MarketDataSyncRunCreated> {
  return apiPost<MarketDataSyncRunCreated>("/api/v1/config/market-data/sync-runs/", body);
}

export function getMarketDataSyncRunProgress(runId: string): Promise<MarketDataSyncRunProgress> {
  return apiGet<MarketDataSyncRunProgress>(`/api/v1/config/market-data/sync-runs/${runId}/progress/`);
}
