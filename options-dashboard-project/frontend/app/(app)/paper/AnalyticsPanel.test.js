import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import AnalyticsPanel from "./AnalyticsPanel";

function makeChainCache() {
  return {
    "2026-09-18": {
      chain: [
        { strike: 25000, call: { ltp: 150, iv: 0.16, delta: 0.55, gamma: 0.002, theta: -12.5, vega: 8.3 }, put: { ltp: 120, iv: 0.19, delta: -0.45, gamma: 0.0021, theta: -11.0, vega: 7.8 } },
      ],
      underlying_spot_price: 25000,
    },
  };
}

function render(props) {
  return renderToStaticMarkup(
    React.createElement(AnalyticsPanel, {
      chainCache: makeChainCache(),
      spot: 25000,
      expiry: "2026-09-18",
      symbol: "NIFTY",
      isMobile: false,
      ...props,
    })
  );
}

describe("AnalyticsPanel — hierarchy & Phase D primitives", () => {
  it("renders the provenance legend with LIVE/DERIVED/STATISTICS labels", () => {
    const html = render({});
    expect(html).toContain("LIVE");
    expect(html).toContain("DERIVED");
    expect(html).toContain("STATISTICS");
    expect(html).toContain("broker/chain data");
  });

  it("shows the CURRENT OBSERVATION — CE vs PE table", () => {
    const html = render({});
    expect(html).toContain("CURRENT OBSERVATION");
    expect(html).toContain("CE vs PE");
    expect(html).toContain("Higher side");
  });

  it("shows the PRICE / IV RELATIONSHIP section", () => {
    const html = render({});
    expect(html).toContain("PRICE / IV RELATIONSHIP");
    // Labels use inline textTransform:uppercase
    expect(html).toContain("PRICE CHANGE");
    expect(html).toContain("IV CHANGE");
    expect(html).toContain("PRICE DIRECTION");
    expect(html).toContain("IV DIRECTION");
  });

  it("shows the STATISTICS section with unavailable message", () => {
    const html = render({});
    expect(html).toContain("STATISTICS");
    expect(html).toContain("unavailable until a reliable historical sample exists");
  });

  it("shows the VIX section as unavailable", () => {
    const html = render({});
    expect(html).toContain("VIX");
    expect(html).toContain("unavailable");
    expect(html).toContain("ATM / index / average IV is never substituted for VIX");
  });

  it("shows the expandable IV detail button", () => {
    const html = render({});
    // The button text (collapsed state)
    expect(html).toContain("IV detail");
    expect(html).toContain("current");
    expect(html).toContain("previous");
    expect(html).toContain("rolling stats");
  });

  it("preserves null values as unavailable (never zero)", () => {
    const html = render({ chainCache: {} });
    expect(html).toContain("Load a chain for");
  });

  it("shows the neutral analytics disclaimer", () => {
    const html = render({});
    expect(html).toContain("Analytics only — measurements and relationships, no buy/sell advice");
  });
});
