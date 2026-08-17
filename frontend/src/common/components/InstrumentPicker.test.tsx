// frontend/src/common/components/InstrumentPicker.test.tsx
//
// Checkpoint 63.x follow-up: proves the shared instrument picker only
// ever offers real, backend-sourced instruments (never free text), and
// honestly discloses that index (NIFTY/SENSEX) selection is unavailable
// rather than either hiding it or fabricating constituent data.
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

function stubQuotes(quotes: unknown[]): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/market-data/quotes/")) return jsonResponse(quotes);
      return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
    }),
  );
}

const RELIANCE_QUOTE = {
  symbol: "RELIANCE",
  exchange: "NSE",
  last_price: "1234.56",
  source_timestamp: "2026-08-14T06:00:00Z",
  freshness_age_seconds: 5,
  is_stale: false,
};

describe("InstrumentPickerSingle", () => {
  it("offers only real observed instruments, never a free-text input", async () => {
    stubQuotes([RELIANCE_QUOTE]);
    renderWithAuth(
      <InstrumentPickerSingle id="test-picker" value="" onChange={() => {}} />,
    );

    await waitFor(() => expect(screen.getByText("NSE:RELIANCE")).toBeInTheDocument());
    expect(document.querySelector('input[type="text"]')).toBeNull();
    expect(screen.getByRole("combobox", { name: "Instrument" }).tagName).toBe("SELECT");
  });

  it("discloses that index (NIFTY/SENSEX) selection is unavailable rather than fabricating it", async () => {
    stubQuotes([]);
    renderWithAuth(<InstrumentPickerSingle id="test-picker" value="" onChange={() => {}} />);

    expect(screen.getByText("INDEX SELECTION UNAVAILABLE")).toBeInTheDocument();
    expect(screen.queryByText(/NIFTY 50/i)).not.toBeInTheDocument();
  });

  it("includes extra fixed options (e.g. the deterministic fixture) alongside observed instruments", async () => {
    stubQuotes([]);
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
  it("selecting a checkbox calls onChange with the real instrument id", async () => {
    stubQuotes([RELIANCE_QUOTE]);
    const onChange = vi.fn();
    renderWithAuth(
      <InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={onChange} />,
    );

    await waitFor(() => expect(screen.getByText("NSE:RELIANCE")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("checkbox", { name: "NSE:RELIANCE" }));

    expect(onChange).toHaveBeenCalledWith(["NSE:RELIANCE"]);
  });

  it("shows an honest empty state when no instruments have been observed yet", async () => {
    stubQuotes([]);
    renderWithAuth(<InstrumentPickerMulti idPrefix="test-multi" value={[]} onChange={() => {}} />);

    await waitFor(() =>
      expect(screen.getByText(/No observed instruments yet/)).toBeInTheDocument(),
    );
  });
});
