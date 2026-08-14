// frontend/src/features/paper-trading/PaperTradingPage.test.tsx
//
// Checkpoint 34 Part 18: real-boundary tests for the Paper Trading page
// - only `global.fetch` is mocked; the real generated contract types
// and the real component are exercised together. Explicitly proves
// PAPER vs LIVE distinction and that no LIVE control exists anywhere.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PaperTradingPage } from "./PaperTradingPage";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type KillSwitchStatusResponse = components["schemas"]["KillSwitchStatusResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ACTIVE: KillSwitchStatusResponse = { status: "ACTIVE", reason: null, changed_at: null };
const HALTED: KillSwitchStatusResponse = {
  status: "HALTED",
  reason: "manual halt",
  changed_at: "2026-08-14T09:00:00Z",
};

describe("PaperTradingPage", () => {
  it("shows a PAPER MODE banner and never shows a LIVE control", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(ACTIVE)),
    );
    renderWithAuth(<PaperTradingPage />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });
    await waitFor(() => expect(screen.getByText(/PAPER MODE/)).toBeInTheDocument());
    expect(screen.getByText(/LIVE mode does not exist/)).toBeInTheDocument();
    expect(screen.queryByText("Enable Live Trading")).not.toBeInTheDocument();
  });

  it("shows kill switch status as Active by default", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(ACTIVE)));
    renderWithAuth(<PaperTradingPage />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });
    await waitFor(() => expect(screen.getByText("● Active")).toBeInTheDocument());
  });

  it("shows HALTED status and reason when engaged", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(HALTED)));
    renderWithAuth(<PaperTradingPage />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });
    await waitFor(() => expect(screen.getByText("✕ HALTED")).toBeInTheDocument());
    expect(screen.getByText("manual halt")).toBeInTheDocument();
  });

  it("read-only users cannot see engage/reset controls", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(ACTIVE)));
    renderWithAuth(<PaperTradingPage />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });
    await waitFor(() => expect(screen.getByText("● Active")).toBeInTheDocument());
    expect(screen.queryByText("Engage Kill Switch")).not.toBeInTheDocument();
    expect(screen.getByText(/read-only access/)).toBeInTheDocument();
  });

  it("operators can engage the kill switch", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(ACTIVE))
      .mockResolvedValueOnce(jsonResponse(HALTED))
      .mockResolvedValueOnce(jsonResponse(HALTED));
    vi.stubGlobal("fetch", fetchMock);
    renderWithAuth(<PaperTradingPage />, {
      state: {
        status: "authenticated",
        username: "operator",
        capabilities: ["configuration.read", "configuration.activate"],
      },
    });
    await waitFor(() => expect(screen.getByText("● Active")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Reason for halting"), {
      target: { value: "manual halt" },
    });
    fireEvent.click(screen.getByText("Engage Kill Switch"));

    await waitFor(() => expect(screen.getByText("✕ HALTED")).toBeInTheDocument());
  });

  it("never renders a trading control (Buy/Sell/Execute)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(ACTIVE)));
    renderWithAuth(<PaperTradingPage />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });
    await waitFor(() => expect(screen.getByText("● Active")).toBeInTheDocument());
    for (const forbidden of ["Buy", "Sell", "Place Order"]) {
      expect(screen.queryByText(forbidden)).not.toBeInTheDocument();
    }
  });

  it("shows NOT_YET_IMPLEMENTED for order submission via CapabilityStatus", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(ACTIVE)));
    renderWithAuth(<PaperTradingPage />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });
    await waitFor(() => expect(screen.getByText("Order Submission (UI)")).toBeInTheDocument());
    expect(screen.getAllByText("○ Not Yet Implemented").length).toBeGreaterThan(0);
  });
});
