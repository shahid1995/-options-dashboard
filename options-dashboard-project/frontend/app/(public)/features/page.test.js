import { describe, it, expect, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Mock the @/lib/ui module at the top level for Node.js test environment
vi.mock("@/lib/ui", () => ({
  useIsMobile: () => false,
  C: {},
  SYMBOLS: [],
  LOT_SIZES: {},
  fmtIN: (n) => (n != null ? String(n) : "-"),
}));

// Mock next/navigation for useSearchParams
vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => null }),
}));

// Mock AuthModalContext
vi.mock("@/components/public/AuthModalContext", () => {
  const { createContext, useContext } = require("react");
  const AuthModalContext = createContext({ open: () => {} });
  return {
    default: function AuthModalProvider({ children }) {
      return React.createElement(AuthModalContext.Provider, { value: { open: () => {} } }, children);
    },
    useAuthModal: () => ({ open: () => {} }),
  };
});

import FeaturesClientPage from "./page";

describe("Features Page — P4 Tests", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(FeaturesClientPage));

  it("contains StrikeNova branding", () => {
    const html = renderPage();
    expect(html).toContain("StrikeNova");
  });

  it("contains Capability Atlas sections", () => {
    const html = renderPage();
    expect(html).toContain("MARKET INTELLIGENCE");
    expect(html).toContain("STRATEGY LAB");
    expect(html).toContain("PAPER TRADING");
  });

  it("has CTA destinations to product pages", () => {
    const html = renderPage();
    expect(html).toContain('href="/market-intelligence"');
    expect(html).toContain('href="/strategy-lab"');
    expect(html).toContain('href="/paper-trading"');
  });

  it("contains research-direction labels", () => {
    const html = renderPage();
    expect(html).toContain("RESEARCH");
  });

  it("does not contain visible Options Dashboard branding", () => {
    const html = renderPage();
    expect(html).not.toContain("Options Dashboard");
    expect(html).not.toContain("OPTIONS DASHBOARD");
  });

  it("does not contain misleading LIVE CHAIN wording", () => {
    const html = renderPage();
    expect(html).not.toContain("LIVE CHAIN");
  });
});

describe("Features Page — Intelligence Stack", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(FeaturesClientPage));

  it("renders the intelligence stack section", () => {
    const html = renderPage();
    expect(html).toContain("INTELLIGENCE STACK");
    expect(html).toContain("From market data to structured decisions");
  });

  it("lists the analytical layers in pipeline order", () => {
    const html = renderPage();
    for (const layer of [
      "MARKET DATA",
      "POSITIONING",
      "VOLATILITY",
      "GREEKS",
      "STRUCTURE",
      "SCENARIOS",
      "STRATEGY",
      "RISK",
    ]) {
      expect(html).toContain(layer);
    }
  });
});

describe("Features Page — Deep Capability coverage", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(FeaturesClientPage));

  it("renders the go-deeper capability grid with validated capabilities", () => {
    const html = renderPage();
    expect(html).toContain("GO DEEPER");
    for (const card of [
      "Gamma Exposure",
      "Volatility Intelligence",
      "Greeks Analytics",
      "Scenario Engine",
      "Capital &amp; Margin",
      "Trade Rehearsal",
    ]) {
      expect(html).toContain(card);
    }
  });
});

describe("Features Page — Product Evidence (illustrative data contract)", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(FeaturesClientPage));

  it("renders the evidence section with an explicit illustrative indication", () => {
    const html = renderPage();
    expect(html).toContain("PRODUCT EVIDENCE — ILLUSTRATIVE");
  });

  it("marks every sample metric as DEMO with an ILLUSTRATIVE source", () => {
    const html = renderPage();
    expect(html).toContain("DEMO");
    expect(html).toContain("ILLUSTRATIVE");
    // 19 sample metrics across the six evidence views, each marked twice
    // (status badge + source label).
    const demoCount = (html.match(/DEMO/g) || []).length;
    const illustrativeCount = (html.match(/ILLUSTRATIVE/g) || []).length;
    expect(demoCount).toBeGreaterThanOrEqual(19);
    expect(illustrativeCount).toBeGreaterThanOrEqual(19);
  });

  it("never presents sample metrics as live data", () => {
    const html = renderPage();
    expect(html).not.toContain('"LIVE"');
    expect(html).not.toContain(">LIVE<");
    expect(html).not.toContain("LIVE CHAIN");
  });

  it("keeps evidence CTAs pointing at the real product routes", () => {
    const html = renderPage();
    expect(html).toContain('href="/market-intelligence"');
    expect(html).toContain('href="/strategy-lab"');
    expect(html).toContain('href="/paper-trading"');
  });

  it("preserves the existing Features composition while adding the story sections", () => {
    const source = fs.readFileSync(
      path.resolve(process.cwd(), "app/(public)/features/ClientPage.js"),
      "utf8",
    );
    // Existing capability grid must keep its current value.
    expect(source).toContain("minItemWidth={320}");
    // Story sections must be composed (not inlined) and WhyStrikeNova must
    // remain excluded (Founder-gated).
    expect(source).toContain("<IntelligenceStack />");
    expect(source).toContain("<DeepCapabilityGrid />");
    expect(source).toContain("<ProductEvidenceGrid />");
    expect(source).not.toContain("WhyStrikeNova");
  });
});
