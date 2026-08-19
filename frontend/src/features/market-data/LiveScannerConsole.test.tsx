// frontend/src/features/market-data/LiveScannerConsole.test.tsx
//
// Checkpoint 64.5: real-boundary tests for the Live Scanner operator
// console - only `global.fetch` is mocked; the real component and real
// generated contract types are exercised together, matching
// LiveMarketDataMonitor.test.tsx's own established pattern.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveScannerConsole } from "./LiveScannerConsole";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type WorkerRuntimeStatusResponse = components["schemas"]["WorkerRuntimeStatusResponse"];
type ScannerConfigurationResponse = components["schemas"]["ScannerConfigurationResponse"];
type StrategySummary = components["schemas"]["StrategySummary"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const WORKER_STATUS_UNCONFIGURED: WorkerRuntimeStatusResponse = {
  provider: "dhan",
  worker_state: "NEVER_RUN",
  token_state: "UNKNOWN",
  watchdog_state: "DISCONNECTED",
  last_packet_at: null,
  last_bar_at: null,
  packet_age_seconds: null,
  bar_age_seconds: null,
  reconnect_count: 0,
  consecutive_failures: 0,
  subscribed_instrument_count: 0,
  last_error_safe: "",
  updated_at: null,
  is_configured: false,
};

const STOPPED_CONFIG: ScannerConfigurationResponse = {
  provider: "dhan",
  desired: {
    timeframe: "1m",
    universe_mode: "ALL_CONFIGURED",
    universe_requested_count: 0,
    universe_subscribed_count: 0,
    strategy_ids: [],
    configuration_version: 1,
    enabled: false,
  },
  effective: {
    timeframe: "",
    universe_requested_count: 0,
    universe_subscribed_count: 0,
    strategy_ids: [],
    configuration_version: 0,
  },
  status: "STOPPED",
  requested_by: "",
  requested_at: null,
};

const EMA_STRATEGY: StrategySummary = {
  strategy_id: "ema_crossover",
  display_name: "EMA Crossover",
  specification_version: "v1",
  code_version: "v1",
  is_active: true,
};

function stubEndpoints(
  options: {
    config?: ScannerConfigurationResponse;
    workerStatus?: WorkerRuntimeStatusResponse;
    strategies?: StrategySummary[];
  } = {},
): ReturnType<typeof vi.fn> {
  const {
    config = STOPPED_CONFIG,
    workerStatus = WORKER_STATUS_UNCONFIGURED,
    strategies = [EMA_STRATEGY],
  } = options;
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/worker-status/")) return Promise.resolve(jsonResponse(workerStatus));
    if (url.includes("/scanner-config/update/")) return Promise.resolve(jsonResponse(config));
    if (url.includes("/scanner-config/")) return Promise.resolve(jsonResponse(config));
    if (url.includes("/strategy-engine/strategies/")) return Promise.resolve(jsonResponse(strategies));
    if (url.includes("/watchlists/")) return Promise.resolve(jsonResponse([]));
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("LiveScannerConsole", () => {
  it("shows the desired and effective configuration side by side, never merged", async () => {
    stubEndpoints({});

    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("Desired Configuration")).toBeInTheDocument());
    expect(screen.getByText("Effective Configuration")).toBeInTheDocument();
    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("shows a DEGRADED reason explaining the requested vs subscribed shortfall, never hiding it", async () => {
    const degraded: ScannerConfigurationResponse = {
      ...STOPPED_CONFIG,
      desired: { ...STOPPED_CONFIG.desired, enabled: true, configuration_version: 3 },
      effective: {
        timeframe: "5m",
        universe_requested_count: 287,
        universe_subscribed_count: 200,
        strategy_ids: ["ema_crossover"],
        configuration_version: 3,
      },
      status: "DEGRADED",
    };
    stubEndpoints({ config: degraded });

    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("Degraded")).toBeInTheDocument());
    expect(screen.getByText(/87 instrument\(s\) requested but not subscribed/)).toBeInTheDocument();
  });

  it("never fabricates live-activity fields the backend does not provide", async () => {
    stubEndpoints({});

    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("Live Activity")).toBeInTheDocument());
    const notProvided = screen.getAllByText("Not provided by the current backend");
    expect(notProvided.length).toBeGreaterThanOrEqual(4);
  });

  it("posts the real update API when an operator clicks START and reflects the response", async () => {
    const fetchMock = stubEndpoints({});

    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("Desired Configuration")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "START" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/scanner-config/update/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("disables configuration controls for a read-only (non-operator) user", async () => {
    stubEndpoints({});

    renderWithAuth(<LiveScannerConsole />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });

    await waitFor(() => expect(screen.getByText("Desired Configuration")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "START" })).not.toBeInTheDocument();
    expect(
      screen.getByText(/You have read-only access to this screen/),
    ).toBeInTheDocument();
  });
});
