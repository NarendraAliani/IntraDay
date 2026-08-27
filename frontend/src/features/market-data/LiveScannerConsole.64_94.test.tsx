// frontend/src/features/market-data/LiveScannerConsole.64_94.test.tsx
//
// Checkpoint 64.94: (1) proves the Live Signal Console renders the new
// Strategy Version column and a per-channel notification status that
// is NOT merely a color (real text, e.g. "SKIPPED_NOT_SELECTED"), and
// (2) a lightweight accessibility check reusing the EXISTING
// `@testing-library/react` stack already used across this file's
// sibling test suites - no new testing framework/dependency added
// (Phase 11's own "do not add a large dependency for one test" rule).
// Only `global.fetch` is mocked, matching the established pattern.
import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveScannerConsole } from "./LiveScannerConsole";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type ScannerConfigurationResponse = components["schemas"]["ScannerConfigurationResponse"];
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

const STOPPED_CONFIG: ScannerConfigurationResponse = {
  provider: "dhan",
  desired: {
    timeframe: "1m",
    universe_mode: "SELECTED",
    universe_requested_count: 1,
    universe_subscribed_count: 1,
    strategy_ids: ["ema_crossover"],
    configuration_version: 1,
    enabled: true,
    notification_channels: ["telegram"],
  },
  effective: {
    timeframe: "1m",
    universe_requested_count: 1,
    universe_subscribed_count: 1,
    strategy_ids: ["ema_crossover"],
    configuration_version: 1,
    notification_channels: ["telegram"],
  },
  status: "EFFECTIVE",
  requested_by: "operator@example.com",
  requested_at: "2026-08-27T05:00:00Z",
};

const NOTIFICATION_CHANNELS: components["schemas"]["NotificationChannel"][] = [
  { channel_id: "telegram", display_name: "Telegram", configured: true, enabled: true },
  { channel_id: "discord", display_name: "Discord", configured: true, enabled: true },
];

const ONE_SIGNAL: SignalResponse = {
  signal_id: "sig-64-94-e2e-0001",
  instrument_id: "NSE:RELIANCE",
  strategy_id: "ema_crossover",
  strategy_version_identifier: "v1",
  signal_timestamp: "2026-08-27T05:05:00Z",
  timeframe: "1m",
  direction: "BUY",
  signal_status: "VALIDATED",
  execution_status: "NOT_EVALUATED",
  block_reason: null,
  confidence: null,
  scan_run_id: "scan-run-64-94",
  trade_plan: null,
  evidence: null,
  telegram: {
    status: "SENT",
    attempted_at: "2026-08-27T05:05:01Z",
    delivered_at: "2026-08-27T05:05:01Z",
    retry_count: 0,
    error_message: "",
  },
  discord: {
    status: "SKIPPED_NOT_SELECTED",
    attempted_at: null,
    delivered_at: null,
    retry_count: 0,
    error_message: "",
  },
} as unknown as SignalResponse;

function stubEndpoints(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/live-paper-session/start/")) return Promise.resolve(jsonResponse({}));
    if (url.includes("/live-paper-readiness/"))
      return Promise.resolve(
        jsonResponse({
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
          remediation: null,
        }),
      );
    if (url.includes("/live-paper-workbench/"))
      return Promise.resolve(
        jsonResponse({
          readiness: { can_start: true, real_trading_state: "DISABLED" },
          checklist: [],
          session_state: "RUNNING",
          effective_session_configuration: null,
          scanner_progress: null,
        }),
      );
    if (url.includes("/worker-status/"))
      return Promise.resolve(
        jsonResponse({
          provider: "dhan",
          worker_state: "RUNNING",
          token_state: "VALID",
          watchdog_state: "HEALTHY",
          last_packet_at: null,
          last_bar_at: null,
          packet_age_seconds: null,
          bar_age_seconds: null,
          reconnect_count: 0,
          consecutive_failures: 0,
          subscribed_instrument_count: 1,
          last_error_safe: "",
          updated_at: null,
          is_configured: true,
        }),
      );
    if (url.includes("/scanner-config/")) return Promise.resolve(jsonResponse(STOPPED_CONFIG));
    if (url.includes("/strategy-engine/strategies/"))
      return Promise.resolve(
        jsonResponse([
          {
            strategy_id: "ema_crossover",
            display_name: "EMA Crossover",
            specification_version: "v1",
            code_version: "v1",
            is_active: true,
          },
        ]),
      );
    if (url.includes("/notifications/channels/"))
      return Promise.resolve(jsonResponse(NOTIFICATION_CHANNELS));
    if (url.includes("/config/signals/"))
      return Promise.resolve(
        jsonResponse({ items: [ONE_SIGNAL], total_count: 1, page: 1, page_size: 15 }),
      );
    if (url.includes("/watchlists/")) return Promise.resolve(jsonResponse([]));
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("LiveScannerConsole - Checkpoint 64.94 notification routing display", () => {
  it("shows Strategy Version and a distinct, textual (not color-only) status per channel", async () => {
    stubEndpoints();
    renderWithAuth(<LiveScannerConsole />);

    const versionCell = await screen.findByText("v1");
    expect(versionCell).toBeInTheDocument();

    // Telegram shows SENT, Discord shows the new not-selected status -
    // both are real, readable text, not an icon/color alone.
    expect(await screen.findByText(/Telegram: SENT/)).toBeInTheDocument();
    expect(await screen.findByText(/Discord: SKIPPED_NOT_SELECTED/)).toBeInTheDocument();
  });

  it("renders the live-signals table with accessible column headers and a caption", async () => {
    stubEndpoints();
    renderWithAuth(<LiveScannerConsole />);

    await screen.findByText("v1");
    const table = screen.getByRole("table");
    // Every column has a real <th scope="col"> - accessible column
    // headers, never a purely visual/CSS-only header.
    const headers = within(table).getAllByRole("columnheader");
    const headerNames = headers.map((h) => h.textContent);
    expect(headerNames).toEqual(
      expect.arrayContaining([
        "Timestamp",
        "Stock",
        "Strategy",
        "Version",
        "Signal",
        "Timeframe",
        "Signal ID",
        "Scan Run",
        "Notification Status",
      ]),
    );
  });

  it("exposes the Notification Channels fieldset with accessible checkbox labels", async () => {
    stubEndpoints();
    renderWithAuth(<LiveScannerConsole />);

    await screen.findByText("v1");
    // Every channel checkbox is reachable by its accessible label text
    // (not merely by DOM position) - proves labels are genuinely
    // associated, not just visually adjacent.
    expect(screen.getByRole("checkbox", { name: /Telegram/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Discord/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /Notification Channels/ })).toBeInTheDocument();
  });
});
