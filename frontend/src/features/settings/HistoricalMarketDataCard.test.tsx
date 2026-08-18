// frontend/src/features/settings/HistoricalMarketDataCard.test.tsx
//
// Real-boundary test for the Settings page's manual historical-data-
// sync card - only `global.fetch` is mocked, the real component, the
// real InstrumentPickerMulti it embeds, and the real generated
// contract types are exercised together (matching DhanSettingsCard.
// test.tsx's own established philosophy).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HistoricalMarketDataCard } from "./HistoricalMarketDataCard";
import { renderWithAuth } from "../../test/testAuth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function stub(options: {
  progress?: unknown;
  createStatus?: number;
}): { calls: string[] } {
  const calls: string[] = [];
  const { progress, createStatus = 202 } = options;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.includes("/market-data/quotes/")) return jsonResponse([]);
      if (url.includes("/market-data/instruments/")) {
        const isNse = url.includes("exchange=NSE");
        return jsonResponse({
          exchange: isNse ? "NSE" : "BSE",
          instruments: isNse
            ? [{ instrument_id: "NSE:RELIANCE", display_name: "Reliance Industries" }]
            : [],
          data_source: "DHAN_SCRIP_MASTER",
        });
      }
      if (url.includes("/market-data/sync-runs/") && url.endsWith("/progress/")) {
        return jsonResponse(
          progress ?? {
            run_id: "test-run",
            status: "COMPLETED",
            progress_percent: 100,
            current_instrument: "",
            message: "Market data sync completed",
            total_instruments: 1,
            completed_instruments: 1,
            bars_fetched: 5,
            bars_persisted: 5,
            cache_hits: 0,
            api_requests: 1,
            failed_instruments: [],
            created_at: "2026-01-01T09:00:00Z",
            started_at: "2026-01-01T09:00:00Z",
            completed_at: "2026-01-01T09:00:01Z",
          },
        );
      }
      if (url.includes("/market-data/sync-runs/") && init?.method === "POST") {
        return jsonResponse({ run_id: "test-run" }, createStatus);
      }
      return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
    }),
  );
  return { calls };
}

describe("HistoricalMarketDataCard", () => {
  it("is disabled until at least one instrument is selected", async () => {
    stub({});
    renderWithAuth(<HistoricalMarketDataCard />);

    await waitFor(() => expect(screen.getByText("Reliance Industries")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Fetch & Save" })).toBeDisabled();
  });

  it("starts a sync run and shows real, polled progress - never a fake timer bar", async () => {
    stub({});
    renderWithAuth(<HistoricalMarketDataCard />);

    await waitFor(() => expect(screen.getByText("Reliance Industries")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Reliance Industries"));
    fireEvent.click(screen.getByRole("button", { name: "Fetch & Save" }));

    await waitFor(() => expect(screen.getByText(/COMPLETED/)).toBeInTheDocument());
    expect(screen.getByText(/Bars fetched: 5/)).toBeInTheDocument();
    expect(screen.getByText(/Bars persisted: 5/)).toBeInTheDocument();
  });

  it("discloses which instruments were skipped, never silently hiding a partial failure", async () => {
    stub({
      progress: {
        run_id: "test-run",
        status: "PARTIAL",
        progress_percent: 100,
        current_instrument: "",
        message: "Market data sync partial",
        total_instruments: 1,
        completed_instruments: 1,
        bars_fetched: 0,
        bars_persisted: 0,
        cache_hits: 0,
        api_requests: 1,
        failed_instruments: [{ instrument_id: "NSE:RELIANCE", reason: "historical data unavailable" }],
        created_at: "2026-01-01T09:00:00Z",
        started_at: "2026-01-01T09:00:00Z",
        completed_at: "2026-01-01T09:00:01Z",
      },
    });
    renderWithAuth(<HistoricalMarketDataCard />);

    await waitFor(() => expect(screen.getByText("Reliance Industries")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Reliance Industries"));
    fireEvent.click(screen.getByRole("button", { name: "Fetch & Save" }));

    await waitFor(() =>
      expect(screen.getByText(/NSE:RELIANCE: historical data unavailable/)).toBeInTheDocument(),
    );
  });
});
