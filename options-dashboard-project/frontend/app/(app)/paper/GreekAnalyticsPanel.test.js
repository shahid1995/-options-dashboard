import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import GreekAnalyticsPanel from "./GreekAnalyticsPanel";

// Minimal analytics payload
function makeAnalytics() {
  return {
    rows: [
      {
        legId: "l1",
        action: "buy",
        strike: 25000,
        type: "call",
        qty: 1,
        expiry: "2026-09-18",
        live: { delta: 0.55, gamma: 0.002, thetaPerDay: -12.5, vegaPerVolPoint: 8.3 },
        model: { delta: 0.58, gamma: 0.0021, thetaPerDay: -13.0, vegaPerVolPoint: 8.5 },
      },
    ],
    totals: {
      live: { delta: 0.55, gamma: 0.002, thetaPerDay: -12.5, vegaPerVolPoint: 8.3 },
      model: { delta: 0.58, gamma: 0.0021, thetaPerDay: -13.0, vegaPerVolPoint: 8.5 },
      difference: { delta: 0.03, gamma: 0.0001, thetaPerDay: -0.5, vegaPerVolPoint: 0.2 },
      status: {
        live: { delta: "available", gamma: "available", thetaPerDay: "available", vegaPerVolPoint: "available" },
        model: { delta: "available", gamma: "available", thetaPerDay: "available", vegaPerVolPoint: "available" },
      },
    },
    contributions: {
      delta: { entries: [{ legId: "l1", label: "BUY 25000 CE", value: 0.55, pct: 100 }], total: 0.55 },
      gamma: { entries: [{ legId: "l1", label: "BUY 25000 CE", value: 0.002, pct: 100 }], total: 0.002 },
      thetaPerDay: { entries: [{ legId: "l1", label: "BUY 25000 CE", value: -12.5, pct: 100 }], total: -12.5 },
      vegaPerVolPoint: { entries: [{ legId: "l1", label: "BUY 25000 CE", value: 8.3, pct: 100 }], total: 8.3 },
    },
    warnings: [],
  };
}

function render(props) {
  return renderToStaticMarkup(
    React.createElement(GreekAnalyticsPanel, {
      analytics: makeAnalytics(),
      isMobile: false,
      ...props,
    })
  );
}

describe("GreekAnalyticsPanel — hierarchy & Phase D primitives", () => {
  it("renders the unit contract legend with explicit LIVE/MODELLED/Δ MODEL labels", () => {
    const html = render({});
    expect(html).toContain("LIVE");
    expect(html).toContain("MODELLED");
    expect(html).toContain("Δ MODEL");
    expect(html).toContain("broker/chain Greeks");
    expect(html).toContain("Black-Scholes at the current state");
  });

  it("shows the strategy summary table with canonical Greek headers", () => {
    const html = render({});
    expect(html).toContain("GREEK");
    expect(html).toContain("Delta");
    expect(html).toContain("Gamma");
    expect(html).toContain("Theta/day");
    expect(html).toContain("Vega/1pt");
  });

  it("renders per-leg LIVE vs MODELLED comparison table", () => {
    const html = render({});
    expect(html).toContain("Δ (L / M)");
    expect(html).toContain("Γ (L / M)");
    expect(html).toContain("Θ/day (L / M)");
    expect(html).toContain("V/1pt (L / M)");
    expect(html).toContain("L = LIVE (broker chain)");
    expect(html).toContain("M = MODELLED (Black-Scholes)");
  });

  it("shows the Greek Contributors section with segmented control", () => {
    const html = render({});
    expect(html).toContain("GREEK CONTRIBUTORS");
    expect(html).toContain("which leg drives the strategy");
    expect(html).toContain("Strategy total");
    expect(html).toContain("Contribution % = leg value ÷ signed strategy total × 100");
  });

  it("preserves null values as unavailable (never zero)", () => {
    const analytics = makeAnalytics();
    analytics.totals.live.delta = null;
    analytics.totals.model.delta = null;
    analytics.totals.difference.delta = null;
    analytics.totals.status.live.delta = "unavailable";
    analytics.totals.status.model.delta = "unavailable";
    const html = render({ analytics });
    const dashCount = (html.match(/—/g) || []).length;
    expect(dashCount).toBeGreaterThan(0);
  });

  it("shows status notes for partial/unavailable values", () => {
    const analytics = makeAnalytics();
    analytics.totals.status.live.gamma = "partial";
    analytics.totals.status.model.thetaPerDay = "unavailable";
    const html = render({ analytics });
    expect(html).toContain("partial");
    expect(html).toContain("unavailable");
  });

  it("renders warnings from the calculation layer", () => {
    const analytics = makeAnalytics();
    analytics.warnings = [{ code: "W001", message: "Test warning" }];
    const html = render({ analytics });
    expect(html).toContain("W001");
    expect(html).toContain("Test warning");
  });
});
