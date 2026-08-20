// frontend/src/features/market-data/LiveMarketDataMonitor.test.tsx
//
// Checkpoint 23: real-boundary tests for the Live Market Data Monitor -
// only `global.fetch` is mocked; the real generated contract types and
// the real component are exercised together.
//
// Checkpoint 62.x: rewritten for the Active Signal Monitor redesign.
// The former blanket "no forbidden trading word anywhere in the page"
// check is replaced with a narrower, more accurate one: this page now
// legitimately DISCUSSES risk/order OUTCOMES (already-safely-gated
// PAPER results) and explicitly explains which fields (stop loss,
// targets) are NOT available - what must never appear is an
// interactive ORDER-PLACEMENT CONTROL (a Buy/Sell/Execute button, a
// quantity input, a submit-order form), which this test checks for
// directly rather than banning the underlying words.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveMarketDataMonitor } from "./LiveMarketDataMonitor";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type SessionResponse = components["schemas"]["SessionResponse"];
type MarketDataHealthResponse = components["schemas"]["MarketDataHealthResponse"];
type QuoteResponse = components["schemas"]["QuoteResponse"];
type BarResponse = components["schemas"]["BarResponse"];
type SignalResponse = components["schemas"]["SignalResponse"];
type SignalListResponse = components["schemas"]["SignalListResponse"];
type StrategySummary = components["schemas"]["StrategySummary"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const SESSION: SessionResponse = {
  session_date: "2026-08-14",
  exchange: "NSE",
  market_open: "2026-08-14T03:45:00Z",
  market_close: "2026-08-14T10:00:00Z",
  square_off_deadline: "2026-08-14T09:50:00Z",
  status: "OPEN",
};

const HEALTH_DISCONNECTED: MarketDataHealthResponse = {
  state: "DISCONNECTED",
  last_success_at: null,
  last_failure_at: null,
  last_error_safe: "",
  freshness_age_seconds: null,
  consecutive_failures: 0,
  reconnect_count: 0,
  subscription_active: false,
};

const HEALTH_CONNECTED: MarketDataHealthResponse = {
  state: "CONNECTED_FRESH",
  last_success_at: "2026-08-14T06:00:00Z",
  last_failure_at: null,
  last_error_safe: "",
  freshness_age_seconds: 5,
  consecutive_failures: 0,
  reconnect_count: 0,
  subscription_active: false,
};

const RELIANCE_QUOTE: QuoteResponse = {
  symbol: "RELIANCE",
  exchange: "NSE",
  last_price: "1234.5600",
  source_timestamp: "2026-08-14T06:00:00Z",
  freshness_age_seconds: 5,
  is_stale: false,
};

const RELIANCE_BAR: BarResponse = {
  symbol: "RELIANCE",
  exchange: "NSE",
  timeframe: "1m",
  interval_start: "2026-08-14T06:00:00Z",
  interval_end: "2026-08-14T06:01:00Z",
  open: "1230.0000",
  high: "1236.0000",
  low: "1228.0000",
  close: "1234.5600",
  status: "CLOSED",
  observation_count: 4,
  data_source: "dhan",
};

const EMA_STRATEGY: StrategySummary = {
  strategy_id: "ema_crossover",
  display_name: "EMA Crossover",
  specification_version: "v1",
  code_version: "v1",
  is_active: true,
};

const EMPTY_SIGNALS: SignalListResponse = { items: [], total_count: 0, page: 1, page_size: 10 };

const RELIANCE_SIGNAL: SignalResponse = {
  signal_id: "sig-1",
  strategy_id: "ema_crossover",
  instrument_id: "NSE:RELIANCE",
  direction: "BULLISH",
  price: "1234.5600",
  timeframe: "5m",
  signal_timestamp: "2026-08-14T06:00:00Z",
  risk_status: "APPROVED",
  risk_reason: "",
  order_status: "FILLED",
  created_at: "2026-08-14T06:00:00Z",
  trade_plan: null,
  telegram: null,
  discord: null,
  evidence: null,
};

const WORKER_STATUS_UNCONFIGURED = {
  provider: "dhan",
  worker_state: "STOPPED",
  token_state: "UNCONFIGURED",
  watchdog_state: "DISCONNECTED",
  last_packet_at: null,
  last_bar_at: null,
  packet_age_seconds: null,
  bar_age_seconds: null,
  reconnect_count: 0,
  consecutive_failures: 0,
  subscribed_instrument_count: 0,
  last_error_safe: "",
  updated_at: null,
  is_configured: false,
};

const READINESS_BLOCKED = {
  state: "CREDENTIAL_EXPIRED",
  provider: "dhan",
  credential_state: "EXPIRED",
  credential_expiry: "2026-07-25T07:10:00Z",
  provider_state: "NEVER_REPORTED",
  watchdog_state: "NEVER_REPORTED",
  market_state: "OPEN",
  paper_execution_state: "ENABLED",
  real_trading_state: "DISABLED",
  can_start: false,
  safe_reason: "Dhan access token has expired.",
  remediation: "Renew the Dhan access token and revalidate configuration.",
};

function stubEndpoints(options: {
  session?: SessionResponse;
  health?: MarketDataHealthResponse;
  quotes?: QuoteResponse[];
  bars?: BarResponse[];
  readiness?: typeof READINESS_BLOCKED;
  strategies?: StrategySummary[];
  signals?: SignalListResponse;
  workerStatus?: typeof WORKER_STATUS_UNCONFIGURED;
}): ReturnType<typeof vi.fn> {
  const {
    session = SESSION,
    health = HEALTH_DISCONNECTED,
    quotes = [],
    bars = [],
    strategies = [EMA_STRATEGY],
    signals = EMPTY_SIGNALS,
    workerStatus = WORKER_STATUS_UNCONFIGURED,
    readiness = READINESS_BLOCKED,
  } = options;
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/live-paper-readiness/")) return Promise.resolve(jsonResponse(readiness));
    if (url.includes("/worker-status/")) return Promise.resolve(jsonResponse(workerStatus));
    if (url.includes("/session/")) return Promise.resolve(jsonResponse(session));
    if (url.includes("/health/")) return Promise.resolve(jsonResponse(health));
    if (url.includes("/bars/")) return Promise.resolve(jsonResponse(bars));
    if (url.includes("/quotes/")) return Promise.resolve(jsonResponse(quotes));
    if (url.includes("/strategy-engine/strategies/")) return Promise.resolve(jsonResponse(strategies));
    if (url.includes("/communication/")) {
      return Promise.resolve(jsonResponse({ signal_id: "sig-1", attempts: [] }));
    }
    if (url.includes("/signals/")) return Promise.resolve(jsonResponse(signals));
    return Promise.resolve(jsonResponse(health));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("LiveMarketDataMonitor (Active Signal Monitor)", () => {
  it("shows an honest empty state naming the current scan configuration when no signals exist", async () => {
    stubEndpoints({});

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => {
      expect(
        screen.getByText(
          /No active signals\. Timeframe: 5m\. Universe: All Stocks\./i,
        ),
      ).toBeInTheDocument();
    });
  });

  it("renders a real qualifying signal in the active signal table, never a market-data row", async () => {
    stubEndpoints({
      health: HEALTH_CONNECTED,
      quotes: [RELIANCE_QUOTE],
      signals: { items: [RELIANCE_SIGNAL], total_count: 1, page: 1, page_size: 10 },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => {
      expect(screen.getByText("ema_crossover")).toBeInTheDocument();
      expect(screen.getByText("RELIANCE")).toBeInTheDocument();
      expect(screen.getByText("BULLISH")).toBeInTheDocument();
      expect(screen.getByText("APPROVED")).toBeInTheDocument();
    });
  });

  it("shows real strategy names from the registry, never the old mock names", async () => {
    stubEndpoints({});

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    expect(screen.queryByText(/trend follower/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/breakout hunter/i)).not.toBeInTheDocument();
  });

  it("shows signal details with an honest 'not provided' note when no TradePlan exists", async () => {
    stubEndpoints({
      signals: { items: [RELIANCE_SIGNAL], total_count: 1, page: 1, page_size: 10 },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    const detailsButton = await waitFor(
      () => {
        const button = screen.getByRole("button", { name: /details/i });
        expect(button).toBeInTheDocument();
        return button;
      },
      { timeout: 3000 },
    );
    fireEvent.click(detailsButton);

    await waitFor(() => {
      expect(screen.getByText("Signal Details")).toBeInTheDocument();
      expect(screen.getByText(/directional-only and does not compute a trade plan/i)).toBeInTheDocument();
    });
  });

  it("Checkpoint 64.18: shows an honest 'not available' note when no signal evidence is persisted", async () => {
    stubEndpoints({
      signals: { items: [RELIANCE_SIGNAL], total_count: 1, page: 1, page_size: 10 },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    const detailsButton = await waitFor(() => screen.getByRole("button", { name: /details/i }));
    fireEvent.click(detailsButton);

    await waitFor(() => expect(screen.getByText("Why This Signal?")).toBeInTheDocument());
    expect(
      screen.getByText(/Strategy evidence is not available for this signal/),
    ).toBeInTheDocument();
  });

  it("Checkpoint 64.18: shows the real, persisted strategy evidence generically - never hardcoded per strategy", async () => {
    const signalWithEvidence: SignalResponse = {
      ...RELIANCE_SIGNAL,
      evidence: {
        schema_version: "1",
        fields: [
          { label: "Fast EMA", value: "1234.50" },
          { label: "Slow EMA", value: "1229.40" },
          { label: "Crossover", value: "Bullish" },
        ],
      },
    };
    stubEndpoints({
      signals: { items: [signalWithEvidence], total_count: 1, page: 1, page_size: 10 },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    const detailsButton = await waitFor(() => screen.getByRole("button", { name: /details/i }));
    fireEvent.click(detailsButton);

    await waitFor(() => expect(screen.getByText("Why This Signal?")).toBeInTheDocument());
    expect(screen.getByText("Fast EMA")).toBeInTheDocument();
    expect(screen.getByText("1234.50")).toBeInTheDocument();
    expect(screen.getByText("Slow EMA")).toBeInTheDocument();
    expect(screen.getByText("1229.40")).toBeInTheDocument();
    expect(screen.getByText("Crossover")).toBeInTheDocument();
    expect(screen.getByText("Bullish")).toBeInTheDocument();
  });

  it("keeps market-data diagnostics collapsed by default, expandable on demand", async () => {
    stubEndpoints({ health: HEALTH_CONNECTED, quotes: [RELIANCE_QUOTE], bars: [RELIANCE_BAR] });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/market data health/i)).toBeInTheDocument());
    expect(screen.queryByText("Market Session")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /market data health/i }));

    await waitFor(() => expect(screen.getByText("Market Session")).toBeInTheDocument());
    expect(screen.getAllByText("RELIANCE").length).toBeGreaterThan(0);
  });

  it("shows the truthful live worker status once diagnostics are expanded", async () => {
    stubEndpoints({
      workerStatus: {
        ...WORKER_STATUS_UNCONFIGURED,
        is_configured: true,
        worker_state: "RUNNING",
        token_state: "VALID",
        watchdog_state: "HEALTHY",
        subscribed_instrument_count: 4,
        reconnect_count: 2,
      },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/market data health/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /market data health/i }));

    await waitFor(() => expect(screen.getByText("Live Worker Status")).toBeInTheDocument());
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("Checkpoint 64.12: shows BLOCKED with a real remediation when Dhan credential is expired", async () => {
    stubEndpoints({ readiness: READINESS_BLOCKED });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/market data health/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /market data health/i }));

    await waitFor(() =>
      expect(screen.getByText("Live Paper Session Readiness")).toBeInTheDocument(),
    );
    expect(screen.getByText("● BLOCKED")).toBeInTheDocument();
    expect(screen.getByText("NOT AVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("Dhan access token has expired.")).toBeInTheDocument();
    expect(screen.getByText(/renew the dhan access token/i)).toBeInTheDocument();
    // Real Trading must always read DISABLED, regardless of readiness state.
    expect(screen.getByText("DISABLED")).toBeInTheDocument();
  });

  it("Checkpoint 64.12: shows READY when the gate reports can_start", async () => {
    stubEndpoints({
      readiness: {
        ...READINESS_BLOCKED,
        state: "READY_FOR_PAPER",
        credential_state: "VALID",
        provider_state: "HEALTHY",
        watchdog_state: "HEALTHY",
        can_start: true,
        safe_reason: "All readiness checks passed.",
        remediation: "Start the Live Paper Session explicitly.",
      },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/market data health/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /market data health/i }));

    await waitFor(() => expect(screen.getByText("● READY")).toBeInTheDocument());
    expect(screen.getByText("AVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("DISABLED")).toBeInTheDocument(); // Real Trading still disabled
  });

  it("shows an honest 'never run' note when the worker has no reported status", async () => {
    stubEndpoints({});

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/market data health/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /market data health/i }));

    await waitFor(() =>
      expect(screen.getByText(/has never run in this environment/i)).toBeInTheDocument(),
    );
  });

  it("never renders an order-placement control (button, quantity input, or submit form)", async () => {
    stubEndpoints({
      health: HEALTH_CONNECTED,
      quotes: [RELIANCE_QUOTE],
      signals: { items: [RELIANCE_SIGNAL], total_count: 1, page: 1, page_size: 10 },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText("ema_crossover")).toBeInTheDocument());

    const forbiddenButtonNames = [/^buy$/i, /^sell$/i, /^execute$/i, /place order/i, /submit order/i];
    for (const pattern of forbiddenButtonNames) {
      expect(screen.queryByRole("button", { name: pattern })).not.toBeInTheDocument();
    }
    expect(screen.queryByLabelText(/quantity/i)).not.toBeInTheDocument();
    expect(document.querySelector('input[type="number"]')).not.toBeInTheDocument();
  });

  it("renders a safe error message when loading signals fails, never raw backend internals", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/signals/")) {
        return Promise.resolve(
          jsonResponse({ error_code: "internal_error", message: "Unable to load signals." }, 500),
        );
      }
      if (url.includes("/session/")) return Promise.resolve(jsonResponse(SESSION));
      if (url.includes("/health/")) return Promise.resolve(jsonResponse(HEALTH_DISCONNECTED));
      if (url.includes("/bars/")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/quotes/")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/strategy-engine/strategies/")) return Promise.resolve(jsonResponse([EMA_STRATEGY]));
      return Promise.resolve(jsonResponse(HEALTH_DISCONNECTED));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to load signals.");
  });

  it("changing the timeframe control re-requests signals with the new timeframe (real wiring, not cosmetic)", async () => {
    const fetchMock = stubEndpoints({});

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/no active signals/i)).toBeInTheDocument());
    fetchMock.mockClear();

    fireEvent.change(screen.getByLabelText(/timeframe/i), { target: { value: "15m" } });

    await waitFor(() => {
      const calledWith15m = fetchMock.mock.calls.some((call) =>
        String(call[0]).includes("timeframe=15m"),
      );
      expect(calledWith15m).toBe(true);
    });
  });

  it("Checkpoint 64.9: shows real TradePlan values and communication badges in the signal table", async () => {
    const signalWithPlan: SignalResponse = {
      ...RELIANCE_SIGNAL,
      signal_id: "sig-plan",
      trade_plan: {
        entry_price: "100.0000",
        stop_loss: "98.0000",
        target_1: "103.0000",
        target_2: "105.0000",
        target_3: "108.0000",
        trailing_stop_loss: "99.0000",
        calculation_method: "ATR test plan",
      },
      telegram: {
        status: "SENT",
        attempted_at: "2026-08-14T06:00:00Z",
        delivered_at: "2026-08-14T06:00:00Z",
        retry_count: 0,
        error_message: "",
      },
      discord: {
        status: "FAILED",
        attempted_at: "2026-08-14T06:00:00Z",
        delivered_at: null,
        retry_count: 2,
        error_message: "simulated failure",
      },
    };
    stubEndpoints({
      signals: { items: [signalWithPlan], total_count: 1, page: 1, page_size: 25 },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText("₹98.0000")).toBeInTheDocument());
    expect(screen.getByText("₹103.0000")).toBeInTheDocument();
    expect(screen.getByText("SENT")).toBeInTheDocument();
    expect(screen.getByText("FAILED")).toBeInTheDocument();
  });

  it("Checkpoint 64.9: shows 'Not provided' for a directional-only strategy's TradePlan columns, never fabricated values", async () => {
    stubEndpoints({
      signals: { items: [RELIANCE_SIGNAL], total_count: 1, page: 1, page_size: 25 },
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getAllByText("Not provided").length).toBeGreaterThan(0));
    expect(screen.getAllByText("No attempt yet").length).toBeGreaterThan(0);
  });

  it("Checkpoint 64.9: changing the risk-status filter re-requests signals with the real query parameter", async () => {
    const fetchMock = stubEndpoints({});

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/no active signals/i)).toBeInTheDocument());
    fetchMock.mockClear();

    fireEvent.change(screen.getByLabelText(/risk status/i), { target: { value: "REJECTED" } });

    await waitFor(() => {
      const called = fetchMock.mock.calls.some((call) =>
        String(call[0]).includes("risk_status=REJECTED"),
      );
      expect(called).toBe(true);
    });
  });

  it("Checkpoint 64.9: changing the sort order re-requests signals with the real sort parameter", async () => {
    const fetchMock = stubEndpoints({});

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/no active signals/i)).toBeInTheDocument());
    fetchMock.mockClear();

    fireEvent.change(screen.getByLabelText(/^sort$/i), { target: { value: "oldest" } });

    await waitFor(() => {
      const called = fetchMock.mock.calls.some((call) => String(call[0]).includes("sort=oldest"));
      expect(called).toBe(true);
    });
  });

  it("Checkpoint 64.9: changing rows-per-page re-requests signals with the real page_size parameter", async () => {
    const fetchMock = stubEndpoints({});

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText(/no active signals/i)).toBeInTheDocument());
    fetchMock.mockClear();

    fireEvent.change(screen.getByLabelText(/rows per page/i), { target: { value: "100" } });

    await waitFor(() => {
      const called = fetchMock.mock.calls.some((call) =>
        String(call[0]).includes("page_size=100"),
      );
      expect(called).toBe(true);
    });
  });
});
