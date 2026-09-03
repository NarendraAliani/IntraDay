// frontend/src/features/reports/ReportsOverviewPage.tsx
//
// Checkpoint 32 Part 11: the reporting surface and navigation-
// discoverability home for every report type and major product
// capability, including ones not yet available - a deliberate
// placeholder, never a blank page, per Part 11's explicit instruction.
import type { JSX } from "react";

import { CapabilityStatus } from "../../common/components/CapabilityStatus";
import { Icon } from "../../common/icons/Icon";
import { CAPABILITY_REGISTRY } from "./capabilityRegistry";
import {
  CONDITIONS_PASSED,
  CONDITIONS_TOTAL,
  CURRENT_CLASSIFICATION,
  TRADING_GRADE_BAR_CONDITIONS,
} from "./marketDataQualityReport";
import { REPORT_CATALOGUE } from "./reportCatalogue";

// Checkpoint FRONTEND-5 Part 2: NOT_SATISFIED's label used a raw "✕"
// Unicode glyph outside the closed icon system (flagged, but correctly
// left unfixed, by FRONTEND-4). Replaced here with the real `error`
// icon from `Icon.tsx`. SATISFIED/BLOCKED's own glyphs are untouched -
// this page's broader density/layout question stays deliberately
// deferred, out of scope for this checkpoint.
const CONDITION_LABEL: Record<string, string> = {
  SATISFIED: "✓ Satisfied",
  NOT_SATISFIED: "Not Satisfied",
  BLOCKED: "⊘ Blocked",
};

const CONDITION_CLASS: Record<string, string> = {
  SATISFIED: "badge badge--active",
  NOT_SATISFIED: "badge badge--danger",
  BLOCKED: "badge badge--historical",
};

export function ReportsOverviewPage(): JSX.Element {
  return (
    <div className="reports-overview">
      <h1>Reports</h1>
      <p className="configuration-viewer__subtitle">
        Every report type this platform is designed to produce, and every major product
        capability it currently has or plans to build - each shown with its honest, current
        state. Nothing here claims a capability is working when it is not.
      </p>

      <section className="capability-status-section" aria-labelledby="report-catalogue-heading">
        <h2 id="report-catalogue-heading">Report Catalogue</h2>
        <div className="capability-status-grid">
          {REPORT_CATALOGUE.map((entry) => (
            <CapabilityStatus
              key={entry.reportType}
              title={entry.title}
              description={`${entry.purpose} UI surface: ${entry.uiSurface}.`}
              status={entry.status}
            />
          ))}
        </div>
      </section>

      <section
        className="capability-status-section"
        aria-labelledby="market-data-quality-heading"
      >
        <h2 id="market-data-quality-heading">Market Data Quality Report</h2>
        <p>
          Current classification:{" "}
          <span
            className={`badge ${CURRENT_CLASSIFICATION === "TRADING_GRADE_BAR" ? "badge--active" : "badge--pending"}`}
          >
            {CURRENT_CLASSIFICATION}
          </span>{" "}
          ({CONDITIONS_PASSED} of {CONDITIONS_TOTAL} TRADING_GRADE_BAR conditions satisfied).
          This classification never changes until ALL conditions below are satisfied - it is
          never inferred from partial progress.
        </p>
        <table className="market-data-monitor__table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Condition</th>
              <th scope="col">Status</th>
              <th scope="col">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {TRADING_GRADE_BAR_CONDITIONS.map((condition) => (
              <tr key={condition.ordinal}>
                <td>{condition.ordinal}</td>
                <td>{condition.description}</td>
                <td>
                  <span className={CONDITION_CLASS[condition.status]}>
                    {condition.status === "NOT_SATISFIED" && <Icon name="error" />}{" "}
                    {CONDITION_LABEL[condition.status]}
                  </span>
                </td>
                <td>{condition.evidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="capability-status__doc-link">
          Full evidence: <code>docs/research/TRADING_GRADE_BAR_VALIDATION.md</code>
        </p>
      </section>

      <section className="capability-status-section" aria-labelledby="export-heading">
        <h2 id="export-heading">Report Export</h2>
        <div className="capability-status-grid">
          <CapabilityStatus
            title="Export PDF"
            description="Download any report as a formatted PDF document."
            status="PLANNED"
            prerequisite="A chosen document-generation library, not yet architecturally justified for a single report type."
          />
          <CapabilityStatus
            title="Export CSV"
            description="Download tabular report data (e.g. trade tables) as CSV."
            status="PLANNED"
          />
          <CapabilityStatus
            title="Export JSON"
            description="Download the underlying report data as machine-readable JSON."
            status="PLANNED"
            prerequisite="A dedicated export endpoint - the underlying data already exists via the results API."
          />
        </div>
      </section>

      {CAPABILITY_REGISTRY.map((group) => (
        <section
          key={group.groupTitle}
          className="capability-status-section"
          aria-labelledby={`capability-${group.groupTitle}`}
        >
          <h2 id={`capability-${group.groupTitle}`}>{group.groupTitle}</h2>
          <div className="capability-status-grid">
            {group.capabilities.map((capability) => (
              <CapabilityStatus key={capability.title} {...capability} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
