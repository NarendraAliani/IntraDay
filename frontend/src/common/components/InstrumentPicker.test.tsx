// frontend/src/common/components/InstrumentPicker.test.tsx
//
// Checkpoint 63.x follow-up: proves the shared instrument picker only
// ever offers real, backend-sourced instruments (never free text),
// shows ONLY the real company/display name (never a bare or
// parenthetical instrument id), supports real-time client-side search,
// "Select All" selects every real (or currently-filtered) exchange
// instrument (not just observed ones) when the exchange master list is
// available, degrades honestly when it is not, and discloses that
// index (NIFTY/SENSEX) selection is unavailable rather than either
// hiding it or fabricating constituent data.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InstrumentPickerMulti, InstrumentPickerSingle } from "./InstrumentPicker";
import { renderWithAuth } from "../../test/testAuth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

interface StubInstrument {
  symbol: string;
  displayName: string;
}

interface StubWatchlist {
  name: string;
  instrument_ids: string[];
}

function stub(options: {
  quotes?: unknown[];
  nseInstruments?: StubInstrument[];
  bseInstruments?: StubInstrument[];
  masterAvailable?: boolean;
  watchlists?: StubWatchlist[];
  watchlistsFail?: boolean;
}): void {
  const {
    quotes = [],
    nseInstruments = [],
    bseInstruments = [],
    masterAvailable = true,
    watchlists = [],
    watchlistsFail = false,
  } = options;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/market-data/quotes/")) return jsonResponse(quotes);
      if (url.endsWith("/watchlists/")) {
        if (watchlistsFail) return jsonResponse({ error_code: "internal_error", message: "fail" }, 500);
        return jsonResponse(watchlists);
      }
      if (url.includes("/market-data/instruments/")) {
        if (!masterAvailable) {
          return jsonResponse({ exchange: "NSE", instruments: [], data_source: "UNAVAILABLE" });
        }
        const isNse = url.includes("exchange=NSE");
        const prefix = isNse ? "NSE" : "BSE";
        return jsonResponse({
          exchange: prefix,
          instruments: (isNse ? nseInstruments : bseInstruments).map((i) => ({
            instrument_id: `${prefix}:${i.symbol}`,
            display_name: i.displayName,
          })),
          data_source: "DHAN_SCRIP_MASTER",
        });
      }
      return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
    }),
  );
}

const RELIANCE = { symbol: "RELIANCE", displayName: "Reliance Industries" };
const TCS = { symbol: "TCS", displayName: "Tata Consultancy Services" };
const INFY = { symbol: "INFY", displayName: "Infosys" };
const HDFCBANK = { symbol: "HDFCBANK", displayName: "HDFC Bank" };

const RELIANCE_QUOTE = {
  symbol: "RELIANCE",
  exchange: "NSE",
  last_price: "1234.56",
  source_timestamp: "2026-08-14T06:00:00Z",
  freshness_age_seconds: 5,
  is_stale: false,
};

describe("InstrumentPickerSingle", () => {
  it("shows only the real company name - never a bare/parenthetical instrument id, never free text", async () => {
    stub({ nseInstruments: [RELIANCE] });
    renderWithAuth(<InstrumentPickerSingle id="test-picker" value="" onChange={() => {}} />);

    await waitFor(() => expect(screen.getByText("Reliance Industries")).toBeInTheDocument());
    expect(screen.queryByText(/NSE:RELIANCE/)).not.toBeInTheDocument();
    expect(document.querySelector('input[type="text"]#test-picker')).toBeNull();
    expect(screen.getByRole("combobox", { name: "Instrument" }).tagName).toBe("SELECT");
  });

  it("filters options in real time as the operator types a search query", async () => {
    stub({ nseInstruments: [RELIANCE, TCS, INFY] });
    renderWithAuth(<InstrumentPickerSingle id="test-picker" value="" onChange={() => {}} />);

    await waitFor(() => expect(screen.getByText("Infosys")).toBeInTheDocument());
    expect(screen.getByText("Reliance Industries")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search stocks"), { target: { value: "info" } });

    expect(screen.getByText("Infosys")).toBeInTheDocument();
    expect(screen.queryByText("Reliance Industries")).not.toBeInTheDocument();
    expect(screen.queryByText("Tata Consultancy Services")).not.toBeInTheDocument();
  });

  it("discloses that index (NIFTY/SENSEX) selection is unavailable rather than fabricating it", async () => {
    stub({});
    renderWithAuth(<InstrumentPickerSingle id="test-picker" value="" onChange={() => {}} />);

    expect(screen.getByText("INDEX SELECTION UNAVAILABLE")).toBeInTheDocument();
    expect(screen.queryByText(/NIFTY 50/i)).not.toBeInTheDocument();
  });

  it("includes extra fixed options (e.g. the deterministic fixture) alongside real instruments", async () => {
    stub({});
    renderWithAuth(
      <InstrumentPickerSingle
        id="test-picker"
        value=""
        onChange={() => {}}
        extraOptions={["NSE:FIXTURE01"]}
      />,
    );

    await waitFor(() => expect(screen.getByText("NSE:FIXTURE01")).toBeInTheDocument());
  });
});

describe("InstrumentPickerMulti", () => {
  it("selecting a checkbox calls onChange with the real instrument id, labeled only by its real name", async () => {
    stub({ quotes: [RELIANCE_QUOTE], nseInstruments: [RELIANCE] });
    const onChange = vi.fn();
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={onChange} />);

    await waitFor(() => expect(screen.getByText("Reliance Industries")).toBeInTheDocument());
    expect(screen.queryByText(/NSE:RELIANCE/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Reliance Industries" }));

    expect(onChange).toHaveBeenCalledWith(["NSE:RELIANCE"]);
  });

  it("filters the checklist in real time as the operator types a search query", async () => {
    stub({ nseInstruments: [RELIANCE, TCS, INFY, HDFCBANK] });
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={() => {}} />);

    await waitFor(() => expect(screen.getByText("HDFC Bank")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Search stocks"), { target: { value: "tata" } });

    expect(screen.getByText("Tata Consultancy Services")).toBeInTheDocument();
    expect(screen.queryByText("HDFC Bank")).not.toBeInTheDocument();
    expect(screen.queryByText("Reliance Industries")).not.toBeInTheDocument();
    expect(screen.getByText("1 match")).toBeInTheDocument();
  });

  it('"Select All" selects every real exchange instrument, not only ones with a live quote', async () => {
    stub({
      quotes: [RELIANCE_QUOTE], // only RELIANCE has ever been observed live
      nseInstruments: [RELIANCE, TCS, INFY, HDFCBANK], // but the exchange has many more
    });
    const onChange = vi.fn();
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={onChange} />);

    await waitFor(() => expect(screen.getByText("Tata Consultancy Services")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Select All" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.arrayContaining(["NSE:RELIANCE", "NSE:TCS", "NSE:INFY", "NSE:HDFCBANK"]),
    );
  });

  it('"Select All" only selects the currently search-filtered instruments when a query is active', async () => {
    stub({ nseInstruments: [RELIANCE, TCS, INFY, HDFCBANK] });
    const onChange = vi.fn();
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={onChange} />);

    await waitFor(() => expect(screen.getByText("HDFC Bank")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Search stocks"), { target: { value: "bank" } });
    fireEvent.click(screen.getByRole("button", { name: "Select All (Matching)" }));

    expect(onChange).toHaveBeenCalledWith(["NSE:HDFCBANK"]);
  });

  it("degrades honestly to observed-only selection when the exchange master list is unavailable", async () => {
    stub({ quotes: [RELIANCE_QUOTE], masterAvailable: false });
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={() => {}} />);

    await waitFor(() => expect(screen.getByText("OBSERVED INSTRUMENTS ONLY")).toBeInTheDocument());
  });

  it("shows an honest empty state when no instruments are available", async () => {
    stub({});
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={() => {}} />);

    await waitFor(() =>
      expect(screen.getByText(/No instruments available yet/)).toBeInTheDocument(),
    );
  });

  it("Checkpoint FRONTEND-DATA-TABLES: paginates the checklist instead of rendering every instrument at once", async () => {
    const many = Array.from({ length: 150 }, (_, i) => ({
      symbol: `STOCK${String(i).padStart(3, "0")}`,
      displayName: `Stock ${String(i).padStart(3, "0")} Ltd`,
    }));
    stub({ nseInstruments: many });
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={() => {}} />);

    await waitFor(() => expect(screen.getByText("150 matches")).toBeInTheDocument());
    // Only one page (100/page) of checkboxes should be in the DOM, not all 150.
    expect(screen.getAllByRole("checkbox").length).toBe(100);
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    await waitFor(() => expect(screen.getByText("Page 2 of 2")).toBeInTheDocument());
    expect(screen.getAllByRole("checkbox").length).toBe(50);
  });

  it('"Select All" still applies to every filtered instrument across all pages, not only the visible page', async () => {
    const many = Array.from({ length: 120 }, (_, i) => ({
      symbol: `STOCK${String(i).padStart(3, "0")}`,
      displayName: `Stock ${String(i).padStart(3, "0")} Ltd`,
    }));
    stub({ nseInstruments: many });
    const onChange = vi.fn();
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={onChange} />);

    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Select All" }));

    expect(onChange).toHaveBeenCalledWith(expect.arrayContaining(many.map((i) => `NSE:${i.symbol}`)));
    expect((onChange.mock.calls[0][0] as string[]).length).toBe(120);
  });

  describe("CHECKPOINT-FRONTEND-8: Load from watchlist", () => {
    it("offers the operator's own saved watchlists and adds a chosen one's instruments to the selection", async () => {
      stub({
        nseInstruments: [RELIANCE, TCS, INFY],
        watchlists: [{ name: "core-momentum", instrument_ids: ["NSE:RELIANCE", "NSE:TCS"] }],
      });
      const onChange = vi.fn();
      renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={onChange} />);

      await waitFor(() =>
        expect(screen.getByText("core-momentum (2)")).toBeInTheDocument(),
      );
      fireEvent.change(screen.getByLabelText("Load from watchlist"), {
        target: { value: "core-momentum" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Add to selection" }));

      expect(onChange).toHaveBeenCalledWith(
        expect.arrayContaining(["NSE:RELIANCE", "NSE:TCS"]),
      );
      expect((onChange.mock.calls[0][0] as string[]).length).toBe(2);
    });

    it("is ADDITIVE - a watchlist load never removes an already-selected instrument, and never duplicates one", async () => {
      stub({
        nseInstruments: [RELIANCE, TCS, INFY],
        watchlists: [{ name: "core-momentum", instrument_ids: ["NSE:RELIANCE", "NSE:INFY"] }],
      });
      const onChange = vi.fn();
      // The operator already manually picked TCS before loading the watchlist.
      renderWithAuth(
        <InstrumentPickerMulti idPrefix="test-multi" value={["NSE:TCS"]} onChange={onChange} />,
      );

      await waitFor(() =>
        expect(screen.getByText("core-momentum (2)")).toBeInTheDocument(),
      );
      fireEvent.change(screen.getByLabelText("Load from watchlist"), {
        target: { value: "core-momentum" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Add to selection" }));

      const result = onChange.mock.calls[0][0] as string[];
      expect(new Set(result)).toEqual(new Set(["NSE:TCS", "NSE:RELIANCE", "NSE:INFY"]));
      expect(result.length).toBe(3); // no duplicates
    });

    it("shows nothing when the operator has no saved watchlists yet - never an empty/broken control", async () => {
      stub({ nseInstruments: [RELIANCE], watchlists: [] });
      renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={() => {}} />);

      await waitFor(() => expect(screen.getByText("Reliance Industries")).toBeInTheDocument());
      expect(screen.queryByLabelText("Load from watchlist")).not.toBeInTheDocument();
    });

    it("degrades honestly when the watchlists list fails to load", async () => {
      stub({ nseInstruments: [RELIANCE], watchlistsFail: true });
      renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={() => {}} />);

      await waitFor(() =>
        expect(screen.getByText("Unable to load your saved watchlists.")).toBeInTheDocument(),
      );
      // The rest of the picker still works even though watchlist loading failed.
      expect(screen.getByText("Reliance Industries")).toBeInTheDocument();
    });
  });
});
