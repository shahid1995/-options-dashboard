import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import IVAnalyticsPanel from "./IVAnalyticsPanel";

function makeChainCache() {
  return {
    "2026-09-18": {
      chain: [
        { strike: 24800, call: { ltp: 250, iv: 0.18 }, put: { ltp: 80, iv: 0.17 } },
        { strike: 25000, call: { ltp: 150, iv: 0.16 }, put: { ltp: 120, iv: 0.19 } },
        { strike: 25200, call: { ltp: 80, iv: 0.15 }, put: { ltp: 200, iv: 0.21 } },
      ],
      underlying_spot_price: 25000,
    },
  };
}

function render(props) {
  return renderToStaticMarkup(
    React.createElement(IVAnalyticsPanel, {
      chainCache: makeChainCache(),
      spot: 25000,
      expiry: "2026-09-18",
      isMobile: false,
      ...props,
    })
  );
}

describe("IVAnalyticsPanel — hierarchy & Phase D primitives", () => {
  it("renders the provenance legend with LIVE/DERIVED/HISTORY labels", () => {
    const html = render({});
    expect(html).toContain("LIVE");
    expect(html).toContain("DERIVED");
    expect(html).toContain("HISTORY");
    expect(html).toContain("broker/chain IV");
    expect(html).toContain("ATM average, skew, slope, session change");
  });

  it("shows ATM IV metrics (Call, Put, Average, Session Change)", () => {
    const html = render({});
    // Metric uses CSS textTransform:uppercase — DOM has mixed-case labels
    expect(html).toContain("ATM IV · Call");
    expect(html).toContain("ATM IV · Put");
    expect(html).toContain("ATM IV · Average");
    expect(html).toContain("IV change · session");
  });

  it("shows ATM skew metrics for both put and call sides", () => {
    const html = render({});
    expect(html).toContain("ATM SKEW · PUT");
    expect(html).toContain("ATM SKEW · CALL");
    expect(html).toContain("vol pts");
  });

  it("shows IV curve chart title with expiry", () => {
    const html = render({});
    expect(html).toContain("IV CURVE");
    expect(html).toContain("2026-09-18");
    expect(html).toContain("IV vs strike (call / put, separate lines)");
  });

  it("shows term structure chart title", () => {
    const html = render({});
    expect(html).toContain("IV TERM STRUCTURE");
    expect(html).toContain("ATM IV vs days to expiry");
  });

  it("preserves null values as unavailable (never zero)", () => {
    const html = render({ chainCache: {} });
    const dashCount = (html.match(/—/g) || []).length;
    expect(dashCount).toBeGreaterThan(0);
  });

  it("shows broker IV normalization caption", () => {
    const html = render({});
    expect(html).toContain("broker IV normalized to %");
  });
});
