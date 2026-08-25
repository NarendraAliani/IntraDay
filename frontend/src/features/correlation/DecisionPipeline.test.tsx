// frontend/src/features/correlation/DecisionPipeline.test.tsx
//
// Checkpoint 64.80-F3 Phase 13: component tests for the Decision
// Pipeline. The REAL component tree, the REAL icon system, the REAL
// theme provider and the REAL audited model are exercised - there is no
// mock model, because a mocked correlation model would defeat the entire
// point of this checkpoint.
//
// Covered here: the pipeline renders; each correlation state renders
// correctly and legibly; no false correlation is displayed; theme
// switching preserves the pipeline; icons come from the common icon
// system; keyboard navigation reaches every destination; the stacked
// layout stays readable; navigation destinations fire; and the safety
// negatives (no Gainz control, no live-execution control, no NSE_FNO /
// OI / IV / Greeks surface) hold.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThemeProvider } from "../../app/theme/ThemeProvider";
import { THEME_STORAGE_KEY } from "../../app/theme/themeStorage";
import { DecisionPipeline } from "./DecisionPipeline";
import {
  ALL_AUDITED_LINKS,
  PIPELINE_NODES,
  STATUS_MEANING,
  nodeLabel,
} from "./correlationModel";
import type {
  CorrelationLink,
  CorrelationStatus,
  PipelineDestination,
} from "./correlationModel";

function renderPipeline(onNavigate?: (destination: PipelineDestination) => void) {
  return render(
    <ThemeProvider>
      <DecisionPipeline onNavigate={onNavigate} />
    </ThemeProvider>,
  );
}

/** Locates the rendered card for one audited link by its "Source to
 * Target" pair label, which is unique across the model. */
function linkCard(link: CorrelationLink): HTMLElement {
  const pair = `${nodeLabel(link.source)} to ${nodeLabel(link.target)}`;
  // Scoped to `.pipeline-link__pair` deliberately: a plain text search
  // for "Market Data to Outcome" also matches the SECTION HEADING, and
  // silently returning the heading here would make these assertions
  // test nothing.
  const label = [...document.querySelectorAll(".pipeline-link__pair")].find(
    (element) => element.textContent?.trim() === pair,
  );
  expect(label, `link card for ${link.id}`).toBeDefined();
  const card = label?.closest(".pipeline-link");
  expect(card, `link card for ${link.id}`).not.toBeNull();
  return card as HTMLElement;
}

/** Exact accessible-name matcher. Deliberately NOT a RegExp:
 * `destinationLabel` values contain regex operators - "Open Reports
 * (Signal Report)" would be read as a capture group and match the wrong
 * thing (or nothing at all). Testing Library accepts a predicate, which
 * sidesteps escaping entirely. */
function byLabel(label: string | null): (accessibleName: string) => boolean {
  const expected = (label ?? "").replace(/\s+/g, " ").trim();
  return (accessibleName: string) =>
    accessibleName.replace(/\s+/g, " ").trim() === expected;
}

function firstLinkWithStatus(status: CorrelationStatus): CorrelationLink {
  const link = ALL_AUDITED_LINKS.find((entry) => entry.status === status);
  expect(link, `the audit must include a ${status} link to exercise`).toBeDefined();
  return link as CorrelationLink;
}

describe("Decision Pipeline - it renders", () => {
  it("renders the pipeline with its heading", () => {
    renderPipeline();
    expect(
      screen.getByRole("heading", { name: /Market Data to Outcome/i }),
    ).toBeInTheDocument();
  });

  it("renders all seven stages, in order, as a semantic ordered list", () => {
    const { container } = renderPipeline();
    const list = container.querySelector(".pipeline__chain");
    expect(list?.tagName).toBe("OL");
    const stages = container.querySelectorAll(".pipeline__stage");
    expect(stages).toHaveLength(PIPELINE_NODES.length);
    for (const [index, node] of PIPELINE_NODES.entries()) {
      expect(stages[index].textContent).toContain(node.label);
      expect(stages[index].textContent).toContain(`Stage ${index + 1}`);
    }
  });

  it("renders every stage as a heading with its own accessible name", () => {
    renderPipeline();
    for (const node of PIPELINE_NODES) {
      expect(
        screen.getAllByRole("heading", { name: new RegExp(node.label, "i") }).length,
      ).toBeGreaterThan(0);
    }
  });

  it("names the real endpoint(s) behind every stage", () => {
    renderPipeline();
    for (const node of PIPELINE_NODES) {
      for (const api of node.apis) {
        // Rendered verbatim, HTTP verb included, so the reader can see
        // it is a read-only GET and nothing else.
        expect(screen.getAllByText(api).length).toBeGreaterThan(0);
        expect(api.startsWith("GET ")).toBe(true);
      }
    }
  });
});

// ---------------------------------------------------------------------
// One test per correlation state (Phase 13's explicit list).
// ---------------------------------------------------------------------

describe("Decision Pipeline - each correlation state renders correctly", () => {
  it("a FOUND relationship renders its status word, its explanation and its evidence", () => {
    renderPipeline();
    const link = firstLinkWithStatus("FOUND");
    const card = linkCard(link);
    expect(within(card).getByText("FOUND")).toBeInTheDocument();
    expect(card.textContent).toContain(link.relationship);
    expect(card.textContent).toContain("API evidence:");
    expect(card.dataset.status).toBe("FOUND");
  });

  it("a PARTIAL relationship renders as PARTIAL and states what is missing", () => {
    renderPipeline();
    const link = firstLinkWithStatus("PARTIAL");
    const card = linkCard(link);
    expect(within(card).getByText("PARTIAL")).toBeInTheDocument();
    expect(card.textContent).toContain("Gap:");
    expect(card.textContent).not.toContain("FOUND");
  });

  it("a NOT AVAILABLE relationship renders honestly rather than as a working link", () => {
    renderPipeline();
    const link = firstLinkWithStatus("NOT AVAILABLE");
    const card = linkCard(link);
    expect(within(card).getByText("NOT AVAILABLE")).toBeInTheDocument();
    expect(card.textContent).toContain("Gap:");
  });

  it("a NOT FOUND relationship renders as NOT FOUND", () => {
    renderPipeline();
    const link = firstLinkWithStatus("NOT FOUND");
    const card = linkCard(link);
    expect(within(card).getByText("NOT FOUND")).toBeInTheDocument();
    expect(card.textContent).toContain(link.relationship);
  });

  it("a NOT APPLICABLE relationship explains why there is nothing to expose", () => {
    renderPipeline();
    const link = firstLinkWithStatus("NOT APPLICABLE");
    const card = linkCard(link);
    expect(within(card).getByText("NOT APPLICABLE")).toBeInTheDocument();
    expect(card.textContent).toContain("no conditions");
  });

  it("a NOT YET IMPLEMENTED relationship renders as future scope", () => {
    renderPipeline();
    const link = firstLinkWithStatus("NOT YET IMPLEMENTED");
    const card = linkCard(link);
    expect(within(card).getByText("NOT YET IMPLEMENTED")).toBeInTheDocument();
  });

  it("renders a legend defining every status word in the vocabulary", () => {
    renderPipeline();
    for (const [status, meaning] of Object.entries(STATUS_MEANING)) {
      expect(screen.getAllByText(status).length).toBeGreaterThan(0);
      expect(screen.getByText(meaning)).toBeInTheDocument();
    }
  });

  it("states explicitly that a FOUND status is not a claim of causation", () => {
    renderPipeline();
    expect(
      screen.getByText(/does not claim the upstream stage caused the downstream outcome/i),
    ).toBeInTheDocument();
  });

  it("renders every audited link exactly once", () => {
    const { container } = renderPipeline();
    expect(container.querySelectorAll(".pipeline-link")).toHaveLength(
      ALL_AUDITED_LINKS.length,
    );
  });
});

// ---------------------------------------------------------------------
// No false correlation.
// ---------------------------------------------------------------------

describe("Decision Pipeline - no false correlation is displayed", () => {
  it("draws no edge that is not in the audited model", () => {
    const { container } = renderPipeline();
    const renderedPairs = [...container.querySelectorAll(".pipeline-link__pair")].map(
      (element) => element.textContent?.trim(),
    );
    const auditedPairs = ALL_AUDITED_LINKS.map(
      (link) => `${nodeLabel(link.source)} to ${nodeLabel(link.target)}`,
    );
    expect(renderedPairs.sort()).toEqual(auditedPairs.sort());
  });

  it("never shows a status word that the model did not assign to that link", () => {
    renderPipeline();
    for (const link of ALL_AUDITED_LINKS) {
      const card = linkCard(link);
      const badges = [...card.querySelectorAll(".badge")].map((b) => b.textContent?.trim());
      expect(badges).toEqual([link.status]);
    }
  });

  it("shows no Gainz control of any kind", () => {
    const { container } = renderPipeline();
    expect(container.textContent).not.toMatch(/gainz/i);
    expect(
      screen.queryByRole("button", { name: /enable|activate|deploy|go live/i }),
    ).toBeNull();
  });

  it("shows no live-trading or live-execution stage", () => {
    const { container } = renderPipeline();
    expect(container.textContent).not.toMatch(/live execution/i);
    expect(container.textContent).not.toMatch(/place (a )?live order/i);
  });

  it("introduces no NSE_FNO, option, OI, IV or Greeks surface", () => {
    const { container } = renderPipeline();
    const text = container.textContent ?? "";
    for (const term of [
      "NSE_FNO",
      "OptionQuote",
      "OptionChain",
      "OptionBar",
      "open interest",
      "implied volatility",
      "greeks",
    ]) {
      expect(new RegExp(term, "i").test(text), `${term} must not appear`).toBe(false);
    }
  });

  it("states plainly that the equity feature registry is what is shown", () => {
    renderPipeline();
    expect(screen.getByText(/no options fields exist in this registry/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------
// Icons, themes, accessibility, navigation, responsiveness.
// ---------------------------------------------------------------------

describe("Decision Pipeline - iconography", () => {
  it("renders icons through the common icon system, with the shared grammar", () => {
    const { container } = renderPipeline();
    const icons = container.querySelectorAll("svg.icon");
    expect(icons.length).toBeGreaterThan(PIPELINE_NODES.length);
    for (const icon of icons) {
      expect(icon.getAttribute("viewBox")).toBe("0 0 24 24");
      expect(icon.getAttribute("stroke")).toBe("currentColor");
    }
  });

  it("uses no Unicode glyph or emoji as a status marker", () => {
    const { container } = renderPipeline();
    expect(container.textContent ?? "").not.toMatch(/[●○✓✗⚠→]/u);
  });

  it("hides decorative icons and the connector rule from assistive technology", () => {
    const { container } = renderPipeline();
    for (const icon of container.querySelectorAll("svg.icon")) {
      expect(icon.getAttribute("aria-hidden")).toBe("true");
    }
    for (const rule of container.querySelectorAll(".pipeline__connector-rule")) {
      expect(rule.getAttribute("aria-hidden")).toBe("true");
    }
  });
});

describe("Decision Pipeline - theme switching preserves the pipeline", () => {
  it("renders identically under every theme", async () => {
    const themes = ["focus", "midnight", "obsidian", "aurora"];
    let baseline: number | null = null;
    for (const theme of themes) {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
      const { container, unmount } = renderPipeline();
      const links = container.querySelectorAll(".pipeline-link").length;
      const stages = container.querySelectorAll(".pipeline__stage").length;
      expect(stages).toBe(PIPELINE_NODES.length);
      expect(links).toBe(ALL_AUDITED_LINKS.length);
      if (baseline === null) baseline = links;
      expect(links).toBe(baseline);
      // Status words survive the theme change - state is never carried
      // by colour alone.
      expect(container.textContent).toContain("FOUND");
      expect(container.textContent).toContain("PARTIAL");
      unmount();
    }
    window.localStorage.clear();
  });
});

describe("Decision Pipeline - accessibility", () => {
  it("states every relationship as a full sentence, not as an arrow", () => {
    renderPipeline();
    for (const link of ALL_AUDITED_LINKS) {
      expect(screen.getByText(link.relationship)).toBeInTheDocument();
    }
  });

  it("carries the sequence in the markup, so order does not depend on visual position", () => {
    const { container } = renderPipeline();
    const stages = [...container.querySelectorAll(".pipeline__stage")];
    const labels = stages.map(
      (stage) => stage.querySelector(".pipeline-node__title")?.textContent?.trim(),
    );
    expect(labels).toEqual(PIPELINE_NODES.map((node) => node.label));
  });

  it("gives the pipeline region an accessible name", () => {
    renderPipeline();
    expect(
      screen.getByRole("region", { name: /Market Data to Outcome/i }),
    ).toBeInTheDocument();
  });

  it("exposes every navigation destination as a real, focusable button", () => {
    renderPipeline(vi.fn());
    const navigable = PIPELINE_NODES.filter((node) => node.destination !== null);
    const buttons = navigable.map(
      (node) =>
        screen.getAllByRole("button", { name: byLabel(node.destinationLabel) })[0] as HTMLButtonElement,
    );
    expect(buttons).toHaveLength(navigable.length);
    for (const button of buttons) {
      // A real <button> is keyboard-reachable in document order and is
      // never removed from the tab sequence.
      expect(button.tagName).toBe("BUTTON");
      expect(button.getAttribute("type")).toBe("button");
      expect(button.hasAttribute("disabled")).toBe(false);
      expect(button.getAttribute("tabindex")).not.toBe("-1");
      button.focus();
      expect(document.activeElement).toBe(button);
    }
  });

  it("activates a destination from the keyboard", () => {
    const onNavigate = vi.fn();
    renderPipeline(onNavigate);
    const button = screen.getAllByRole("button", { name: /Go to Market Data/i })[0];
    button.focus();
    expect(document.activeElement).toBe(button);
    // jsdom does not synthesise the implicit click a <button> fires on
    // Enter/Space, so the keypress and the resulting activation are
    // asserted explicitly - the point being that no key handler of our
    // own is needed, because this is a native button.
    fireEvent.keyDown(button, { key: "Enter", code: "Enter" });
    fireEvent.click(button);
    expect(onNavigate).toHaveBeenCalledWith("market-data");
  });
});

describe("Decision Pipeline - drill-down navigation", () => {
  it("navigates to each existing screen a node points at", () => {
    const onNavigate = vi.fn();
    renderPipeline(onNavigate);
    for (const node of PIPELINE_NODES.filter((entry) => entry.destination !== null)) {
      onNavigate.mockClear();
      fireEvent.click(
        screen.getAllByRole("button", { name: byLabel(node.destinationLabel) })[0],
      );
      expect(onNavigate).toHaveBeenCalledWith(node.destination);
    }
  });

  it("renders no navigation control at all when no navigation handler is supplied", () => {
    renderPipeline();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("Decision Pipeline - responsive / stacked layout", () => {
  it("uses one markup tree for both layouts, so nothing is duplicated when stacked", () => {
    const { container } = renderPipeline();
    // Exactly one chain, and every stage carries its own connector
    // container rather than a separate mobile-only rendering.
    expect(container.querySelectorAll(".pipeline__chain")).toHaveLength(1);
    const connectors = container.querySelectorAll(".pipeline__connector");
    expect(connectors).toHaveLength(PIPELINE_NODES.length - 1);
  });

  it("keeps every relationship readable as text when connectors stack", () => {
    const { container } = renderPipeline();
    for (const connector of container.querySelectorAll(".pipeline__connector")) {
      // The rule is decorative; the status word and the sentence are
      // always present in the same connector block, so a stacked layout
      // never leaves a line without its label.
      expect(connector.querySelector(".pipeline-link__relationship")).not.toBeNull();
      expect(connector.querySelector(".badge")).not.toBeNull();
    }
  });
});
