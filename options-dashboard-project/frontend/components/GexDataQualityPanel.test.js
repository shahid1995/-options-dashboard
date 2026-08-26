import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import GexDataQualityPanel from "./GexDataQualityPanel";

function render(node) {
  return renderToStaticMarkup(node);
}

const mockQuality = {
  generatedAt: "2026-08-26T10:00:00Z",
  classification: "GOOD",
  score: 94.2,
  totalOptionCandles: 514610,
  totalOptionGreeks: 514610,
  totalHistoricalGex: 507185,
  totalNiftyCandles: 57675,
  totalContractSpecs: 20584,
  timestampsTotal: 12262,
  timestampsWithGex: 12262,
};

describe("GexDataQualityPanel", () => {
  it("renders with valid data", () => {
    const html = render(<GexDataQualityPanel quality={mockQuality} />);
    expect(html).toContain("GEX DATA QUALITY");
    expect(html).toContain("GOOD");
    expect(html).toContain("94.2/100");
  });

  it("renders compact mode", () => {
    const html = render(<GexDataQualityPanel quality={mockQuality} compact />);
    expect(html).toContain("GOOD");
    expect(html).toContain("94.2/100");
  });

  it("renders null quality", () => {
    const html = render(<GexDataQualityPanel quality={null} />);
    expect(html).toContain("No data quality information available");
  });

  it("shows coverage percentage", () => {
    const html = render(<GexDataQualityPanel quality={mockQuality} />);
    // 507185 / 514610 = 98.6%
    expect(html).toContain("98.6% coverage");
  });

  it("shows timestamp coverage", () => {
    const html = render(<GexDataQualityPanel quality={mockQuality} />);
    // 12262 / 12262 = 100.0%
    expect(html).toContain("100.0% with GEX");
  });

  it("shows all metric labels", () => {
    const html = render(<GexDataQualityPanel quality={mockQuality} />);
    expect(html).toContain("HISTORICAL GEX");
    expect(html).toContain("OPTION CANDLES");
    expect(html).toContain("OPTION GREEKS");
    expect(html).toContain("NIFTY CANDLES");
    expect(html).toContain("TIMESTAMPS");
  });
});
