// frontend/src/common/api/paperTradingApi.ts
//
// Checkpoint 35 Part 4/5: typed wrappers around the paper-trading APIs
// (/api/v1/config/paper-trading/...), mirroring marketDataApi.ts's own
// established pattern - generated OpenAPI contract types only, thin
// fetch wrappers. No response model is hand-duplicated in React.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type PaperOrderResponse = components["schemas"]["PaperOrderResponse"];
export type PaperTradeResponse = components["schemas"]["PaperTradeResponse"];
export type PaperPositionResponse = components["schemas"]["PaperPositionResponse"];
export type PaperFundsResponse = components["schemas"]["PaperFundsResponse"];
export type PaperOrderSubmitRequest = components["schemas"]["PaperOrderSubmitRequest"];
export type PaperOrderSubmitResponse = components["schemas"]["PaperOrderSubmitResponse"];

export function getPaperOrders(): Promise<PaperOrderResponse[]> {
  return apiGet("/api/v1/config/paper-trading/orders/");
}

export function getPaperTrades(): Promise<PaperTradeResponse[]> {
  return apiGet("/api/v1/config/paper-trading/trades/");
}

export function getPaperPositions(): Promise<PaperPositionResponse[]> {
  return apiGet("/api/v1/config/paper-trading/positions/");
}

export function getPaperFunds(): Promise<PaperFundsResponse> {
  return apiGet("/api/v1/config/paper-trading/funds/");
}

export function submitPaperOrder(
  request: PaperOrderSubmitRequest,
): Promise<PaperOrderSubmitResponse> {
  return apiPost("/api/v1/config/paper-trading/orders/submit/", request);
}
