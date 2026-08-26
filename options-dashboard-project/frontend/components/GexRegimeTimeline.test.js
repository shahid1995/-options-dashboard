import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import GexRegimeTimeline from "./GexRegimeTimeline";

function render(node) {
  return renderToStaticMarkup(node);
}

const mockRegime = {
  regimes: [
    { timestamp: "2026-08-26T09:15:00", spot: 24200, netGex: 50000, regime: "POSITIVE_GAMMA", regimeDuration: 1 },
    { timestamp: "2026-08-26T09:18:00", spot: 24210, netGex: 30000, regime: "POSITIVE_GAMMA", regimeDuration: 2 },
    { timestamp: "2026-08-26T09:21:00", spot: 24190, netGex: -20000, regime: "NEGATIVE_GAMMA", previousRegime: "POSITIVE_GAMMA", regimeTransition: "POSITIVE_GAMMA→NEGATIVE_GAMMA", regimeDuration: 1 },
  ],
  count: 3,
};

describe("GexRegimeTimeline", () => {
  it("renders with valid data", () => {
    const html = render(<GexRegimeTimeline data={mockRegime} />);
    expect(html).toContain("GAMMA REGIME TIMELINE");
    expect(html).toContain("Current: NEGATIVE GAMMA");
    expect(html).toContain("1 transitions");
  });

  it("renders empty state", () => {
    const html = render(<GexRegimeTimeline data={{ regimes: [], count: 0 }} />);
    expect(html).toContain("No regime data available");
  });

  it("renders null data", () => {
    const html = render(<GexRegimeTimeline data={null} />);
    expect(html).toContain("No regime data available");
  });

  it("shows regime legend", () => {
    const html = render(<GexRegimeTimeline data={mockRegime} />);
    expect(html).toContain("POSITIVE GAMMA");
    expect(html).toContain("NEGATIVE GAMMA");
    expect(html).toContain("NEUTRAL");
  });
});
