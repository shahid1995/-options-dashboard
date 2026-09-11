import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("@/lib/ui", () => ({
  C: {},
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

import PublicFooter from "./PublicFooter";

describe("PublicFooter — P6 Tests", () => {
  const renderFooter = () => renderToStaticMarkup(React.createElement(PublicFooter));

  it("contains StrikeNova branding", () => {
    const html = renderFooter();
    expect(html).toContain("STRIKENOVA");
  });

  it("does not contain Options Dashboard branding", () => {
    const html = renderFooter();
    expect(html).not.toContain("Options Dashboard");
  });

  it("contains PRODUCT group with all product links", () => {
    const html = renderFooter();
    expect(html).toContain("PRODUCT");
    expect(html).toContain("Features");
    expect(html).toContain("Market Intelligence");
    expect(html).toContain("Strategy Lab");
    expect(html).toContain("Paper Trading");
  });

  it("contains LEARN group with all learning links", () => {
    const html = renderFooter();
    expect(html).toContain("LEARN");
    expect(html).toContain("How It Works");
    expect(html).toContain("About");
  });

  it("contains Account group with login/get-started", () => {
    const html = renderFooter();
    expect(html).toContain("ACCOUNT");
    expect(html).toContain("Log in");
    expect(html).toContain("Get Started");
  });

  it("has correct href for all navigation links", () => {
    const html = renderFooter();
    expect(html).toContain('href="/features"');
    expect(html).toContain('href="/market-intelligence"');
    expect(html).toContain('href="/strategy-lab"');
    expect(html).toContain('href="/paper-trading"');
    expect(html).toContain('href="/how-it-works"');
    expect(html).toContain('href="/about"');
  });
});
