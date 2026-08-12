// frontend/src/common/auth/AuthContext.tsx
//
// Checkpoint 11: minimal authentication boundary. A single React Context
// + provider component - not Redux or another global-state framework,
// consistent with this project's "no heavy framework" pattern for the API
// layer (Checkpoint 9 §11). The backend remains the sole authority: this
// context only reflects `GET /api/v1/auth/session/`'s real response, it
// never invents or locally assumes an authentication state.
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { fetchCurrentUser, login as loginRequest, logout as logoutRequest } from "../api/authApi";
import { ApiNetworkError, ApiRequestError, setSessionExpiredHandler } from "../api/client";
import type { CurrentUserResponse, LoginRequest } from "../api/authApi";

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; username: string; capabilities: string[] };

export interface AuthContextValue {
  state: AuthState;
  /** Resolves on success; throws `ApiRequestError`/`ApiNetworkError` on failure
   * (caller - the login screen - is responsible for rendering the message). */
  login: (credentials: LoginRequest) => Promise<void>;
  logout: () => Promise<void>;
  /** True while `login`'s promise is in flight - the login screen's disabled state. */
  isAuthenticating: boolean;
}

// Exported (not just AuthProvider/useAuth) so tests can render a subtree
// with a fixed, fake-network-free auth state via
// `<AuthContext.Provider value={...}>` - see src/test/testAuth.tsx.
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function toAuthState(body: CurrentUserResponse): AuthState {
  if (body.is_authenticated && body.username) {
    return { status: "authenticated", username: body.username, capabilities: body.capabilities };
  }
  return { status: "anonymous" };
}

export function AuthProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const [isAuthenticating, setIsAuthenticating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchCurrentUser()
      .then((body) => {
        if (!cancelled) {
          setState(toAuthState(body));
        }
      })
      .catch(() => {
        // A failure to even reach the session endpoint (network error) is
        // treated the same as "not logged in" - there is no protected
        // data to show either way, and the Configuration Viewer's own
        // panels will surface a real error once the user is authenticated
        // and tries to load data.
        if (!cancelled) {
          setState({ status: "anonymous" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Session expiry (Checkpoint 11 §20 frontend test 10): any API
    // response that comes back 401 - e.g. the session cookie expired or
    // was invalidated server-side between page loads - drops the
    // frontend back to the anonymous state, so a stale "authenticated"
    // UI is never shown against a session the backend no longer honors.
    setSessionExpiredHandler(() => setState({ status: "anonymous" }));
    return () => setSessionExpiredHandler(null);
  }, []);

  const login = useCallback(async (credentials: LoginRequest): Promise<void> => {
    setIsAuthenticating(true);
    try {
      const body = await loginRequest(credentials);
      setState(toAuthState(body));
    } catch (error) {
      if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
        throw error;
      }
      throw new Error("An unexpected error occurred.");
    } finally {
      setIsAuthenticating(false);
    }
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    try {
      await logoutRequest();
    } finally {
      // Always return to the anonymous state, even if the logout request
      // itself failed (e.g. network error) - the frontend never claims a
      // still-authenticated state once the user has asked to log out.
      setState({ status: "anonymous" });
    }
  }, []);

  return (
    <AuthContext.Provider value={{ state, login, logout, isAuthenticating }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
