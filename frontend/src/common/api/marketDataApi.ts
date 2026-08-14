// frontend/src/common/api/marketDataApi.ts
//
// Checkpoint 23: typed wrappers around the read-only live market-data
// API (/api/v1/config/market-data/...), mirroring settingsApi.ts's own
// established pattern (Checkpoint 22) - generated OpenAPI contract
// types only, thin fetch wrappers.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type SessionResponse = components["schemas"]["SessionResponse"];
export type MarketDataHealthResponse = components["schemas"]["MarketDataHealthResponse"];
export type QuoteResponse = components["schemas"]["QuoteResponse"];

export function getMarketSession(): Promise<SessionResponse> {
  return apiGet<SessionResponse>("/api/v1/config/market-data/session/");
}

export function getMarketDataHealth(): Promise<MarketDataHealthResponse> {
  return apiGet<MarketDataHealthResponse>("/api/v1/config/market-data/health/");
}

export function getCurrentQuotes(): Promise<QuoteResponse[]> {
  return apiGet<QuoteResponse[]>("/api/v1/config/market-data/quotes/");
}

/** Performs exactly one live Dhan fetch and returns the freshly
 * recomputed health snapshot - never called automatically, only on
 * explicit user action (the "Refresh" button). */
export function refreshMarketData(): Promise<MarketDataHealthResponse> {
  return apiPost<MarketDataHealthResponse>("/api/v1/config/market-data/refresh/");
}
