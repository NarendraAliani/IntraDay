// frontend/src/features/screening/ScreenerPage.test.tsx
//
// CHECKPOINT-SCANNER-B: network-mocked tests for the Screener page -
// field/operator/value picker, instrument picker, Run, and the honest
// MATCHED/NO_MATCH/NOT_GATE_VERIFIED results table. Never mocks the
// backend's OWN evaluation logic - only the HTTP boundary, matching
// this project's established `vi.stubGlobal("fetch", ...)` pattern.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScreenerPage } from "./ScreenerPage";
import { renderWithAuth } from "../../test/testAuth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const FIELD_REGISTRY = [
  {
    field_id: "close",
    display_name: "Close",
    category: "RAW_PRICE",
    data_type: "DECIMAL",
    source: "domain.market_data.contracts.Bar",
    timeframe_support: "any",
    required_inputs: [],
    availability: "HISTORICAL_AND_SAMPLE",
    version: "v1",
    description: "Bar close price.",
  },
  {
    field_id: "rsi",
    display_name: "Relative Strength Index",
    category: "DERIVED_FEATURE",
    data_type: "DECIMAL",
    source: "signal_intelligence.feature_engine",
    timeframe_support: "any",
    required_inputs: ["close"],
    availability: "HISTORICAL_AND_SAMPLE",
    version: "v1",
    description: "Wilder RSI.",
  },
];

function stubFetch(evaluateResponse: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/strategy-engine/fields/")) return jsonResponse(FIELD_REGISTRY);
      if (url.includes("/market-data/quotes/")) return jsonResponse([]);
      if (url.includes("/market-data/instruments/")) {
        return jsonResponse({
          exchange: "NSE",
          instruments: [{ symbol: "RELIANCE", display_name: "Reliance Industries" }],
          data_source: "SCRIP_MASTER",
        });
      }
      if (url.includes("/screening/evaluate/")) return jsonResponse(evaluateResponse);
      return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
    }),
  );
}

describe("ScreenerPage", () => {
  it("labels itself Historical mode and never mentions live/real-time", async () => {
    stubFetch({ mode: "HISTORICAL", results: [], matched_count: 0, evaluated_count: 0, not_gate_verified_count: 0 });
    renderWithAuth(<ScreenerPage />);
    await waitFor(() => expect(screen.getByText("Historical mode")).toBeInTheDocument());
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toContain("live");
    expect(bodyText.toLowerCase()).not.toContain("real-time");
    expect(bodyText.toLowerCase()).not.toContain("real time");
  });

  it("never mentions signals, orders, or paper trading - a read-only exploration tool", async () => {
    stubFetch({ mode: "HISTORICAL", results: [], matched_count: 0, evaluated_count: 0, not_gate_verified_count: 0 });
    renderWithAuth(<ScreenerPage />);
    await waitFor(() => expect(screen.getByText("Screener")).toBeInTheDocument());
    const bodyText = document.body.textContent ?? "";
    for (const forbidden of ["Buy", "Sell", "Place Order", "Submit Paper Order", "Signal"]) {
      expect(bodyText).not.toContain(forbidden);
    }
  });

  it("renders a matched result with its evidence trail", async () => {
    stubFetch({
      mode: "HISTORICAL",
      results: [
        {
          instrument_id: "NSE:RELIANCE",
          status: "MATCHED",
          matched_condition_details: ["close > 100: True"],
          coverage_detail: "",
        },
      ],
      matched_count: 1,
      evaluated_count: 1,
      not_gate_verified_count: 0,
    });
    renderWithAuth(<ScreenerPage />);
    await waitFor(() => expect(screen.getByText("Screener")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Compare to"), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(screen.getByText("NSE:RELIANCE")).toBeInTheDocument());
    expect(screen.getByText("Matched")).toBeInTheDocument();
    expect(screen.getByText("close > 100: True")).toBeInTheDocument();
  });

  it("honestly labels an instrument it could not verify, distinct from a no-match", async () => {
    stubFetch({
      mode: "HISTORICAL",
      results: [
        {
          instrument_id: "NSE:RELIANCE",
          status: "NOT_GATE_VERIFIED",
          matched_condition_details: [],
          coverage_detail: "INCOMPLETE_COVERAGE: 0/72 bars cached",
        },
      ],
      matched_count: 0,
      evaluated_count: 0,
      not_gate_verified_count: 1,
    });
    renderWithAuth(<ScreenerPage />);
    await waitFor(() => expect(screen.getByText("Screener")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Compare to"), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(screen.getByText("Not verified")).toBeInTheDocument());
    expect(screen.getByText(/INCOMPLETE_COVERAGE/)).toBeInTheDocument();
    expect(screen.getByText(/could not be checked/)).toBeInTheDocument();
  });

  it("disables Run until every condition has a comparison value and an instrument is selected", async () => {
    stubFetch({ mode: "HISTORICAL", results: [], matched_count: 0, evaluated_count: 0, not_gate_verified_count: 0 });
    renderWithAuth(<ScreenerPage />);
    await waitFor(() => expect(screen.getByText("Screener")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
  });

  it("adds and removes condition rows, combining with AND/OR", async () => {
    stubFetch({ mode: "HISTORICAL", results: [], matched_count: 0, evaluated_count: 0, not_gate_verified_count: 0 });
    renderWithAuth(<ScreenerPage />);
    await waitFor(() => expect(screen.getByText("Screener")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    expect(screen.getAllByLabelText("Field")).toHaveLength(2);
    expect(screen.getByLabelText("Combine with")).toBeInTheDocument();

    const removeButtons = screen.getAllByRole("button", { name: "Remove" });
    fireEvent.click(removeButtons[1]);
    expect(screen.getAllByLabelText("Field")).toHaveLength(1);
  });
});
