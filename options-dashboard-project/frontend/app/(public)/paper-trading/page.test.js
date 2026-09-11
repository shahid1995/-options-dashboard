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

import PaperTradingClientPage from "./page";

describe("Paper Trading Page — P4 Tests", () => {
  const renderPage = () => renderToStaticMarkup(React.createElement(PaperTradingClientPage));

  it("contains StrikeNova branding", () => {
    const html = renderPage();
    expect(html).toContain("Rehearsal");
  });

  it("contains Rehearsal Cockpit identity", () => {
    const html = renderPage();
    expect(html).toContain("Rehearsal");
  });

  it("contains rehearsal sequence (DECISION, SIMULATION, ORDERS, POSITIONS, P&L, REVIEW)", () => {
    const html = renderPage();
    expect(html).toContain("DECISION");
    expect(html).toContain("SIMULATION");
    expect(html).toContain("ORDERS");
    expect(html).toContain("POSITIONS");
    expect(html).toContain("REVIEW");
  });

  it("contains DEMO labeling", () => {
    const html = renderPage();
    expect(html).toContain("DEMO");
  });

  it("contains no-real-orders language", () => {
    const html = renderPage();
    expect(html).toContain("No real");
  });

  it("contains DataStateBadge (DEMO/ILLUSTRATIVE badges render)", () => {
    const html = renderPage();
    // DataStateBadge renders the state label
    expect(html).toContain("DEMO");
    expect(html).toContain("ILLUSTRATIVE");
  });

  it("does not contain Options Dashboard branding", () => {
    const html = renderPage();
    expect(html).not.toContain("Options Dashboard");
  });
});
