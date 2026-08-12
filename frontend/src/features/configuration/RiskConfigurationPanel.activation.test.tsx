// frontend/src/features/configuration/RiskConfigurationPanel.activation.test.tsx
//
// Checkpoint 10: tests for the risk-configuration activation workflow -
// select historical version -> confirm -> real activation API client ->
// backend state change -> refreshed active state. Only `global.fetch` (the
// network boundary) is mocked; the real generated contract types, the real
// `activateRiskConfigurationVersion`/`apiPost` client functions, and the
// real `RiskConfigurationPanel` component are exercised together - the
// same real-boundary philosophy established in Checkpoint 9's
// RiskConfigurationPanel.test.tsx.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RiskConfigurationPanel } from "./RiskConfigurationPanel";
import type { components } from "@shared/generated_contracts/api-types";

type RiskConfigurationResponse = components["schemas"]["RiskConfigurationResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function record(version: string, isActive: boolean): RiskConfigurationResponse {
  return {
    risk_configuration_id: "default",
    version,
    limits: {
      max_intraday_loss: "10000.00",
      max_position_size: "50000.00",
      max_per_trade_risk: "1000.00",
    },
    created_at: "2026-01-01T09:15:00Z",
    is_active: isActive,
  };
}

const INITIAL_LIST: RiskConfigurationResponse[] = [record("v1", true), record("v2", false)];
const AFTER_ACTIVATION_LIST: RiskConfigurationResponse[] = [record("v1", false), record("v2", true)];

async function renderLoaded(fetchMock: ReturnType<typeof vi.fn>): Promise<void> {
  vi.stubGlobal("fetch", fetchMock);
  render(<RiskConfigurationPanel />);
  await waitFor(() => expect(screen.getByText(/default — v1/)).toBeInTheDocument());
}

describe("RiskConfigurationPanel activation workflow", () => {
  it("shows an Activate action only for historical versions", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(INITIAL_LIST));
    await renderLoaded(fetchMock);

    expect(screen.getByRole("button", { name: "Activate Version v2" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Activate Version v1" }),
    ).not.toBeInTheDocument();
  });

  it("opens a confirmation dialog identifying current and target versions on Activate click", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(INITIAL_LIST));
    await renderLoaded(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Activate Version v2" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Current active version:/).parentElement).toHaveTextContent(
      "v1",
    );
    expect(within(dialog).getByText(/New active version:/).parentElement).toHaveTextContent("v2");
  });

  it("does not call the API when Cancel is clicked", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(INITIAL_LIST));
    await renderLoaded(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Activate Version v2" }));
    const dialog = await screen.findByRole("dialog");
    const callCountBeforeCancel = fetchMock.mock.calls.length;

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBe(callCountBeforeCancel);
  });

  it("confirming calls the real activation endpoint with the correct path", async () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(jsonResponse(record("v2", true)));
      }
      return Promise.resolve(jsonResponse(INITIAL_LIST));
    });
    await renderLoaded(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Activate Version v2" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm Activation of Version v2" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/config/risk/default/v2/activate/"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("disables the confirm button while submitting so repeated clicks cannot double-submit", async () => {
    let resolvePost: (() => void) | undefined;
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolvePost = () => resolve(jsonResponse(record("v2", true)));
        });
      }
      return Promise.resolve(jsonResponse(INITIAL_LIST));
    });
    await renderLoaded(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Activate Version v2" }));
    const dialog = await screen.findByRole("dialog");
    const confirmButton = within(dialog).getByRole("button", {
      name: "Confirm Activation of Version v2",
    });

    fireEvent.click(confirmButton);
    // Button becomes disabled once submitting starts; further clicks are
    // no-ops at the DOM level, but also guarded in the handler itself.
    await waitFor(() => expect(confirmButton).toBeDisabled());
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    const postCallsWhileSubmitting = fetchMock.mock.calls.filter((call: unknown[]) => {
      const init = call[1] as RequestInit | undefined;
      return init?.method === "POST";
    });
    expect(postCallsWhileSubmitting).toHaveLength(1);

    resolvePost?.();
  });

  it("refreshes real backend state and closes the dialog on successful activation", async () => {
    let getCallCount = 0;
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(jsonResponse(record("v2", true)));
      }
      getCallCount += 1;
      return Promise.resolve(jsonResponse(getCallCount === 1 ? INITIAL_LIST : AFTER_ACTIVATION_LIST));
    });
    await renderLoaded(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Activate Version v2" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm Activation of Version v2" }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Real refetch happened (GET called a second time) and the DOM
    // reflects the fresh backend state, not a locally-mutated guess.
    expect(getCallCount).toBe(2);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Activate Version v1" })).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "Activate Version v2" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Version v2 is now the active risk configuration/),
    ).toBeInTheDocument();
  });

  it("closes the dialog on Escape without calling the activation API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(INITIAL_LIST));
    await renderLoaded(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Activate Version v2" }));
    await screen.findByRole("dialog");
    const callCountBeforeEscape = fetchMock.mock.calls.length;

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.length).toBe(callCountBeforeEscape);
  });

  it("shows a safe error message and keeps the dialog open on a backend rejection (409)", async () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({ error_code: "invalid_activation", message: "Version not found." }, 404),
        );
      }
      return Promise.resolve(jsonResponse(INITIAL_LIST));
    });
    await renderLoaded(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Activate Version v2" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm Activation of Version v2" }),
    );

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Version not found."));
    // Dialog stays open so the user can retry or cancel; no fabricated success.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows a safe error message on a network failure", async () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.reject(new TypeError("network down"));
      }
      return Promise.resolve(jsonResponse(INITIAL_LIST));
    });
    await renderLoaded(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Activate Version v2" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm Activation of Version v2" }),
    );

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/Unable to reach the IntraDay API/),
    );
  });

  it("shows the empty state with no activation affordance when there are no versions", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    render(<RiskConfigurationPanel />);

    await waitFor(() =>
      expect(screen.getByText(/No risk configuration versions found for "default"/)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /Activate Version/ })).not.toBeInTheDocument();
  });
});
