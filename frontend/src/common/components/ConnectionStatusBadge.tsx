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

const STATUS_ICONS: Record<Status, string> = {
  NOT_CONFIGURED: "○",
  CONFIGURED: "◐",
  CONNECTING: "◐",
  CONNECTED: "●",
  DISCONNECTED: "○",
  AUTHENTICATION_FAILED: "✕",
  TOKEN_EXPIRED: "✕",
  CONNECTION_ERROR: "✕",
  DISABLED: "○",
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
      {STATUS_ICONS[status]} {STATUS_LABELS[status]}
    </span>
  );
}
