// frontend/src/app/App.tsx
//
// Checkpoint 9: root application component. Replaced Checkpoint 4's
// BootstrapPlaceholder now that a real screen exists.
//
// Checkpoint 11: the Configuration Viewer is no longer reachable as an
// anonymous screen. `AuthProvider` establishes the authentication
// boundary; this component is the client-side half of enforcing it
// (routing only - the backend remains the real enforcement point, see
// docs/architecture/AUTHENTICATION_AUTHORIZATION.md). Three states:
// loading (initial session check in flight), anonymous (show
// LoginScreen), authenticated (show the control-plane application with a
// sign-out affordance).
//
// Checkpoint 22: a second top-level screen (Settings) is added alongside
// Configuration Viewer. No routing library is introduced for two
// screens - a single piece of local state toggles which one renders,
// matching this project's existing "no heavy framework unless the
// screen count actually needs it" convention (Checkpoint 9 §11).
//
// Checkpoint 23: a third screen (Live Market Data Monitor) is added the
// same way - still no routing library for three screens.
//
// Checkpoint 27: Backtesting, Watchlists, and Strategy Monitor/Compare
// are added the same way - still no routing library. Every new nav
// entry reads DISCOVER/CONFIGURE/BACKTEST/REVIEW language, never
// BUY/SELL/DEPLOY LIVE (Part 34).
//
// Checkpoint 64.80-F2: the shell gains a product identity (brand mark +
// semantic navigation icons + a user-facing Theme control). The
// navigation MECHANISM is unchanged - still one piece of local state,
// still no routing library. `ThemeProvider` wraps the shell here rather
// than in `main.tsx` so that every test which renders <App /> gets a
// correctly themed tree without having to know the theme system exists.
import { useEffect, useRef, useState } from "react";

import { useAuth } from "../common/auth/AuthContext";
import { Icon } from "../common/icons/Icon";
import type { IconName } from "../common/icons/Icon";
import { ThemeProvider } from "./theme/ThemeProvider";
import { ThemeSelector } from "./theme/ThemeSelector";
import { LoadingState } from "../common/components/LoadingState";
import { ConfigurationViewer } from "../features/configuration/ConfigurationViewer";
import { LoginScreen } from "../features/auth/LoginScreen";
import { LiveMarketDataMonitor } from "../features/market-data/LiveMarketDataMonitor";
import { LivePaperOperationsConsole } from "../features/market-data/LivePaperOperationsConsole";
import { LiveScannerConsole } from "../features/market-data/LiveScannerConsole";
import { SettingsPage } from "../features/settings/SettingsPage";
import { StrategyConfigurationPage } from "../features/strategy-config/StrategyConfigurationPage";
import { BacktestingWorkbenchPage } from "../features/backtesting/BacktestingWorkbenchPage";
import { ComparisonPage } from "../features/backtesting/ComparisonPage";
import { StrategyMonitorPage } from "../features/backtesting/StrategyMonitorPage";
import { WatchlistPage } from "../features/backtesting/WatchlistPage";
import { ScreenerPage } from "../features/screening/ScreenerPage";
import { ReportsOverviewPage } from "../features/reports/ReportsOverviewPage";
import { PaperTradingPage } from "../features/paper-trading/PaperTradingPage";
// Checkpoint 64.80-F: the Application Dashboard becomes the landing
// screen, and the Market Data Archive gets a minimal detail shell. Both
// are added as ordinary entries in the EXISTING screen-state pattern -
// no routing library is introduced, no navigation redesign.
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { MarketDataArchivePage } from "../features/market-data/MarketDataArchivePage";

type Screen =
  | "dashboard"
  | "market-data-archive"
  | "configuration"
  | "settings"
  | "live-scanner"
  | "live-paper-operations"
  | "market-data"
  | "strategies"
  | "backtesting"
  | "comparison"
  | "watchlists"
  | "screener"
  | "strategy-monitor"
  | "paper-trading"
  | "reports";

interface NavItem {
  id: Screen;
  label: string;
  icon: IconName;
}

/** Checkpoint 64.80-F2 Phase 8: every navigation entry carries a
 * semantic icon from the ONE icon system. The icons are decorative -
 * the text label is always present and is what assistive technology
 * announces - so they are `aria-hidden` by construction (see Icon.tsx).
 *
 * Checkpoint FRONTEND-4: grouped by function into 4 dropdown groups
 * (plus Dashboard, which stays a standalone top-level entry - it's the
 * landing screen, not a member of any category). This replaces the
 * flat 14-button row that wrapped across 3 lines at a normal viewport
 * width (`FRONTEND-2`'s own Category 3 finding). Every screen/route
 * this app has is still here, under exactly the same `Screen` id - only
 * how they're grouped for display changed, nothing was removed or
 * renamed. */
const NAV_GROUPS: Array<{ id: string; label: string; icon: IconName; items: NavItem[] }> = [
  {
    id: "live-operations",
    label: "Live Operations",
    icon: "signal",
    items: [
      { id: "live-scanner", label: "Live Scanner", icon: "signal" },
      { id: "live-paper-operations", label: "Live Paper Operations", icon: "paper-trading" },
      { id: "market-data", label: "Market Data", icon: "market" },
    ],
  },
  {
    id: "research",
    label: "Research",
    icon: "research",
    items: [
      { id: "strategies", label: "Strategies", icon: "research" },
      { id: "backtesting", label: "Backtesting", icon: "research" },
      { id: "comparison", label: "Compare", icon: "research" },
      { id: "watchlists", label: "Watchlists", icon: "market" },
      { id: "screener", label: "Screener", icon: "research" },
    ],
  },
  {
    // Checkpoint FRONTEND-4: the group is deliberately labeled
    // "System Setup," not "Configuration" - a group whose own summary
    // shares an accessible name with one of its own items (the
    // "Configuration" screen) is a real, genuine collision in a real
    // browser's accessibility tree (Chromium exposes `<summary>` with
    // an implicit `button` role) - found live via Playwright, which
    // enforces this; jsdom-based unit tests do not, and missed it.
    id: "configuration",
    label: "System Setup",
    icon: "settings",
    items: [
      { id: "configuration", label: "Configuration", icon: "settings" },
      { id: "settings", label: "Settings", icon: "settings" },
      { id: "strategy-monitor", label: "Strategy Monitor", icon: "system-health" },
    ],
  },
  {
    id: "trading-record",
    label: "Trading Record",
    icon: "archive",
    items: [
      { id: "paper-trading", label: "Paper Trading", icon: "paper-trading" },
      { id: "reports", label: "Reports", icon: "archive" },
      { id: "market-data-archive", label: "Market Data Archive", icon: "archive" },
    ],
  },
];

const DASHBOARD_ITEM: NavItem = { id: "dashboard", label: "Dashboard", icon: "dashboard" };

function AppShell(): JSX.Element {
  const { state, logout } = useAuth();
  const [screen, setScreen] = useState<Screen>("dashboard");
  // CHECKPOINT-FRONTEND-5 Issue 1: which nav dropdown (if any) is open -
  // fully CONTROLLED state, not the native <details> "open" attribute
  // driven by `containsActive`. The old approach forced a group back
  // open on every render whenever the active screen lived inside it,
  // which meant a group containing the current screen could never
  // actually be closed - the operator's own "requires an extra click
  // elsewhere" report. Selecting an item, clicking outside the nav, or
  // pressing Escape all now close it in one action.
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (openGroupId === null) return;
    function handlePointerDown(event: MouseEvent): void {
      if (navRef.current && !navRef.current.contains(event.target as Node)) {
        setOpenGroupId(null);
      }
    }
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") setOpenGroupId(null);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [openGroupId]);

  if (state.status === "loading") {
    return (
      <main className="app-shell app-shell--loading">
        <LoadingState label="Checking your session…" />
      </main>
    );
  }

  if (state.status === "anonymous") {
    return <LoginScreen />;
  }

  return (
    <>
      <div className="app-shell__header-bar">
        <header className="app-shell__header">
          <p className="app-shell__brand">
            <Icon name="signal" />
            IntraDay
          </p>
          <nav className="app-shell__nav" aria-label="Primary" ref={navRef}>
            <button
              type="button"
              className={screen === DASHBOARD_ITEM.id ? "nav-link nav-link--active" : "nav-link"}
              aria-current={screen === DASHBOARD_ITEM.id ? "page" : undefined}
              onClick={() => {
                setScreen(DASHBOARD_ITEM.id);
                setOpenGroupId(null);
              }}
            >
              <Icon name={DASHBOARD_ITEM.icon} />
              {DASHBOARD_ITEM.label}
            </button>
            {NAV_GROUPS.map((group) => {
              const containsActive = group.items.some((item) => item.id === screen);
              const isOpen = openGroupId === group.id;
              return (
                <details key={group.id} className="nav-group" open={isOpen}>
                  <summary
                    className={
                      containsActive ? "nav-group__toggle nav-group__toggle--active" : "nav-group__toggle"
                    }
                    onClick={(e) => {
                      // Fully controlled - the native disclosure toggle
                      // is never trusted on its own (see the state
                      // comment above), so the default browser toggle
                      // is prevented and replaced with explicit state.
                      e.preventDefault();
                      setOpenGroupId((prev) => (prev === group.id ? null : group.id));
                    }}
                  >
                    <Icon name={group.icon} />
                    {group.label}
                  </summary>
                  <div className="nav-group__items">
                    {group.items.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={screen === item.id ? "nav-link nav-link--active" : "nav-link"}
                        aria-current={screen === item.id ? "page" : undefined}
                        onClick={() => {
                          setScreen(item.id);
                          setOpenGroupId(null);
                        }}
                      >
                        <Icon name={item.icon} />
                        {item.label}
                      </button>
                    ))}
                  </div>
                </details>
              );
            })}
          </nav>
          <div className="app-shell__identity">
            <ThemeSelector />
            <span>
              Signed in as <strong>{state.username}</strong>
            </span>
            <button type="button" onClick={() => void logout()}>
              Sign out
            </button>
          </div>
        </header>
      </div>
      <main>
      {screen === "dashboard" && (
        <DashboardPage
          onOpenMarketData={() => setScreen("market-data")}
          onOpenArchive={() => setScreen("market-data-archive")}
          onOpenPaperTrading={() => setScreen("paper-trading")}
          onOpenBacktesting={() => setScreen("backtesting")}
          // Checkpoint 64.80-F3 Phase 7: the Decision Pipeline drills
          // down into EXISTING screens through the EXISTING navigation
          // mechanism (this project has no router - one piece of screen
          // state, see the header comment). `PipelineDestination` is a
          // closed union of screen ids that already exist, so a node can
          // never point at a screen this application does not have.
          onNavigate={(destination) => setScreen(destination)}
        />
      )}
      {screen === "market-data-archive" && <MarketDataArchivePage />}
      {screen === "configuration" && <ConfigurationViewer />}
      {screen === "settings" && <SettingsPage />}
      {screen === "live-scanner" && <LiveScannerConsole />}
      {screen === "live-paper-operations" && <LivePaperOperationsConsole />}
      {screen === "market-data" && <LiveMarketDataMonitor />}
      {screen === "strategies" && <StrategyConfigurationPage />}
      {screen === "backtesting" && <BacktestingWorkbenchPage />}
      {screen === "comparison" && <ComparisonPage />}
      {screen === "watchlists" && <WatchlistPage />}
      {screen === "screener" && <ScreenerPage />}
      {screen === "strategy-monitor" && <StrategyMonitorPage />}
      {screen === "paper-trading" && <PaperTradingPage />}
      {screen === "reports" && <ReportsOverviewPage />}
      </main>
    </>
  );
}

export function App(): JSX.Element {
  return (
    <ThemeProvider>
      <AppShell />
    </ThemeProvider>
  );
}
