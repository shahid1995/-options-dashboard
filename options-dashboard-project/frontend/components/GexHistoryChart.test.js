import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import GexHistoryChart from "./GexHistoryChart";

function render(node) {
  return renderToStaticMarkup(node);
}

const mockHistory = {
  timestamps: [
    { timestamp: "2026-08-26T09:15:00", spot: 24200, callGex: 100000, putGex: -80000, netGex: 20000, absoluteGex: 20000, instrumentCount: 40, strikeCount: 20 },
    { timestamp: "2026-08-26T09:18:00", spot: 24210, callGex: 120000, putGex: -90000, netGex: 30000, absoluteGex: 30000, instrumentCount: 40, strikeCount: 20 },
    { timestamp: "2026-08-26T09:21:00", spot: 24190, callGex: 80000, putGex: -100000, netGex: -20000, absoluteGex: 20000, instrumentCount: 40, strikeCount: 20 },
  ],
  changes: [],
  accelerations: [],
  count: 3,
};

describe("GexHistoryChart", () => {
  it("renders with valid data", () => {
    const html = render(<GexHistoryChart data={mockHistory} />);
    expect(html).toContain("HISTORICAL NET GEX");
    expect(html).toContain("3 timestamps");
  });

  it("renders empty state", () => {
    const html = render(<GexHistoryChart data={{ timestamps: [], count: 0 }} />);
    expect(html).toContain("No historical GEX data available");
  });

  it("renders null data", () => {
    const html = render(<GexHistoryChart data={null} />);
    expect(html).toContain("No historical GEX data available");
  });

  it("contains chart elements", () => {
    const html = render(<GexHistoryChart data={mockHistory} />);
    expect(html).toContain("recharts");
  });
});
