// frontend/src/test/testAuth.tsx
//
// Checkpoint 11: test-only helpers for rendering components that call
// `useAuth()` without needing a real `/api/v1/auth/session/` network
// round-trip in every unrelated test. Provides a fixed `AuthContextValue`
// directly via `AuthContext.Provider` - the real `AuthProvider` (and its
// real network call) is exercised separately, by
// src/common/auth/AuthContext.test.tsx and the login-workflow tests.
import { render } from "@testing-library/react";
import { vi } from "vitest";
import type { RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";

import { AuthContext } from "../common/auth/AuthContext";
import type { AuthContextValue, AuthState } from "../common/auth/AuthContext";

const DEFAULT_AUTHENTICATED_STATE: AuthState = {
  status: "authenticated",
  username: "operator",
  capabilities: ["configuration.read", "configuration.activate"],
};

export function authValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    state: DEFAULT_AUTHENTICATED_STATE,
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    isAuthenticating: false,
    ...overrides,
  };
}

/** Renders `ui` inside a fixed `AuthContext.Provider` - defaults to an
 * authenticated operator (read + activate capabilities), matching what
 * most Configuration Viewer tests need without repeating the setup. */
export function renderWithAuth(
  ui: ReactElement,
  authOverrides: Partial<AuthContextValue> = {},
): RenderResult {
  return render(
    <AuthContext.Provider value={authValue(authOverrides)}>{ui}</AuthContext.Provider>,
  );
}
