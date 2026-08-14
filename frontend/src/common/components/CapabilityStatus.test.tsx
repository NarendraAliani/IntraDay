// frontend/src/common/components/CapabilityStatus.test.tsx
//
// Checkpoint 32 Part 17: the shared placeholder component renders the
// right label per status and surfaces blocker/prerequisite text only
// when provided.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CapabilityStatus } from "./CapabilityStatus";

describe("CapabilityStatus", () => {
  it("renders the AVAILABLE label for an available capability", () => {
    render(
      <CapabilityStatus title="Backtesting" description="desc" status="AVAILABLE" />,
    );
    expect(screen.getByText(/Available/)).toBeInTheDocument();
  });

  it("renders the blocker text only for BLOCKED status", () => {
    render(
      <CapabilityStatus
        title="WebSocket Live Feed"
        description="desc"
        status="BLOCKED"
        blocker="No persistent process exists."
      />,
    );
    expect(screen.getByText(/Blocked/)).toBeInTheDocument();
    expect(screen.getByText(/No persistent process exists\./)).toBeInTheDocument();
  });

  it("does not render blocker text when status is not BLOCKED", () => {
    render(
      <CapabilityStatus
        title="Paper Trading"
        description="desc"
        status="PLANNED"
        blocker="should not show"
      />,
    );
    expect(screen.queryByText("should not show")).not.toBeInTheDocument();
  });

  it("renders prerequisite text when provided", () => {
    render(
      <CapabilityStatus
        title="Walk Forward"
        description="desc"
        status="PLANNED"
        prerequisite="A defined window protocol."
      />,
    );
    expect(screen.getByText(/A defined window protocol\./)).toBeInTheDocument();
  });
});
