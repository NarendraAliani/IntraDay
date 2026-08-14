// frontend/src/common/api/backtestingApi.ts
//
// Checkpoint 27: typed wrappers around the backtesting/watchlist/
// strategy-research-status API (/api/v1/config/backtesting/,
// /api/v1/config/watchlists/, /api/v1/config/strategy-engine/
// research-status/), mirroring strategyApi.ts's own established
// pattern - generated OpenAPI contract types only, thin fetch wrappers.
import { apiDelete, apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type BacktestRunRequest = components["schemas"]["BacktestRunRequest"];
export type BacktestResult = components["schemas"]["BacktestResult"];

/** `BacktestResult.configuration`/`.data_quality` are typed `unknown` by
 * the OpenAPI generator (JSONField - see application/contracts/
 * backtesting.py's own docstring for why nested structures are JSONField
 * rather than duplicated serializers). These narrow, UI-only shapes give
 * components a typed view without inventing a second backend contract. */
export interface BacktestConfigurationView {
  instrument_id: string;
  timeframe: string;
  initial_capital: string;
}

export interface DataQualityView {
  data_source: string;
  data_quality: string;
  bar_count: number;
  transaction_cost_assumption: string;
  slippage_assumption: string;
  survivorship_bias_note: string;
}

export function asConfigurationView(result: BacktestResult): BacktestConfigurationView {
  return result.configuration as unknown as BacktestConfigurationView;
}

export function asDataQualityView(result: BacktestResult): DataQualityView {
  return result.data_quality as unknown as DataQualityView;
}
export type WatchlistResponse = components["schemas"]["WatchlistResponse"];
export type WatchlistSaveRequest = components["schemas"]["WatchlistSaveRequest"];
export type ResearchStatusResponse = components["schemas"]["ResearchStatusResponse"];

export function runBacktest(body: BacktestRunRequest): Promise<BacktestResult> {
  return apiPost<BacktestResult>("/api/v1/config/backtesting/run/", body);
}

export function getBacktestResult(backtestId: string): Promise<BacktestResult> {
  return apiGet<BacktestResult>(`/api/v1/config/backtesting/results/${backtestId}/`);
}

export function listBacktestResults(strategyId: string): Promise<BacktestResult[]> {
  return apiGet<BacktestResult[]>(`/api/v1/config/backtesting/strategies/${strategyId}/results/`);
}

export function listWatchlists(): Promise<WatchlistResponse[]> {
  return apiGet<WatchlistResponse[]>("/api/v1/config/watchlists/");
}

export function saveWatchlist(body: WatchlistSaveRequest): Promise<WatchlistResponse> {
  return apiPost<WatchlistResponse>("/api/v1/config/watchlists/save/", body);
}

export function deleteWatchlist(name: string): Promise<void> {
  return apiDelete(`/api/v1/config/watchlists/${name}/delete/`);
}

export function listResearchStatuses(): Promise<ResearchStatusResponse[]> {
  return apiGet<ResearchStatusResponse[]>("/api/v1/config/strategy-engine/research-status/");
}

export function setResearchStatus(
  strategyId: string,
  status: string,
): Promise<ResearchStatusResponse> {
  return apiPost<ResearchStatusResponse>(
    `/api/v1/config/strategy-engine/strategies/${strategyId}/research-status/set/`,
    { status },
  );
}
