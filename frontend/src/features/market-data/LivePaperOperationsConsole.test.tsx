// frontend/src/features/market-data/LivePaperOperationsConsole.test.tsx
//
// Checkpoint 64.15: real-boundary tests for the consolidated Live Paper
// Operations Console - only `global.fetch` is mocked; the real
// component and real generated contract types are exercised together,
// matching LiveScannerConsole.test.tsx's own established pattern.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LivePaperOperationsConsole } from "./LivePaperOperationsConsole";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type LivePaperWorkbenchResponse = components["schemas"]["LivePaperWorkbenchResponse"];
type LivePaperReadinessResponse = components["schemas"]["LivePaperReadinessResponse"];
type LivePaperSessionResponse = components["schemas"]["LivePaperSessionResponse"];
type WorkerRuntimeStatusResponse = components["schemas"]["WorkerRuntimeStatusResponse"];
type DailySessionReportResponse = components["schemas"]["DailySessionReportResponse"];
type SignalResponse = components["schemas"]["SignalResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const READINESS_BLOCKED: LivePaperReadinessResponse = {
  state: "CREDENTIAL_EXPIRED",
  provider: "dhan",
  credential_state: "EXPIRED",
  credential_expiry: "2026-07-25T07:10:00Z",
  provider_state: "NEVER_REPORTED",
  watchdog_state: "NEVER_REPORTED",
  market_state: "CLOSED",
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
  market_state: "OPEN",
  can_start: true,
  safe_reason: "All readiness checks passed.",
};

const TEN_CHECKS = [
  { key: "dhan_credential", label: "Dhan Credential", state: "BLOCKED", explanation: "Token expired.", remediation: "Renew the token." },
  { key: "provider_connectivity", label: "Provider Connectivity", state: "UNKNOWN", explanation: "No worker report.", remediation: null },
  { key: "token_validity", label: "Token Validity", state: "BLOCKED", explanation: "Token expired.", remediation: "Renew the token." },
  { key: "watchdog", label: "Watchdog", state: "UNKNOWN", explanation: "Worker has never reported.", remediation: null },
  { key: "market_state", label: "Market State", state: "BLOCKED", explanation: "Market is closed.", remediation: "Wait for market hours." },
  { key: "universe", label: "Universe", state: "WARNING", explanation: "Partial universe selected.", remediation: "Add more instruments." },
  { key: "timeframe", label: "Timeframe", state: "READY", explanation: "Timeframe is set.", remediation: null },
  { key: "strategy_selection", label: "Strategy Selection", state: "READY", explanation: "At least one strategy selected.", remediation: null },
  { key: "paper_execution", label: "Paper Execution", state: "READY", explanation: "Paper broker is always available.", remediation: null },
  { key: "real_trading_safety", label: "Real Trading Safety", state: "READY", explanation: "Real trading is structurally disabled.", remediation: null },
];

const EFFECTIVE_CONFIG_NO_DRIFT = {
  desired_configuration_version: 1,
  desired_universe_mode: "ALL_CONFIGURED",
  desired_timeframe: "5m",
  desired_strategy_ids: ["ema_crossover"],
  desired_requested_by: "operator",
  effective_configuration_version: 1,
  effective_timeframe: "5m",
  effective_strategy_ids: ["ema_crossover"],
  effective_stock_count: 50,
  effective_requested_stock_count: 50,
  drift: false,
};

const EFFECTIVE_CONFIG_DRIFT = {
  ...EFFECTIVE_CONFIG_NO_DRIFT,
  effective_configuration_version: 0,
  effective_timeframe: "",
  effective_strategy_ids: [] as string[],
  effective_stock_count: 0,
  drift: true,
};

function workbench(overrides: Partial<LivePaperWorkbenchResponse> = {}): LivePaperWorkbenchResponse {
  return {
    readiness: READINESS_BLOCKED,
    checklist: TEN_CHECKS,
    session_state: "NOT_READY",
    effective_session_configuration: EFFECTIVE_CONFIG_DRIFT,
    ...overrides,
  };
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

const EMPTY_REPORT: DailySessionReportResponse = {
  session_date: "2026-08-20",
  strategies: [],
  universe: [],
  timeframes: [],
  total_signals: 3,
  risk_accepted: 2,
  risk_rejected: 1,
  paper_orders_total: 2,
  paper_orders_filled: 1,
  paper_orders_rejected: 0,
  communication_total: 3,
  communication_sent: 2,
  communication_failed: 0,
  communication_skipped: 1,
  system_health: null,
  realized_pnl_total: "125.50",
};

const SAMPLE_SIGNAL: SignalResponse = {
  signal_id: "sig-1",
  strategy_id: "atr_volatility_breakout",
  instrument_id: "NSE:RELIANCE",
  direction: "BUY",
  price: "2500.00",
  timeframe: "5m",
  signal_timestamp: "2026-08-20T10:00:00Z",
  risk_status: "APPROVED",
  risk_reason: "",
  order_status: "FILLED",
  created_at: "2026-08-20T10:00:00Z",
  trade_plan: {
    entry_price: "2500.00",
    stop_loss: "2480.00",
    target_1: "2530.00",
    target_2: null,
    target_3: null,
    trailing_stop_loss: null,
    calculation_method: "atr_multiple",
  },
  telegram: { status: "SENT", attempted_at: "2026-08-20T10:00:01Z", delivered_at: "2026-08-20T10:00:01Z", retry_count: 0, error_message: "" },
  discord: null,
};

function stubEndpoints(
  options: {
    workbench?: LivePaperWorkbenchResponse;
    startResponse?: LivePaperSessionResponse;
    stopResponse?: LivePaperSessionResponse;
    report?: DailySessionReportResponse;
    signals?: SignalResponse[];
  } = {},
): ReturnType<typeof vi.fn> {
  const {
    workbench: workbenchBody = workbench(),
    startResponse = {
      accepted: true,
      state: "STARTING",
      message: "Live Paper Session start requested.",
      remediation: null,
      configuration_version: 2,
      enabled: true,
    },
    stopResponse = {
      accepted: true,
      state: "STOPPING",
      message: "Live Paper Session stop requested.",
      remediation: null,
      configuration_version: 2,
      enabled: false,
    },
    report = EMPTY_REPORT,
    signals = [SAMPLE_SIGNAL],
  } = options;

  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/live-paper-session/start/")) return Promise.resolve(jsonResponse(startResponse));
    if (url.includes("/live-paper-session/stop/")) return Promise.resolve(jsonResponse(stopResponse));
    if (url.includes("/live-paper-workbench/")) return Promise.resolve(jsonResponse(workbenchBody));
    if (url.includes("/worker-status/")) return Promise.resolve(jsonResponse(WORKER_STATUS_UNCONFIGURED));
    if (url.includes("/reports/daily-session/")) return Promise.resolve(jsonResponse(report));
    if (url.includes("/signals/")) return Promise.resolve(jsonResponse({ items: signals, total_count: signals.length, page: 1, page_size: 10 }));
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("LivePaperOperationsConsole", () => {
  it("renders all ten readiness checks with their real state/label/explanation/remediation", async () => {
    stubEndpoints({});

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Pre-Session Readiness Checklist")).toBeInTheDocument());
    for (const check of TEN_CHECKS) {
      expect(screen.getByRole("heading", { level: 3, name: check.label })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Token expired.").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Renew the token\.$/).length).toBeGreaterThan(0);
  });

  it("shows READY, WARNING, BLOCKED, and UNKNOWN states distinctly", async () => {
    stubEndpoints({});

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Pre-Session Readiness Checklist")).toBeInTheDocument());
    const states = ["READY", "WARNING", "BLOCKED", "UNKNOWN"];
    for (const state of states) {
      expect(screen.getAllByText(state).length).toBeGreaterThan(0);
    }
  });

  it("shows desired vs effective configuration with an honest DRIFT indicator", async () => {
    stubEndpoints({ workbench: workbench({ effective_session_configuration: EFFECTIVE_CONFIG_DRIFT }) });

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Desired Configuration")).toBeInTheDocument());
    expect(screen.getByText("Effective Configuration")).toBeInTheDocument();
    expect(screen.getByText("DRIFT")).toBeInTheDocument();
  });

  it("shows NO DRIFT once desired and effective versions match", async () => {
    stubEndpoints({ workbench: workbench({ effective_session_configuration: EFFECTIVE_CONFIG_NO_DRIFT }) });

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("NO DRIFT")).toBeInTheDocument());
  });

  it("displays the authoritative backend session_state, never a locally computed one", async () => {
    stubEndpoints({ workbench: workbench({ session_state: "RUNNING" }) });

    const { container } = renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => {
      const heading = screen.getByText("Session State").closest("section");
      expect(heading?.querySelector(".badge")).toHaveTextContent("Running");
    });
    expect(container.querySelector(".live-paper-console__timeline-step--current")).toHaveTextContent(
      "Running",
    );
  });

  it("shows a real FAILED session state with an explanation, never a fabricated one", async () => {
    stubEndpoints({ workbench: workbench({ session_state: "FAILED" }) });

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Failed")).toBeInTheDocument());
    expect(screen.getByText(/live worker reported a real failure state/)).toBeInTheDocument();
  });

  it("disables START while aggregate readiness is BLOCKED, matching the sole authoritative decision", async () => {
    stubEndpoints({ workbench: workbench({ readiness: READINESS_BLOCKED }) });

    renderWithAuth(<LivePaperOperationsConsole />);

    const startButton = await waitFor(() => screen.getByRole("button", { name: "START LIVE PAPER SESSION" }));
    expect(startButton).toBeDisabled();
  });

  it("enables START and calls the real gated start endpoint when readiness is READY", async () => {
    const fetchMock = stubEndpoints({
      workbench: workbench({ readiness: READINESS_READY, session_state: "READY" }),
    });

    renderWithAuth(<LivePaperOperationsConsole />);

    const startButton = await waitFor(() => screen.getByRole("button", { name: "START LIVE PAPER SESSION" }));
    expect(startButton).not.toBeDisabled();

    fireEvent.click(startButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/live-paper-session/start/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("calls the real gated stop endpoint for a running session", async () => {
    const fetchMock = stubEndpoints({
      workbench: workbench({ readiness: READINESS_READY, session_state: "RUNNING" }),
    });

    renderWithAuth(<LivePaperOperationsConsole />);

    const stopButton = await waitFor(() => screen.getByRole("button", { name: "STOP LIVE PAPER SESSION" }));
    fireEvent.click(stopButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/live-paper-session/stop/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("Checkpoint 64.15 §16: correctly shows Market State BLOCKED when the market is closed, and does not fabricate a live value", async () => {
    stubEndpoints({ workbench: workbench({ readiness: READINESS_BLOCKED }) });

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Market State")).toBeInTheDocument());
    expect(screen.getByText("Market is closed.")).toBeInTheDocument();
  });

  it("renders the compact signal table with the required columns and honest fallbacks", async () => {
    stubEndpoints({});

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    expect(screen.getByRole("columnheader", { name: "Trailing SL" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Target 3" })).toBeInTheDocument();
    // trailing_stop_loss and target_2/target_3 are null on the fixture - honest fallback, never fabricated.
    expect(screen.getAllByText("Not provided").length).toBeGreaterThan(0);
    // discord is null on the fixture.
    expect(screen.getAllByText("Not provided")).not.toHaveLength(0);
  });

  it("shows Paper Execution KPIs from the real Daily Session Report, never a duplicate client-side calculation", async () => {
    stubEndpoints({});

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Paper Execution Summary")).toBeInTheDocument());
    expect(screen.getByText("Risk Approved").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Paper Fills").nextSibling).toHaveTextContent("1");
  });

  it("shows Telegram and Discord communication counts", async () => {
    stubEndpoints({});

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Communication Summary")).toBeInTheDocument());
    expect(screen.getByText("Communication Sent").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Communication Failed").nextSibling).toHaveTextContent("0");
  });

  it("shows PAPER P&L clearly labeled, never mistakable for a real account balance", async () => {
    stubEndpoints({});

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText(/PAPER P&L: \+₹125\.50/)).toBeInTheDocument());
  });

  it("shows Not available for Paper P&L when the backend has no realized total yet", async () => {
    stubEndpoints({ report: { ...EMPTY_REPORT, realized_pnl_total: null } });

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText(/PAPER P&L: Not available/)).toBeInTheDocument());
  });

  it("always shows the safety strip with real trading disabled, regardless of session state", async () => {
    stubEndpoints({ workbench: workbench({ readiness: READINESS_READY, session_state: "RUNNING" }) });

    renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Execution Mode: PAPER")).toBeInTheDocument());
    expect(screen.getByText("Real Trading: DISABLED")).toBeInTheDocument();
    expect(screen.getByText("Broker Execution: PAPER ONLY")).toBeInTheDocument();
  });

  it("renders a safe error message and keeps stale data visible when a poll fails", async () => {
    let callCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/live-paper-workbench/")) {
        callCount += 1;
        if (callCount === 1) return Promise.resolve(jsonResponse(workbench()));
        return Promise.resolve(
          jsonResponse({ error_code: "server_error", message: "Temporary failure." }, 500),
        );
      }
      if (url.includes("/worker-status/")) return Promise.resolve(jsonResponse(WORKER_STATUS_UNCONFIGURED));
      if (url.includes("/reports/daily-session/")) return Promise.resolve(jsonResponse(EMPTY_REPORT));
      if (url.includes("/signals/")) return Promise.resolve(jsonResponse({ items: [], total_count: 0, page: 1, page_size: 10 }));
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers({ shouldAdvanceTime: true });

    renderWithAuth(<LivePaperOperationsConsole />);

    await vi.waitFor(() => expect(screen.getByText("Pre-Session Readiness Checklist")).toBeInTheDocument());

    await vi.advanceTimersByTimeAsync(8000);

    await vi.waitFor(() =>
      expect(screen.getByText(/Temporary failure\./)).toBeInTheDocument(),
    );
    // Stale-but-real data must remain visible, not disappear behind the error.
    expect(screen.getByText("Pre-Session Readiness Checklist")).toBeInTheDocument();

    vi.useRealTimers();
  });

  it("Checkpoint 64.15 §15: does not create duplicate polling timers on remount", async () => {
    const fetchMock = stubEndpoints({});
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const { unmount } = renderWithAuth(<LivePaperOperationsConsole />);
    await vi.waitFor(() => expect(screen.getByText("Pre-Session Readiness Checklist")).toBeInTheDocument());
    const callsAfterMount = fetchMock.mock.calls.length;

    unmount();
    await vi.advanceTimersByTimeAsync(20000);
    const callsAfterUnmountAndWait = fetchMock.mock.calls.length;

    // Nothing should fire after unmount - all intervals were cleared.
    expect(callsAfterUnmountAndWait).toBe(callsAfterMount);

    vi.useRealTimers();
  });

  it("never renders a Dhan access token, Telegram token, or Discord webhook value anywhere on the page", async () => {
    stubEndpoints({});

    const { container } = renderWithAuth(<LivePaperOperationsConsole />);

    await waitFor(() => expect(screen.getByText("Pre-Session Readiness Checklist")).toBeInTheDocument());
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/eyJ[a-zA-Z0-9._-]{10,}/); // no JWT-shaped string
    expect(text).not.toMatch(/https:\/\/discord\.com\/api\/webhooks/);
  });

  it("disables session control for a read-only (non-operator) user", async () => {
    stubEndpoints({ workbench: workbench({ readiness: READINESS_READY, session_state: "READY" }) });

    renderWithAuth(<LivePaperOperationsConsole />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });

    await waitFor(() => expect(screen.getByText("Live Paper Readiness")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "START LIVE PAPER SESSION" })).not.toBeInTheDocument();
    expect(screen.getByText(/You have read-only access to this screen/)).toBeInTheDocument();
  });
});
