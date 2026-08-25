// frontend/src/features/dashboard/dashboardModel.ts
//
// Checkpoint 64.80-F: the SINGLE place the Application Dashboard turns a
// backend status contract into a user-facing label + semantic tone.
//
// Phase 3's explicit rule: business-critical market state is never
// calculated independently in multiple frontend components. The market
// is OPEN/PRE_OPEN/CLOSED because `GET /api/v1/config/market-data/
// session/` said so (`SessionResponse.status`) - this module only maps
// that backend answer to presentation, it never computes it from the
// browser clock, and there is deliberately no fallback branch that
// guesses a session state when the API is unavailable (that case is
// UNKNOWN, honestly).
//
// Phase 4's explicit rule: `WorkerRuntimeStatus` semantics
// (RUNNING/STOPPED/DEGRADED/UNKNOWN) are the backend's, not ours. The
// backend serializes `worker_state` as a bare `string` (see
// worker_runtime_status_views.py), so this module *recognizes* the four
// documented values and maps anything else to UNKNOWN - it never
// invents a fifth status and never reinterprets one value as another.
import type {
  MarketDataHealthResponse,
  SessionResponse,
  WorkerRuntimeStatusResponse,
} from "../../common/api/marketDataApi";
import type { SystemReadinessResponse } from "../../common/api/systemApi";
import type { IconName } from "../../common/icons/Icon";

/**
 * The dashboard's semantic status vocabulary (Phase 12). Each tone maps
 * onto an EXISTING `badge--*` design-system class - no new colors are
 * hard-coded anywhere in this checkpoint.
 *
 * - HEALTHY    - working as intended right now
 * - WARNING    - working but degraded / needs attention
 * - BLOCKED    - actively failing or explicitly halted
 * - INACTIVE   - deliberately off / not running (NOT an error)
 * - UNAVAILABLE- the backend does not expose this yet, or the call failed
 */
export type StatusTone = "HEALTHY" | "WARNING" | "BLOCKED" | "INACTIVE" | "UNAVAILABLE";

/** Existing design-system badge classes (styles.css) - reused, never redefined. */
export const TONE_BADGE_CLASS: Record<StatusTone, string> = {
  HEALTHY: "badge--active",
  WARNING: "badge--pending",
  BLOCKED: "badge--danger",
  INACTIVE: "badge--historical",
  UNAVAILABLE: "badge--historical",
};

/** Icon prefix so status is never communicated by color alone (Phase 17),
 * matching ActiveBadge/ConnectionStatusBadge's existing convention.
 *
 * Checkpoint 64.80-F2 Phase 8: these were Unicode circle/cross glyphs.
 * They now name icons in the ONE icon system, because a Unicode symbol
 * rendered next to real SVG iconography is exactly the "competing icon
 * systems" the checkpoint forbids - and glyph rendering varied per
 * platform font, which a status marker cannot afford. The semantic
 * status vocabulary itself is UNCHANGED (Phase 11). */
export const TONE_ICON_NAME: Record<StatusTone, IconName> = {
  HEALTHY: "success",
  WARNING: "warning",
  BLOCKED: "error",
  INACTIVE: "info",
  UNAVAILABLE: "info",
};

export interface StatusDescriptor {
  /** Short, screen-readable status word shown inside the badge. */
  label: string;
  tone: StatusTone;
  /** One plain-English sentence explaining what the label means. */
  detail: string;
}

// --- Market session -------------------------------------------------

export type MarketSessionStatus = SessionResponse["status"] | "UNKNOWN";

const MARKET_LABEL: Record<MarketSessionStatus, string> = {
  OPEN: "NSE MARKET OPEN",
  PRE_OPEN: "NSE PRE-OPEN",
  CLOSED: "NSE MARKET CLOSED",
  UNKNOWN: "NSE MARKET STATUS UNKNOWN",
};

const MARKET_TONE: Record<MarketSessionStatus, StatusTone> = {
  OPEN: "HEALTHY",
  PRE_OPEN: "WARNING",
  CLOSED: "INACTIVE",
  UNKNOWN: "UNAVAILABLE",
};

const MARKET_DETAIL: Record<MarketSessionStatus, string> = {
  OPEN: "The exchange session is live. Market data may be flowing.",
  PRE_OPEN: "The pre-open call auction window is in progress. Continuous trading has not started.",
  CLOSED: "The exchange session is not running. No live market data is expected right now.",
  UNKNOWN:
    "The session API could not be read, so the market state is not known. It is NOT being guessed from your device clock.",
};

/** The ONE market-state selector for the whole dashboard. Pass `null`
 * when the session API failed or has not returned - the answer is
 * UNKNOWN, never an optimistic default. */
export function describeMarketSession(session: SessionResponse | null): StatusDescriptor {
  const status: MarketSessionStatus = session ? session.status : "UNKNOWN";
  return { label: MARKET_LABEL[status], tone: MARKET_TONE[status], detail: MARKET_DETAIL[status] };
}

// --- Worker runtime status ------------------------------------------

export type WorkerState = "RUNNING" | "STOPPED" | "DEGRADED" | "UNKNOWN";

const KNOWN_WORKER_STATES: readonly WorkerState[] = ["RUNNING", "STOPPED", "DEGRADED", "UNKNOWN"];

/** Recognizes the backend's four documented `WorkerRuntimeStatus`
 * values. Anything else - including an empty string - is reported as
 * UNKNOWN rather than silently rendered as a new status word. */
export function normalizeWorkerState(rawState: string | null | undefined): WorkerState {
  const candidate = (rawState ?? "").trim().toUpperCase();
  return KNOWN_WORKER_STATES.includes(candidate as WorkerState)
    ? (candidate as WorkerState)
    : "UNKNOWN";
}

const WORKER_TONE: Record<WorkerState, StatusTone> = {
  RUNNING: "HEALTHY",
  DEGRADED: "WARNING",
  STOPPED: "INACTIVE",
  UNKNOWN: "UNAVAILABLE",
};

const WORKER_DETAIL: Record<WorkerState, string> = {
  RUNNING: "The market-data worker process is running and reporting runtime status.",
  DEGRADED: "The worker is running but the backend has flagged it as degraded.",
  STOPPED: "The market-data worker is not running. No live packets are being ingested.",
  UNKNOWN: "The worker has not reported a recognized runtime state.",
};

export function describeWorkerState(
  worker: WorkerRuntimeStatusResponse | null,
): StatusDescriptor {
  const state = normalizeWorkerState(worker?.worker_state);
  if (worker && !worker.is_configured) {
    return {
      label: "NOT CONFIGURED",
      tone: "UNAVAILABLE",
      detail:
        "No market-data provider credentials are configured, so the worker cannot report a runtime state.",
    };
  }
  return { label: state, tone: WORKER_TONE[state], detail: WORKER_DETAIL[state] };
}

// --- Data provider health -------------------------------------------

type HealthState = MarketDataHealthResponse["state"];

const HEALTH_LABEL: Record<HealthState, string> = {
  CONNECTED_FRESH: "CONNECTED — FRESH",
  CONNECTED_STALE: "CONNECTED — STALE",
  DISCONNECTED: "DISCONNECTED",
  AUTHENTICATION_FAILED: "AUTHENTICATION FAILED",
  ERROR: "ERROR",
  MARKET_CLOSED: "MARKET CLOSED",
};

const HEALTH_TONE: Record<HealthState, StatusTone> = {
  CONNECTED_FRESH: "HEALTHY",
  CONNECTED_STALE: "WARNING",
  DISCONNECTED: "INACTIVE",
  AUTHENTICATION_FAILED: "BLOCKED",
  ERROR: "BLOCKED",
  MARKET_CLOSED: "INACTIVE",
};

export function describeProviderHealth(
  health: MarketDataHealthResponse | null,
): StatusDescriptor {
  if (!health) {
    return {
      label: "NOT AVAILABLE",
      tone: "UNAVAILABLE",
      detail: "The market-data health API could not be read.",
    };
  }
  return {
    label: HEALTH_LABEL[health.state],
    tone: HEALTH_TONE[health.state],
    detail:
      health.state === "MARKET_CLOSED"
        ? "The provider reports the exchange session is closed, so no fresh data is expected."
        : health.last_error_safe || "Provider connection state as reported by the backend.",
  };
}

// --- Composed system readiness --------------------------------------

type ReadinessState = SystemReadinessResponse["state"];

const READINESS_TONE: Record<ReadinessState, StatusTone> = {
  READY: "HEALTHY",
  DEGRADED: "WARNING",
  HALTED: "BLOCKED",
  SQUARE_OFF_UNRESOLVED: "BLOCKED",
  FAILED: "BLOCKED",
};

export function describeSystemReadiness(
  readiness: SystemReadinessResponse | null,
): StatusDescriptor {
  if (!readiness) {
    return {
      label: "NOT AVAILABLE",
      tone: "UNAVAILABLE",
      detail: "The composed system-readiness API could not be read.",
    };
  }
  return {
    label: readiness.state,
    tone: READINESS_TONE[readiness.state],
    detail:
      readiness.reasons.length > 0
        ? readiness.reasons.join(" ")
        : "The backend reports no outstanding readiness reasons.",
  };
}

// --- Formatting helpers ---------------------------------------------

/** Renders a nullable ISO timestamp honestly - "Never" rather than a
 * fabricated placeholder date. */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Not available";
  return parsed.toLocaleString();
}

export function formatAgeSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not available";
  if (value < 60) return `${Math.round(value)}s ago`;
  if (value < 3600) return `${Math.round(value / 60)}m ago`;
  return `${Math.round(value / 3600)}h ago`;
}
