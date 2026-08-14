// frontend/src/features/settings/TelegramSettingsCard.test.tsx
//
// Checkpoint 22: real-boundary tests for the Telegram settings card,
// mirroring DhanSettingsCard.test.tsx's coverage for the parts specific
// to this provider (channel id + bot token fields, masked display,
// permission gating).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TelegramSettingsCard } from "./TelegramSettingsCard";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type TelegramSettingsResponse = components["schemas"]["TelegramSettingsResponse"];
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

const UNCONFIGURED: TelegramSettingsResponse = {
  channel_id_masked: "",
  channel_id_source: "UNCONFIGURED",
  bot_token_configured: false,
  bot_token_source: "UNCONFIGURED",
  enabled: false,
  updated_at: null,
  updated_by_username: "",
};

const CONFIGURED: TelegramSettingsResponse = {
  channel_id_masked: "-1••••56",
  channel_id_source: "DATABASE",
  bot_token_configured: true,
  bot_token_source: "DATABASE",
  enabled: true,
  updated_at: "2026-01-01T09:00:00Z",
  updated_by_username: "operator",
};

const NOT_CONFIGURED_STATUS: ConnectionStatusResponse = {
  provider: "telegram",
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

describe("TelegramSettingsCard", () => {
  it("renders the masked channel id, never a raw bot token", async () => {
    stubTwoGets(CONFIGURED, NOT_CONFIGURED_STATUS);

    renderWithAuth(<TelegramSettingsCard />);

    await waitFor(() => expect(screen.getByText("-1••••56")).toBeInTheDocument());
    expect(screen.getByText("Configured")).toBeInTheDocument();
  });

  it("hides the form for a reader without operator capability", async () => {
    stubTwoGets(UNCONFIGURED, NOT_CONFIGURED_STATUS);

    renderWithAuth(<TelegramSettingsCard />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });

    await waitFor(() => expect(screen.getByText(/read-only access/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /^save$/i })).not.toBeInTheDocument();
  });

  it("submits bot token and channel id, and clears fields on success", async () => {
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

    renderWithAuth(<TelegramSettingsCard />);

    await waitFor(() => expect(screen.getByLabelText(/channel id/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/channel id/i), { target: { value: "-100123456" } });
    fireEvent.change(screen.getByLabelText(/bot token/i), {
      target: { value: "fake-bot-token-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText("-1••••56")).toBeInTheDocument());
    expect(saveRequestBody).toEqual({
      bot_token: "fake-bot-token-123",
      channel_id: "-100123456",
      enabled: false,
    });
    expect((screen.getByLabelText(/bot token/i) as HTMLInputElement).value).toBe("");
  });
});
