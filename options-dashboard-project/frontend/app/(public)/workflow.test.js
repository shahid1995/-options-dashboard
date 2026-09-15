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
    expect(html).toContain("M48 170 L160 170");
    expect(html).toContain("M160 170 L440 70");
    expect(html).toContain("L440 70 L590 70");
    expect(html).toContain('fill={COLOR.negative}');
    expect(html).toContain('fill={COLOR.positive}');
    expect(html).toContain('stroke={COLOR.strategy}');
    expect(html).toContain("MAX PROFIT · CAPPED");
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
