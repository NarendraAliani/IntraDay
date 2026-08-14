// frontend/src/features/settings/DhanSettingsCard.test.tsx
//
// Checkpoint 22: real-boundary tests for the Dhan settings card - only
// `global.fetch` is mocked, the real generated contract types, the real
// settingsApi.ts client functions, and the real component are exercised
// together (matching RiskConfigurationPanel.test.tsx's established
// philosophy). Every credential value used here is an obviously-fake
// placeholder, never anything resembling a real secret.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DhanSettingsCard } from "./DhanSettingsCard";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type DhanSettingsResponse = components["schemas"]["DhanSettingsResponse"];
type ConnectionStatusResponse = components["schemas"]["ConnectionStatusResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const UNCONFIGURED: DhanSettingsResponse = {
  client_id_masked: "",
  client_id_source: "UNCONFIGURED",
  access_token_configured: false,
  access_token_source: "UNCONFIGURED",
  enabled: false,
  updated_at: null,
  updated_by_username: "",
};

const CONFIGURED: DhanSettingsResponse = {
  client_id_masked: "10••••23",
  client_id_source: "DATABASE",
  access_token_configured: true,
  access_token_source: "DATABASE",
  enabled: true,
  updated_at: "2026-01-01T09:00:00Z",
  updated_by_username: "operator",
};

const NOT_CONFIGURED_STATUS: ConnectionStatusResponse = {
  provider: "dhan",
  status: "NOT_CONFIGURED",
  last_checked_at: null,
  last_success_at: null,
  last_failure_at: null,
  failure_reason_safe: "",
  latency_ms: null,
};

function stubTwoGets(settingsBody: unknown, statusBody: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/status/")) {
        return Promise.resolve(jsonResponse(statusBody));
      }
      return Promise.resolve(jsonResponse(settingsBody));
    }),
  );
}

describe("DhanSettingsCard", () => {
  it("shows a loading state before the responses resolve", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );

    renderWithAuth(<DhanSettingsCard />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("renders the masked client id and configured status, never a raw secret", async () => {
    stubTwoGets(CONFIGURED, NOT_CONFIGURED_STATUS);

    renderWithAuth(<DhanSettingsCard />);

    await waitFor(() => expect(screen.getByText("10••••23")).toBeInTheDocument());
    expect(screen.getByText("Configured")).toBeInTheDocument();
    expect(screen.queryByText(/^\d{10}$/)).not.toBeInTheDocument();
  });

  it("hides the save/test-connection form for a reader without operator capability", async () => {
    stubTwoGets(UNCONFIGURED, NOT_CONFIGURED_STATUS);

    renderWithAuth(<DhanSettingsCard />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });

    await waitFor(() =>
      expect(screen.getByText(/read-only access/i)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /test connection/i })).not.toBeInTheDocument();
  });

  it("shows the save/test-connection form for an operator", async () => {
    stubTwoGets(UNCONFIGURED, NOT_CONFIGURED_STATUS);

    renderWithAuth(<DhanSettingsCard />);

    await waitFor(() => expect(screen.getByRole("button", { name: /^save$/i })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /test connection/i })).toBeInTheDocument();
  });

  it("submits client id and access token, then clears the form fields on success", async () => {
    let saveRequestBody: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/save/")) {
          saveRequestBody = init?.body ? JSON.parse(String(init.body)) : null;
          return Promise.resolve(jsonResponse(CONFIGURED));
        }
        if (url.includes("/status/")) {
          return Promise.resolve(jsonResponse(NOT_CONFIGURED_STATUS));
        }
        return Promise.resolve(jsonResponse(UNCONFIGURED));
      }),
    );

    renderWithAuth(<DhanSettingsCard />);

    await waitFor(() => expect(screen.getByLabelText(/client id/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/client id/i), {
      target: { value: "1000000123" },
    });
    fireEvent.change(screen.getByLabelText(/access token/i), {
      target: { value: "fake-test-token-not-real" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText("10••••23")).toBeInTheDocument());
    expect(saveRequestBody).toEqual({
      client_id: "1000000123",
      access_token: "fake-test-token-not-real",
      enabled: false,
    });
    // Fields are cleared after a successful save - never re-populated
    // with the just-submitted secret (write-only pattern).
    expect((screen.getByLabelText(/access token/i) as HTMLInputElement).value).toBe("");
  });

  it("performs a test connection and displays the returned status without leaking secrets", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/test/")) {
          return Promise.resolve(
            jsonResponse({
              provider: "dhan",
              status: "AUTHENTICATION_FAILED",
              last_checked_at: "2026-01-01T09:00:00Z",
              last_success_at: null,
              last_failure_at: "2026-01-01T09:00:00Z",
              failure_reason_safe: "Dhan rejected the configured Client ID/Access Token.",
              latency_ms: 300,
            }),
          );
        }
        if (url.includes("/status/")) {
          return Promise.resolve(jsonResponse(NOT_CONFIGURED_STATUS));
        }
        return Promise.resolve(jsonResponse(CONFIGURED));
      }),
    );

    renderWithAuth(<DhanSettingsCard />);

    await waitFor(() => expect(screen.getByText("Configured")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));

    await waitFor(() =>
      expect(screen.getByText(/authentication failed/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Dhan rejected the configured Client ID/Access Token."),
    ).toBeInTheDocument();
  });

  it("renders a safe error message when loading fails, never raw backend internals", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({ error_code: "internal_error", message: "Unable to load settings." }, 500),
        ),
      ),
    );

    renderWithAuth(<DhanSettingsCard />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to load settings.");
  });
});
