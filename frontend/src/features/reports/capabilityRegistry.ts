// frontend/src/features/reports/capabilityRegistry.ts
//
// Checkpoint 32 Part 4/6: ONE authoritative list of every major product
// capability and its current, honest state - used by the Reports
// Overview page's navigation-discoverability sections. No page should
// hand-write a second, competing list of "what this platform can do" -
// they should import from here.
import type { CapabilityState, CapabilityStatusProps } from "../../common/components/CapabilityStatus";

export interface CapabilityGroup {
  groupTitle: string;
  capabilities: CapabilityStatusProps[];
}

const RUNTIME_DECISION_DOC = "docs/architecture/RUNTIME_ARCHITECTURE_DECISION.md";
const TRADING_GRADE_DOC = "docs/research/TRADING_GRADE_BAR_VALIDATION.md";

export const CAPABILITY_REGISTRY: CapabilityGroup[] = [
  {
    groupTitle: "Research",
    capabilities: [
      {
        title: "Backtesting",
        description: "Single-instrument strategy backtesting with a verified Indian cost model.",
        status: "AVAILABLE",
      },
      {
        title: "Portfolio Backtesting",
        description: "Multi-instrument, shared-capital-pool backtesting.",
        status: "AVAILABLE",
      },
      {
        title: "Comparison",
        description: "Side-by-side comparison of two or more backtest results.",
        status: "AVAILABLE",
      },
      {
        title: "Independent Reference Validation",
        description: "Cross-checks the backtest engine against an independently-derived reference implementation.",
        status: "AVAILABLE",
        documentationLink: "docs/research/BACKTEST_REFERENCE_VALIDATION.md",
      },
      {
        title: "Walk Forward Analysis",
        description: "Rolling out-of-sample re-validation of a strategy across successive windows.",
        status: "PLANNED",
        prerequisite: "A defined walk-forward window/re-optimization protocol.",
      },
      {
        title: "Monte Carlo Simulation",
        description: "Randomized trade-order/return resampling to estimate result robustness.",
        status: "PLANNED",
        prerequisite: "A defined resampling methodology.",
      },
      {
        title: "Robustness Validation",
        description: "Parameter-sensitivity and regime-stability analysis.",
        status: "PLANNED",
      },
    ],
  },
  {
    groupTitle: "Market Data",
    capabilities: [
      {
        title: "Live Market Data Monitor",
        description: "Read-only observation of live NSE cash-equity prices via periodic REST polling.",
        status: "PARTIAL",
        documentationLink: "docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md",
      },
      {
        title: "Trading-Grade Bars",
        description: "Bars that satisfy the full six-condition TRADING_GRADE_BAR acceptance definition.",
        status: "BLOCKED",
        blocker: "4 of 6 conditions unmet - primarily no persistent-process WebSocket hosting.",
        prerequisite: "A resolved, implemented WebSocket runtime.",
        documentationLink: TRADING_GRADE_DOC,
      },
      {
        title: "WebSocket Live Feed",
        description: "Continuous, tick-by-tick market-data ingestion from Dhan's WebSocket feed.",
        status: "BLOCKED",
        blocker: "No non-Docker persistent process exists yet to host a WebSocket client.",
        prerequisite: "Implementation of the runtime architecture decided in Checkpoint 32.",
        documentationLink: RUNTIME_DECISION_DOC,
      },
      {
        title: "Gap Recovery",
        description: "Reconciling missed intervals against Dhan's historical/intraday endpoint after a disconnect.",
        status: "BLOCKED",
        blocker: "Contingent on the WebSocket Live Feed, which does not exist yet.",
        documentationLink: TRADING_GRADE_DOC,
      },
    ],
  },
  {
    groupTitle: "Trading",
    capabilities: [
      {
        title: "Strategy Execution (Live)",
        description: "Wiring a strategy's signals to real-time market data for live decision-making.",
        status: "NOT_YET_IMPLEMENTED",
        blocker: "Signal generation remains unwired from live/trading-grade data by design.",
      },
      {
        title: "Paper Trading",
        description: "Simulated order execution against live prices, without real broker orders.",
        status: "PLANNED",
        prerequisite: "TRADING_GRADE_BAR and RESEARCH_READY.",
      },
      {
        title: "Order Management",
        description: "Order lifecycle tracking (placement, modification, cancellation, fills).",
        status: "PLANNED",
      },
      {
        title: "Risk Engine",
        description: "Non-bypassable pre-trade risk gating for every signal.",
        status: "PLANNED",
      },
      {
        title: "Live Execution",
        description: "Real broker order placement.",
        status: "NOT_YET_IMPLEMENTED",
        blocker: "This platform has never placed a real order, by design.",
      },
    ],
  },
  {
    groupTitle: "Notifications",
    capabilities: [
      {
        title: "Telegram",
        description: "Outbound notification delivery via Telegram.",
        status: "AVAILABLE",
      },
      {
        title: "Discord",
        description: "Outbound notification delivery via Discord.",
        status: "AVAILABLE",
      },
      {
        title: "WhatsApp",
        description: "Outbound notification delivery via WhatsApp.",
        status: "NOT_YET_IMPLEMENTED",
      },
      {
        title: "AI Agent Controls",
        description: "Autonomous agent-driven configuration or trading assistance.",
        status: "NOT_YET_IMPLEMENTED",
      },
    ],
  },
];

export function stateBadgeCount(state: CapabilityState): number {
  return CAPABILITY_REGISTRY.flatMap((group) => group.capabilities).filter(
    (capability) => capability.status === state,
  ).length;
}
