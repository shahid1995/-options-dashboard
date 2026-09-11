import { describe, it, expect, vi } from "vitest";
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
