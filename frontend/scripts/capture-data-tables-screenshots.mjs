// frontend/scripts/capture-data-tables-screenshots.mjs
//
// Checkpoint FRONTEND-DATA-TABLES: throwaway screenshot capture
// utility, same pattern as `capture-live-ready-screenshots.mjs`
// (FRONTEND-LIVE-READY) - NOT a permanent E2E suite. Scoped to the two
// pages this checkpoint fixed: the instrument-picker checklist
// (via LiveScannerConsole, one of its 4 real call sites) and the
// Compare (Strategy Comparison) page. Real Vite dev server, every
// backend call intercepted at the network layer.
//
// Run with the dev server already up on the port below:
//   npx vite --port 5199   (in one terminal)
//   node scripts/capture-data-tables-screenshots.mjs   (in another)
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, "../docs/design-audit/data-tables");
mkdirSync(OUT_DIR, { recursive: true });

const BASE_URL = "http://127.0.0.1:5199";

const MOCK_USER = {
  is_authenticated: true,
  username: "design-audit-mock-user",
  capabilities: ["configuration.read", "configuration.activate"],
};

// 150 real-shaped instruments so the paginated picker has more than
// one page to show - the actual exchange list is ~8,558; 150 is
// enough to demonstrate the fix without an enormous fixture.
// Real `InstrumentSummary` shape is `{ instrument_id, display_name }`
// (shared/generated_contracts/api-types.ts) - an earlier draft of this
// mock used `symbol`/`company_name` instead, which left every entry's
// `displayName` undefined and made the picker's own
// `a.displayName.localeCompare(...)` sort throw, silently caught by
// its try/catch and shown as "Unable to load the instrument list."
// Fixed here, not worked around - this is what the real contract sends.
const MANY_INSTRUMENTS = Array.from({ length: 150 }, (_, i) => ({
  instrument_id: `NSE:STOCK${String(i).padStart(3, "0")}`,
  display_name: `Stock ${String(i).padStart(3, "0")} Industries Ltd`,
}));

// 45 backtest results for one strategy, matching the real shape
// `to_json_dict()` produces (research/backtesting/serialization.py).
function backtestResult(i) {
  const day = String(1 + (i % 28)).padStart(2, "0");
  return {
    backtest_id: `bt-${(1000000000000 + i).toString(16)}`,
    generated_at: `2026-08-${day}T0${(i % 9) + 1}:00:00Z`,
    configuration: {
      instrument_id: `NSE:${["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"][i % 5]}`,
      timeframe: ["1m", "5m", "15m"][i % 3],
      start: "2026-08-01T00:00:00Z",
      end: "2026-08-28T00:00:00Z",
      strategy_id: "ema_crossover",
      specification_version: "v1",
      code_version: "v1",
      configuration_version: String(1 + (i % 5)),
      initial_capital: "100000",
    },
    trades: [],
    equity_curve: [],
    mark_to_market_curve: [],
    metrics: {
      total_trades: 10 + i,
      winning_trades: 6,
      losing_trades: 4,
      win_rate_percent: "60.00",
      gross_profit: "500",
      gross_loss: "-200",
      net_pnl: String((i % 7) * 15.5 - 20),
      profit_factor: "2.5",
      max_drawdown: "50",
      max_drawdown_percent: String((i % 5) + 1),
      average_trade: "20",
      average_winner: "50",
      average_loser: "-40",
      sharpe_ratio_trade_level: "1.2",
      sortino_ratio_trade_level: "1.5",
      final_capital: "100300",
      return_percent: String((i % 7) * 0.15),
    },
    data_quality: {
      data_source: "dhan",
      data_quality: "REAL",
      bar_count: 200,
      transaction_cost_assumption: "flat pct",
      slippage_assumption: "flat pct",
      survivorship_bias_note: "n/a",
    },
    validation: {},
    trust_level: "GATE_VERIFIED",
    cost_model_identity: { name: "FLAT_PERCENTAGE", version: "v1", effective_from: "2026-01-01" },
  };
}
const MANY_RESULTS = Array.from({ length: 45 }, (_, i) => backtestResult(i));

function jsonBody(obj, status = 200) {
  return {
    status,
    contentType: "application/json",
    headers: {
      "Access-Control-Allow-Origin": BASE_URL,
      "Access-Control-Allow-Credentials": "true",
    },
    body: JSON.stringify(obj),
  };
}

async function installApiMocks(page) {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;

    if (route.request().method() === "OPTIONS") {
      return route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": BASE_URL,
          "Access-Control-Allow-Credentials": "true",
          "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
          "Access-Control-Allow-Headers": "content-type,x-csrftoken",
        },
      });
    }

    if (p === "/api/v1/auth/session/") return route.fulfill(jsonBody(MOCK_USER));
    if (p.startsWith("/api/v1/auth/")) return route.fulfill(jsonBody({ detail: "ok" }));

    // Dashboard renders first on load.
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

    // Live Scanner selection UI (one real call site of InstrumentPickerMulti).
    if (p === "/api/v1/config/market-data/live-paper-workbench/") {
      return route.fulfill(
        jsonBody({
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
            remediation: "Start the Live Paper Session explicitly.",
          },
          checklist: [],
          session_state: "STOPPED",
          effective_session_configuration: {
            desired_configuration_version: 1,
            desired_universe_mode: "SELECTED",
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
        }),
      );
    }
    if (p === "/api/v1/config/market-data/live-paper-readiness/") {
      return route.fulfill(jsonBody({ can_start: true }));
    }
    if (p === "/api/v1/config/market-data/worker-status/") {
      return route.fulfill(
        jsonBody({
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
        }),
      );
    }
    if (p === "/api/v1/config/market-data/scanner-config/" || p === "/api/v1/config/market-data/scanner-config/update/") {
      return route.fulfill(
        jsonBody({
          provider: "dhan",
          desired: {
            timeframe: "5m",
            universe_mode: "SELECTED",
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
        }),
      );
    }
    if (p === "/api/v1/config/strategy-engine/strategies/") {
      return route.fulfill(
        jsonBody([
          { strategy_id: "ema_crossover", display_name: "EMA Crossover", specification_version: "v1", code_version: "v1", is_active: true },
        ]),
      );
    }
    if (p === "/api/v1/config/notifications/channels/") return route.fulfill(jsonBody([]));
    if (p === "/api/v1/config/watchlists/") return route.fulfill(jsonBody([]));
    if (p === "/api/v1/config/signals/") return route.fulfill(jsonBody({ items: [], total_count: 0, page: 1, page_size: 10 }));
    if (p === "/api/v1/config/reports/daily-session/") {
      return route.fulfill(
        jsonBody({
          session_date: "2026-09-09",
          strategies: [],
          universe: [],
          timeframes: [],
          total_signals: 0,
          risk_accepted: 0,
          risk_rejected: 0,
          paper_orders_total: 0,
          paper_orders_filled: 0,
          paper_orders_rejected: 0,
          communication_total: 0,
          communication_sent: 0,
          communication_failed: 0,
          communication_skipped: 0,
          telegram: { sent: 0, failed: 0, pending: 0 },
          discord: { sent: 0, failed: 0, pending: 0 },
          system_health: null,
          realized_pnl_total: "0.00",
          open_positions: 0,
          closed_positions: 0,
          unrealized_pnl_total: "0.00",
          session_duration_seconds: null,
          configuration_version: null,
        }),
      );
    }

    // The paginated instrument picker itself.
    if (p === "/api/v1/config/market-data/instruments/") {
      return route.fulfill(
        jsonBody({
          exchange: url.searchParams.get("exchange") ?? "NSE",
          data_source: "DHAN_SCRIP_MASTER",
          instruments: url.searchParams.get("exchange") === "BSE" ? [] : MANY_INSTRUMENTS,
        }),
      );
    }
    if (p === "/api/v1/config/market-data/quotes/") return route.fulfill(jsonBody([]));

    // Compare page.
    if (p === "/api/v1/config/backtesting/strategies/ema_crossover/results/") {
      return route.fulfill(jsonBody(MANY_RESULTS));
    }

    if (route.request().method() !== "GET") return route.fulfill(jsonBody({}));
    if (p.endsWith("/")) return route.fulfill(jsonBody([]));
    return route.fulfill(jsonBody({}));
  });
}

async function capture(browser, { fileName, screenLabel, themeName, themeId, afterNav }) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", (err) => console.log(`[pageerror] ${fileName}:`, err.message));
  page.on("console", (msg) => { if (msg.type() === "error") console.log(`[console.error] ${fileName}:`, msg.text()); });
  page.on("requestfailed", (r) => console.log(`[reqfailed] ${fileName}:`, r.url()));
  await installApiMocks(page);

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
  if (afterNav) await afterNav(page);

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
    await capture(browser, {
      fileName: "live-scanner-instrument-picker",
      screenLabel: "Live Scanner",
      themeName,
      themeId,
      afterNav: async (page) => {
        // Selected Stocks radio is already the default in this fixture's
        // scanner-config (universe_mode: SELECTED); wait for the picker's
        // checklist to render before capturing.
        await page.waitForTimeout(400);
      },
    });

    await capture(browser, {
      fileName: "compare-results-list",
      screenLabel: "Compare",
      themeName,
      themeId,
    });
  }

  await browser.close();
}

main();
