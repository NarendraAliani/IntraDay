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
type LivePaperReadinessResponse = components["schemas"]["LivePaperReadinessResponse"];
type LivePaperSessionResponse = components["schemas"]["LivePaperSessionResponse"];

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
    strategy_ids: ["ema_crossover"],
    configuration_version: 1,
    enabled: false,
    notification_channels: [],
  },
  effective: {
    timeframe: "",
    universe_requested_count: 0,
    universe_subscribed_count: 0,
    strategy_ids: [],
    configuration_version: 0,
    notification_channels: [],
  },
  status: "STOPPED",
  requested_by: "",
  requested_at: null,
};

const NOTIFICATION_CHANNELS: components["schemas"]["NotificationChannel"][] = [
  { channel_id: "telegram", display_name: "Telegram", configured: true, enabled: true },
  { channel_id: "discord", display_name: "Discord", configured: true, enabled: true },
];

const EMPTY_WORKBENCH: components["schemas"]["LivePaperWorkbenchResponse"] = {
  readiness: {
    state: "READY_FOR_PAPER",
    provider: "dhan",
    credential_state: "VALID",
    credential_expiry: null,
    provider_state: "HEALTHY",
    watchdog_state: "HEALTHY",
    market_state: "OPEN",
    paper_execution_state: "ENABLED",
    real_trading_state: "DISABLED",
    can_start: true,
    safe_reason: "All readiness checks passed.",
    // Checkpoint FRONTEND-1: `remediation` is non-nullable on
    // `LivePaperReadinessResponse` (backend: `serializers.CharField()`,
    // no `allow_null=True`) - see the sibling `.64_93.test.tsx` fixture
    // for the full explanation. Same real backend value reused here.
    remediation:
      "Start the Live Paper Session explicitly - this gate reporting READY never starts it automatically.",
  },
  checklist: [],
  session_state: "STOPPED",
  effective_session_configuration: {
    desired_configuration_version: 1,
    desired_universe_mode: "ALL_CONFIGURED",
    desired_timeframe: "1m",
    desired_strategy_ids: [],
    desired_requested_by: "",
    effective_configuration_version: 0,
    effective_timeframe: "",
    effective_strategy_ids: [],
    effective_stock_count: 0,
    effective_requested_stock_count: 0,
    drift: false,
  },
  scanner_progress: null,
};

const EMA_STRATEGY: StrategySummary = {
  strategy_id: "ema_crossover",
  display_name: "EMA Crossover",
  specification_version: "v1",
  code_version: "v1",
  is_active: true,
};

const READINESS_BLOCKED: LivePaperReadinessResponse = {
  state: "CREDENTIAL_EXPIRED",
  provider: "dhan",
  credential_state: "EXPIRED",
  credential_expiry: "2026-07-25T07:10:00Z",
  provider_state: "NEVER_REPORTED",
  watchdog_state: "NEVER_REPORTED",
  market_state: "OPEN",
  paper_execution_state: "ENABLED",
  real_trading_state: "DISABLED",
  can_start: false,
  safe_reason: "Dhan access token has expired.",
  remediation: "Renew the Dhan access token and revalidate configuration.",
};

const READINESS_READY: LivePaperReadinessResponse = {
  ...READINESS_BLOCKED,
  state: "READY_FOR_PAPER",
  credential_state: "VALID",
  provider_state: "HEALTHY",
  watchdog_state: "HEALTHY",
  can_start: true,
  safe_reason: "All readiness checks passed.",
};

const SESSION_STARTED: LivePaperSessionResponse = {
  accepted: true,
  state: "STARTING",
  message: "Live Paper Session start requested.",
  remediation: null,
  configuration_version: 2,
  enabled: true,
};

function stubEndpoints(
  options: {
    config?: ScannerConfigurationResponse;
    workerStatus?: WorkerRuntimeStatusResponse;
    strategies?: StrategySummary[];
    readiness?: LivePaperReadinessResponse;
    startResponse?: LivePaperSessionResponse;
  } = {},
): ReturnType<typeof vi.fn> {
  const {
    config = STOPPED_CONFIG,
    workerStatus = WORKER_STATUS_UNCONFIGURED,
    strategies = [EMA_STRATEGY],
    readiness = READINESS_BLOCKED,
    startResponse = SESSION_STARTED,
  } = options;
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/live-paper-session/start/")) {
      return Promise.resolve(jsonResponse(startResponse));
    }
    if (url.includes("/live-paper-session/stop/")) {
      return Promise.resolve(
        jsonResponse({ ...startResponse, accepted: true, state: "STOPPING", enabled: false }),
      );
    }
    if (url.includes("/live-paper-readiness/")) return Promise.resolve(jsonResponse(readiness));
    if (url.includes("/live-paper-workbench/"))
      return Promise.resolve(
        jsonResponse({ ...EMPTY_WORKBENCH, readiness, session_state: config.desired.enabled ? "RUNNING" : "STOPPED" }),
      );
    if (url.includes("/worker-status/")) return Promise.resolve(jsonResponse(workerStatus));
    if (url.includes("/scanner-config/update/")) return Promise.resolve(jsonResponse(config));
    if (url.includes("/scanner-config/")) return Promise.resolve(jsonResponse(config));
    if (url.includes("/strategy-engine/strategies/")) return Promise.resolve(jsonResponse(strategies));
    if (url.includes("/notifications/channels/")) return Promise.resolve(jsonResponse(NOTIFICATION_CHANNELS));
    if (url.includes("/config/signals/")) return Promise.resolve(jsonResponse({ items: [], total_count: 0, page: 1, page_size: 15 }));
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

  it("never fabricates scanner-runtime fields the backend does not provide", async () => {
    stubEndpoints({});

    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("Scanner Runtime")).toBeInTheDocument());
    // EMPTY_WORKBENCH.scanner_progress is null (no scan has ever run) - every
    // field is honestly "Not provided", never a fabricated 0/placeholder.
    const notProvided = screen.getAllByText("Not provided by the current backend");
    expect(notProvided.length).toBeGreaterThanOrEqual(4);
  });

  it("Checkpoint 64.13: disables START LIVE PAPER SESSION while readiness is BLOCKED", async () => {
    stubEndpoints({ readiness: READINESS_BLOCKED });

    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("NOT READY")).toBeInTheDocument());
    const startButton = screen.getByRole("button", { name: "START LIVE PAPER SESSION" });
    expect(startButton).toBeDisabled();
    expect(screen.getByText("Dhan access token has expired.")).toBeInTheDocument();
  });

  it("Checkpoint 64.13: enables START and calls the real gated start endpoint when readiness is READY", async () => {
    const fetchMock = stubEndpoints({ readiness: READINESS_READY });

    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("READY TO SCAN")).toBeInTheDocument());
    const startButton = screen.getByRole("button", { name: "START LIVE PAPER SESSION" });
    expect(startButton).not.toBeDisabled();

    fireEvent.click(startButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/live-paper-session/start/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("Checkpoint 64.13: shows STOP LIVE PAPER SESSION and calls the real gated stop endpoint for a running session", async () => {
    const runningConfig: ScannerConfigurationResponse = {
      ...STOPPED_CONFIG,
      desired: { ...STOPPED_CONFIG.desired, enabled: true },
      status: "EFFECTIVE",
    };
    const fetchMock = stubEndpoints({ config: runningConfig, readiness: READINESS_READY });

    renderWithAuth(<LiveScannerConsole />);

    const stopButton = await waitFor(() =>
      screen.getByRole("button", { name: "STOP LIVE PAPER SESSION" }),
    );
    fireEvent.click(stopButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/live-paper-session/stop/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("Checkpoint 64.13: real trading always reads DISABLED regardless of readiness state", async () => {
    stubEndpoints({ readiness: READINESS_READY });

    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText(/Real Trading: DISABLED/)).toBeInTheDocument());
  });

  it("Checkpoint 64.17 §12: requires explicit confirmation before applying a configuration change to a RUNNING session", async () => {
    const runningConfig: ScannerConfigurationResponse = {
      ...STOPPED_CONFIG,
      desired: { ...STOPPED_CONFIG.desired, enabled: true },
      status: "EFFECTIVE",
    };
    const fetchMock = stubEndpoints({ config: runningConfig, readiness: READINESS_READY });

    renderWithAuth(<LiveScannerConsole />);

    const applyButton = await waitFor(() =>
      screen.getByRole("button", { name: "Apply Configuration" }),
    );
    fireEvent.click(applyButton);

    // The update endpoint must NOT be called yet - confirmation is required first.
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/scanner-config/update/"),
      expect.anything(),
    );
    const dialog = await waitFor(() => screen.getByRole("dialog"));
    expect(dialog).toHaveTextContent("RUNNING");

    fireEvent.click(screen.getByRole("button", { name: "Apply now" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/scanner-config/update/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("Checkpoint 64.17 §12: cancelling the confirmation makes no request at all", async () => {
    const runningConfig: ScannerConfigurationResponse = {
      ...STOPPED_CONFIG,
      desired: { ...STOPPED_CONFIG.desired, enabled: true },
      status: "EFFECTIVE",
    };
    const fetchMock = stubEndpoints({ config: runningConfig, readiness: READINESS_READY });

    renderWithAuth(<LiveScannerConsole />);

    const applyButton = await waitFor(() =>
      screen.getByRole("button", { name: "Apply Configuration" }),
    );
    fireEvent.click(applyButton);
    await waitFor(() => screen.getByRole("dialog"));

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/scanner-config/update/"),
      expect.anything(),
    );
  });

  it("disables configuration controls for a read-only (non-operator) user", async () => {
    stubEndpoints({});

    renderWithAuth(<LiveScannerConsole />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });

    await waitFor(() => expect(screen.getByText("Desired Configuration")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "START LIVE PAPER SESSION" })).not.toBeInTheDocument();
    expect(
      screen.getByText(/You have read-only access to this screen/),
    ).toBeInTheDocument();
  });
});
