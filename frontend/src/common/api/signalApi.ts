// frontend/src/common/api/signalApi.ts
//
// Checkpoint 62.x: typed wrapper around the FIRST read-only signals API
// (/api/v1/config/signals/) - mirrors marketDataApi.ts/strategyApi.ts's
// own established pattern (generated OpenAPI contract types only, thin
// fetch wrapper, no hand-duplicated response shape).
import { apiGet } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type SignalResponse = components["schemas"]["SignalResponse"];
export type SignalListResponse = components["schemas"]["SignalListResponse"];

export interface ListSignalsParams {
  page?: number;
  pageSize?: number;
  strategyId?: string;
  instrumentId?: string;
  timeframe?: string;
  direction?: string;
}

/** Server-side paginated and filtered - never fetches an unbounded
 * signal history into the browser. Every filter maps to a REAL query
 * parameter `DjangoSignalRepository.list_signals()` actually applies -
 * never a client-side-only filter over an already-fetched array. */
export function listSignals(params: ListSignalsParams = {}): Promise<SignalListResponse> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.strategyId) query.set("strategy_id", params.strategyId);
  if (params.instrumentId) query.set("instrument_id", params.instrumentId);
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.direction) query.set("direction", params.direction);
  const suffix = query.toString();
  return apiGet<SignalListResponse>(`/api/v1/config/signals/${suffix ? `?${suffix}` : ""}`);
}
