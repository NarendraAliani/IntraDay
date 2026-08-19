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
export type TradePlanField = components["schemas"]["TradePlanField"];
export type ChannelStatus = components["schemas"]["ChannelStatus"];
export type CommunicationAttempt = components["schemas"]["CommunicationAttempt"];
export type SignalCommunicationHistoryResponse =
  components["schemas"]["SignalCommunicationHistoryResponse"];

export interface ListSignalsParams {
  page?: number;
  pageSize?: number;
  strategyId?: string;
  instrumentId?: string;
  timeframe?: string;
  direction?: string;
  riskStatus?: string;
  orderStatus?: string;
  dateFrom?: string;
  dateTo?: string;
  telegramStatus?: string;
  discordStatus?: string;
  sort?: "newest" | "oldest" | "strategy" | "stock" | "risk_status";
}

/** Server-side paginated and filtered - never fetches an unbounded
 * signal history into the browser. Every filter/sort maps to a REAL
 * query parameter `DjangoSignalRepository.list_signals()` actually
 * applies - never a client-side-only filter over an already-fetched
 * array. Checkpoint 64.9: each item now carries its real TradePlan
 * (`null` for a directional-only strategy) and current Telegram/
 * Discord delivery status (`null` when no attempt exists yet). */
export function listSignals(params: ListSignalsParams = {}): Promise<SignalListResponse> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.strategyId) query.set("strategy_id", params.strategyId);
  if (params.instrumentId) query.set("instrument_id", params.instrumentId);
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.direction) query.set("direction", params.direction);
  if (params.riskStatus) query.set("risk_status", params.riskStatus);
  if (params.orderStatus) query.set("order_status", params.orderStatus);
  if (params.dateFrom) query.set("date_from", params.dateFrom);
  if (params.dateTo) query.set("date_to", params.dateTo);
  if (params.telegramStatus) query.set("telegram_status", params.telegramStatus);
  if (params.discordStatus) query.set("discord_status", params.discordStatus);
  if (params.sort) query.set("sort", params.sort);
  const suffix = query.toString();
  return apiGet<SignalListResponse>(`/api/v1/config/signals/${suffix ? `?${suffix}` : ""}`);
}

/** The FULL communication attempt history (every retry) for one
 * signal - powers the signal detail traceability panel. Never fetched
 * for the whole list (the list view only needs "current status",
 * already included on each `SignalResponse`). */
export function getSignalCommunicationHistory(
  signalId: string,
): Promise<SignalCommunicationHistoryResponse> {
  return apiGet<SignalCommunicationHistoryResponse>(
    `/api/v1/config/signals/${encodeURIComponent(signalId)}/communication/`,
  );
}
