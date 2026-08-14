// frontend/src/features/strategy-config/StrategyConfigurationPage.test.tsx
//
// Checkpoint 26 Part 19: real-boundary tests for the Strategy
// Configuration screen - only `global.fetch` is mocked; the real
// generated contract types, the real strategyApi.ts client functions,
// and the real generic renderer component are exercised together
// (matching LiveMarketDataMonitor.test.tsx's established philosophy).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StrategyConfigurationPage } from "./StrategyConfigurationPage";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type FieldDefinition = components["schemas"]["FieldDefinition"];
type StrategySummary = components["schemas"]["StrategySummary"];
type StrategySchema = components["schemas"]["StrategySchema"];
type StrategyConfigurationResponse = components["schemas"]["StrategyConfigurationResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const FIELDS: FieldDefinition[] = [
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
];

const STRATEGIES: StrategySummary[] = [
  {
    strategy_id: "ema_crossover",
    display_name: "EMA Crossover",
    specification_version: "v1",
    code_version: "v1",
    is_active: false,
  },
  {
    strategy_id: "sma_trend_filter",
    display_name: "SMA Trend Filter",
    specification_version: "v1",
    code_version: "v1",
    is_active: false,
  },
];

const EMA_SCHEMA: StrategySchema = {
  strategy_id: "ema_crossover",
  parameters: [
    {
      parameter_id: "fast_lookback",
      label: "Fast EMA Lookback",
      parameter_type: "INTEGER",
      required: true,
      default: 9,
      minimum: "1",
      maximum: "200",
      allowed_values: [],
      field_category: null,
      depends_on: [],
      help_text: "Period of the fast (short) EMA.",
    },
    {
      parameter_id: "slow_lookback",
      label: "Slow EMA Lookback",
      parameter_type: "INTEGER",
      required: true,
      default: 21,
      minimum: "2",
      maximum: "400",
      allowed_values: [],
      field_category: null,
      depends_on: [],
      help_text: "Period of the slow (long) EMA. Must exceed fast_lookback.",
    },
  ],
};

const SMA_SCHEMA: StrategySchema = {
  strategy_id: "sma_trend_filter",
  parameters: [
    {
      parameter_id: "lookback",
      label: "SMA Lookback",
      parameter_type: "INTEGER",
      required: true,
      default: 20,
      minimum: "1",
      maximum: "400",
      allowed_values: [],
      field_category: null,
      depends_on: [],
      help_text: "Period of the trend-filter SMA.",
    },
  ],
};

function stubFetch(routes: Record<string, unknown>): void {
  // Longest-path-first matching: "/strategies/ema_crossover/schema/" must
  // win over the shorter "/strategies/" route for the same URL.
  const sortedRoutes = Object.entries(routes).sort((a, b) => b[0].length - a[0].length);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      for (const [path, body] of sortedRoutes) {
        if (url.includes(path)) {
          return jsonResponse(body);
        }
      }
      return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
    }),
  );
}

describe("StrategyConfigurationPage", () => {
  it("lists strategies from the registry endpoint - no hardcoded list", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": EMA_SCHEMA,
      "/strategy-engine/strategies/ema_crossover/configurations/": [],
    });

    renderWithAuth(<StrategyConfigurationPage />);

    await waitFor(() => {
      expect(screen.getByText("EMA Crossover")).toBeInTheDocument();
    });
    expect(screen.getByText("SMA Trend Filter")).toBeInTheDocument();
  });

  it("renders parameter controls purely from the schema (generic renderer)", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": EMA_SCHEMA,
      "/strategy-engine/strategies/ema_crossover/configurations/": [],
    });

    renderWithAuth(<StrategyConfigurationPage />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/Slow EMA Lookback/)).toBeInTheDocument();
  });

  it("clears stale parameter values when the strategy selection changes (dependent dropdowns)", async () => {
    let schemaCallCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/strategy-engine/fields/")) return jsonResponse(FIELDS);
        if (url.includes("/strategy-engine/strategies/") && url.endsWith("/strategies/")) {
          return jsonResponse(STRATEGIES);
        }
        if (url.includes("/ema_crossover/schema/")) {
          schemaCallCount += 1;
          return jsonResponse(EMA_SCHEMA);
        }
        if (url.includes("/sma_trend_filter/schema/")) {
          return jsonResponse(SMA_SCHEMA);
        }
        if (url.includes("/configurations/")) return jsonResponse([]);
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );

    renderWithAuth(<StrategyConfigurationPage />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument();
    });

    const select = screen.getByLabelText("Strategy") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "sma_trend_filter" } });

    await waitFor(() => {
      expect(screen.getByLabelText(/SMA Lookback/)).toBeInTheDocument();
    });
    // The EMA-only "Fast EMA Lookback" control must be gone - not just
    // hidden - proving the stale schema/values were actually cleared.
    expect(screen.queryByLabelText(/Fast EMA Lookback/)).not.toBeInTheDocument();
    expect(schemaCallCount).toBe(1);
  });

  it("shows the read-only notice and hides Save for users without configuration.activate", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": EMA_SCHEMA,
      "/strategy-engine/strategies/ema_crossover/configurations/": [],
    });

    renderWithAuth(<StrategyConfigurationPage />, {
      state: {
        status: "authenticated",
        username: "reader",
        capabilities: ["configuration.read"],
      },
    });

    await waitFor(() => {
      expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /Save Configuration/ })).not.toBeInTheDocument();
    expect(screen.getByText(/read-only access/)).toBeInTheDocument();
  });

  it("lists saved configurations and never renders order/broker language", async () => {
    const saved: StrategyConfigurationResponse = {
      strategy_id: "ema_crossover",
      specification_version: "v1",
      code_version: "v1",
      configuration_version: "cfg-v1",
      values: { fast_lookback: 5, slow_lookback: 10 },
      created_at: "2026-08-14T06:00:00Z",
      created_by: "operator",
    };
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": EMA_SCHEMA,
      "/strategy-engine/strategies/ema_crossover/configurations/": [saved],
    });

    renderWithAuth(<StrategyConfigurationPage />);

    await waitFor(() => {
      expect(screen.getByText("cfg-v1")).toBeInTheDocument();
    });

    const bodyText = document.body.textContent ?? "";
    for (const forbidden of ["Buy", "Sell", "Place Order", "Execute Trade"]) {
      expect(bodyText).not.toContain(forbidden);
    }
  });
});
