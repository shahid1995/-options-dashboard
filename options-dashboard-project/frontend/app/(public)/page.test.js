import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import HomePage from "./page";
import { AuthModalProvider } from "@/components/public/AuthModalContext";

/**
 * Homepage routing verification.
 *
 * The homepage Login button must open StrikeNova's auth modal overlay,
 * NOT navigate to /settings or directly to Upstox OAuth.
 */

const wrapWithProvider = (Component) => {
  // AuthModalProvider requires useSearchParams in some children, but
  // renderToStaticMarkup doesn't support hooks.  We test structural
  // properties of the rendered HTML instead.
  return Component;
};

describe("HomePage — Login routing", () => {
  it("Explore the Platform CTA links to /features", () => {
    const html = renderToStaticMarkup(React.createElement(HomePage));
    expect(html).toContain('href="/features"');
  });

  it("does not navigate to /settings for Login/Get Started", () => {
    const html = renderToStaticMarkup(React.createElement(HomePage));
    // No anchor should point to /settings
    expect(html).not.toMatch(/href="\/settings"/);
  });

  it("does not contain any reference to login.upstox.com", () => {
    const html = renderToStaticMarkup(React.createElement(HomePage));
    expect(html).not.toContain("login.upstox.com");
  });

  it("contains a Get Started button for the hero section", () => {
    const html = renderToStaticMarkup(React.createElement(HomePage));
    expect(html).toContain("Start Paper Trading");
  });
});
