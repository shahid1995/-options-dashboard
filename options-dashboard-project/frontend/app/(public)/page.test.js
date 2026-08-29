import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import HomePage from "./page";

/**
 * Phase 10.2B-5 — Homepage routing verification.
 *
 * The homepage Login button must navigate to StrikeNova's own auth UI
 * (/settings), NOT directly to Upstox OAuth (/auth/login).
 */

describe("HomePage — Login routing", () => {
  it("Login / Get Started buttons link to /settings (StrikeNova auth UI)", () => {
    const html = renderToStaticMarkup(React.createElement(HomePage));
    // The CTASection at the bottom has primaryHref
    expect(html).toContain("href=\"/settings\"");
    // Must NOT contain a direct link to the Upstox OAuth endpoint
    expect(html).not.toContain("/auth/login");
  });

  it("does not contain any reference to login.upstox.com", () => {
    const html = renderToStaticMarkup(React.createElement(HomePage));
    expect(html).not.toContain("login.upstox.com");
  });

  it("Explore the Platform CTA still links to /features", () => {
    const html = renderToStaticMarkup(React.createElement(HomePage));
    expect(html).toContain("href=\"/features\"");
  });
});
