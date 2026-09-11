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

import PublicHeader from "./PublicHeader";

describe("PublicHeader — P6 Tests", () => {
  const renderHeader = () => renderToStaticMarkup(React.createElement(PublicHeader));

  it("contains StrikeNova branding", () => {
    const html = renderHeader();
    expect(html).toContain("STRIKENOVA");
  });

  it("does not contain Options Dashboard branding", () => {
    const html = renderHeader();
    expect(html).not.toContain("Options Dashboard");
  });

  it("contains Product and Learn group buttons", () => {
    const html = renderHeader();
    expect(html).toContain("Product");
    expect(html).toContain("Learn");
  });

  it("contains Get Started CTA", () => {
    const html = renderHeader();
    expect(html).toContain("Get Started");
  });

  it("contains Login button", () => {
    const html = renderHeader();
    expect(html).toContain("Log in");
  });

  it("has mobile menu toggle button", () => {
    const html = renderHeader();
    expect(html).toContain("Open navigation");
    expect(html).toContain("pub-nav-mobile-toggle");
  });

  it("has desktop nav links container", () => {
    const html = renderHeader();
    expect(html).toContain("pub-nav-links");
  });
});
