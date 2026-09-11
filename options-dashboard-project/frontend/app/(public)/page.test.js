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

// Mock AuthModalContext to avoid rendering AuthModal (which uses browser APIs)
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
 * Homepage routing verification.
 */
describe("HomePage — Login routing", () => {
  const renderPage = () => {
    return renderToStaticMarkup(React.createElement(HomePage));
  };

  it("Explore StrikeNova CTA links to /features", () => {
    const html = renderPage();
    expect(html).toContain('href="/features"');
  });

  it("does not navigate to /settings for Login/Get Started", () => {
    const html = renderPage();
    expect(html).not.toMatch(/href="\/settings"/);
  });

  it("does not contain any reference to login.upstox.com", () => {
    const html = renderPage();
    expect(html).not.toContain("login.upstox.com");
  });

  it("contains a Get Started button for the hero section", () => {
    const html = renderPage();
    expect(html).toContain("Get Started");
  });

  it("contains StrikeNova branding", () => {
    const html = renderPage();
    expect(html).toContain("StrikeNova");
  });

  it("contains Options Intelligence tagline", () => {
    const html = renderPage();
    expect(html).toContain("Options Intelligence");
  });

  it("contains Signal Field visualization", () => {
    const html = renderPage();
    expect(html).toContain("Signal Field");
  });
});
