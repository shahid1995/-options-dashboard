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
  const { createContext } = require("react");
  const AuthModalContext = createContext({ open: () => {} });
  return {
    default: function AuthModalProvider({ children }) {
      return React.createElement(AuthModalContext.Provider, { value: { open: () => {} } }, children);
    },
    useAuthModal: () => ({ open: () => {} }),
  };
});

import MarketIntelligenceClientPage from "./page";

describe("Market Intelligence Page — P4 Tests", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(MarketIntelligenceClientPage));

  it("contains StrikeNova branding", () => {
    const html = renderPage();
    expect(html).toContain("Market Intelligence");
  });

  it("contains Signal Field visualization", () => {
    const html = renderPage();
    expect(html).toContain("Signal Field");
  });

  it("contains analytical dimensions (PRICE, OI, IV, GREEKS, STRUCTURE)", () => {
    const html = renderPage();
    expect(html).toContain("PRICE");
    expect(html).toContain("OI");
    expect(html).toContain("IV");
    expect(html).toContain("GREEKS");
    expect(html).toContain("STRUCTURE");
  });

  it("contains DEMO labeling", () => {
    const html = renderPage();
    expect(html).toContain("DEMO");
  });

  it("contains research-direction labeling", () => {
    const html = renderPage();
    expect(html).toContain("RESEARCH");
  });

  it("has CTA to Strategy Lab", () => {
    const html = renderPage();
    expect(html).toContain('href="/strategy-lab"');
  });

  it("does not contain Options Dashboard branding", () => {
    const html = renderPage();
    expect(html).not.toContain("Options Dashboard");
  });
});
