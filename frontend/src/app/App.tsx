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
import { useState } from "react";

import { useAuth } from "../common/auth/AuthContext";
import { LoadingState } from "../common/components/LoadingState";
import { ConfigurationViewer } from "../features/configuration/ConfigurationViewer";
import { LoginScreen } from "../features/auth/LoginScreen";
import { SettingsPage } from "../features/settings/SettingsPage";

type Screen = "configuration" | "settings";

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
          <button
            type="button"
            className={screen === "configuration" ? "nav-link nav-link--active" : "nav-link"}
            aria-current={screen === "configuration" ? "page" : undefined}
            onClick={() => setScreen("configuration")}
          >
            Configuration
          </button>
          <button
            type="button"
            className={screen === "settings" ? "nav-link nav-link--active" : "nav-link"}
            aria-current={screen === "settings" ? "page" : undefined}
            onClick={() => setScreen("settings")}
          >
            Settings
          </button>
        </nav>
        <span>
          Signed in as <strong>{state.username}</strong>
        </span>
        <button type="button" onClick={() => void logout()}>
          Sign out
        </button>
      </header>
      {screen === "configuration" ? <ConfigurationViewer /> : <SettingsPage />}
    </main>
  );
}

export function App(): JSX.Element {
  return <AppShell />;
}
