// frontend/src/features/backtesting/StrategyMonitorPage.test.tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StrategyMonitorPage } from "./StrategyMonitorPage";
import { renderWithAuth } from "../../test/testAuth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const STATUSES = [
  { strategy_id: "ema_crossover", status: "RESEARCH_ACTIVE" },
  { strategy_id: "sma_trend_filter", status: "RESEARCH_PAUSED" },
];

describe("StrategyMonitorPage", () => {
  it("renders research status per strategy and never implies live trading", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(STATUSES)));
    renderWithAuth(<StrategyMonitorPage />);
    await waitFor(() => expect(screen.getByText("ema_crossover")).toBeInTheDocument());
    expect(screen.getByText("RESEARCH_ACTIVE")).toBeInTheDocument();
    expect(screen.getByText("RESEARCH_PAUSED")).toBeInTheDocument();
    expect(screen.getByText(/does NOT control live trading/)).toBeInTheDocument();
  });

  it("pauses an active strategy via the toggle control", async () => {
    let paused = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/research-status/set/")) {
          paused = true;
          return jsonResponse({ strategy_id: "ema_crossover", status: "RESEARCH_PAUSED" });
        }
        return jsonResponse(
          paused
            ? [{ strategy_id: "ema_crossover", status: "RESEARCH_PAUSED" }]
            : STATUSES,
        );
      }),
    );
    renderWithAuth(<StrategyMonitorPage />);
    await waitFor(() => expect(screen.getByText("ema_crossover")).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "Pause Research" })[0]);
    await waitFor(() => expect(paused).toBe(true));
  });
});
