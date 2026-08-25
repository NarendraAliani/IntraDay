// frontend/src/features/dashboard/dashboardModel.test.ts
//
// Checkpoint 64.80-F: unit tests for the SINGLE market/worker status
// selector. These guard the two rules that matter most:
//   1. Market state is only ever what the backend said - a missing
//      session response is UNKNOWN, never optimistically OPEN/CLOSED.
//   2. `WorkerRuntimeStatus` semantics are the backend's - an
//      unrecognized value degrades to UNKNOWN rather than becoming a
//      new, frontend-invented status word.
import { describe, expect, it } from "vitest";

import {
  TONE_BADGE_CLASS,
  describeMarketSession,
  describeProviderHealth,
  describeSystemReadiness,
  describeWorkerState,
  formatAgeSeconds,
  formatTimestamp,
  normalizeWorkerState,
} from "./dashboardModel";
import {
  HEALTH_MARKET_CLOSED,
  READINESS_DEGRADED,
  SESSION_CLOSED,
  SESSION_OPEN,
  WORKER_RUNNING,
  WORKER_STOPPED,
} from "./dashboardFixtures";

describe("describeMarketSession", () => {
  it("reports CLOSED as NSE MARKET CLOSED with an inactive (not error) tone", () => {
    const result = describeMarketSession(SESSION_CLOSED);
    expect(result.label).toBe("NSE MARKET CLOSED");
    expect(result.tone).toBe("INACTIVE");
  });

  it("reports OPEN as healthy", () => {
    expect(describeMarketSession(SESSION_OPEN).tone).toBe("HEALTHY");
  });

  it("reports PRE_OPEN distinctly from OPEN", () => {
    const preOpen = describeMarketSession({ ...SESSION_CLOSED, status: "PRE_OPEN" });
    expect(preOpen.label).toBe("NSE PRE-OPEN");
    expect(preOpen.tone).toBe("WARNING");
  });

  it("reports UNKNOWN - never a guess - when no session response is available", () => {
    const result = describeMarketSession(null);
    expect(result.label).toBe("NSE MARKET STATUS UNKNOWN");
    expect(result.tone).toBe("UNAVAILABLE");
    expect(result.detail).toMatch(/NOT being guessed/i);
  });
});

describe("normalizeWorkerState", () => {
  it.each(["RUNNING", "STOPPED", "DEGRADED", "UNKNOWN"] as const)(
    "recognizes the backend value %s exactly",
    (value) => {
      expect(normalizeWorkerState(value)).toBe(value);
    },
  );

  it("degrades an unrecognized backend value to UNKNOWN rather than inventing a status", () => {
    expect(normalizeWorkerState("SOMETHING_NEW")).toBe("UNKNOWN");
    expect(normalizeWorkerState("")).toBe("UNKNOWN");
    expect(normalizeWorkerState(null)).toBe("UNKNOWN");
    expect(normalizeWorkerState(undefined)).toBe("UNKNOWN");
  });
});

describe("describeWorkerState", () => {
  it("treats STOPPED as inactive, not as a failure", () => {
    const result = describeWorkerState(WORKER_STOPPED);
    expect(result.label).toBe("STOPPED");
    expect(result.tone).toBe("INACTIVE");
  });

  it("treats RUNNING as healthy", () => {
    expect(describeWorkerState(WORKER_RUNNING).tone).toBe("HEALTHY");
  });

  it("treats DEGRADED as a warning", () => {
    expect(
      describeWorkerState({ ...WORKER_STOPPED, worker_state: "DEGRADED" }).tone,
    ).toBe("WARNING");
  });

  it("reports NOT CONFIGURED when the provider has no credentials configured", () => {
    const result = describeWorkerState({ ...WORKER_STOPPED, is_configured: false });
    expect(result.label).toBe("NOT CONFIGURED");
    expect(result.tone).toBe("UNAVAILABLE");
  });

  it("reports UNAVAILABLE when the worker API could not be read", () => {
    expect(describeWorkerState(null).tone).toBe("UNAVAILABLE");
  });
});

describe("describeProviderHealth and describeSystemReadiness", () => {
  it("maps MARKET_CLOSED to an inactive tone with an explanatory detail", () => {
    const result = describeProviderHealth(HEALTH_MARKET_CLOSED);
    expect(result.label).toBe("MARKET CLOSED");
    expect(result.tone).toBe("INACTIVE");
  });

  it("maps AUTHENTICATION_FAILED to BLOCKED", () => {
    expect(
      describeProviderHealth({ ...HEALTH_MARKET_CLOSED, state: "AUTHENTICATION_FAILED" }).tone,
    ).toBe("BLOCKED");
  });

  it("reports NOT AVAILABLE when health could not be read", () => {
    expect(describeProviderHealth(null).label).toBe("NOT AVAILABLE");
  });

  it("surfaces the backend's own readiness reasons verbatim", () => {
    const result = describeSystemReadiness(READINESS_DEGRADED);
    expect(result.label).toBe("DEGRADED");
    expect(result.detail).toContain("No archive reconciliation evidence recorded.");
  });
});

describe("status tone tokens", () => {
  it("maps every tone onto an existing design-system badge class", () => {
    for (const badgeClass of Object.values(TONE_BADGE_CLASS)) {
      expect(badgeClass).toMatch(/^badge--/);
    }
  });
});

describe("formatting helpers are honest about missing values", () => {
  it("renders a null timestamp as Never, not as a fabricated date", () => {
    expect(formatTimestamp(null)).toBe("Never");
    expect(formatTimestamp(undefined)).toBe("Never");
  });

  it("renders an unparseable timestamp as Not available", () => {
    expect(formatTimestamp("not-a-date")).toBe("Not available");
  });

  it("renders a null age as Not available, never as 0 seconds", () => {
    expect(formatAgeSeconds(null)).toBe("Not available");
    expect(formatAgeSeconds(0)).toBe("0s ago");
  });

  it("scales age units", () => {
    expect(formatAgeSeconds(90)).toBe("2m ago");
    expect(formatAgeSeconds(7200)).toBe("2h ago");
  });
});
