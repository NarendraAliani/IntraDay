// frontend/src/features/market-data/LiveScannerConsole.64_93.test.tsx
//
// Checkpoint 64.93: coverage for what THIS checkpoint added on top of
// the already-tested 64.5 console (see LiveScannerConsole.test.tsx) -
// universe/strategy/notification validation reasons, the explicit
// READY/NOT READY readiness gate, the registry-driven notification
// multi-select, Gainz's structural absence, and the same-page live
// signal console.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveScannerConsole } from "./LiveScannerConsole";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type ScannerConfigurationResponse = components["schemas"]["ScannerConfigurationResponse"];
type StrategySummary = components["schemas"]["StrategySummary"];
type NotificationChannel = components["schemas"]["NotificationChannel"];
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

const READY_READINESS: components["schemas"]["LivePaperReadinessResponse"] = {
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
  // Checkpoint FRONTEND-1: `LivePaperReadinessResponse.remediation` is a
  // non-nullable `string` (backend: `live_paper_readiness_views.py:86`,
  // `serializers.CharField()` with no `allow_null=True`) - unlike
  // `LivePaperSessionResponse.remediation`, which IS nullable. For
  // READY_FOR_PAPER specifically, the real backend value
  // (`live_paper_readiness.py`'s own `_REMEDIATIONS` table) is this
  // exact string - reused here rather than an empty placeholder so the
  // fixture matches real backend output, not just the type.
  remediation:
    "Start the Live Paper Session explicitly - this gate reporting READY never starts it automatically.",
};

const BASE_CONFIG: ScannerConfigurationResponse = {
  provider: "dhan",
  desired: {
    timeframe: "5m",
    universe_mode: "ALL_CONFIGURED",
    universe_requested_count: 0,
    universe_subscribed_count: 0,
    strategy_ids: [],
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

const STRATEGIES: StrategySummary[] = [
  { strategy_id: "ema_crossover", display_name: "EMA Crossover", specification_version: "v1", code_version: "v1", is_active: true },
  { strategy_id: "sma_trend_filter", display_name: "SMA Trend Filter", specification_version: "v1", code_version: "v1", is_active: true },
  { strategy_id: "atr_volatility_breakout", display_name: "ATR Volatility Breakout", specification_version: "v1", code_version: "v1", is_active: true },
];

const CHANNELS: NotificationChannel[] = [
  { channel_id: "telegram", display_name: "Telegram", configured: true, enabled: true },
  { channel_id: "discord", display_name: "Discord", configured: false, enabled: true },
];

const EMPTY_WORKBENCH: components["schemas"]["LivePaperWorkbenchResponse"] = {
  readiness: READY_READINESS,
  checklist: [],
  session_state: "STOPPED",
  effective_session_configuration: {
    desired_configuration_version: 1,
    desired_universe_mode: "ALL_CONFIGURED",
    desired_timeframe: "5m",
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

const ONE_SIGNAL: SignalResponse = {
  signal_id: "11111111-2222-3333-4444-555555555555",
  strategy_id: "ema_crossover",
  instrument_id: "NSE_EQ:1333",
  direction: "LONG",
  price: "101.50",
  timeframe: "5m",
  signal_timestamp: "2026-08-27T05:30:00Z",
  risk_status: "APPROVED",
  risk_reason: "",
  order_status: "FILLED",
  created_at: "2026-08-27T05:30:01Z",
  trade_plan: {
    entry_price: "101.50",
    stop_loss: "99.00",
    target_1: "105.00",
    target_2: null,
    target_3: null,
    trailing_stop_loss: null,
    calculation_method: "atr",
  },
  telegram: { status: "DELIVERED", attempted_at: "2026-08-27T05:30:02Z", delivered_at: "2026-08-27T05:30:03Z", retry_count: 0, error_message: "" },
  discord: { status: "FAILED", attempted_at: "2026-08-27T05:30:02Z", delivered_at: null, retry_count: 2, error_message: "webhook timeout" },
  evidence: null,
  scan_run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  strategy_version_identifier: "v1:v1:v1",
};

function stubEndpoints(
  options: {
    config?: ScannerConfigurationResponse;
    strategies?: StrategySummary[];
    channels?: NotificationChannel[];
    signals?: SignalResponse[];
  } = {},
): ReturnType<typeof vi.fn> {
  const { config = BASE_CONFIG, strategies = STRATEGIES, channels = CHANNELS, signals = [] } = options;
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/live-paper-workbench/")) return Promise.resolve(jsonResponse(EMPTY_WORKBENCH));
    if (url.includes("/live-paper-readiness/")) return Promise.resolve(jsonResponse(READY_READINESS));
    if (url.includes("/worker-status/")) return Promise.resolve(jsonResponse({
      provider: "dhan", worker_state: "NEVER_RUN", token_state: "UNKNOWN", watchdog_state: "DISCONNECTED",
      last_packet_at: null, last_bar_at: null, packet_age_seconds: null, bar_age_seconds: null,
      reconnect_count: 0, consecutive_failures: 0, subscribed_instrument_count: 0, last_error_safe: "",
      updated_at: null, is_configured: false,
    }));
    if (url.includes("/scanner-config/update/")) return Promise.resolve(jsonResponse(config));
    if (url.includes("/scanner-config/")) return Promise.resolve(jsonResponse(config));
    if (url.includes("/strategy-engine/strategies/")) return Promise.resolve(jsonResponse(strategies));
    if (url.includes("/notifications/channels/")) return Promise.resolve(jsonResponse(channels));
    if (url.includes("/config/signals/"))
      return Promise.resolve(jsonResponse({ items: signals, total_count: signals.length, page: 1, page_size: 15 }));
    if (url.includes("/watchlists/")) return Promise.resolve(jsonResponse([{ name: "Momentum Watchlist", instrument_ids: [] }]));
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("LiveScannerConsole - Checkpoint 64.93", () => {
  it("defaults to All Stocks and requires a strategy before scanning is READY", async () => {
    stubEndpoints({});
    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("NOT READY")).toBeInTheDocument());
    expect(screen.getByText("No strategy selected.")).toBeInTheDocument();
    expect(screen.getByLabelText("All Stocks")).toBeChecked();
  });

  it("Watchlist universe without a selected watchlist is an explicit NOT READY reason", async () => {
    stubEndpoints({});
    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => screen.getByLabelText("Watchlist"));
    fireEvent.click(screen.getByLabelText("Watchlist"));

    await waitFor(() => expect(screen.getByText("Watchlist not selected.")).toBeInTheDocument());
  });

  it("selecting an unconfigured notification channel is an explicit NOT READY reason", async () => {
    stubEndpoints({});
    renderWithAuth(<LiveScannerConsole />);

    const discordCheckbox = await waitFor(() => screen.getByLabelText(/Discord/));
    fireEvent.click(discordCheckbox);

    await waitFor(() =>
      expect(screen.getByText("Discord is enabled but not configured.")).toBeInTheDocument(),
    );
  });

  it("selecting a configured channel and a strategy reaches READY TO SCAN", async () => {
    stubEndpoints({});
    renderWithAuth(<LiveScannerConsole />);

    fireEvent.click(await waitFor(() => screen.getByLabelText("EMA Crossover")));
    fireEvent.click(await waitFor(() => screen.getByLabelText(/Telegram/)));

    await waitFor(() => expect(screen.getByText("READY TO SCAN")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "START LIVE PAPER SESSION" })).not.toBeDisabled();
  });

  it("the strategy multi-select is registry-driven and Gainz never appears", async () => {
    stubEndpoints({});
    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    expect(screen.getByText("SMA Trend Filter")).toBeInTheDocument();
    expect(screen.getByText("ATR Volatility Breakout")).toBeInTheDocument();
    expect(screen.queryByText(/gainz/i)).not.toBeInTheDocument();
  });

  it("renders a same-page live signal table with stock/strategy/entry/target and per-channel delivery status", async () => {
    stubEndpoints({ signals: [ONE_SIGNAL] });
    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("Live Signals")).toBeInTheDocument());
    const row = screen.getByText("1333").closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText("ema_crossover")).toBeInTheDocument();
    expect(cells.getByText("₹101.50")).toBeInTheDocument();
    expect(cells.getByText("₹105.00")).toBeInTheDocument();
    // Discord failing must NOT hide the signal - the row is still rendered.
    expect(cells.getByText(/Telegram: DELIVERED/)).toBeInTheDocument();
    expect(cells.getByText(/Discord: FAILED/)).toBeInTheDocument();
    expect(cells.getByText("aaaaaaaa")).toBeInTheDocument();
  });

  it("shows an empty-state message rather than fabricating rows when there are no signals yet", async () => {
    stubEndpoints({ signals: [] });
    renderWithAuth(<LiveScannerConsole />);

    await waitFor(() => expect(screen.getByText("No signals yet this session.")).toBeInTheDocument());
  });
});
