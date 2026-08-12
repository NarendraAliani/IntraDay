// frontend/src/common/auth/AuthContext.test.tsx
//
// Checkpoint 11: tests for the real `AuthProvider`/`useAuth` - the actual
// network calls (`fetchCurrentUser`/`login`/`logout`) are exercised, only
// `global.fetch` is mocked.
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "./AuthContext";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function Probe(): JSX.Element {
  const { state, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="status">{state.status}</span>
      {state.status === "authenticated" && (
        <span data-testid="username">{state.username}</span>
      )}
      <button
        type="button"
        onClick={() => {
          void login({ username: "reader", password: "secret" }).catch(() => {});
        }}
      >
        do-login
      </button>
      <button type="button" onClick={() => void logout()}>
        do-logout
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  it("loads the current-user state on mount", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ is_authenticated: true, username: "reader", capabilities: ["configuration.read"] }),
      ),
    );

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    expect(screen.getByTestId("status")).toHaveTextContent("loading");
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("username")).toHaveTextContent("reader");
  });

  it("treats an anonymous session response as the anonymous state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ is_authenticated: false, username: null, capabilities: [] }),
      ),
    );

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
  });

  it("drops back to anonymous after logout", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (typeof url === "string" && url.includes("/logout/")) {
        return Promise.resolve(
          jsonResponse({ is_authenticated: false, username: null, capabilities: [] }),
        );
      }
      return Promise.resolve(
        jsonResponse({ is_authenticated: true, username: "reader", capabilities: ["configuration.read"] }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await act(async () => {
      screen.getByText("do-logout").click();
    });

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
  });

  it("drops back to anonymous when any request comes back 401 (session expiry)", async () => {
    let requestCount = 0;
    const fetchMock = vi.fn().mockImplementation(() => {
      requestCount += 1;
      if (requestCount === 1) {
        return Promise.resolve(
          jsonResponse(
            { is_authenticated: true, username: "reader", capabilities: ["configuration.read"] },
          ),
        );
      }
      return Promise.resolve(
        jsonResponse({ error_code: "invalid_credentials", message: "Invalid username or password." }, 401),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    // A later request (e.g. a stale session) comes back 401.
    await act(async () => {
      screen.getByText("do-login").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
  });
});
