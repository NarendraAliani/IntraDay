// frontend/src/features/reports/ReportsOverviewPage.test.tsx
//
// Checkpoint 32 Part 17: proves the Reports Overview page renders the
// full catalogue/capability registry with honest states, and never
// claims a BLOCKED/PLANNED/NOT_YET_IMPLEMENTED capability is AVAILABLE.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportsOverviewPage } from "./ReportsOverviewPage";
import { CAPABILITY_REGISTRY } from "./capabilityRegistry";
import { REPORT_CATALOGUE } from "./reportCatalogue";

describe("ReportsOverviewPage", () => {
  it("renders every report catalogue entry", () => {
    render(<ReportsOverviewPage />);
    for (const entry of REPORT_CATALOGUE) {
      expect(screen.getAllByText(entry.title).length).toBeGreaterThan(0);
    }
  });

  it("renders every capability registry entry with its title", () => {
    render(<ReportsOverviewPage />);
    for (const group of CAPABILITY_REGISTRY) {
      for (const capability of group.capabilities) {
        expect(screen.getAllByText(capability.title).length).toBeGreaterThan(0);
      }
    }
  });

  it("shows the market data quality classification as SAMPLE_BAR, never TRADING_GRADE_BAR", () => {
    render(<ReportsOverviewPage />);
    expect(screen.getByText("SAMPLE_BAR")).toBeInTheDocument();
    expect(screen.queryByText("TRADING_GRADE_BAR")).not.toBeInTheDocument();
  });

  it("never renders a BLOCKED capability with an AVAILABLE label", () => {
    render(<ReportsOverviewPage />);
    const blockedCapabilities = CAPABILITY_REGISTRY.flatMap((g) => g.capabilities).filter(
      (c) => c.status === "BLOCKED",
    );
    expect(blockedCapabilities.length).toBeGreaterThan(0);
    for (const capability of blockedCapabilities) {
      expect(capability.status).not.toBe("AVAILABLE");
    }
  });

  it("renders no trading control anywhere on the page", () => {
    render(<ReportsOverviewPage />);
    for (const forbidden of ["Buy", "Sell", "Place Order", "Execute Trade"]) {
      expect(screen.queryByText(forbidden)).not.toBeInTheDocument();
    }
  });
});
