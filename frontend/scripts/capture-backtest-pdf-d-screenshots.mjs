// frontend/scripts/capture-backtest-pdf-d-screenshots.mjs
//
// CHECKPOINT-BACKTEST-PDF-D Issue 4: throwaway screenshot capture
// utility (NOT a permanent E2E suite - same disposable-script
// convention as capture-design-audit-screenshots.mjs, whose own
// `installApiMocks()` this reuses verbatim rather than re-deriving a
// second, possibly-wrong mock shape) proving the improved Strategy
// Backtesting "Configure Backtest" view (clarified Run Backtest vs.
// Prepare Data & Start Backtest workflow copy, fixed Historical Data
// Readiness date-range grid) renders correctly in both themes. Drives
// the real Vite dev server with Playwright/Chromium, mocks every
// backend call at the network layer (no real Django server, no real
// Dhan call, no real DB row touched).
//
// Run with the frontend dev server already up:
//   npm run dev   (in one terminal)
//   node scripts/capture-backtest-pdf-d-screenshots.mjs   (in another)
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
  username: "pdf-d-screenshot-mock-user",
  capabilities: ["configuration.read", "configuration.write"],
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

    if (route.request().method() !== "GET") {
      return route.fulfill(jsonBody({}));
    }

    if (p === "/api/v1/config/market-data/instruments/") {
      return route.fulfill(
        jsonBody({
          exchange: "NSE",
          data_source: "DHAN_SCRIP_MASTER",
          instruments: [
            { instrument_id: "NSE:FIXTURE01", symbol: "FIXTURE01", name: "Fixture 01" },
            { instrument_id: "NSE:RELIANCE", symbol: "RELIANCE", name: "Reliance Industries" },
            { instrument_id: "NSE:HDFCBANK", symbol: "HDFCBANK", name: "HDFC Bank" },
          ],
        }),
      );
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
    if (p.includes("/backtesting/") && p.endsWith("/results/")) {
      return route.fulfill(jsonBody([]));
    }

    // Generic fallback - an empty, well-formed shape for anything else.
    if (p.endsWith("/")) {
      return route.fulfill(jsonBody([]));
    }
    return route.fulfill(jsonBody({}));
  });
}

async function capture(browser, themeName, themeId) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1400 } });
  const page = await context.newPage();
  page.on("pageerror", (err) => console.log(`[pageerror] ${themeName}:`, err.message));
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

  // Open "Configure" on the first strategy card to reach the improved
  // help-text section this checkpoint's Issue 4 changes.
  await page.getByRole("button", { name: "Configure", exact: true }).first().click();
  await page.waitForTimeout(500);

  const file = path.join(OUT_DIR, `backtesting-configure-pdf-d-${themeName}.png`);
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
