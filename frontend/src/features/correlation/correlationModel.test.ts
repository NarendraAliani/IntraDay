// frontend/src/features/correlation/correlationModel.test.ts
//
// Checkpoint 64.80-F3 Phase 13: the HONESTY gate.
//
// This is the most important test file in the checkpoint. The Decision
// Pipeline's whole claim is "every relationship shown here is one the
// existing API actually establishes". A comment cannot enforce that. So
// this file reads the checked-in generated contract
// (`shared/generated_contracts/api-types.ts`) as text and asserts that
// every endpoint and schema field the model cites as evidence for a
// FOUND or PARTIAL link genuinely exists in it - and, symmetrically,
// that every field the model claims is MISSING is genuinely absent.
//
// If someone later adds a link asserting a correlation that the backend
// does not expose, this file fails.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  ALL_AUDITED_LINKS,
  FORBIDDEN_RELATIONSHIPS,
  PIPELINE_LINKS,
  PIPELINE_NODES,
  STATUS_MEANING,
  STATUS_TONE,
  SUPPLEMENTARY_LINKS,
  nodeById,
  outgoingLink,
  statusDescriptor,
} from "./correlationModel";
import type { CorrelationStatus } from "./correlationModel";

const CONTRACT = readFileSync(
  join(__dirname, "..", "..", "..", "shared", "generated_contracts", "api-types.ts"),
  "utf-8",
);

/** Extracts one named schema's body from the generated contract, so a
 * field assertion is scoped to the right schema rather than matching the
 * same field name anywhere in a 5000-line file. */
function schemaBody(name: string): string {
  const match = CONTRACT.match(new RegExp(`\\n        ${name}: \\{\\n([\\s\\S]*?)\\n        \\};`));
  expect(match, `schema ${name} must exist in the generated contract`).not.toBeNull();
  return match ? match[1] : "";
}

describe("the generated contract is readable (sanity check for this gate itself)", () => {
  it("contains the schema block and a substantial number of paths", () => {
    expect(CONTRACT.length).toBeGreaterThan(10000);
    expect(CONTRACT).toContain("export interface components");
  });
});

describe("Phase 2 - one consistent correlation vocabulary", () => {
  it("every audited link uses a status word from the closed vocabulary", () => {
    const vocabulary = Object.keys(STATUS_MEANING);
    for (const link of ALL_AUDITED_LINKS) {
      expect(vocabulary).toContain(link.status);
    }
  });

  it("every status word has both a meaning and a tone", () => {
    for (const status of Object.keys(STATUS_MEANING) as CorrelationStatus[]) {
      expect(STATUS_MEANING[status].length).toBeGreaterThan(20);
      expect(STATUS_TONE[status]).toBeTruthy();
      expect(statusDescriptor(status).label).toBe(status);
    }
  });

  it("all six vocabulary words are exercised by at least one audited link", () => {
    const used = new Set(ALL_AUDITED_LINKS.map((link) => link.status));
    for (const status of Object.keys(STATUS_MEANING)) {
      expect([...used]).toContain(status);
    }
  });
});

describe("Phase 1 - every link carries real evidence", () => {
  it("no link is asserted without evidence text", () => {
    for (const link of ALL_AUDITED_LINKS) {
      expect(link.evidence.length, `${link.id} must cite evidence`).toBeGreaterThan(40);
      expect(link.relationship.length, `${link.id} must explain itself`).toBeGreaterThan(20);
    }
  });

  it("every link's endpoints reference real, checked-in API paths", () => {
    const cited = new Set<string>();
    for (const link of ALL_AUDITED_LINKS) {
      for (const path of link.evidence.match(/\/api\/v1\/[A-Za-z0-9/_{}-]*\//g) ?? []) {
        cited.add(path);
      }
    }
    // Every link that cites an endpoint must cite one that exists.
    expect(cited.size).toBeGreaterThan(0);
    for (const path of cited) {
      expect(CONTRACT, `${path} must exist in the generated contract`).toContain(`"${path}"`);
    }
  });

  it("every node's listed APIs exist in the generated contract", () => {
    for (const node of PIPELINE_NODES) {
      for (const api of node.apis) {
        const path = api.replace(/^GET /, "");
        expect(CONTRACT, `${node.id} cites ${path}`).toContain(`"${path}"`);
      }
    }
  });

  it("no link connects nodes that are not in the pipeline", () => {
    for (const link of ALL_AUDITED_LINKS) {
      expect(nodeById(link.source), `${link.id} source`).toBeDefined();
      expect(nodeById(link.target), `${link.id} target`).toBeDefined();
    }
  });
});

// ---------------------------------------------------------------------
// The FOUND claims, checked one by one against the real contract.
// ---------------------------------------------------------------------

describe("FOUND - Market Data to Features", () => {
  it("FieldDefinition really exposes required_inputs and source", () => {
    const body = schemaBody("FieldDefinition");
    expect(body).toContain("required_inputs");
    expect(body).toContain("source");
    expect(body).toContain("field_id");
  });

  it("the field registry endpoint really exists", () => {
    expect(CONTRACT).toContain('"/api/v1/config/strategy-engine/fields/"');
  });
});

describe("FOUND - Scanner to Strategy", () => {
  it("ScannerConfigurationState really exposes strategy_ids", () => {
    expect(schemaBody("ScannerConfigurationState")).toContain("strategy_ids");
  });

  it("ScannerProgressResponse really exposes current_strategy", () => {
    const body = schemaBody("ScannerProgressResponse");
    expect(body).toContain("current_strategy");
    expect(body).toContain("strategies_total");
  });
});

describe("FOUND - Strategy to Signal", () => {
  it("SignalResponse really carries strategy_id", () => {
    expect(schemaBody("SignalResponse")).toContain("strategy_id");
  });

  it("SignalReportResponse really aggregates by_strategy", () => {
    expect(schemaBody("SignalReportResponse")).toContain("by_strategy");
  });
});

describe("FOUND - Paper Trade to Outcome", () => {
  it("PaperTradeResponse really carries realized_pnl", () => {
    expect(schemaBody("PaperTradeResponse")).toContain("realized_pnl");
  });

  it("the daily session report really carries realized_pnl_total", () => {
    expect(schemaBody("DailySessionReportResponse")).toContain("realized_pnl_total");
  });
});

describe("FOUND - Strategy to Backtest outcome", () => {
  it("backtest results really are addressable per strategy", () => {
    expect(CONTRACT).toContain('"/api/v1/config/backtesting/strategies/{strategy_id}/results/"');
  });
});

// ---------------------------------------------------------------------
// The PARTIAL / NOT FOUND / NOT AVAILABLE claims. These are the ones an
// over-eager UI would quietly upgrade to FOUND, so each asserts the
// ABSENCE that justifies the downgrade.
// ---------------------------------------------------------------------

describe("PARTIAL - Signal to Paper Trade is NOT a direct join", () => {
  it("PaperSessionSignal does carry signal_id together with order_status", () => {
    const body = schemaBody("PaperSessionSignal");
    expect(body).toContain("signal_id");
    expect(body).toContain("order_status");
  });

  // Checkpoint 64.82: this assertion previously asserted the ABSENCE of
  // `signal_id` on `PaperTradeResponse`. Checkpoint 64.81 added that
  // field (`PaperTradeRecord.signal_id`, populated by an ID join from
  // the trade's own `order_ids` to its entry order - never inferred),
  // and 64.82 regenerated the contract, so the absence is no longer
  // true. Asserting the CURRENT contract truth rather than a stale gap.
  it("PaperTradeResponse now carries signal_id (closed by Checkpoint 64.81)", () => {
    const body = schemaBody("PaperTradeResponse");
    expect(body).toContain("signal_id");
    expect(body).toContain("order_ids");
  });

  it("the model reports this link as PARTIAL, never FOUND", () => {
    const link = PIPELINE_LINKS.find((entry) => entry.id === "signal-to-paper-trade");
    expect(link?.status).toBe("PARTIAL");
    expect(link?.gap.length).toBeGreaterThan(20);
  });
});

describe("PARTIAL - Features to Strategy exposes category, not resolved fields", () => {
  it("ParameterDefinition exposes field_category but no resolved field list", () => {
    const body = schemaBody("ParameterDefinition");
    expect(body).toContain("field_category");
    expect(body).not.toContain("required_features");
  });

  // Checkpoint 64.82: previously asserted that NO endpoint published
  // `required_features`. Checkpoint 64.81 exposed it on the strategy
  // configuration response, and 64.82 additionally exposes it on the
  // correlation strategy trace. Asserting the current contract truth.
  it("required_features is now published by the contract (closed by 64.81/64.82)", () => {
    expect(CONTRACT).toContain("required_features");
  });

  it("the model reports this link as PARTIAL", () => {
    const link = SUPPLEMENTARY_LINKS.find((entry) => entry.id === "features-to-strategy");
    expect(link?.status).toBe("PARTIAL");
  });
});

describe("PARTIAL - a scan run cannot be joined to an individual signal", () => {
  it("ScannerProgressResponse exposes only an aggregate signals_found", () => {
    expect(schemaBody("ScannerProgressResponse")).toContain("signals_found");
  });

  // Checkpoint 64.82: previously asserted that `SignalResponse` carried
  // NO scan-run identifier. Checkpoint 64.81 added `scan_run_id` (the
  // existing timestamp-shaped `ScannerScanProgress.scan_id`, propagated
  // - not a new identity), and 64.82 regenerated the contract.
  it("SignalResponse now carries scan_run_id (closed by Checkpoint 64.81)", () => {
    const body = schemaBody("SignalResponse");
    expect(body).toContain("scan_run_id");
  });
});

describe("NOT FOUND - Paper Trade to Strategy version", () => {
  it("no paper schema carries a strategy version field", () => {
    for (const schema of [
      "PaperTradeResponse",
      "PaperOrderResponse",
      "PaperPositionResponse",
      "PaperSessionTrade",
    ]) {
      const body = schemaBody(schema);
      expect(body, `${schema} must not carry specification_version`).not.toContain(
        "specification_version",
      );
      expect(body, `${schema} must not carry code_version`).not.toContain("code_version");
      expect(body, `${schema} must not carry configuration_version`).not.toContain(
        "configuration_version",
      );
    }
  });

  it("the model reports this relationship as NOT FOUND", () => {
    const link = SUPPLEMENTARY_LINKS.find(
      (entry) => entry.id === "paper-trade-to-strategy-version",
    );
    expect(link?.status).toBe("NOT FOUND");
  });
});

describe("NOT AVAILABLE - signal evidence cannot be joined to the field registry", () => {
  it("SignalResponse.evidence is an untyped dictionary, not a field_id list", () => {
    const body = schemaBody("SignalResponse");
    expect(body).toContain("evidence");
    expect(body).not.toContain("field_id");
  });

  it("the model reports this relationship as NOT AVAILABLE", () => {
    const link = SUPPLEMENTARY_LINKS.find((entry) => entry.id === "features-to-signal");
    expect(link?.status).toBe("NOT AVAILABLE");
  });
});

describe("NOT APPLICABLE - there is no scanner-condition entity", () => {
  it("ScannerConfigurationState exposes no condition or feature field at all", () => {
    const body = schemaBody("ScannerConfigurationState");
    expect(body).not.toContain("condition");
    expect(body).not.toContain("feature");
    expect(body).not.toContain("field");
  });

  it("the model reports Features to Scanner as NOT APPLICABLE, not as a gap", () => {
    const link = PIPELINE_LINKS.find((entry) => entry.id === "features-to-scanner");
    expect(link?.status).toBe("NOT APPLICABLE");
  });
});

// Checkpoint FRONTEND-1: the "NOT YET IMPLEMENTED - archive completeness
// has no HTTP API" guard this block used to contain (checkpoint 64.90) is
// now factually false, not a real gap - Checkpoint 64.83 Phases 3/5 added
// real, deliberate, documented endpoints:
// `/api/v1/market-data/archive/{trading_date}/` and
// `/api/v1/market-data/reconciliation/{trading_date}/` (note: neither
// ever lived under `/config/` - the removed assertion's own path was
// never the real one, even when this test was first written). Both are
// intentional, stable backend surface (exercised extensively by this
// session's own backend checkpoints, via `MarketDataArchiveDay`'s
// `reconciliation_status`/`reconciliation_outcome` fields) - the correct
// fix is removing this stale premise, not asserting the feature's
// continued absence. No frontend consumption of these endpoints exists
// yet; that remains a real, separate gap this test file does not track.

// ---------------------------------------------------------------------
// The scope rules.
// ---------------------------------------------------------------------

describe("Scope - no invented and no out-of-scope correlation", () => {
  const modelText = readFileSync(join(__dirname, "correlationModel.ts"), "utf-8");
  const componentText = readFileSync(join(__dirname, "DecisionPipeline.tsx"), "utf-8");

  it("introduces no NSE_FNO / options / OI / IV / Greeks relationship", () => {
    const banned = [
      "OptionQuote",
      "OptionChain",
      "OptionBar",
      "NSE_FNO",
      "open_interest",
      "implied_volatility",
      "greeks",
    ];
    for (const term of banned) {
      const pattern = new RegExp(term, "i");
      // The model names these only inside FORBIDDEN_RELATIONSHIPS, which
      // is a list of edges that must NEVER be drawn - it is not a link.
      const linkText = ALL_AUDITED_LINKS.map(
        (link) => `${link.relationship} ${link.evidence}`,
      ).join(" ");
      expect(pattern.test(linkText), `${term} must not appear in any audited link`).toBe(false);
      expect(pattern.test(componentText), `${term} must not appear in the component`).toBe(false);
    }
  });

  it("declares no live-execution edge", () => {
    for (const link of ALL_AUDITED_LINKS) {
      expect(link.target).not.toBe("live-execution");
      expect(link.source).not.toBe("live-execution");
    }
    expect(PIPELINE_NODES.map((node) => node.id)).not.toContain("live-execution");
    expect(FORBIDDEN_RELATIONSHIPS).toContain("Signal to Live Execution");
  });

  it("offers no Gainz activation control and no Gainz node", () => {
    expect(PIPELINE_NODES.map((node) => node.id)).not.toContain("gainz");
    expect(/gainz/i.test(componentText)).toBe(false);
  });

  it("does not reintroduce a second icon or theme system", () => {
    expect(modelText).not.toMatch(/<svg/i);
    expect(componentText).not.toMatch(/<svg/i);
    expect(componentText).toContain('from "../../common/icons/Icon"');
    expect(componentText).toContain('from "../dashboard/StatusBadge"');
  });
});

describe("Phase 3 - the chain is a real, ordered sequence", () => {
  it("runs Market Data to Features to Scanner to Strategy to Signal to Paper Trade to Outcome", () => {
    expect(PIPELINE_NODES.map((node) => node.id)).toEqual([
      "market-data",
      "features",
      "scanner",
      "strategy",
      "signal",
      "paper-trade",
      "outcome",
    ]);
  });

  it("every stage except the last has exactly one outgoing chain link", () => {
    const ids = PIPELINE_NODES.map((node) => node.id);
    for (const id of ids.slice(0, -1)) {
      expect(outgoingLink(id), `${id} must have an outgoing link`).toBeDefined();
    }
    expect(outgoingLink("outcome")).toBeUndefined();
  });

  it("each chain link joins consecutive stages - no stage is skipped", () => {
    const ids = PIPELINE_NODES.map((node) => node.id);
    for (const link of PIPELINE_LINKS) {
      expect(ids.indexOf(link.target)).toBe(ids.indexOf(link.source) + 1);
    }
  });

  it("every navigable node points at a screen the application really has", () => {
    const realScreens = [
      "market-data",
      "strategies",
      "live-scanner",
      "paper-trading",
      "reports",
      "backtesting",
    ];
    for (const node of PIPELINE_NODES) {
      if (node.destination !== null) {
        expect(realScreens).toContain(node.destination);
        expect(node.destinationLabel).toBeTruthy();
      }
    }
  });
});
