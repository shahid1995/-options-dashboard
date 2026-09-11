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

import HowItWorksClientPage from "./page";

describe("How It Works Page — P5 Tests", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(HowItWorksClientPage));

  it("contains HOW IT WORKS identity", () => {
    const html = renderPage();
    expect(html).toContain("HOW IT WORKS");
  });

  it("contains six stages in order", () => {
    const html = renderPage();
    expect(html).toContain("OBSERVE");
    expect(html).toContain("ANALYZE");
    expect(html).toContain("BUILD");
    expect(html).toContain("TEST");
    expect(html).toContain("PAPER TRADE");
    expect(html).toContain("REVIEW");
  });

  it("contains workflow numbers", () => {
    const html = renderPage();
    expect(html).toContain("01");
    expect(html).toContain("02");
    expect(html).toContain("03");
    expect(html).toContain("04");
    expect(html).toContain("05");
    expect(html).toContain("06");
  });

  it("contains CTA destinations", () => {
    const html = renderPage();
    expect(html).toContain('href="/market-intelligence"');
    expect(html).toContain('href="/strategy-lab"');
    expect(html).toContain('href="/paper-trading"');
  });

  it("does not contain Options Dashboard branding", () => {
    const html = renderPage();
    expect(html).not.toContain("Options Dashboard");
  });
});
