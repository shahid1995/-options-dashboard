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
  useRouter: () => ({ push: () => {} }),
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

vi.mock("@/lib/session", () => ({
  captureGoogleIdTokenFromUrl: () => null,
  setSessionId: () => {},
}));

vi.mock("@/lib/api", () => ({
  loginGoogle: () => Promise.resolve({}),
}));

import PublicLayout from "./PublicLayout";

describe("PublicLayout — P7 Accessibility Tests", () => {
  const renderLayout = () =>
    renderToStaticMarkup(
      React.createElement(PublicLayout, null, React.createElement("div", { "data-testid": "content" }, "Test content"))
    );

  it("contains main landmark", () => {
    const html = renderLayout();
    expect(html).toContain("<main");
  });

  it("contains navigation landmark", () => {
    const html = renderLayout();
    expect(html).toContain("<nav");
  });

  it("contains footer landmark", () => {
    const html = renderLayout();
    expect(html).toContain("<footer");
  });

  it("contains PublicHeader with StrikeNova branding", () => {
    const html = renderLayout();
    expect(html).toContain("STRIKENOVA");
  });

  it("contains PublicFooter with StrikeNova branding", () => {
    const html = renderLayout();
    // Footer appears twice (once in header dropdown area, once in footer)
    const count = (html.match(/STRIKENOVA/g) || []).length;
    expect(count).toBeGreaterThanOrEqual(2);
  });
});
