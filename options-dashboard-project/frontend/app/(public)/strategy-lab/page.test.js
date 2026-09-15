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

import StrategyLabClientPage from "./page";

describe("Strategy Lab Page — P4 Tests", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(StrategyLabClientPage));

  it("contains StrikeNova branding", () => {
    const html = renderPage();
    expect(html).toContain("Strategy Forge");
  });

  it("contains Strategy Forge identity", () => {
    const html = renderPage();
    expect(html).toContain("Strategy Forge");
  });

  it("contains strategy-leg content", () => {
    const html = renderPage();
    expect(html).toContain("25500");
    expect(html).toContain("25700");
  });

  it("contains payoff chart", () => {
    const html = renderPage();
    expect(html).toContain("PAYOFF");
  });

  it("contains Greeks content", () => {
    const html = renderPage();
    expect(html).toContain("Greeks");
  });

  it("contains DEMO labeling", () => {
    const html = renderPage();
    expect(html).toContain("DEMO");
  });

  it("has CTA to Paper Trading", () => {
    const html = renderPage();
    expect(html).toContain('href="/paper-trading"');
  });

  it("does not contain Options Dashboard branding", () => {
    const html = renderPage();
    expect(html).not.toContain("Options Dashboard");
  });
});
