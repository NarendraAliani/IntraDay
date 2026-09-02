// frontend/scripts/capture-design-audit-screenshots.mjs
//
// Checkpoint FRONTEND-2: throwaway screenshot capture utility. NOT a
// permanent E2E suite - a one-off tool for the visual/UX audit. Drives
// the real Vite dev server (assumed already running on :5173) with
// Playwright/Chromium, intercepts every backend API call at the network
// layer (no real Django server, no real Dhan call, no real DB row is
// ever touched - see CHECKPOINT_FRONTEND-2_SUMMARY.md "auth approach"),
// and captures a full-page screenshot of each of the 10 screens in both
// the light ("focus") and dark ("midnight") theme - 20 images total.
//
// Run with the frontend dev server already up:
//   npm run dev   (in one terminal)
//   node scripts/capture-design-audit-screenshots.mjs   (in another)
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, "../docs/design-audit");
mkdirSync(OUT_DIR, { recursive: true });

const BASE_URL = "http://127.0.0.1:5173";

// Screens named in the checkpoint directive, mapped to the visible nav
// label App.tsx renders (see NAV_ITEMS in src/app/App.tsx) so the script
// clicks through the real navigation exactly as a user would.
const SCREENS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "market-data-archive", label: "Market Data Archive" },
  { id: "settings", label: "Settings" },
  { id: "strategies", label: "Strategies" },
  { id: "backtesting", label: "Backtesting" },
  { id: "comparison", label: "Compare" },
  { id: "watchlists", label: "Watchlists" },
  { id: "strategy-monitor", label: "Strategy Monitor" },
  { id: "paper-trading", label: "Paper Trading" },
  { id: "reports", label: "Reports" },
];

// Mock/fixture data, clearly labelled as such (PROHIBITIONS: no real
// account, no real Dhan call). Kept intentionally generic - it exists to
// make screens render meaningfully, not to exercise business logic.
const MOCK_USER = {
  is_authenticated: true,
  username: "design-audit-mock-user",
  capabilities: ["configuration.read", "configuration.write"],
};

function jsonBody(obj) {
  return {
    status: 200,
    contentType: "application/json",
    // CORS headers: the app fetches a different origin (VITE_API_BASE_URL,
    // :8000) than the page it runs on (:5173) with credentials: "include",
    // so a mocked response needs these or the browser discards it as a
    // cross-origin failure even though Playwright never touched the wire.
    headers: {
      "Access-Control-Allow-Origin": "http://127.0.0.1:5173",
      "Access-Control-Allow-Credentials": "true",
    },
    body: JSON.stringify(obj),
  };
}

// A single catch-all interceptor: the real backend is NEVER contacted.
// Auth/session is mocked authenticated; every other /api/** GET gets a
// generic "empty but well-formed" response so screens render their real
// empty state rather than crashing - per the checkpoint directive,
// "empty-state screens are fine to capture as-is if that's genuinely
// what a first-time user would see." A handful of endpoints get slightly
// richer fixture bodies so key screens (dashboard, watchlists,
// backtesting) show representative data instead of only empty states.
async function installApiMocks(page) {
  // Scoped to the backend ORIGIN (not just any URL containing "api") -
  // a path-based "**/api/**" glob would also match Vite-served source
  // files like src/common/api/client.ts and corrupt module loading.
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

    // Dashboard screen fixtures - shapes copied from
    // src/features/dashboard/dashboardFixtures.ts (the project's own
    // generated-contract-typed test fixtures), so the mock is exactly
    // what the real OpenAPI contract promises, not an invented shape.
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
    if (p === "/api/v1/config/market-data/health/") {
      return route.fulfill(
        jsonBody({
          state: "HEALTHY",
          last_success_at: "2026-09-02T09:59:00Z",
          last_failure_at: null,
          last_error_safe: "",
          freshness_age_seconds: 4,
          consecutive_failures: 0,
          reconnect_count: 0,
          subscription_active: true,
        }),
      );
    }
    if (p === "/api/v1/config/market-data/worker-status/") {
      return route.fulfill(
        jsonBody({
          provider: "DHAN",
          worker_state: "RUNNING",
          token_state: "VALID",
          watchdog_state: "ARMED",
          last_packet_at: "2026-09-02T09:59:00Z",
          last_bar_at: "2026-09-02T09:59:00Z",
          packet_age_seconds: 2,
          bar_age_seconds: 4,
          reconnect_count: 0,
          consecutive_failures: 0,
          subscribed_instrument_count: 42,
          last_error_safe: "",
          updated_at: "2026-09-02T09:59:00Z",
          is_configured: true,
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

    // The backend contracts here are bare arrays (see e.g.
    // listStrategies/listWatchlists/listResearchStatuses in
    // src/common/api/*.ts), never a paginated {results: [...]} envelope
    // - the fallback below mirrors that.
    if (p === "/api/v1/config/watchlists/") {
      return route.fulfill(
        jsonBody([
          { name: "Nifty Momentum (mock)", instrument_ids: ["NSE:RELIANCE", "NSE:TCS"] },
          { name: "Breakout Candidates (mock)", instrument_ids: ["NSE:INFY"] },
        ]),
      );
    }
    if (p.endsWith("/schema/")) {
      return route.fulfill(
        jsonBody({ strategy_id: "ema-crossover", display_name: "EMA Crossover (mock)", parameters: [] }),
      );
    }
    if (p === "/api/v1/config/strategy-engine/strategies/" || p.endsWith("/strategies/")) {
      return route.fulfill(
        jsonBody([
          { strategy_id: "ema-crossover", display_name: "EMA Crossover (mock)", is_active: true },
          { strategy_id: "atr-breakout", display_name: "ATR Breakout (mock)", is_active: true },
        ]),
      );
    }
    if (p === "/api/v1/config/paper-trading/session/") {
      return route.fulfill(
        jsonBody({
          mode: "REPLAY",
          exists: false,
          accepted: false,
          message: "No paper session active (mock).",
          session_id: "",
          status: "STOPPED",
          strategy_id: "",
          timeframe: "5m",
          instrument_ids: [],
          replay_date: "2026-09-02",
          replay_cursor: 0,
          replay_total_steps: 0,
          playback_speed: 5,
          quantity: "10",
          available_strategy_ids: ["ema-crossover", "atr-breakout"],
          account: {
            starting_capital: "1000000.00",
            available_capital: "1000000.00",
            utilized_margin: "0.00",
            realized_pnl: "0.00",
            unrealized_pnl: "0.00",
          },
          open_positions: [],
          closed_trades: [],
          recent_signals: [],
        }),
      );
    }
    if (p === "/api/v1/config/kill-switch/") {
      return route.fulfill(jsonBody({ status: "ACTIVE", reason: null, changed_at: null }));
    }
    if (p === "/api/v1/config/paper-trading/funds/") {
      return route.fulfill(
        jsonBody({
          available_balance: "100000.00",
          utilized_margin: "0.00",
          updated_at: "2026-09-02T09:59:00Z",
        }),
      );
    }
    if (p.includes("/backtesting/") && p.endsWith("/results/")) {
      return route.fulfill(jsonBody([]));
    }
    if (p.endsWith("/statuses/") || p.includes("research-status")) {
      return route.fulfill(jsonBody([]));
    }

    // Generic fallback: an empty array satisfies every list-shaped
    // endpoint above that isn't explicitly mocked (the checkpoint
    // directive treats a genuine empty state as an acceptable capture).
    if (p.endsWith("/")) {
      return route.fulfill(jsonBody([]));
    }
    return route.fulfill(jsonBody({}));
  });
}

async function captureScreen(browser, screen, themeName, themeId) {
  // A fresh page per capture - simpler and far more robust than reusing
  // one page across 20 navigations/reloads (which was observed to
  // eventually crash the renderer under repeated HMR/websocket churn).
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", (err) => console.log(`[pageerror] ${screen.id}-${themeName}:`, err.message));
  await installApiMocks(page);

  await page.addInitScript((id) => {
    try {
      window.localStorage.setItem("intraday.ui.theme.v1", id);
    } catch {
      /* ignore - best effort */
    }
  }, themeId);

  await page.goto(BASE_URL, { waitUntil: "networkidle" });

  if (screen.id !== "dashboard") {
    const navButton = page.getByRole("button", { name: screen.label, exact: true });
    await navButton.click();
  }
  await page.waitForTimeout(500); // let the screen's own fetch effects settle

  const file = path.join(OUT_DIR, `${screen.id}-${themeName}.png`);
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
    for (const screen of SCREENS) {
      try {
        await captureScreen(browser, screen, themeName, themeId);
      } catch (err) {
        console.error(`FAILED to capture ${screen.id}-${themeName}:`, err.message);
      }
    }
  }

  await browser.close();
}

main();
