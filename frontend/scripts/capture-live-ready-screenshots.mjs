// frontend/scripts/capture-live-ready-screenshots.mjs
//
// Checkpoint FRONTEND-LIVE-READY: throwaway screenshot capture utility,
// same pattern as `capture-design-audit-screenshots.mjs` (FRONTEND-2) -
// NOT a permanent E2E suite. Scoped to exactly the two screens this
// checkpoint audits: Live Scanner (selection UI) and Live Paper
// Operations (the console the operator will watch live tomorrow).
// Drives the real Vite dev server with Playwright/Chromium, intercepts
// every backend API call at the network layer (no real Django server,
// no real Dhan call, no real DB row is ever touched), and captures
// full-page screenshots across a few realistic states in both themes.
//
// Run with the frontend dev server already up:
//   npm run dev   (in one terminal)
//   node scripts/capture-live-ready-screenshots.mjs   (in another)
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, "../docs/design-audit/live-ready");
mkdirSync(OUT_DIR, { recursive: true });

const BASE_URL = "http://127.0.0.1:5173";

const MOCK_USER = {
  is_authenticated: true,
  username: "design-audit-mock-user",
  capabilities: ["configuration.read", "configuration.activate"],
};

const WORKER_STATUS = {
  provider: "dhan",
  worker_state: "RUNNING",
  token_state: "VALID",
  watchdog_state: "ARMED",
  last_packet_at: "2026-09-09T09:59:00Z",
  last_bar_at: "2026-09-09T09:59:00Z",
  packet_age_seconds: 2,
  bar_age_seconds: 4,
  reconnect_count: 0,
  consecutive_failures: 0,
  subscribed_instrument_count: 5,
  last_error_safe: "",
  updated_at: "2026-09-09T09:59:00Z",
  is_configured: true,
};

const READINESS_READY = {
  state: "READY_FOR_PAPER",
  provider: "dhan",
  credential_state: "VALID",
  credential_expiry: "2026-09-09T10:17:40Z",
  provider_state: "HEALTHY",
  watchdog_state: "HEALTHY",
  market_state: "OPEN",
  paper_execution_state: "ENABLED",
  real_trading_state: "DISABLED",
  can_start: true,
  safe_reason: "All readiness checks passed.",
  remediation:
    "Start the Live Paper Session explicitly - this gate reporting READY never starts it automatically.",
};

const TEN_CHECKS_READY = [
  { key: "dhan_credential", label: "Dhan Credential", state: "READY", explanation: "Token valid.", remediation: null },
  { key: "provider_connectivity", label: "Provider Connectivity", state: "READY", explanation: "Worker reporting HEALTHY.", remediation: null },
  { key: "token_validity", label: "Token Validity", state: "READY", explanation: "Token valid until 2026-09-09 10:17:40 UTC.", remediation: null },
  { key: "watchdog", label: "Watchdog", state: "READY", explanation: "Watchdog armed.", remediation: null },
  { key: "market_state", label: "Market State", state: "READY", explanation: "Market is open.", remediation: null },
  { key: "universe", label: "Universe", state: "READY", explanation: "5 instruments selected.", remediation: null },
  { key: "timeframe", label: "Timeframe", state: "READY", explanation: "Timeframe is set.", remediation: null },
  { key: "strategy_selection", label: "Strategy Selection", state: "READY", explanation: "3 strategies selected.", remediation: null },
  { key: "paper_execution", label: "Paper Execution", state: "READY", explanation: "Paper broker is always available.", remediation: null },
  { key: "real_trading_safety", label: "Real Trading Safety", state: "READY", explanation: "Real trading is structurally disabled.", remediation: null },
];

const EFFECTIVE_CONFIG_NO_DRIFT = {
  desired_configuration_version: 4,
  desired_universe_mode: "SELECTED",
  desired_timeframe: "5m",
  desired_strategy_ids: ["ema_crossover", "sma_trend_filter", "atr_volatility_breakout"],
  desired_requested_by: "operator",
  effective_configuration_version: 4,
  effective_timeframe: "5m",
  effective_strategy_ids: ["ema_crossover", "sma_trend_filter", "atr_volatility_breakout"],
  effective_stock_count: 5,
  effective_requested_stock_count: 5,
  drift: false,
};

const SCAN_PROGRESS = {
  status: "SCANNING",
  timeframe: "5m",
  universe_total: 5,
  universe_processed: 3,
  remaining: 2,
  progress_percent: 60,
  current_instrument: "NSE:HDFCBANK",
  current_strategy: "sma_trend_filter",
  strategies_total: 3,
  strategies_processed: 2,
  signals_found: 1,
  started_at: "2026-09-09T09:15:00Z",
  last_progress_at: "2026-09-09T09:44:00Z",
  stale: false,
  last_error_safe: "",
};

const SAMPLE_SIGNAL = {
  scan_run_id: "run-1",
  strategy_version_identifier: "v1",
  signal_id: "sig-1",
  strategy_id: "atr_volatility_breakout",
  instrument_id: "NSE:RELIANCE",
  direction: "BUY",
  price: "2500.00",
  timeframe: "5m",
  signal_timestamp: "2026-09-09T09:40:00Z",
  risk_status: "APPROVED",
  risk_reason: "",
  order_status: "FILLED",
  created_at: "2026-09-09T09:40:00Z",
  trade_plan: {
    entry_price: "2500.00",
    stop_loss: "2480.00",
    target_1: "2530.00",
    target_2: "2550.00",
    target_3: null,
    trailing_stop_loss: null,
    calculation_method: "atr_multiple",
  },
  telegram: { status: "SENT", attempted_at: "2026-09-09T09:40:01Z", delivered_at: "2026-09-09T09:40:01Z", retry_count: 0, error_message: "" },
  discord: { status: "FAILED", attempted_at: "2026-09-09T09:40:01Z", delivered_at: null, retry_count: 2, error_message: "webhook timeout" },
  evidence: null,
};

const REPORT_WITH_ACTIVITY = {
  session_date: "2026-09-09",
  strategies: ["ema_crossover", "sma_trend_filter", "atr_volatility_breakout"],
  universe: ["NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK", "NSE:INFY", "NSE:ICICIBANK"],
  timeframes: ["5m"],
  total_signals: 1,
  risk_accepted: 1,
  risk_rejected: 0,
  paper_orders_total: 1,
  paper_orders_filled: 1,
  paper_orders_rejected: 0,
  communication_total: 2,
  communication_sent: 1,
  communication_failed: 1,
  communication_skipped: 0,
  telegram: { sent: 1, failed: 0, pending: 0 },
  discord: { sent: 0, failed: 1, pending: 0 },
  system_health: null,
  realized_pnl_total: "0.00",
  open_positions: 1,
  closed_positions: 0,
  unrealized_pnl_total: "18.50",
  session_duration_seconds: 1500,
  configuration_version: 4,
};

const REPORT_EMPTY = {
  ...REPORT_WITH_ACTIVITY,
  total_signals: 0,
  risk_accepted: 0,
  paper_orders_total: 0,
  paper_orders_filled: 0,
  communication_total: 0,
  communication_sent: 0,
  communication_failed: 0,
  telegram: { sent: 0, failed: 0, pending: 0 },
  discord: { sent: 0, failed: 0, pending: 0 },
  realized_pnl_total: "0.00",
  open_positions: 0,
  unrealized_pnl_total: "0.00",
};

const STRATEGIES = [
  { strategy_id: "ema_crossover", display_name: "EMA Crossover", specification_version: "v1", code_version: "v1", is_active: true },
  { strategy_id: "sma_trend_filter", display_name: "SMA Trend Filter", specification_version: "v1", code_version: "v1", is_active: true },
  { strategy_id: "atr_volatility_breakout", display_name: "ATR Volatility Breakout", specification_version: "v1", code_version: "v1", is_active: true },
];

const NOTIFICATION_CHANNELS = [
  { channel_id: "telegram", display_name: "Telegram", configured: true, enabled: true },
  { channel_id: "discord", display_name: "Discord", configured: true, enabled: true },
];

const SCANNER_CONFIG_RUNNING = {
  provider: "dhan",
  desired: {
    timeframe: "5m",
    universe_mode: "SELECTED",
    universe_requested_count: 5,
    universe_subscribed_count: 5,
    strategy_ids: ["ema_crossover", "sma_trend_filter", "atr_volatility_breakout"],
    configuration_version: 4,
    enabled: true,
    notification_channels: ["telegram", "discord"],
  },
  effective: {
    timeframe: "5m",
    universe_requested_count: 5,
    universe_subscribed_count: 5,
    strategy_ids: ["ema_crossover", "sma_trend_filter", "atr_volatility_breakout"],
    configuration_version: 4,
    notification_channels: ["telegram", "discord"],
  },
  status: "RUNNING",
  requested_by: "operator",
  requested_at: "2026-09-09T09:15:00Z",
};

function jsonBody(obj, status = 200) {
  return {
    status,
    contentType: "application/json",
    headers: {
      "Access-Control-Allow-Origin": "http://127.0.0.1:5173",
      "Access-Control-Allow-Credentials": "true",
    },
    body: JSON.stringify(obj),
  };
}

function workbench(overrides = {}) {
  return {
    readiness: READINESS_READY,
    checklist: TEN_CHECKS_READY,
    session_state: "STOPPED",
    effective_session_configuration: EFFECTIVE_CONFIG_NO_DRIFT,
    scanner_progress: null,
    ...overrides,
  };
}

// One state definition per capture: which workbench/report/signals shape
// to mock, matching Part 2's four requested states.
const STATES = {
  "idle-pre-start": {
    workbench: workbench({ session_state: "STOPPED", scanner_progress: null }),
    report: REPORT_EMPTY,
    signals: [],
  },
  "running-no-signals": {
    workbench: workbench({ session_state: "RUNNING", scanner_progress: SCAN_PROGRESS }),
    report: REPORT_EMPTY,
    signals: [],
  },
  "running-with-signal": {
    workbench: workbench({
      session_state: "RUNNING",
      scanner_progress: { ...SCAN_PROGRESS, signals_found: 1 },
    }),
    report: REPORT_WITH_ACTIVITY,
    signals: [SAMPLE_SIGNAL],
  },
  "completed-session": {
    workbench: workbench({
      session_state: "STOPPED",
      scanner_progress: { ...SCAN_PROGRESS, status: "COMPLETED", progress_percent: 100, remaining: 0, universe_processed: 5 },
    }),
    report: REPORT_WITH_ACTIVITY,
    signals: [SAMPLE_SIGNAL],
  },
};

async function installApiMocks(page, state) {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;

    if (route.request().method() === "OPTIONS") {
      return route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "http://127.0.0.1:5173",
          "Access-Control-Allow-Credentials": "true",
          "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          "Access-Control-Allow-Headers": "content-type,x-csrftoken",
        },
      });
    }

    if (p === "/api/v1/auth/session/") return route.fulfill(jsonBody(MOCK_USER));
    if (p.startsWith("/api/v1/auth/")) return route.fulfill(jsonBody({ detail: "ok" }));

    // Dashboard renders first on load, before navigation to either
    // audited screen - it needs these to avoid throwing before the nav
    // buttons ever appear (fixture shapes copied from
    // capture-design-audit-screenshots.mjs, FRONTEND-2).
    if (p === "/api/v1/config/market-data/session/") {
      return route.fulfill(
        jsonBody({
          session_date: "2026-09-09",
          exchange: "NSE",
          market_open: "2026-09-09T03:45:00Z",
          market_close: "2026-09-09T10:00:00Z",
          square_off_deadline: "2026-09-09T09:45:00Z",
          status: "OPEN",
        }),
      );
    }
    if (p === "/api/v1/config/market-data/health/") {
      return route.fulfill(
        jsonBody({
          state: "HEALTHY",
          last_success_at: "2026-09-09T09:59:00Z",
          last_failure_at: null,
          last_error_safe: "",
          freshness_age_seconds: 4,
          consecutive_failures: 0,
          reconnect_count: 0,
          subscription_active: true,
        }),
      );
    }
    if (p === "/api/v1/system/readiness/") {
      return route.fulfill(
        jsonBody({
          state: "READY",
          reasons: [],
          database_ok: true,
          market_data_state: "HEALTHY",
          session_status: "OPEN",
          kill_switch_engaged: false,
          square_off_unresolved_count: 0,
        }),
      );
    }

    if (p === "/api/v1/config/market-data/live-paper-workbench/") {
      return route.fulfill(jsonBody(state?.workbench ?? workbench()));
    }
    if (p === "/api/v1/config/market-data/live-paper-readiness/") {
      return route.fulfill(jsonBody(READINESS_READY));
    }
    if (p === "/api/v1/config/market-data/worker-status/") {
      return route.fulfill(jsonBody(WORKER_STATUS));
    }
    if (p === "/api/v1/config/market-data/scanner-config/") {
      return route.fulfill(jsonBody(SCANNER_CONFIG_RUNNING));
    }
    if (p === "/api/v1/config/market-data/scanner-config/update/") {
      return route.fulfill(jsonBody(SCANNER_CONFIG_RUNNING));
    }
    if (p === "/api/v1/config/strategy-engine/strategies/") {
      return route.fulfill(jsonBody(STRATEGIES));
    }
    if (p === "/api/v1/config/notifications/channels/") {
      return route.fulfill(jsonBody(NOTIFICATION_CHANNELS));
    }
    if (p === "/api/v1/config/watchlists/") {
      return route.fulfill(jsonBody([]));
    }
    if (p === "/api/v1/config/market-data/instruments/") {
      return route.fulfill(
        jsonBody({
          exchange: url.searchParams.get("exchange") ?? "NSE",
          data_source: "DHAN_SCRIP_MASTER",
          instruments: [
            { instrument_id: "NSE:RELIANCE", symbol: "RELIANCE", company_name: "Reliance Industries" },
            { instrument_id: "NSE:TCS", symbol: "TCS", company_name: "Tata Consultancy Services" },
            { instrument_id: "NSE:HDFCBANK", symbol: "HDFCBANK", company_name: "HDFC Bank" },
            { instrument_id: "NSE:INFY", symbol: "INFY", company_name: "Infosys" },
            { instrument_id: "NSE:ICICIBANK", symbol: "ICICIBANK", company_name: "ICICI Bank" },
          ],
        }),
      );
    }
    if (p === "/api/v1/config/market-data/quotes/") {
      return route.fulfill(jsonBody([]));
    }
    if (p === "/api/v1/config/signals/") {
      const items = state?.signals ?? [];
      return route.fulfill(jsonBody({ items, total_count: items.length, page: 1, page_size: 10 }));
    }
    if (p === "/api/v1/config/reports/daily-session/") {
      return route.fulfill(jsonBody(state?.report ?? REPORT_EMPTY));
    }

    if (route.request().method() !== "GET") return route.fulfill(jsonBody({}));
    if (p.endsWith("/")) return route.fulfill(jsonBody([]));
    return route.fulfill(jsonBody({}));
  });
}

async function capture(browser, { fileName, screenLabel, themeName, themeId, state }) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", (err) => console.log(`[pageerror] ${fileName}:`, err.message));
  await installApiMocks(page, state);

  await page.addInitScript((id) => {
    try {
      window.localStorage.setItem("intraday.ui.theme.v1", id);
    } catch {
      /* ignore - best effort */
    }
  }, themeId);

  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  const navButton = page.getByRole("button", { name: screenLabel, exact: true });
  await navButton.click();
  await page.waitForTimeout(600);

  const file = path.join(OUT_DIR, `${fileName}-${themeName}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log(`captured ${file}`);

  await context.close();
}

async function main() {
  const browser = await chromium.launch();

  for (const [themeName, themeId] of [
    ["light", "focus"],
    ["dark", "midnight"],
  ]) {
    // Live Scanner selection UI - one representative state is enough,
    // this is a config-editing screen, not a monitoring screen.
    await capture(browser, {
      fileName: "live-scanner-selection",
      screenLabel: "Live Scanner",
      themeName,
      themeId,
      state: STATES["idle-pre-start"],
    });

    for (const [stateName, state] of Object.entries(STATES)) {
      await capture(browser, {
        fileName: `live-paper-operations-${stateName}`,
        screenLabel: "Live Paper Operations",
        themeName,
        themeId,
        state,
      });
    }
  }

  await browser.close();
}

main();
