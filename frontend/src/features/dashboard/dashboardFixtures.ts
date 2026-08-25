// frontend/src/features/dashboard/dashboardFixtures.ts
//
// Checkpoint 64.80-F Phase 15: deterministic API fixtures used ONLY by
// tests. This module is imported exclusively from `*.test.tsx` files -
// no production component imports it, and no mock data appears in any
// production dashboard component.
//
// Every fixture is shaped by the GENERATED OpenAPI contract types, so a
// backend contract change breaks these fixtures at type-check time
// rather than letting the tests drift away from reality.
import type {
  MarketDataHealthResponse,
  SessionResponse,
  WorkerRuntimeStatusResponse,
} from "../../common/api/marketDataApi";
import type { SystemReadinessResponse } from "../../common/api/systemApi";

export const SESSION_CLOSED: SessionResponse = {
  session_date: "2026-08-25",
  exchange: "NSE",
  market_open: "2026-08-25T03:45:00Z",
  market_close: "2026-08-25T10:00:00Z",
  square_off_deadline: "2026-08-25T09:45:00Z",
  status: "CLOSED",
};

export const SESSION_OPEN: SessionResponse = { ...SESSION_CLOSED, status: "OPEN" };

export const HEALTH_MARKET_CLOSED: MarketDataHealthResponse = {
  state: "MARKET_CLOSED",
  last_success_at: null,
  last_failure_at: null,
  last_error_safe: "",
  freshness_age_seconds: null,
  consecutive_failures: 0,
  reconnect_count: 0,
  subscription_active: false,
};

export const WORKER_STOPPED: WorkerRuntimeStatusResponse = {
  provider: "DHAN",
  worker_state: "STOPPED",
  token_state: "UNKNOWN",
  watchdog_state: "IDLE",
  last_packet_at: null,
  last_bar_at: null,
  packet_age_seconds: null,
  bar_age_seconds: null,
  reconnect_count: 0,
  consecutive_failures: 0,
  subscribed_instrument_count: 0,
  last_error_safe: "",
  updated_at: null,
  is_configured: true,
};

export const WORKER_RUNNING: WorkerRuntimeStatusResponse = {
  ...WORKER_STOPPED,
  worker_state: "RUNNING",
  watchdog_state: "ARMED",
  last_packet_at: "2026-08-25T09:59:00Z",
  last_bar_at: "2026-08-25T09:59:00Z",
  subscribed_instrument_count: 42,
};

export const READINESS_DEGRADED: SystemReadinessResponse = {
  state: "DEGRADED",
  reasons: ["Market data is not connected.", "No archive reconciliation evidence recorded."],
  database_ok: true,
  market_data_state: "MARKET_CLOSED",
  session_status: "CLOSED",
  kill_switch_engaged: false,
  square_off_unresolved_count: 0,
};

/** A readiness snapshot with an EMPTY reasons list - drives the empty-state
 * assertion (an empty successful list must render EmptyState, never a
 * blank area and never a fabricated reason). */
export const READINESS_READY_NO_REASONS: SystemReadinessResponse = {
  ...READINESS_DEGRADED,
  state: "READY",
  reasons: [],
};
