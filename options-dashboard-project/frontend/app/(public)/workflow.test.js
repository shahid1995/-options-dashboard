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

  it("renders Market View as initially active with market data", () => {
    const html = renderPage();
    expect(html).toContain("25,500");
    expect(html).toContain("BALANCED");
    expect(html).toContain("0.92");
    expect(html).toContain("14.2%");
  });

  it("contains supporting labels for each workflow stage", () => {
    const html = renderPage();
    expect(html).toContain("Understand the environment");
    expect(html).toContain("Choose the structure");
    expect(html).toContain("See how it behaves");
    expect(html).toContain("Know the boundaries");
  });

  it("contains Strategy Lab CTA linked to /strategy-lab", () => {
    const html = renderPage();
    expect(html).toContain("/strategy-lab");
    expect(html).toContain("Open Strategy Lab");
  });

  it("contains demo-data disclaimer", () => {
    const html = renderPage();
    expect(html).toMatch(/Demo|DEMO/);
    expect(html).toMatch(/Illustrative|ILLUSTRATIVE/);
  });

  it("contains accessible tab elements", () => {
    const html = renderPage();
    expect(html).toContain('role="tab"');
    expect(html).toContain('role="tablist"');
    expect(html).toContain('role="tabpanel"');
  });

  it("contains MAX PROFIT and MAX LOSS metrics", () => {
    const html = renderPage();
    expect(html).toContain("MAX PROFIT");
    expect(html).toContain("3,250");
    expect(html).toContain("MAX LOSS");
    expect(html).toContain("9,750");
  });

  it("contains breakeven levels", () => {
    const html = renderPage();
    expect(html).toContain("25,250");
    expect(html).toContain("25,750");
  });
});
