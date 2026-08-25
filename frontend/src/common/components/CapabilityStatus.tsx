// frontend/src/common/components/CapabilityStatus.tsx
//
// Checkpoint 32 Part 5: the ONE reusable placeholder/status mechanism
// for the whole frontend - every page that needs to represent an
// unavailable, partial, planned, or blocked capability uses this
// component, never handcrafted per-page markup. Never used to represent
// a capability that is genuinely fully working - that case renders its
// real UI, not this component.
import type { JSX } from "react";

import { Icon } from "../icons/Icon";
import type { IconName } from "../icons/Icon";

export type CapabilityState =
  | "AVAILABLE"
  | "PARTIAL"
  | "PLANNED"
  | "BLOCKED"
  | "NOT_YET_IMPLEMENTED"
  | "RESEARCH_ONLY";

export interface CapabilityStatusProps {
  title: string;
  description: string;
  status: CapabilityState;
  blocker?: string;
  prerequisite?: string;
  documentationLink?: string;
  expectedCheckpoint?: string;
}

const STATE_LABEL: Record<CapabilityState, string> = {
  AVAILABLE: "Available",
  PARTIAL: "Partial",
  PLANNED: "Planned",
  BLOCKED: "Blocked",
  NOT_YET_IMPLEMENTED: "Not Yet Implemented",
  RESEARCH_ONLY: "Research Only",
};

// Checkpoint 64.80-F2 Phase 8: icon names from the single icon system,
// replacing Unicode glyphs. Capability semantics are unchanged.
const STATE_ICON: Record<CapabilityState, IconName> = {
  AVAILABLE: "success",
  PARTIAL: "warning",
  PLANNED: "info",
  BLOCKED: "error",
  NOT_YET_IMPLEMENTED: "info",
  RESEARCH_ONLY: "warning",
};

const STATE_BADGE_CLASS: Record<CapabilityState, string> = {
  AVAILABLE: "badge--active",
  PARTIAL: "badge--pending",
  PLANNED: "badge--historical",
  BLOCKED: "badge--danger",
  NOT_YET_IMPLEMENTED: "badge--historical",
  RESEARCH_ONLY: "badge--pending",
};

/** A single capability's status - used both as a compact inline badge
 * (`variant="badge"`, the default) and as a fuller explanatory card
 * (`variant="card"`) depending on where it's placed. */
export function CapabilityStatus({
  title,
  description,
  status,
  blocker,
  prerequisite,
  documentationLink,
  expectedCheckpoint,
}: CapabilityStatusProps): JSX.Element {
  return (
    <div className="capability-status" data-status={status}>
      <div className="capability-status__header">
        <span className="capability-status__title">{title}</span>
        <span className={`badge ${STATE_BADGE_CLASS[status]}`}>
          <Icon name={STATE_ICON[status]} /> {STATE_LABEL[status]}
        </span>
      </div>
      <p className="capability-status__description">{description}</p>
      {status === "BLOCKED" && blocker && (
        <p className="capability-status__blocker">
          <strong>Why unavailable:</strong> {blocker}
        </p>
      )}
      {prerequisite && (
        <p className="capability-status__prerequisite">
          <strong>Prerequisite:</strong> {prerequisite}
        </p>
      )}
      {expectedCheckpoint && (
        <p className="capability-status__checkpoint">
          <strong>Expected at:</strong> {expectedCheckpoint}
        </p>
      )}
      {documentationLink && (
        <p className="capability-status__doc-link">
          <strong>Details:</strong> {documentationLink}
        </p>
      )}
    </div>
  );
}
