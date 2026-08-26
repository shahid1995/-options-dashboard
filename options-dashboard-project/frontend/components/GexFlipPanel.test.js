import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import GexFlipPanel from "./GexFlipPanel";

function render(node) {
  return renderToStaticMarkup(node);
}

const mockFlip = {
  flips: [
    { timestamp: "2026-08-26T09:15:00", spot: 24230, flipStrike: 24200, flipConfidence: 0.85, numSignChanges: 1, status: "ESTIMATED" },
    { timestamp: "2026-08-26T09:18:00", spot: 24240, flipStrike: 24200, flipConfidence: 0.90, numSignChanges: 1, status: "ESTIMATED" },
  ],
  count: 2,
};

describe("GexFlipPanel", () => {
  it("renders with valid data", () => {
    const html = render(<GexFlipPanel data={mockFlip} />);
    expect(html).toContain("GAMMA FLIP");
    expect(html).toContain("SPOT");
    expect(html).toContain("FLIP STRIKE");
    expect(html).toContain("DISTANCE");
  });

  it("shows spot above flip", () => {
    const html = render(<GexFlipPanel data={mockFlip} />);
    expect(html).toContain("Spot is above the gamma flip");
  });

  it("shows spot below flip", () => {
    const belowFlip = {
      flips: [{ timestamp: "2026-08-26T09:15:00", spot: 24100, flipStrike: 24200, flipConfidence: 0.85, numSignChanges: 1, status: "ESTIMATED" }],
      count: 1,
    };
    const html = render(<GexFlipPanel data={belowFlip} />);
    expect(html).toContain("Spot is below the gamma flip");
  });

  it("renders empty state", () => {
    const html = render(<GexFlipPanel data={{ flips: [], count: 0 }} />);
    expect(html).toContain("No flip data available");
  });

  it("shows confidence and status", () => {
    const html = render(<GexFlipPanel data={mockFlip} />);
    expect(html).toContain("Confidence: 90%");
    expect(html).toContain("Status: ESTIMATED");
  });
});
