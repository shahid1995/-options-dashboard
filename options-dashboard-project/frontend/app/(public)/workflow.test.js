import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("@/lib/ui", () => ({
  useIsMobile: () => false,
  usePathname: () => "/",
  C: {},
  SYMBOLS: [],
  LOT_SIZES: {},
  fmtIN: (n) => (n != null ? String(n) : "-"),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => ({ get: () => null }),
}));

import HomePage from "./page";

describe("Context to Strategy Workflow", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(HomePage));

  it("contains four workflow stages", () => {
    const html = renderPage();
    expect(html).toContain("MARKET VIEW");
    expect(html).toContain("STRATEGY");
    expect(html).toContain("PAYOFF");
    expect(html).toContain("RISK");
  });

  it("renders the illustrative market view and bull call structure", () => {
    const html = renderPage();
    expect(html).toContain("25,500");
    expect(html).toContain("BALANCED");
    expect(html).toContain("BULL CALL SPREAD");
    expect(html).toContain("25,450");
    expect(html).toContain("25,550");
    expect(html).toContain("45 pts");
    expect(html).toContain("+55 pts");
  });

  it("renders a mathematically consistent reward-to-risk example", () => {
    const html = renderPage();
    expect(html).toContain("1.22 : 1");
    expect(html).toContain("BREAKEVEN 25,495");
    expect(html).toContain("MAX PROFIT");
    expect(html).toContain("MAX LOSS");
  });

  it("renders a capped payoff with one straight rising segment", () => {
    const html = renderPage();
    expect(html).toContain('viewBox="0 0 620 250"');
    expect(html).toContain("MAX PROFIT · CAPPED");
    expect(html).toContain("BREAKEVEN 25,495");
    expect(html).toContain("Payoff rises linearly");
  });

  it("renders Risk First around the same defined-risk bull call spread", () => {
    const html = renderPage();
    expect(html).toContain("RISK FIRST");
    expect(html).toContain("RISK BOUNDARIES");
    expect(html).toContain("REWARD / RISK");
    expect(html).toContain("1.22 : 1");
    expect(html).toContain("-45 pts");
    expect(html).toContain("+55 pts");
    expect(html).toContain("25,495");
    expect(html).toContain("Below 25,450");
    expect(html).toContain("Above 25,550");
    expect(html).toContain("WHAT THIS MEANS");
    expect(html).toContain("MAX PROFIT · CAPPED");
  });

  it("renders Paper Execution as a decision-to-review workflow", () => {
    const html = renderPage();
    expect(html).toContain("PAPER EXECUTION");
    // Four workflow steps are always visible as tab labels
    expect(html).toContain("DECIDE");
    expect(html).toContain("EXECUTE");
    expect(html).toContain("MANAGE");
    expect(html).toContain("REVIEW");
    // Default step (DECIDE) renders its content statically
    expect(html).toContain("BULL CALL SPREAD");
    // Workflow summary grid renders below the tabs
    expect(html).toContain("01 · SIMULATE");
    expect(html).toContain("02 · MANAGE");
    expect(html).toContain("03 · LEARN");
    expect(html).toContain("PAPER ENVIRONMENT");
  });

  it("preserves the homepage strategy CTA and demo semantics", () => {
    const html = renderPage();
    expect(html).toContain("/strategy-lab");
    expect(html).toContain("Open Strategy Lab");
    expect(html).toMatch(/Demo|DEMO/);
    expect(html).toMatch(/Illustrative|ILLUSTRATIVE/);
  });

  it("retains accessible tab semantics", () => {
    const html = renderPage();
    expect(html).toContain('role="tab"');
    expect(html).toContain('role="tablist"');
    expect(html).toContain('role="tabpanel"');
  });
});
