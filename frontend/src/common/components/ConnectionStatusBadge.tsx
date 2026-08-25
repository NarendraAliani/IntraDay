// frontend/src/common/components/ConnectionStatusBadge.tsx
//
// Checkpoint 22: shared status indicator for the three provider Settings
// cards (Dhan/Telegram/Discord) - maps the backend's own
// `ConnectionStatusResponse.status` enum to an icon + text label, never
// color alone (matching ActiveBadge's existing accessibility pattern).
// Deliberately keeps "Configured" and "Connected" visually distinct
// (Checkpoint 22 §14's core honesty requirement: configured != connected)
// - CONFIGURED renders as a neutral/pending badge, never the same green
// as CONNECTED.
import type { components } from "@shared/generated_contracts/api-types";

import { Icon } from "../icons/Icon";
import type { IconName } from "../icons/Icon";

type Status = components["schemas"]["ConnectionStatusResponseStatusEnum"];

const STATUS_LABELS: Record<Status, string> = {
  NOT_CONFIGURED: "Not configured",
  CONFIGURED: "Configured — not yet tested",
  CONNECTING: "Testing connection…",
  CONNECTED: "Connected",
  DISCONNECTED: "Disconnected",
  AUTHENTICATION_FAILED: "Authentication failed",
  TOKEN_EXPIRED: "Token expired",
  CONNECTION_ERROR: "Connection error",
  DISABLED: "Disabled",
};

// Checkpoint 64.80-F2 Phase 8: SVG icon names from the single icon
// system, replacing Unicode glyphs. The CONFIGURED-vs-CONNECTED honesty
// distinction is preserved exactly: CONFIGURED still gets the "warning"
// (partial) marker and the pending badge, never CONNECTED's success one.
const STATUS_ICONS: Record<Status, IconName> = {
  NOT_CONFIGURED: "info",
  CONFIGURED: "warning",
  CONNECTING: "warning",
  CONNECTED: "success",
  DISCONNECTED: "info",
  AUTHENTICATION_FAILED: "error",
  TOKEN_EXPIRED: "error",
  CONNECTION_ERROR: "error",
  DISABLED: "info",
};

const STATUS_CLASS: Record<Status, string> = {
  NOT_CONFIGURED: "badge--historical",
  CONFIGURED: "badge--pending",
  CONNECTING: "badge--pending",
  CONNECTED: "badge--active",
  DISCONNECTED: "badge--historical",
  AUTHENTICATION_FAILED: "badge--danger",
  TOKEN_EXPIRED: "badge--danger",
  CONNECTION_ERROR: "badge--danger",
  DISABLED: "badge--historical",
};

export function ConnectionStatusBadge({ status }: { status: Status }): JSX.Element {
  return (
    <span className={`badge ${STATUS_CLASS[status]}`}>
      <Icon name={STATUS_ICONS[status]} /> {STATUS_LABELS[status]}
    </span>
  );
}
