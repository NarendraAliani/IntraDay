// frontend/src/features/configuration/RiskConfigurationPanel.test.tsx
//
// Checkpoint 9: Configuration screen tests. This is the test that proves
// the real contract boundary end to end - generated OpenAPI TypeScript
// type (components["schemas"]["RiskConfigurationResponse"]) -> the real
// `listRiskConfigurationVersions` API client function -> the real
// `RiskConfigurationPanel` component. Only `global.fetch` (the network
// edge) is mocked; nothing in between is a fake/stubbed interface.
import { render, screen, waitFor } from "@testing-library/react";
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

describe("RiskConfigurationPanel", () => {
  it("shows a loading state before the response resolves", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );

    render(<RiskConfigurationPanel />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("renders real API data end-to-end, distinguishing active from historical versions", async () => {
    const body: RiskConfigurationResponse[] = [
      {
        risk_configuration_id: "default",
        version: "v1",
        limits: {
          max_intraday_loss: "10000.00",
          max_position_size: "50000.00",
          max_per_trade_risk: "1000.00",
        },
        created_at: "2026-01-01T09:15:00Z",
        is_active: false,
      },
      {
        risk_configuration_id: "default",
        version: "v2",
        limits: {
          max_intraday_loss: "12000.00",
          max_position_size: "60000.00",
          max_per_trade_risk: "1500.00",
        },
        created_at: "2026-02-01T09:15:00Z",
        is_active: true,
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(body)),
    );

    render(<RiskConfigurationPanel />);

    await waitFor(() => expect(screen.getByText(/default — v1/)).toBeInTheDocument());
    expect(screen.getByText(/default — v2/)).toBeInTheDocument();
    expect(screen.getAllByText("● Active")).toHaveLength(1);
    expect(screen.getAllByText("○ Historical")).toHaveLength(1);
  });

  it("renders a safe error message instead of leaking backend internals", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { error_code: "not_found", message: "No risk configuration versions found." },
          404,
        ),
      ),
    );

    render(<RiskConfigurationPanel />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("No risk configuration versions found.");
  });

  it("renders an empty state without fabricating sample data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([])));

    render(<RiskConfigurationPanel />);

    await waitFor(() =>
      expect(screen.getByText(/No risk configuration versions found for "default"/)).toBeInTheDocument(),
    );
  });
});
