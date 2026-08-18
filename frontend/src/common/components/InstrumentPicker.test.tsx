// frontend/src/common/components/InstrumentPicker.test.tsx
//
// Checkpoint 63.x follow-up: proves the shared instrument picker only
// ever offers real, backend-sourced instruments (never free text),
// displays real company/display names (never a bare instrument id),
// "Select All" selects every real exchange instrument (not just
// observed ones) when the exchange master list is available, degrades
// honestly when it is not, and discloses that index (NIFTY/SENSEX)
// selection is unavailable rather than either hiding it or fabricating
// constituent data.
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
  it("shows the real company name, never a bare instrument id, and never a free-text input", async () => {
    stub({ nseInstruments: [RELIANCE] });
    renderWithAuth(<InstrumentPickerSingle id="test-picker" value="" onChange={() => {}} />);

    await waitFor(() =>
      expect(screen.getByText("Reliance Industries (NSE:RELIANCE)")).toBeInTheDocument(),
    );
    expect(document.querySelector('input[type="text"]')).toBeNull();
    expect(screen.getByRole("combobox", { name: "Instrument" }).tagName).toBe("SELECT");
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

    await waitFor(() => expect(screen.getByText("NSE:FIXTURE01 (NSE:FIXTURE01)")).toBeInTheDocument());
  });
});

describe("InstrumentPickerMulti", () => {
  it("selecting a checkbox calls onChange with the real instrument id (labeled by its real name)", async () => {
    stub({ quotes: [RELIANCE_QUOTE], nseInstruments: [RELIANCE] });
    const onChange = vi.fn();
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={onChange} />);

    await waitFor(() =>
      expect(screen.getByText("Reliance Industries (NSE:RELIANCE)")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Reliance Industries (NSE:RELIANCE)" }));

    expect(onChange).toHaveBeenCalledWith(["NSE:RELIANCE"]);
  });

  it('"Select All" selects every real exchange instrument, not only ones with a live quote', async () => {
    stub({
      quotes: [RELIANCE_QUOTE], // only RELIANCE has ever been observed live
      nseInstruments: [RELIANCE, TCS, INFY, HDFCBANK], // but the exchange has many more
    });
    const onChange = vi.fn();
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={onChange} />);

    await waitFor(() =>
      expect(screen.getByText("Tata Consultancy Services (NSE:TCS)")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Select All" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.arrayContaining(["NSE:RELIANCE", "NSE:TCS", "NSE:INFY", "NSE:HDFCBANK"]),
    );
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
