// frontend/src/features/correlation/correlationModel.ts
//
// Checkpoint 64.80-F3 Phases 1, 2, 6: the RESULT of the Phase 1 audit,
// encoded as data.
//
// THE CENTRAL RULE OF THIS CHECKPOINT: no relationship may be asserted
// here unless the existing backend/API contract actually establishes it.
// Every link below therefore carries an `evidence` string naming the
// exact endpoint + schema field (or, where the relationship does NOT
// exist, naming what was searched and not found). `correlationModel.
// test.ts` re-asserts those field names against the checked-in
// `shared/generated_contracts/api-types.ts`, so a link claiming FOUND on
// a field that does not exist in the contract fails the build.
//
// NO BACKEND CODE WAS ADDED to expose any of this (Phase 14). Where the
// API does not expose a relationship, the gap is displayed, not filled.
import type { IconName } from "../../common/icons/Icon";
import type { StatusDescriptor, StatusTone } from "../dashboard/dashboardModel";

/** Phase 2: the ONE correlation vocabulary. Every status the pipeline can
 * express is in this union - there is no free-text status anywhere. */
export type CorrelationStatus =
  | "FOUND"
  | "PARTIAL"
  | "NOT FOUND"
  | "NOT APPLICABLE"
  | "NOT AVAILABLE"
  | "NOT YET IMPLEMENTED";

/** What each status word means. Phase 2 explicitly warns against
 * confusing data availability with logical correlation, and correlation
 * with causal proof - so these definitions are deliberately narrow, and
 * the UI renders them verbatim next to the legend. */
export const STATUS_MEANING: Record<CorrelationStatus, string> = {
  FOUND:
    "The API contract exposes a field that directly joins these two things. Verified against the generated contract.",
  PARTIAL:
    "Part of the relationship is exposed - an aggregate, a category, or an id that must be joined indirectly - but not the whole link.",
  "NOT FOUND":
    "The relationship was searched for in the API contract and no field establishes it. This is a real traceability gap, not a UI omission.",
  "NOT APPLICABLE":
    "The relationship does not exist in this platform's design. There is nothing for the backend to expose.",
  "NOT AVAILABLE":
    "The relationship exists inside the backend but no HTTP endpoint publishes it, so the frontend cannot show it.",
  "NOT YET IMPLEMENTED":
    "The capability itself is not built yet, so no relationship can exist until it is.",
};

/** Maps the correlation vocabulary onto the EXISTING 64.80-F2 status-tone
 * vocabulary, so `StatusBadge` (icon + word + colour) renders these with
 * zero new badge classes and zero new icons. The status WORD is always
 * rendered, so colour alone never carries the state (Phase 9). */
export const STATUS_TONE: Record<CorrelationStatus, StatusTone> = {
  FOUND: "HEALTHY",
  PARTIAL: "WARNING",
  "NOT FOUND": "BLOCKED",
  "NOT APPLICABLE": "INACTIVE",
  "NOT AVAILABLE": "UNAVAILABLE",
  "NOT YET IMPLEMENTED": "INACTIVE",
};

export function statusDescriptor(status: CorrelationStatus): StatusDescriptor {
  return { label: status, tone: STATUS_TONE[status], detail: STATUS_MEANING[status] };
}

/** The screens this application actually has. Navigation in this project
 * is a single piece of local state in `App.tsx` (there is NO React
 * Router - checked, Phase 7), so a destination is an id the Dashboard
 * already knows how to switch to. A node with `destination: null` has no
 * screen and renders no navigation control rather than a dead link. */
export type PipelineDestination =
  | "market-data"
  | "strategies"
  | "live-scanner"
  | "paper-trading"
  | "reports"
  | "backtesting";

export interface PipelineNode {
  id: string;
  label: string;
  icon: IconName;
  /** What this stage IS, in one sentence. */
  summary: string;
  /** Which real endpoint(s) back this stage. */
  apis: string[];
  destination: PipelineDestination | null;
  destinationLabel: string | null;
  /** Why there is no destination, when there is none. */
  destinationGap: string | null;
}

export interface CorrelationLink {
  id: string;
  source: string;
  target: string;
  status: CorrelationStatus;
  /** Plain-English statement of the relationship, written so it reads
   * correctly when announced on its own by a screen reader without any
   * arrow or visual position (Phase 11). */
  relationship: string;
  /** The exact endpoint + schema field that establishes (or fails to
   * establish) the link. Never a paraphrase. */
  evidence: string;
  /** What is still missing, and what backend work would close it. Empty
   * string only when the link is fully FOUND with no residual gap. */
  gap: string;
}

// ---------------------------------------------------------------------
// PHASE 3: the primary chain.
// ---------------------------------------------------------------------

export const PIPELINE_NODES: PipelineNode[] = [
  {
    id: "market-data",
    label: "Market Data",
    icon: "market",
    summary:
      "Bars and quotes ingested for the subscribed universe. The raw OHLCV fields every derived feature is computed from.",
    apis: [
      "GET /api/v1/config/market-data/bars/",
      "GET /api/v1/config/market-data/quotes/",
      "GET /api/v1/config/market-data/worker-status/",
    ],
    destination: "market-data",
    destinationLabel: "Go to Market Data",
    destinationGap: null,
  },
  {
    id: "features",
    label: "Features",
    icon: "research",
    summary:
      "The canonical field registry: raw Bar fields plus derived equity indicators (EMA, SMA, RSI, ATR, ADX, Relative Volume, MACD histogram and peers). Equity features only - no options fields exist in this registry.",
    apis: ["GET /api/v1/config/strategy-engine/fields/"],
    destination: "strategies",
    destinationLabel: "Go to Strategy Configuration",
    destinationGap: null,
  },
  {
    id: "scanner",
    label: "Scanner",
    icon: "signal",
    summary:
      "The scan loop. It iterates the subscribed universe on one timeframe and runs the configured strategies over it. It holds no conditions of its own.",
    apis: [
      "GET /api/v1/config/market-data/scanner-config/",
      "GET /api/v1/config/market-data/live-paper-workbench/",
    ],
    destination: "live-scanner",
    destinationLabel: "Go to Live Scanner",
    destinationGap: null,
  },
  {
    id: "strategy",
    label: "Strategy",
    icon: "settings",
    summary:
      "A registered, versioned strategy with a parameter schema and a saved configuration. This is where entry/exit conditions actually live.",
    apis: [
      "GET /api/v1/config/strategy-engine/strategies/",
      "GET /api/v1/config/strategy-engine/strategies/{strategy_id}/schema/",
      "GET /api/v1/config/strategy/{strategy_id}/active/",
    ],
    destination: "strategies",
    destinationLabel: "Go to Strategy Configuration",
    destinationGap: null,
  },
  {
    id: "signal",
    label: "Signal",
    icon: "signal",
    summary:
      "A strategy-produced signal with a direction, a risk decision, a trade plan and strategy-authored evidence.",
    apis: [
      "GET /api/v1/config/signals/",
      "GET /api/v1/config/reports/signals/",
    ],
    destination: "reports",
    destinationLabel: "Go to Reports (Signal Report)",
    destinationGap: null,
  },
  {
    id: "paper-trade",
    label: "Paper Trade",
    icon: "paper-trading",
    summary:
      "Simulated execution only. A paper order, its fills, and the resulting paper trade. Nothing here reaches a real exchange.",
    apis: [
      "GET /api/v1/config/paper-trading/orders/",
      "GET /api/v1/config/paper-trading/trades/",
      "GET /api/v1/config/paper-trading/session/",
    ],
    destination: "paper-trading",
    destinationLabel: "Go to Paper Trading",
    destinationGap: null,
  },
  {
    id: "outcome",
    label: "Outcome",
    icon: "system-health",
    summary:
      "Realized and unrealized P&L for the simulated session, plus the backtest results a strategy has produced.",
    apis: [
      "GET /api/v1/config/reports/daily-session/",
      "GET /api/v1/config/backtesting/strategies/{strategy_id}/results/",
    ],
    destination: "backtesting",
    destinationLabel: "Go to Research and Backtesting",
    destinationGap: null,
  },
];

export const PIPELINE_LINKS: CorrelationLink[] = [
  {
    id: "market-data-to-features",
    source: "market-data",
    target: "features",
    status: "FOUND",
    relationship:
      "Market Data supplies the raw bar fields that Features are computed from.",
    evidence:
      'GET /api/v1/config/strategy-engine/fields/ returns FieldDefinition.required_inputs, which names the raw fields each derived feature consumes (for example RSI requires "close", ATR requires "high", "low", "close"). FieldDefinition.source is "domain.market_data.contracts.Bar" for raw fields and "signal_intelligence.feature_engine" for derived ones.',
    gap: "",
  },
  {
    id: "features-to-scanner",
    source: "features",
    target: "scanner",
    status: "NOT APPLICABLE",
    relationship:
      "Features do not feed Scanner conditions, because this platform's Scanner has no conditions. The Scanner is a scan loop over universe and timeframe; feature evaluation happens inside a Strategy.",
    evidence:
      "ScannerConfigurationState exposes only timeframe, universe_mode, universe_requested_count, universe_subscribed_count, strategy_ids, configuration_version and enabled. There is no scanner-condition entity anywhere in the API contract or the backend (no ScannerCondition class exists in src/). The real Feature relationship is Features to Strategy, shown separately below.",
    gap: "None to close. Reading this as a missing link would misdescribe the architecture.",
  },
  {
    id: "scanner-to-strategy",
    source: "scanner",
    target: "strategy",
    status: "FOUND",
    relationship: "The Scanner runs a declared set of Strategies over the universe.",
    evidence:
      "ScannerConfigurationState.strategy_ids on GET /api/v1/config/market-data/scanner-config/ lists exactly which strategies the scan loop runs. ScannerProgressResponse adds current_strategy, strategies_total and strategies_processed while a scan is in flight.",
    gap: "",
  },
  {
    id: "strategy-to-signal",
    source: "strategy",
    target: "signal",
    status: "FOUND",
    relationship: "Each Signal names the Strategy that produced it.",
    evidence:
      "SignalResponse.strategy_id on GET /api/v1/config/signals/ identifies the producing strategy per signal, and SignalReportResponse.by_strategy aggregates signal counts per strategy.",
    gap: "",
  },
  {
    id: "signal-to-paper-trade",
    source: "signal",
    target: "paper-trade",
    status: "PARTIAL",
    relationship:
      "A Signal can be followed to the paper ORDER it produced, but not directly to the resulting paper TRADE.",
    evidence:
      "PaperSessionSignal carries signal_id together with order_status in one record, so signal-to-order is exposed directly. PaperOrderResponse.idempotency_key is the signal_id and order_id is \"order-{signal_id}\" for engine-generated orders (paper_signal_execution.py). PaperTradeResponse, however, has no signal_id - only order_ids - so signal-to-trade is reachable only by joining through the order id.",
    gap: "Backend/API requirement: expose signal_id on PaperTradeResponse so a realized trade can be attributed to its originating signal without a client-side id join.",
  },
  {
    id: "paper-trade-to-outcome",
    source: "paper-trade",
    target: "outcome",
    status: "FOUND",
    relationship: "Each Paper Trade carries the realized outcome it produced.",
    evidence:
      "PaperTradeResponse.realized_pnl on GET /api/v1/config/paper-trading/trades/, PaperSessionTrade.realized_net_pnl, and DailySessionReportResponse.realized_pnl_total / unrealized_pnl_total / closed_positions on GET /api/v1/config/reports/daily-session/.",
    gap: "",
  },
];

// ---------------------------------------------------------------------
// PHASES 5 & 6: relationships that are NOT part of the single-file chain
// but were audited and must be reported honestly rather than omitted.
// ---------------------------------------------------------------------

export const SUPPLEMENTARY_LINKS: CorrelationLink[] = [
  {
    id: "features-to-strategy",
    source: "features",
    target: "strategy",
    status: "PARTIAL",
    relationship:
      "A Strategy declares which Features it consumes, but only the accepted field CATEGORY is published, not the resolved field list.",
    evidence:
      'GET /api/v1/config/strategy-engine/strategies/{strategy_id}/schema/ returns ParameterDefinition entries whose parameter_type is "FIELD_REFERENCE" and whose field_category names the category of field the parameter accepts. The chosen field_id lives in StrategyConfigurationResponse.values, which the contract types as `unknown`. The authoritative resolved list, Strategy.required_features(config) in trading_engine/strategy_execution/strategy.py, is not exposed by any endpoint.',
    gap: "Backend/API requirement: publish the resolved required_features(config) field_id list per active strategy configuration, so a feature can be traced to every strategy that consumes it.",
  },
  {
    id: "market-data-to-scanner",
    source: "market-data",
    target: "scanner",
    status: "FOUND",
    relationship:
      "The Scanner declares the timeframe and the universe of instruments it consumes market data for.",
    evidence:
      "ScannerConfigurationState.timeframe, universe_requested_count and universe_subscribed_count on GET /api/v1/config/market-data/scanner-config/, alongside WorkerRuntimeStatusResponse.subscribed_instrument_count.",
    gap: "",
  },
  {
    id: "scanner-run-to-signal",
    source: "scanner",
    target: "signal",
    status: "PARTIAL",
    relationship:
      "A scan reports how many Signals it found, but an individual Signal cannot be attributed to a specific scan run.",
    evidence:
      "ScannerProgressResponse.signals_found is an aggregate count only. SignalResponse carries no scan-run identifier, so the count cannot be decomposed into the signals it counted.",
    gap: "Backend/API requirement: carry a scan-run identifier onto SignalResponse.",
  },
  {
    id: "features-to-signal",
    source: "features",
    target: "signal",
    status: "NOT AVAILABLE",
    relationship:
      "A Signal shows the values it was justified by, but those values cannot be joined back to the Feature registry.",
    evidence:
      "SignalResponse.evidence.fields is a list of {label, value} pairs authored by the strategy in its own display order (SignalEvidenceRecordView.fields is a tuple of (label, value) strings). The labels are free-text display strings, not FieldDefinition.field_id values, so there is no programmatic join from signal evidence to the field registry.",
    gap: "Backend/API requirement: emit field_id alongside each evidence label so signal evidence becomes machine-traceable to the field registry.",
  },
  {
    id: "paper-trade-to-strategy-version",
    source: "paper-trade",
    target: "strategy",
    status: "NOT FOUND",
    relationship:
      "A Paper Trade names the Strategy but not the Strategy VERSION, so realized P&L cannot be attributed to a specific configuration.",
    evidence:
      "Searched every paper schema in the contract. PaperTradeResponse, PaperOrderResponse, PaperPositionResponse and PaperSessionTrade all carry strategy_id or instrument_id but none carries specification_version, code_version or configuration_version. DailySessionReportResponse.configuration_version is the scanner configuration version, a different concept.",
    gap: "Backend/API requirement: stamp the flattened strategy version onto paper orders and trades, so a change in P&L can be attributed to a change in configuration.",
  },
  {
    id: "strategy-to-backtest-outcome",
    source: "strategy",
    target: "outcome",
    status: "FOUND",
    relationship: "Backtest results are addressable by the Strategy that produced them.",
    evidence:
      "GET /api/v1/config/backtesting/strategies/{strategy_id}/results/ is keyed on strategy_id and returns BacktestResult, which carries its own trust_level and validation payload.",
    gap: "",
  },
  {
    id: "market-data-to-archive-outcome",
    source: "market-data",
    target: "outcome",
    status: "NOT YET IMPLEMENTED",
    relationship:
      "Archive completeness cannot yet qualify an outcome, because archive completeness has no HTTP API.",
    evidence:
      "The daily market-data archive is produced by the market_data_archive MANAGEMENT COMMAND. No archive or reconciliation schema exists in shared/generated_contracts/api-types.ts, as already recorded on the 64.80-F Dashboard.",
    gap: "Backend requirement: expose archive completeness and reconciliation status as a read-only API before an outcome can be qualified by data quality.",
  },
];

/** Relationships that are deliberately absent and must never be drawn.
 * Kept as data so the honesty test can assert the UI does not render
 * them (Phase 13: "no false correlation is displayed"). */
export const FORBIDDEN_RELATIONSHIPS: string[] = [
  "Signal to Live Execution",
  "Strategy to Live Order",
  "Feature to Option Chain",
  "Feature to Open Interest",
  "Feature to Implied Volatility",
  "Feature to Greeks",
];

export const ALL_AUDITED_LINKS: CorrelationLink[] = [
  ...PIPELINE_LINKS,
  ...SUPPLEMENTARY_LINKS,
];

export function nodeById(id: string): PipelineNode | undefined {
  return PIPELINE_NODES.find((node) => node.id === id);
}

export function nodeLabel(id: string): string {
  return nodeById(id)?.label ?? id;
}

/** The link that leaves a node inside the primary chain, if any. The last
 * node has none. */
export function outgoingLink(nodeId: string): CorrelationLink | undefined {
  return PIPELINE_LINKS.find((link) => link.source === nodeId);
}
