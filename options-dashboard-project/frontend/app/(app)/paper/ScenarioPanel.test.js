import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ScenarioPanel from "./ScenarioPanel";

function makeScenarioResult() {
  return {
    spot: 25000,
    strategyValue: 1250.5,
    scenarioPnl: 250.75,
    scenarioChange: -50.25,
    partial: false,
    scenario: { spotPct: 0, ivShift: 0, timeShiftDays: 0 },
    legs: [
      {
        leg: { id: "l1", action: "buy", strike: 25000, type: "call", qty: 1, expiry: "2026-09-18", strikeMode: "fixed", expiryMode: "fixed" },
        currentLtp: 120,
        scenarioValue: 130,
        modelVsMarket: 10,
        pnlVsEntry: 50,
        pnlChangeVsCurrent: -30,
        delta: 0.55,
        gamma: 0.002,
        theta: -12.5,
        vega: 8.3,
        scenarioIv: 0.18,
        scenarioT: 0.25,
      },
    ],
    warnings: [],
  };
}

function makeMatrix() {
  return {
    axis: "spotIv",
    rows: [-0.01, 0, 0.01],
    columns: [-0.02, 0, 0.02],
    cells: [
      [{ scenarioPnl: -100 }, { scenarioPnl: 0 }, { scenarioPnl: 150 }],
      [{ scenarioPnl: -50 }, { scenarioPnl: 50 }, { scenarioPnl: 200 }],
      [{ scenarioPnl: 0 }, { scenarioPnl: 100 }, { scenarioPnl: 250 }],
    ],
  };
}

function render(props) {
  return renderToStaticMarkup(
    React.createElement(ScenarioPanel, {
      result: makeScenarioResult(),
      matrix: makeMatrix(),
      axis: "spotIv",
      onAxisChange: () => {},
      spotPct: 0,
      onSpotPct: () => {},
      ivShift: 0,
      onIvShift: () => {},
      timeDays: 0,
      onTimeDays: () => {},
      rate: 0,
      onRate: () => {},
      div: 0,
      onDiv: () => {},
      onReset: () => {},
      isMobile: false,
      ...props,
    })
  );
}

describe("ScenarioPanel — hierarchy & Phase D primitives", () => {
  it("renders a null result as an unavailable prompt (never substitutes zero)", () => {
    const html = renderToStaticMarkup(
      React.createElement(ScenarioPanel, {
        result: null,
        matrix: null,
        axis: "spotIv",
        onAxisChange: () => {},
        spotPct: 0,
        onSpotPct: () => {},
        ivShift: 0,
        onIvShift: () => {},
        timeDays: 0,
        onTimeDays: () => {},
        rate: 0,
        onRate: () => {},
        div: 0,
        onDiv: () => {},
        onReset: () => {},
        isMobile: false,
      })
    );
    expect(html).toContain("Add legs to run scenario analysis");
  });

  it("shows the scenario summary labels using Metric (textTransform:uppercase in CSS)", () => {
    const html = render({});
    // Metric uses CSS textTransform:uppercase — DOM has mixed-case labels
    expect(html).toContain("Scenario Spot");
    expect(html).toContain("Scenario IV");
    expect(html).toContain("Strategy Value");
    // & is encoded as &amp; in renderToStaticMarkup
    expect(html).toContain("P&amp;L vs Entry");
    expect(html).toContain("Change vs Current");
  });

  it("renders the LIVE vs MODELLED Greeks comparison with canonical headers", () => {
    const html = render({});
    expect(html).toContain("GREEKS — LIVE vs MODELLED");
    expect(html).toContain("LIVE");
    expect(html).toContain("MODELLED");
    expect(html).toContain("Δ MODEL");
    expect(html).toContain("Theta per calendar day");
    expect(html).toContain("Vega per 1 vol point");
  });

  it("preserves null values as unavailable (never zero)", () => {
    const result = makeScenarioResult();
    result.legs[0].delta = null;
    result.legs[0].gamma = null;
    result.legs[0].theta = null;
    result.legs[0].vega = null;
    const html = render({ result });
    const dashCount = (html.match(/—/g) || []).length;
    expect(dashCount).toBeGreaterThan(0);
    expect(html).not.toContain("0.0000");
  });

  it("keeps the heatmap axis labels neutral and explicit", () => {
    const html = render({});
    expect(html).toContain("SCENARIO P&amp;L HEATMAP");
    expect(html).toContain("Spot × IV");
    expect(html).toContain("Spot × Time");
    expect(html).toContain("IV × Time");
  });

  it("shows per-leg LIVE vs MODELLED table with explicit unit disambiguation", () => {
    const html = render({});
    expect(html).toContain("Live LTP");
    expect(html).toContain("Model Value");
    expect(html).toContain("per-leg model values in raw model units");
    expect(html).toContain("theta per YEAR");
    expect(html).toContain("vega per 1.00 vol fraction");
  });

  it("wraps the heatmap in a ChartContainer panel with consistent radius", () => {
    const html = render({});
    // ChartContainer adds RADIUS.lg (12px)
    expect(html).toContain("border-radius:12px");
    // ChartContainer wraps content in padding
    expect(html).toContain("padding:1rem");
  });

  it("uses the Metric primitive for summary values (consistent typography)", () => {
    const html = render({});
    // Metric renders value with font-size:1.25rem (md size)
    expect(html).toContain("font-size:1.25rem");
    // Metric label with font-size:0.8125rem
    expect(html).toContain("font-size:0.8125rem");
    // Metric uses tabular-nums for values
    expect(html).toContain("font-variant-numeric:tabular-nums");
  });
});
