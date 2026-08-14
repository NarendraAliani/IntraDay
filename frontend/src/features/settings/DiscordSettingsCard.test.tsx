// frontend/src/features/settings/DiscordSettingsCard.test.tsx
//
// Checkpoint 22: real-boundary tests for the Discord settings card,
// mirroring DhanSettingsCard.test.tsx's coverage for the parts specific
// to this provider (single webhook-url secret field, no separate
// identifier field).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DiscordSettingsCard } from "./DiscordSettingsCard";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type DiscordSettingsResponse = components["schemas"]["DiscordSettingsResponse"];
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

const UNCONFIGURED: DiscordSettingsResponse = {
  webhook_configured: false,
  webhook_source: "UNCONFIGURED",
  enabled: false,
  updated_at: null,
  updated_by_username: "",
};

const CONFIGURED: DiscordSettingsResponse = {
  webhook_configured: true,
  webhook_source: "DATABASE",
  enabled: true,
  updated_at: "2026-01-01T09:00:00Z",
  updated_by_username: "operator",
};

const NOT_CONFIGURED_STATUS: ConnectionStatusResponse = {
  provider: "discord",
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

describe("DiscordSettingsCard", () => {
  it("renders configured/not-configured, never the raw webhook URL", async () => {
    stubTwoGets(CONFIGURED, NOT_CONFIGURED_STATUS);

    renderWithAuth(<DiscordSettingsCard />);

    await waitFor(() => expect(screen.getAllByText("Configured").length).toBeGreaterThan(0));
    expect(screen.queryByText(/discord\.com\/api\/webhooks/i)).not.toBeInTheDocument();
  });

  it("hides the form for a reader without operator capability", async () => {
    stubTwoGets(UNCONFIGURED, NOT_CONFIGURED_STATUS);

    renderWithAuth(<DiscordSettingsCard />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });

    await waitFor(() => expect(screen.getByText(/read-only access/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
  });

  it("submits the webhook url and clears the field on success", async () => {
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

    renderWithAuth(<DiscordSettingsCard />);

    await waitFor(() => expect(screen.getByLabelText(/webhook url/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/webhook url/i), {
      target: { value: "https://discord.com/api/webhooks/fake/token" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.getAllByText("Configured").length).toBeGreaterThan(0));
    expect(saveRequestBody).toEqual({
      webhook_url: "https://discord.com/api/webhooks/fake/token",
      enabled: false,
    });
    expect((screen.getByLabelText(/webhook url/i) as HTMLInputElement).value).toBe("");
  });
});
