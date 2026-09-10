// frontend/src/common/components/Sparkline.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders a trend line from real close values", () => {
    render(<Sparkline closes={["100.0000", "105.0000", "110.0000"]} />);
    const svg = screen.getByRole("img", { hidden: true });
    expect(svg).toHaveClass("sparkline--up");
    expect(svg.querySelector("path")).not.toBeNull();
  });

  it("marks a falling series distinctly from a rising one", () => {
    render(<Sparkline closes={["110.0000", "105.0000", "100.0000"]} />);
    const svg = screen.getByRole("img", { hidden: true });
    expect(svg).toHaveClass("sparkline--down");
  });

  it("never fabricates a flat line for insufficient data - renders a plain dash instead", () => {
    render(<Sparkline closes={[]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByRole("img", { hidden: true })).not.toBeInTheDocument();
  });

  it("renders a dash for a single-point series too", () => {
    render(<Sparkline closes={["100.0000"]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
