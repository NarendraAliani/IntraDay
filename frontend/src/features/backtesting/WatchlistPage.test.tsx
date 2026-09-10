// frontend/src/features/backtesting/WatchlistPage.test.tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WatchlistPage } from "./WatchlistPage";
import { renderWithAuth } from "../../test/testAuth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const GATE_VERIFIED_ROW = {
  instrument_id: "NSE:FIXTURE01",
  gate_status: "OK",
  coverage_detail: "",
  price: "171.0000",
  price_source: "HISTORICAL",
  change_percent: "2.5000",
  volume: "72000",
  volume_basis: "HISTORICAL_DAY",
  sparkline: ["165.0000", "168.0000", "171.0000"],
  as_of: "2026-08-17 close",
  is_stale: false,
};

const NOT_GATE_VERIFIED_ROW = {
  instrument_id: "NSE:FIXTURE02",
  gate_status: "NOT_GATE_VERIFIED",
  coverage_detail: "INCOMPLETE_COVERAGE: 0/72 bars (0.0%) cached",
  price: null,
  price_source: "",
  change_percent: null,
  volume: null,
  volume_basis: "",
  sparkline: [],
  as_of: "",
  is_stale: false,
};

function stubFetch(
  handlers: Record<string, unknown>,
  fallback: () => Response = () => jsonResponse({ error_code: "not_found", message: "no route" }, 404),
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      for (const [match, body] of Object.entries(handlers)) {
        if (url.includes(match)) return jsonResponse(body);
      }
      return fallback();
    }),
  );
}

describe("WatchlistPage", () => {
  it("lists existing watchlists with a real price/change/volume/sparkline table, no order controls", async () => {
    stubFetch({
      "/market-data/quotes/": [],
      "/market-data/instruments/": { exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" },
      "/watchlists/core/market-data/": {
        watchlist_name: "core",
        mode: "HISTORICAL",
        results: [GATE_VERIFIED_ROW],
      },
      "/watchlists/": [{ name: "core", instrument_ids: ["NSE:FIXTURE01"] }],
    });
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText(/core/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("NSE:FIXTURE01")).toBeInTheDocument());
    expect(screen.getByText("₹171.0000")).toBeInTheDocument();
    expect(screen.getByText("2.50%")).toBeInTheDocument();
    expect(screen.getByText(/72000/)).toBeInTheDocument();
    expect(screen.getByText(/full day/)).toBeInTheDocument();
    expect(screen.getByText("2026-08-17 close")).toBeInTheDocument();
    expect(screen.getByText("Historical mode")).toBeInTheDocument();

    const bodyText = document.body.textContent ?? "";
    for (const forbidden of ["Buy", "Sell", "Place Order", "Quantity"]) {
      expect(bodyText).not.toContain(forbidden);
    }
  });

  it("labels a NOT_GATE_VERIFIED instrument plainly - never a blank or fabricated price", async () => {
    stubFetch({
      "/market-data/quotes/": [],
      "/market-data/instruments/": { exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" },
      "/watchlists/mixed/market-data/": {
        watchlist_name: "mixed",
        mode: "HISTORICAL",
        results: [GATE_VERIFIED_ROW, NOT_GATE_VERIFIED_ROW],
      },
      "/watchlists/": [{ name: "mixed", instrument_ids: ["NSE:FIXTURE01", "NSE:FIXTURE02"] }],
    });
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText("NSE:FIXTURE02")).toBeInTheDocument());
    expect(screen.getByText("Not verified")).toBeInTheDocument();
    // Every dash-shown field for the unverified row - never a fabricated value.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2); // price + change% for FIXTURE02
  });

  it("defaults to Historical mode with no worker running", async () => {
    stubFetch({
      "/market-data/quotes/": [],
      "/market-data/instruments/": { exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" },
      "/watchlists/core/market-data/": {
        watchlist_name: "core",
        mode: "HISTORICAL",
        results: [GATE_VERIFIED_ROW],
      },
      "/watchlists/": [{ name: "core", instrument_ids: ["NSE:FIXTURE01"] }],
    });
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText("Historical mode")).toBeInTheDocument());
    expect(screen.queryByText("Live mode")).not.toBeInTheDocument();
  });

  it("shows a Live mode badge and an honest historical-fallback note when the envelope is LIVE", async () => {
    const liveRowWithLivePrice = {
      ...GATE_VERIFIED_ROW,
      price_source: "LIVE",
      volume_basis: "SESSION_TO_DATE",
      as_of: "2026-08-17T10:00:00Z",
    };
    const liveRowFallenBackToHistorical = {
      ...GATE_VERIFIED_ROW,
      instrument_id: "NSE:FIXTURE03",
    };
    stubFetch({
      "/market-data/quotes/": [],
      "/market-data/instruments/": { exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" },
      "/watchlists/live-list/market-data/": {
        watchlist_name: "live-list",
        mode: "LIVE",
        results: [liveRowWithLivePrice, liveRowFallenBackToHistorical],
      },
      "/watchlists/": [
        { name: "live-list", instrument_ids: ["NSE:FIXTURE01", "NSE:FIXTURE03"] },
      ],
    });
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText("Live mode")).toBeInTheDocument());
    expect(screen.getByText(/session-to-date/)).toBeInTheDocument();
    // The row that fell back to the historical close is labeled honestly,
    // even though the page-level envelope says LIVE.
    expect(screen.getByText(/last close \(no live quote\)/)).toBeInTheDocument();
  });

  it("saves a new watchlist, picking instruments from real observed quotes (never free text)", async () => {
    let saved = false;
    stubFetch({
      "/market-data/quotes/": [
        {
          symbol: "FIXTURE01",
          exchange: "NSE",
          last_price: "100.00",
          source_timestamp: "2026-08-14T06:00:00Z",
          freshness_age_seconds: 5,
          is_stale: false,
        },
      ],
      "/market-data/instruments/": { exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" },
    });
    // Override with stateful watchlist list/save handling.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/market-data/quotes/")) {
          return jsonResponse([
            {
              symbol: "FIXTURE01",
              exchange: "NSE",
              last_price: "100.00",
              source_timestamp: "2026-08-14T06:00:00Z",
              freshness_age_seconds: 5,
              is_stale: false,
            },
          ]);
        }
        if (url.includes("/market-data/instruments/")) {
          return jsonResponse({ exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" });
        }
        if (url.endsWith("/watchlists/") && !saved) return jsonResponse([]);
        if (url.endsWith("/watchlists/save/")) {
          saved = true;
          return jsonResponse({ name: "new-list", instrument_ids: ["NSE:FIXTURE01"] }, 201);
        }
        if (url.includes("/watchlists/new-list/market-data/")) {
          return jsonResponse({
            watchlist_name: "new-list",
            mode: "HISTORICAL",
            results: [{ ...GATE_VERIFIED_ROW, instrument_id: "NSE:FIXTURE01" }],
          });
        }
        if (url.endsWith("/watchlists/")) {
          return jsonResponse([{ name: "new-list", instrument_ids: ["NSE:FIXTURE01"] }]);
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText(/No watchlists yet/)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Watchlist name"), { target: { value: "new-list" } });
    await waitFor(() => expect(screen.getByText("FIXTURE01")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Save Watchlist" }));

    await waitFor(() => expect(screen.getByText(/new-list/)).toBeInTheDocument());
  });

  it("loads an existing watchlist's instruments into the picker on Edit, and Save changes updates it via the same upsert save call", async () => {
    let currentInstruments = ["NSE:FIXTURE01"];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/market-data/quotes/")) {
          return jsonResponse([
            {
              symbol: "FIXTURE01",
              exchange: "NSE",
              last_price: "100.00",
              source_timestamp: "2026-08-14T06:00:00Z",
              freshness_age_seconds: 5,
              is_stale: false,
            },
            {
              symbol: "FIXTURE02",
              exchange: "NSE",
              last_price: "200.00",
              source_timestamp: "2026-08-14T06:00:00Z",
              freshness_age_seconds: 5,
              is_stale: false,
            },
          ]);
        }
        if (url.includes("/market-data/instruments/")) {
          return jsonResponse({ exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" });
        }
        if (url.includes("/watchlists/existing/market-data/")) {
          return jsonResponse({
            watchlist_name: "existing",
            mode: "HISTORICAL",
            results: currentInstruments.map((id) => ({ ...GATE_VERIFIED_ROW, instrument_id: id })),
          });
        }
        if (url.endsWith("/watchlists/save/") && init?.method === "POST") {
          const body = JSON.parse(String(init.body)) as { name: string; instrument_ids: string[] };
          expect(body.name).toBe("existing"); // the locked name, never renamed
          currentInstruments = body.instrument_ids;
          return jsonResponse({ name: body.name, instrument_ids: body.instrument_ids }, 201);
        }
        if (url.endsWith("/watchlists/")) {
          return jsonResponse([{ name: "existing", instrument_ids: currentInstruments }]);
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText("existing")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByText('Editing "existing"')).toBeInTheDocument();
    // The name field is locked while editing - rename is out of scope.
    expect(screen.getByLabelText("Watchlist name")).toBeDisabled();
    expect(screen.getByLabelText("Watchlist name")).toHaveValue("existing");
    // The existing instrument is pre-checked in the picker.
    const fixture01Checkbox = screen.getByLabelText("FIXTURE01") as HTMLInputElement;
    expect(fixture01Checkbox.checked).toBe(true);

    // Add the second instrument, then save.
    fireEvent.click(screen.getByLabelText("FIXTURE02"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(currentInstruments).toEqual(["NSE:FIXTURE01", "NSE:FIXTURE02"]));
    // Editing state is cleared after a successful save.
    await waitFor(() => expect(screen.queryByText('Editing "existing"')).not.toBeInTheDocument());
    expect(screen.getByText("New watchlist")).toBeInTheDocument();
  });

  it("Cancel leaves the existing watchlist untouched and restores the create-new form", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/market-data/quotes/")) return jsonResponse([]);
        if (url.includes("/market-data/instruments/")) {
          return jsonResponse({ exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" });
        }
        if (url.includes("/watchlists/existing/market-data/")) {
          return jsonResponse({
            watchlist_name: "existing",
            mode: "HISTORICAL",
            results: [GATE_VERIFIED_ROW],
          });
        }
        if (url.endsWith("/watchlists/")) {
          return jsonResponse([{ name: "existing", instrument_ids: ["NSE:FIXTURE01"] }]);
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText("existing")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByText('Editing "existing"')).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("New watchlist")).toBeInTheDocument();
    expect(screen.getByLabelText("Watchlist name")).not.toBeDisabled();
    expect(screen.getByLabelText("Watchlist name")).toHaveValue("");
  });

  it("never lets the operator type a free-text instrument symbol", async () => {
    stubFetch({
      "/market-data/quotes/": [],
      "/market-data/instruments/": { exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" },
      "/watchlists/": [],
    });
    renderWithAuth(<WatchlistPage />);
    await waitFor(() => expect(screen.getByText(/No watchlists yet/)).toBeInTheDocument());

    expect(screen.queryByLabelText(/Instruments/)).not.toBeInTheDocument();
    expect(document.querySelector('input[type="text"]#watchlist-instruments')).toBeNull();
  });
});
