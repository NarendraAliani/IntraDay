// frontend/src/common/api/paperSessionApi.ts
//
// Checkpoint 64.68 §19: typed wrappers around the REPLAY PAPER SESSION
// lifecycle API. Follows `paperTradingApi.ts`'s established pattern
// exactly - generated OpenAPI contract types only, thin fetch wrappers,
// no hand-duplicated response model.
//
// SAFETY: every endpoint below is a PAPER endpoint. There is no
// live-broker or live-order call in this module, because no such
// endpoint exists in the backend at all.
import { apiGet, apiPost } from "./client";
import type { components } from "@shared/generated_contracts/api-types";

export type PaperSessionResponse = components["schemas"]["PaperSessionResponse"];
export type PaperSessionCreateRequest = components["schemas"]["PaperSessionCreateRequest"];
export type PaperSessionAccount = components["schemas"]["PaperSessionAccount"];
export type PaperSessionPosition = components["schemas"]["PaperSessionPosition"];
export type PaperSessionTrade = components["schemas"]["PaperSessionTrade"];
export type PaperSessionSignal = components["schemas"]["PaperSessionSignal"];

const BASE = "/api/v1/config/paper-trading/session/";

export function getPaperSession(): Promise<PaperSessionResponse> {
  return apiGet(BASE);
}

export function configurePaperSession(
  request: PaperSessionCreateRequest,
): Promise<PaperSessionResponse> {
  return apiPost(`${BASE}configure/`, request);
}

export function startPaperSession(): Promise<PaperSessionResponse> {
  return apiPost(`${BASE}start/`, {});
}

export function pausePaperSession(): Promise<PaperSessionResponse> {
  return apiPost(`${BASE}pause/`, {});
}

export function resumePaperSession(): Promise<PaperSessionResponse> {
  return apiPost(`${BASE}resume/`, {});
}

export function stopPaperSession(): Promise<PaperSessionResponse> {
  return apiPost(`${BASE}stop/`, {});
}

export function resetPaperSession(): Promise<PaperSessionResponse> {
  return apiPost(`${BASE}reset/`, {});
}

export function stepPaperSession(): Promise<PaperSessionResponse> {
  return apiPost(`${BASE}step/`, {});
}
