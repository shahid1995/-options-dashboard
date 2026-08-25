/**
 * GEX Profile Chart — Component tests.
 *
 * Uses the project's existing testing convention:
 *   react-dom/server renderToStaticMarkup → string assertions.
 *
 * Tests:
 *   - Renders with valid GEX data
 *   - Positive/negative GEX bar representation
 *   - Zero-GEX reference line
 *   - ATM strike display
 *   - Gamma flip display when available
 *   - Gamma walls display when available
 *   - Empty / missing data states
 *   - Does not crash on null inputs
 *   - Profile label display
 */

import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import GexProfileChart from "../components/GexProfileChart";

/* ── Helpers ────────────────────────────────────────────────────────── */

function render(node) {
  return renderToStaticMarkup(node);
}

const baseAnalytics = {
  current: {
    netGex: 25_000_000,
    callGex: 60_000_000,
    putGex: -35_000_000,
    spot: 25500,
    expiry: "2026-08-28",
  },
  profileLabel: {
    labels: ["POSITIVE_DOMINANT"],
  },
  concentration: { top3Pct: 72 },
  status: "available",
};

const baseSnapshot = {
  spot: 25500,
  expiry: "2026-08-28",
  netGex: 25_000_000,
  callGex: 60_000_000,
  putGex: -35_000_000,
  strikeData: [
    { strike: 25400, callGex: 15_000_000, putGex: -12_000_000, netGex: 3_000_000 },
    { strike: 25500, callGex: 25_000_000, putGex: -18_000_000, netGex: 7_000_000 },
    { strike: 25600, callGex: 20_000_000, putGex: -5_000_000, netGex: 15_000_000 },
  ],
};

const snapshotWithSweep = {
  ...baseSnapshot,
  sweepData: {
    gammaFlipSpot: 25480,
    gammaFlipDistancePct: 0.08,
    gammaFlipDirection: "below",
    callWallStrikes: [25700],
    putWallStrikes: [25200],
    sweepStatus: "available",
  },
};

/* ── Tests ──────────────────────────────────────────────────────────── */

describe("GexProfileChart", () => {
  it("renders with valid GEX data", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).toContain("GEX PROFILE");
    expect(html).toContain("25,500");
    // Summary metrics should render
    expect(html).toContain("NET GEX");
    expect(html).toContain("CALL GEX");
    expect(html).toContain("PUT GEX");
    // Recharts container should be present
    expect(html).toContain("recharts-responsive-container");
    // Legend should render
    expect(html).toContain("Call GEX (+)");
    expect(html).toContain("Put GEX (−)");
  });

  it("displays summary metrics: Net GEX, Call GEX, Put GEX, ATM", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).toContain("NET GEX");
    expect(html).toContain("CALL GEX");
    expect(html).toContain("PUT GEX");
    expect(html).toContain("ATM");
    // ATM strike value should appear
    expect(html).toContain("25,500");
  });

  it("displays the profile regime label", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).toContain("REGIME");
    expect(html).toContain("POSITIVE DOMINANT");
  });

  it("displays expiry and spot in the header", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).toContain("2026-08-28");
    expect(html).toContain("25,500");
  });

  it("shows gamma flip when sweepData is available", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={snapshotWithSweep}
        atmStrike={25500}
      />
    );
    expect(html).toContain("GAMMA FLIP");
    expect(html).toContain("25,480");
    expect(html).toContain("Gamma Flip");
  });

  it("shows call wall when sweepData is available", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={snapshotWithSweep}
        atmStrike={25500}
      />
    );
    expect(html).toContain("CALL WALL");
    expect(html).toContain("25,700");
  });

  it("shows put wall when sweepData is available", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={snapshotWithSweep}
        atmStrike={25500}
      />
    );
    expect(html).toContain("PUT WALL");
    expect(html).toContain("25,200");
  });

  it("renders empty state when no strikeData", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={{ ...baseSnapshot, strikeData: [] }}
        atmStrike={25500}
      />
    );
    expect(html).toContain("GEX data unavailable");
    expect(html).toContain("GEX PROFILE");
  });

  it("does not crash when analytics is null", () => {
    const html = render(
      <GexProfileChart
        analytics={null}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).toContain("GEX PROFILE");
  });

  it("does not crash when latestSnapshot is null", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={null}
        atmStrike={25500}
      />
    );
    // Should render empty state since no strikeData
    expect(html).toContain("GEX data unavailable");
  });

  it("does not crash when both props are null", () => {
    const html = render(
      <GexProfileChart
        analytics={null}
        latestSnapshot={null}
        atmStrike={null}
      />
    );
    expect(html).toContain("GEX data unavailable");
  });

  it("does not render gamma flip when sweepData is absent", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).not.toContain("GAMMA FLIP");
    expect(html).not.toContain("Gamma Flip");
  });

  it("does not render walls when sweepData is absent", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).not.toContain("CALL WALL");
    expect(html).not.toContain("PUT WALL");
  });

  it("handles snapshot with only positive net GEX", () => {
    const snap = {
      ...baseSnapshot,
      strikeData: [
        { strike: 25500, callGex: 10_000_000, putGex: -2_000_000, netGex: 8_000_000 },
      ],
    };
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={snap}
        atmStrike={25500}
      />
    );
    expect(html).toContain("NET GEX");
    // Recharts container renders (chart content is client-side only)
    expect(html).toContain("recharts-responsive-container");
  });

  it("handles snapshot with only negative net GEX", () => {
    const snap = {
      ...baseSnapshot,
      strikeData: [
        { strike: 25500, callGex: 2_000_000, putGex: -10_000_000, netGex: -8_000_000 },
      ],
    };
    const html = render(
      <GexProfileChart
        analytics={{
          ...baseAnalytics,
          current: { ...baseAnalytics.current, netGex: -8_000_000 },
        }}
        latestSnapshot={snap}
        atmStrike={25500}
      />
    );
    expect(html).toContain("NET GEX");
  });

  it("filters out strikes with all-null GEX values and renders the chart", () => {
    const snap = {
      ...baseSnapshot,
      strikeData: [
        { strike: 25500, callGex: 10_000_000, putGex: -5_000_000, netGex: 5_000_000 },
        { strike: 25600, callGex: null, putGex: null, netGex: null },
      ],
    };
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={snap}
        atmStrike={25500}
      />
    );
    // Chart container and summary metrics should render
    expect(html).toContain("recharts-responsive-container");
    expect(html).toContain("NET GEX");
    expect(html).toContain("ATM");
  });

  it("renders legend with call and put indicators", () => {
    const html = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).toContain("Call GEX (+)");
    expect(html).toContain("Put GEX (−)");
  });

  it("mobile layout reduces chart height", () => {
    const htmlMobile = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
        isMobile={true}
      />
    );
    const htmlDesktop = render(
      <GexProfileChart
        analytics={baseAnalytics}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
        isMobile={false}
      />
    );
    // Mobile should have height 320, desktop 380
    expect(htmlMobile).toContain("height:320px");
    expect(htmlDesktop).toContain("height:380px");
  });

  it("handles missing analytics fields gracefully", () => {
    const html = render(
      <GexProfileChart
        analytics={{
          current: { netGex: null, callGex: null, putGex: null },
          profileLabel: { labels: [] },
        }}
        latestSnapshot={baseSnapshot}
        atmStrike={25500}
      />
    );
    expect(html).toContain("GEX PROFILE");
    // Should show dashes for null values
    expect(html).toContain("NET GEX");
  });
});
