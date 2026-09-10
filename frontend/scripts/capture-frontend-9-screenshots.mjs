// frontend/scripts/capture-frontend-9-screenshots.mjs
//
// CHECKPOINT-FRONTEND-9: throwaway screenshot capture utility (NOT a
// permanent E2E suite - same disposable-script convention as
// capture-design-audit-screenshots.mjs / capture-backtest-pdf-d-
// screenshots.mjs, whose mock pattern this reuses) proving the fixed
// Trade Ledger renders IST times (not the viewer's browser-local
// time) in context, both themes. Drives the real Vite dev server with
// Playwright/Chromium, mocks every backend call at the network layer
// (no real Django server, no real Dhan call, no real DB row touched).
//
// Run with the frontend dev server already up:
//   npm run dev   (in one terminal)
//   node scripts/capture-frontend-9-screenshots.mjs   (in another)
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, "../docs/design-audit");
mkdirSync(OUT_DIR, { recursive: true });

const BASE_URL = "http://127.0.0.1:5173";

const MOCK_USER = {
  is_authenticated: true,
  username: "frontend-9-screenshot-mock-user",
  capabilities: ["configuration.read", "configuration.write", "configuration.activate"],
};

// Trade #1's own entry_timestamp is 2026-01-02T04:00:00Z (UTC) ->
// 09:30:00 IST - the same known conversion this checkpoint's own
// Vitest coverage asserts.
const BACKTEST_RESULT = {
  backtest_id: "frontend9-demo",
  generated_at: "2026-01-02T06:00:00Z",
  configuration: { instrument_id: "NSE:FIXTURE01", timeframe: "5m", initial_capital: "100000" },
  trades: [
    {
      trade_id: "ema_crossover-1",
      strategy_id: "ema_crossover",
      direction: "BULLISH",
      entry_timestamp: "2026-01-02T04:00:00Z",
      exit_timestamp: "2026-01-02T04:10:00Z",
      entry_price: "100.00",
      exit_price: "102.00",
      quantity: "10",
      gross_pnl: "20.00",
      costs: "0.00",
      net_pnl: "20.00",
      reason: "signal_reversal",
      cost_breakdown: {
        brokerage: "0.00", stt: "0.00", exchange_transaction_charges: "0.00",
        sebi_charges: "0.00", gst: "0.00", stamp_duty: "0.00",
        other_statutory_charges: "0.00", total: "0.00",
      },
    },
  ],
  equity_curve: [],
  mark_to_market_curve: [],
  metrics: {
    total_trades: 1, winning_trades: 1, losing_trades: 0, win_rate_percent: "100.00",
    gross_profit: "20.00", gross_loss: "0", net_pnl: "20.00", profit_factor: "2.40",
    max_drawdown: "0", max_drawdown_percent: "0", max_drawdown_duration_bars: 0,
    average_trade: "20", average_winner: "20", average_loser: null,
    sharpe_ratio_trade_level: "1.15", sortino_ratio_trade_level: "1.60",
    final_capital: "100020", return_percent: "0.02",
  },
  data_quality: {
    data_source: "fixture", data_quality: "TRADING_GRADE_BAR", bar_count: 10,
    missing_bar_note: "", transaction_cost_assumption: "Flat 0% brokerage assumed.",
    slippage_assumption: "No slippage assumed.",
    survivorship_bias_note: "No survivorship bias adjustment applied.",
  },
  validation: {
    bar_count: 10, signal_count: 1, trade_count: 1, warmup_bars: 6,
    skipped_signals: 0, rejected_trades: 0, data_gaps_note: "None detected.",
  },
  trust_level: "POC",
  cost_model_identity: {
    name: "FLAT_PERCENTAGE", version: "1", effective_from: "2026-01-01", is_verified: false,
  },
};

function jsonBody(obj) {
  return {
    status: 200,
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
    const method = route.request().method();

    if (method === "OPTIONS") {
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

    if (p === "/api/v1/config/market-data/session/") {
      return route.fulfill(
        jsonBody({
          session_date: "2026-09-02",
          exchange: "NSE",
          market_open: "2026-09-02T03:45:00Z",
          market_close: "2026-09-02T10:00:00Z",
          square_off_deadline: "2026-09-02T09:45:00Z",
          status: "OPEN",
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

    if (p.endsWith("/backtesting/run/") && method === "POST") {
      return route.fulfill(jsonBody(BACKTEST_RESULT));
    }
    if (p.endsWith("/schema/")) {
      return route.fulfill(
        jsonBody({ strategy_id: "ema-crossover", display_name: "EMA Crossover (mock)", parameters: [] }),
      );
    }
    if (p === "/api/v1/config/strategy-engine/strategies/" || p.endsWith("/strategies/")) {
      return route.fulfill(
        jsonBody([{ strategy_id: "ema-crossover", display_name: "EMA Crossover (mock)", is_active: true }]),
      );
    }
    if (p === "/api/v1/config/market-data/instruments/") {
      const exchange = url.searchParams.get("exchange") ?? "NSE";
      return route.fulfill(
        jsonBody({
          exchange,
          data_source: "DHAN_SCRIP_MASTER",
          instruments:
            exchange === "NSE"
              ? [{ instrument_id: "NSE:FIXTURE01", display_name: "Fixture 01 (deterministic)" }]
              : [],
        }),
      );
    }
    if (p === "/api/v1/config/market-data/quotes/") {
      return route.fulfill(jsonBody([]));
    }

    if (method !== "GET") return route.fulfill(jsonBody({}));
    if (p.endsWith("/")) return route.fulfill(jsonBody([]));
    return route.fulfill(jsonBody({}));
  });
}

async function capture(browser, themeName, themeId) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
  const page = await context.newPage();
  page.on("pageerror", (err) => console.log(`[pageerror] ${themeName}:`, err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log(`[console.error] ${themeName}:`, msg.text());
  });
  await installApiMocks(page);

  await page.addInitScript((id) => {
    try {
      window.localStorage.setItem("intraday.ui.theme.v1", id);
    } catch {
      /* ignore - best effort */
    }
  }, themeId);

  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  await page.getByText("Research", { exact: true }).click();
  await page.getByRole("button", { name: "Backtesting", exact: true }).click();
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "Configure", exact: true }).first().click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT_DIR, `debug-${themeName}-configure.png`), fullPage: true });
  // Select the single mocked instrument (NSE:FIXTURE01) so exactly one
  // is selected - "Select All" here selects only that one instrument.
  await page.getByRole("button", { name: "Select All", exact: true }).first().click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT_DIR, `debug-${themeName}-selected.png`), fullPage: true });
  await page.getByRole("button", { name: "Run Backtest", exact: true }).click();
  await page.waitForSelector("text=Trade Ledger", { timeout: 10000 });
  await page.waitForTimeout(300);

  const file = path.join(OUT_DIR, `backtesting-trade-ledger-ist-${themeName}.png`);
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
    try {
      await capture(browser, themeName, themeId);
    } catch (err) {
      console.error(`FAILED to capture ${themeName}:`, err.message);
    }
  }
  await browser.close();
}

main();
