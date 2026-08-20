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
import { useState } from "react";

import { useAuth } from "../common/auth/AuthContext";
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

type Screen =
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

const NAV_ITEMS: Array<{ id: Screen; label: string }> = [
  { id: "configuration", label: "Configuration" },
  { id: "settings", label: "Settings" },
  { id: "live-scanner", label: "Live Scanner" },
  { id: "live-paper-operations", label: "Live Paper Operations" },
  { id: "market-data", label: "Market Data" },
  { id: "strategies", label: "Strategies" },
  { id: "backtesting", label: "Backtesting" },
  { id: "comparison", label: "Compare" },
  { id: "watchlists", label: "Watchlists" },
  { id: "strategy-monitor", label: "Strategy Monitor" },
  { id: "paper-trading", label: "Paper Trading" },
  { id: "reports", label: "Reports" },
];

function AppShell(): JSX.Element {
  const { state, logout } = useAuth();
  const [screen, setScreen] = useState<Screen>("configuration");

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
        <nav className="app-shell__nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={screen === item.id ? "nav-link nav-link--active" : "nav-link"}
              aria-current={screen === item.id ? "page" : undefined}
              onClick={() => setScreen(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <span>
          Signed in as <strong>{state.username}</strong>
        </span>
        <button type="button" onClick={() => void logout()}>
          Sign out
        </button>
      </header>
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
  return <AppShell />;
}
