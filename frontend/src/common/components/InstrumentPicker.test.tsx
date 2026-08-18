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

function stub(options: {
  quotes?: unknown[];
  nseInstruments?: StubInstrument[];
  bseInstruments?: StubInstrument[];
  masterAvailable?: boolean;
}): void {
  const { quotes = [], nseInstruments = [], bseInstruments = [], masterAvailable = true } = options;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/market-data/quotes/")) return jsonResponse(quotes);
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
});
