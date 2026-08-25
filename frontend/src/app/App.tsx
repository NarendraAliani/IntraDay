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
import { useState } from "react";

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
  | "strategy-monitor"
  | "paper-trading"
  | "reports";

/** Checkpoint 64.80-F2 Phase 8: every navigation entry carries a
 * semantic icon from the ONE icon system. The icons are decorative -
 * the text label is always present and is what assistive technology
 * announces - so they are `aria-hidden` by construction (see Icon.tsx). */
const NAV_ITEMS: Array<{ id: Screen; label: string; icon: IconName }> = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard" },
  { id: "configuration", label: "Configuration", icon: "settings" },
  { id: "settings", label: "Settings", icon: "settings" },
  { id: "live-scanner", label: "Live Scanner", icon: "signal" },
  { id: "live-paper-operations", label: "Live Paper Operations", icon: "paper-trading" },
  { id: "market-data", label: "Market Data", icon: "market" },
  { id: "market-data-archive", label: "Market Data Archive", icon: "archive" },
  { id: "strategies", label: "Strategies", icon: "research" },
  { id: "backtesting", label: "Backtesting", icon: "research" },
  { id: "comparison", label: "Compare", icon: "research" },
  { id: "watchlists", label: "Watchlists", icon: "market" },
  { id: "strategy-monitor", label: "Strategy Monitor", icon: "system-health" },
  { id: "paper-trading", label: "Paper Trading", icon: "paper-trading" },
  { id: "reports", label: "Reports", icon: "archive" },
];

function AppShell(): JSX.Element {
  const { state, logout } = useAuth();
  const [screen, setScreen] = useState<Screen>("dashboard");

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
    <main>
      <header className="app-shell__header">
        <p className="app-shell__brand">
          <Icon name="signal" />
          IntraDay
        </p>
        <nav className="app-shell__nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={screen === item.id ? "nav-link nav-link--active" : "nav-link"}
              aria-current={screen === item.id ? "page" : undefined}
              onClick={() => setScreen(item.id)}
            >
              <Icon name={item.icon} />
              {item.label}
            </button>
          ))}
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
      {screen === "strategy-monitor" && <StrategyMonitorPage />}
      {screen === "paper-trading" && <PaperTradingPage />}
      {screen === "reports" && <ReportsOverviewPage />}
    </main>
  );
}

export function App(): JSX.Element {
  return (
    <ThemeProvider>
      <AppShell />
    </ThemeProvider>
  );
}
