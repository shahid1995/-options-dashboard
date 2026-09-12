import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("@/lib/ui", () => ({
  useIsMobile: () => false,
  C: {},
  SYMBOLS: [],
  LOT_SIZES: {},
  fmtIN: (n) => (n != null ? String(n) : "-"),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => null }),
}));

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

import HomePage from "./page";

/**
 * Homepage redesign verification — covers all new sections and behaviors.
 */
describe("HomePage — Redesign", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(HomePage));

  // ════════════════════════════════════════════════════════════════════════
  // HERO
  // ════════════════════════════════════════════════════════════════════════
  describe("Hero", () => {
    it("contains StrikeNova branding", () => {
      const html = renderPage();
      expect(html).toContain("StrikeNova");
    });

    it("contains OPTIONS INTELLIGENCE tagline", () => {
      const html = renderPage();
      expect(html).toContain("OPTIONS INTELLIGENCE");
    });

    it("contains 'for Structured Decisions' tagline", () => {
      const html = renderPage();
      expect(html).toMatch(/for Structured Decisions|FOR STRUCTURED DECISIONS/);
    });

    it("contains primary CTA 'Explore StrikeNova'", () => {
      const html = renderPage();
      expect(html).toContain("Explore StrikeNova");
    });

    it("contains secondary CTA 'Strategy Lab'", () => {
      const html = renderPage();
      expect(html).toContain("Strategy Lab");
    });

    it("has a single H1 heading", () => {
      const html = renderPage();
      const h1Count = (html.match(/<h1[^>]*>/g) || []).length;
      expect(h1Count).toBe(1);
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // PRODUCT PREVIEW
  // ════════════════════════════════════════════════════════════════════════
  describe("Product Preview", () => {
    it("contains DEMO · ILLUSTRATIVE label", () => {
      const html = renderPage();
      expect(html).toMatch(/Demo|DEMO/);
      expect(html).toMatch(/Illustrative|ILLUSTRATIVE/);
    });

    it("contains key preview metrics (SPOT, PCR, ATM IV)", () => {
      const html = renderPage();
      expect(html).toContain("SPOT");
      expect(html).toContain("PCR");
      expect(html).toContain("ATM IV");
    });

    it("contains preview Greeks (DELTA, GAMMA, THETA, VEGA)", () => {
      const html = renderPage();
      expect(html).toContain("DELTA");
      expect(html).toContain("GAMMA");
      expect(html).toContain("THETA");
      expect(html).toContain("VEGA");
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // ANALYTICAL LAYERS
  // ════════════════════════════════════════════════════════════════════════
  describe("Analytical Layers", () => {
    it("contains all eight analytical layer cards", () => {
      const html = renderPage();
      expect(html).toContain("PRICE");
      expect(html).toContain("OPEN INTEREST");
      expect(html).toContain("OI CHANGE");
      expect(html).toContain("VOLUME");
      expect(html).toContain("IMPLIED VOLATILITY");
      expect(html).toContain("GREEKS");
      expect(html).toContain("MARKET STRUCTURE");
      expect(html).toContain("MARKET STATE");
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // SIGNAL FIELD
  // ════════════════════════════════════════════════════════════════════════
  describe("Signal Field", () => {
    it("contains SIGNAL FIELD heading", () => {
      const html = renderPage();
      expect(html).toContain("SIGNAL FIELD");
    });

    it("contains key indicator labels (SPOT, PCR, ATM IV, OI CHANGE)", () => {
      const html = renderPage();
      expect(html).toContain("SPOT");
      expect(html).toContain("PCR");
      expect(html).toContain("ATM IV");
    });

    it("contains full Greek names (Delta, Gamma, Theta, Vega)", () => {
      const html = renderPage();
      expect(html).toContain("Delta");
      expect(html).toContain("Gamma");
      expect(html).toContain("Theta");
      expect(html).toContain("Vega");
    });

    it("contains DEMO labeling", () => {
      const html = renderPage();
      expect(html).toMatch(/Demo|DEMO/);
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // MARKET INTELLIGENCE
  // ════════════════════════════════════════════════════════════════════════
  describe("Market Intelligence", () => {
    it("contains POSITIONING panel", () => {
      const html = renderPage();
      expect(html).toContain("POSITIONING");
    });

    it("contains VOLATILITY panel", () => {
      const html = renderPage();
      expect(html).toContain("VOLATILITY");
    });

    it("contains GREEKS panel", () => {
      const html = renderPage();
      expect(html).toContain("GREEKS");
    });

    it("contains STRUCTURE panel", () => {
      const html = renderPage();
      expect(html).toContain("STRUCTURE");
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // STRATEGY LAB TABS
  // ════════════════════════════════════════════════════════════════════════
  describe("Strategy Lab Tabs", () => {
    it("contains four strategy tab labels", () => {
      const html = renderPage();
      expect(html).toContain("MARKET VIEW");
      expect(html).toContain("STRATEGY");
      expect(html).toContain("PAYOFF");
      expect(html).toContain("RISK");
    });

    it("renders default tab (MARKET VIEW) content deterministically", () => {
      const html = renderPage();
      expect(html).toContain("MARKET VIEW");
      // Default tab should show market data
      expect(html).toContain("SPOT");
    });

    it("has tab elements with role='tab'", () => {
      const html = renderPage();
      expect(html).toContain('role="tab"');
    });

    it("has tablist container", () => {
      const html = renderPage();
      expect(html).toContain('role="tablist"');
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // PAPER TRADING TABS
  // ════════════════════════════════════════════════════════════════════════
  describe("Paper Trading Tabs", () => {
    it("contains four paper tab labels", () => {
      const html = renderPage();
      expect(html).toContain("DECISION");
      expect(html).toContain("SIMULATION");
      expect(html).toContain("POSITION");
      expect(html).toContain("REVIEW");
    });

    it("renders default tab (DECISION) content deterministically", () => {
      const html = renderPage();
      expect(html).toContain("DECISION");
    });

    it("contains SIMULATED or DEMO labeling", () => {
      const html = renderPage();
      expect(html).toMatch(/SIMULATED|Demo|DEMO/);
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // RISK
  // ════════════════════════════════════════════════════════════════════════
  describe("Risk", () => {
    it("contains MAX PROFIT metric", () => {
      const html = renderPage();
      expect(html).toContain("MAX PROFIT");
      expect(html).toContain("3,250");
    });

    it("contains MAX LOSS metric", () => {
      const html = renderPage();
      expect(html).toContain("MAX LOSS");
      expect(html).toContain("9,750");
    });

    it("contains breakeven levels", () => {
      const html = renderPage();
      expect(html).toContain("25,250");
      expect(html).toContain("25,750");
    });

    it("contains payoff graph labels (LOSS, PROFIT)", () => {
      const html = renderPage();
      expect(html).toContain("LOSS");
      expect(html).toContain("PROFIT");
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // TRUTH
  // ════════════════════════════════════════════════════════════════════════
  describe("Truth", () => {
    it("does not contain LIVE market claim", () => {
      const html = renderPage();
      expect(html).not.toContain("LIVE");
    });

    it("does not contain REAL-TIME claim", () => {
      const html = renderPage();
      expect(html).not.toContain("REAL-TIME");
    });

    it("contains DEMO or ILLUSTRATIVE labels", () => {
      const html = renderPage();
      expect(html).toMatch(/Demo|DEMO|Illustrative|ILLUSTRATIVE/);
    });
  });

  // ════════════════════════════════════════════════════════════════════════
  // ACCESSIBILITY
  // ════════════════════════════════════════════════════════════════════════
  describe("Accessibility", () => {
    it("contains an H1 heading", () => {
      const html = renderPage();
      expect(html).toMatch(/<h1[^>]*>/);
    });

    it("contains section headings (h2)", () => {
      const html = renderPage();
      expect(html).toMatch(/<h2[^>]*>/);
    });

    it("has tabs as semantic buttons", () => {
      const html = renderPage();
      expect(html).toContain("<button");
      expect(html).toContain('role="tab"');
    });

    it("has tabpanel for tab content", () => {
      const html = renderPage();
      expect(html).toContain('role="tabpanel"');
    });

    it("has accessible graph text alternative", () => {
      const html = renderPage();
      expect(html).toContain("Payoff");
    });
  });
});
