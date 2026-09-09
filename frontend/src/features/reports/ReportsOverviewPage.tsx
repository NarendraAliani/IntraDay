// frontend/src/features/reports/ReportsOverviewPage.tsx
//
// Checkpoint 32 Part 11: the reporting surface and navigation-
// discoverability home for every report type and major product
// capability, including ones not yet available - a deliberate
// placeholder, never a blank page, per Part 11's explicit instruction.
import type { JSX, ReactNode } from "react";

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

// Checkpoint FRONTEND-5 Part 2: NOT_SATISFIED's label used a raw
// "cross mark" Unicode glyph outside the closed icon system (flagged,
// but correctly left unfixed, by FRONTEND-4). Replaced here with the
// real `error` icon from `Icon.tsx`. SATISFIED/BLOCKED's own glyphs
// are untouched - this page's broader density/layout question stays
// deliberately deferred, out of scope for this checkpoint. (Checkpoint
// FRONTEND-6: this comment deliberately avoids spelling the glyph
// literally, so it doesn't itself trip the new whole-features-tree
// glyph guard below.)
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

/** Checkpoint FRONTEND-4: every major section is a collapsible
 * `<details>` panel - the SAME native-disclosure idiom the Dashboard's
 * own evidence section (`FRONTEND-3`) and the grouped navigation
 * (`FRONTEND-4`'s own Part 2) already use, chosen deliberately over
 * building a new ARIA tabs pattern (a Tabs component was explicitly
 * named as "not yet needed" in `FRONTEND_DESIGN_SYSTEM.md`'s own
 * Deferred list - reusing an established, already-accessible pattern
 * is the lower-risk option the checkpoint asked for). No content was
 * removed or restructured - only whether each section is expanded by
 * default changed. Report Catalogue and Market Data Quality Report
 * (the two sections an operator most likely opens Reports FOR - "what
 * can this produce" and "is today's data trading-grade") stay open by
 * default; the remaining, more detailed capability grids start
 * collapsed. */
function ReportSection(props: {
  id: string;
  title: string;
  defaultOpen: boolean;
  children: ReactNode;
}): JSX.Element {
  return (
    <details className="reports-overview__section" open={props.defaultOpen || undefined}>
      <summary className="reports-overview__section-toggle">
        <h2 id={props.id}>{props.title}</h2>
      </summary>
      <div className="reports-overview__section-body" aria-labelledby={props.id}>
        {props.children}
      </div>
    </details>
  );
}

export function ReportsOverviewPage(): JSX.Element {
  return (
    <div className="reports-overview">
      <h1>Reports</h1>
      <p className="configuration-viewer__subtitle">
        Every report type this platform is designed to produce, and every major product
        capability it currently has or plans to build - each shown with its honest, current
        state. Nothing here claims a capability is working when it is not.
      </p>

      <ReportSection id="report-catalogue-heading" title="Report Catalogue" defaultOpen>
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
      </ReportSection>

      <ReportSection
        id="market-data-quality-heading"
        title="Market Data Quality Report"
        defaultOpen
      >
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
      </ReportSection>

      <ReportSection id="export-heading" title="Report Export" defaultOpen={false}>
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
      </ReportSection>

      {CAPABILITY_REGISTRY.map((group) => (
        <ReportSection
          key={group.groupTitle}
          id={`capability-${group.groupTitle}`}
          title={group.groupTitle}
          defaultOpen={false}
        >
          <div className="capability-status-grid">
            {group.capabilities.map((capability) => (
              <CapabilityStatus key={capability.title} {...capability} />
            ))}
          </div>
        </ReportSection>
      ))}
    </div>
  );
}
