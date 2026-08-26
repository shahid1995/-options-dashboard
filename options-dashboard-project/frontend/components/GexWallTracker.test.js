import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import GexWallTracker from "./GexWallTracker";

function render(node) {
  return renderToStaticMarkup(node);
}

const mockWalls = {
  walls: [
    {
      timestamp: "2026-08-26T09:15:00",
      spot: 24230,
      strongestPositive: { strike: 24500, gex: 5000000, absoluteGex: 5000000, distanceFromSpot: 270, distancePct: 0.01114, wallType: "POSITIVE", rank: 1 },
      strongestNegative: { strike: 24000, gex: -3000000, absoluteGex: 3000000, distanceFromSpot: 230, distancePct: 0.00949, wallType: "NEGATIVE", rank: 1 },
      positiveWalls: [
        { strike: 24500, gex: 5000000, absoluteGex: 5000000, distanceFromSpot: 270, distancePct: 0.01114, wallType: "POSITIVE", rank: 1 },
        { strike: 24600, gex: 3000000, absoluteGex: 3000000, distanceFromSpot: 370, distancePct: 0.01527, wallType: "POSITIVE", rank: 2 },
      ],
      negativeWalls: [
        { strike: 24000, gex: -3000000, absoluteGex: 3000000, distanceFromSpot: 230, distancePct: 0.00949, wallType: "NEGATIVE", rank: 1 },
        { strike: 23900, gex: -2000000, absoluteGex: 2000000, distanceFromSpot: 330, distancePct: 0.01362, wallType: "NEGATIVE", rank: 2 },
      ],
    },
  ],
  count: 1,
};

describe("GexWallTracker", () => {
  it("renders with valid data", () => {
    const html = render(<GexWallTracker data={mockWalls} />);
    expect(html).toContain("GAMMA WALLS");
    expect(html).toContain("CALL GAMMA WALL");
    expect(html).toContain("PUT GAMMA WALL");
    expect(html).toContain("24,500");
    expect(html).toContain("24,000");
  });

  it("shows spot price", () => {
    const html = render(<GexWallTracker data={mockWalls} />);
    expect(html).toContain("24,230");
  });

  it("shows all walls list", () => {
    const html = render(<GexWallTracker data={mockWalls} />);
    expect(html).toContain("ALL WALLS");
    expect(html).toContain("CALL 24,600");
    expect(html).toContain("PUT 23,900");
  });

  it("renders empty state", () => {
    const html = render(<GexWallTracker data={{ walls: [], count: 0 }} />);
    expect(html).toContain("No wall data available");
  });

  it("renders null data", () => {
    const html = render(<GexWallTracker data={null} />);
    expect(html).toContain("No wall data available");
  });
});
