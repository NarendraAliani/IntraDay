// frontend/src/features/market-data/MarketDataArchivePage.test.tsx
//
// Checkpoint 64.80-F: the archive shell must be HONEST. Its central
// assertion is negative: while no archive HTTP endpoint exists, this
// page must never render a bar count, a completeness percentage, or a
// "reconciled" status - every archive field reads "Not available".
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MarketDataArchivePage } from "./MarketDataArchivePage";
import { SESSION_CLOSED } from "../dashboard/dashboardFixtures";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubSession(body: unknown = SESSION_CLOSED, status = 200): void {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(body, status)));
}

describe("MarketDataArchivePage", () => {
  it("renders the archive heading and the real trading date from the session API", async () => {
    stubSession();
    render(<MarketDataArchivePage />);
    expect(
      await screen.findByRole("heading", { name: "Market Data Archive", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText("2026-08-25")).toBeInTheDocument();
    expect(screen.getByText("NSE MARKET CLOSED")).toBeInTheDocument();
  });

  it("renders every archive completeness field as Not available - never a fabricated count", async () => {
    stubSession();
    render(<MarketDataArchivePage />);
    await screen.findByRole("heading", { name: "Archive Completeness", level: 2 });
    for (const field of [
      "Symbols",
      "Timeframe",
      "Expected bars",
      "Actual bars",
      "Missing bars",
      "Duplicate bars",
      "First observation",
      "Last observation",
      "Archive status",
      "Reconciliation status",
    ]) {
      const row = screen.getByRole("row", { name: new RegExp(`^${field} `) });
      expect(row.textContent).toMatch(/Not available/i);
      expect(row.textContent).not.toMatch(/\b\d+\b/);
    }
  });

  it("never claims the archive is reconciled or complete", async () => {
    stubSession();
    render(<MarketDataArchivePage />);
    await screen.findByRole("heading", { name: "Archive Completeness", level: 2 });
    expect(screen.queryByText(/\bRECONCILED\b/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bCOMPLETE\b/)).not.toBeInTheDocument();
  });

  it("names the missing backend endpoint as an explicit blocker", async () => {
    stubSession();
    render(<MarketDataArchivePage />);
    expect(
      await screen.findByText(/No archive or reconciliation endpoint exists/i),
    ).toBeInTheDocument();
  });

  it("renders a loading state while the session API is in flight", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<MarketDataArchivePage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading archive overview…");
  });

  it("renders an error state with a retry action when the session API fails", async () => {
    stubSession({ error_code: "server_error", message: "Backend unavailable." }, 500);
    render(<MarketDataArchivePage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Retry loading archive overview" });
    fireEvent.click(retry);
    // Retrying returns the page to its loading state rather than
    // leaving a blank area behind.
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Loading archive overview…",
    );
  });
});
