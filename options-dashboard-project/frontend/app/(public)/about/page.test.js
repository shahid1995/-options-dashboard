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

import AboutClientPage from "./page";

describe("About Page — P5 Tests", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(AboutClientPage));

  it("contains About identity", () => {
    const html = renderPage();
    expect(html).toContain("ABOUT");
  });

  it("contains Why StrikeNova section", () => {
    const html = renderPage();
    expect(html).toContain("WHY STRIKENOVA EXISTS");
  });

  it("contains four philosophy principles", () => {
    const html = renderPage();
    expect(html).toContain("DATA FIRST");
    expect(html).toContain("RISK FIRST");
    expect(html).toContain("STRUCTURED ANALYSIS");
    expect(html).toContain("TRANSPARENCY");
  });

  it("contains What StrikeNova Is Not", () => {
    const html = renderPage();
    expect(html).toContain("SIGNAL-SELLING");
    expect(html).toContain("GUARANTEED-PROFIT");
    expect(html).toContain("BLACK BOX");
  });

  it("contains future/research labeling", () => {
    const html = renderPage();
    expect(html).toContain("RESEARCH DIRECTION");
    expect(html).toContain("COMING LATER");
  });

  it("does not contain Options Dashboard branding", () => {
    const html = renderPage();
    expect(html).not.toContain("Options Dashboard");
  });

  it("does not contain unsupported claims", () => {
    const html = renderPage();
    expect(html).not.toContain("guaranteed");
    expect(html).not.toContain("predicts");
    expect(html).not.toContain("institutional-grade");
  });
});
