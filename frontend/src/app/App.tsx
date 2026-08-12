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
import { useAuth } from "../common/auth/AuthContext";
import { LoadingState } from "../common/components/LoadingState";
import { ConfigurationViewer } from "../features/configuration/ConfigurationViewer";
import { LoginScreen } from "../features/auth/LoginScreen";

function AppShell(): JSX.Element {
  const { state, logout } = useAuth();

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
        <span>
          Signed in as <strong>{state.username}</strong>
        </span>
        <button type="button" onClick={() => void logout()}>
          Sign out
        </button>
      </header>
      <ConfigurationViewer />
    </main>
  );
}

export function App(): JSX.Element {
  return <AppShell />;
}
