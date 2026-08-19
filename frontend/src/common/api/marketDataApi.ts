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
export type BarResponse = components["schemas"]["BarResponse"];
// Checkpoint 64.3: the live WebSocket worker's own runtime status -
// distinct from MarketDataHealthResponse above (the REST-polling
// health signal) - see worker_runtime_status_views.py's own docstring.
export type WorkerRuntimeStatusResponse = components["schemas"]["WorkerRuntimeStatusResponse"];

export function getMarketSession(): Promise<SessionResponse> {
  return apiGet<SessionResponse>("/api/v1/config/market-data/session/");
}

export function getMarketDataHealth(): Promise<MarketDataHealthResponse> {
  return apiGet<MarketDataHealthResponse>("/api/v1/config/market-data/health/");
}

export function getWorkerRuntimeStatus(): Promise<WorkerRuntimeStatusResponse> {
  return apiGet<WorkerRuntimeStatusResponse>("/api/v1/config/market-data/worker-status/");
}

export function getCurrentQuotes(): Promise<QuoteResponse[]> {
  return apiGet<QuoteResponse[]>("/api/v1/config/market-data/quotes/");
}

export type InstrumentListResponse = components["schemas"]["InstrumentListResponse"];

/** Follow-up to Checkpoint 63.x: the real "all tradable instruments for
 * this exchange" list (Dhan scrip master), not limited to only
 * currently live-observed instruments. `data_source` is always
 * explicit - `"UNAVAILABLE"` (with an empty list) when the real master
 * could not be fetched, never silently treated as success. */
export function listInstruments(exchange: "NSE" | "BSE"): Promise<InstrumentListResponse> {
  return apiGet<InstrumentListResponse>(
    `/api/v1/config/market-data/instruments/?exchange=${exchange}`,
  );
}

/** Performs exactly one live Dhan fetch and returns the freshly
 * recomputed health snapshot - never called automatically, only on
 * explicit user action (the "Refresh" button). */
export function refreshMarketData(): Promise<MarketDataHealthResponse> {
  return apiPost<MarketDataHealthResponse>("/api/v1/config/market-data/refresh/");
}

/** Checkpoint 24A: the most recently aggregated 1-minute bars - reads
 * only already-persisted data, never triggers a live fetch or
 * aggregation itself. */
export function getRecentBars(): Promise<BarResponse[]> {
  return apiGet<BarResponse[]>("/api/v1/config/market-data/bars/");
}
