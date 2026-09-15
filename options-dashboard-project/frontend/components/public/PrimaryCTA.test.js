import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import PrimaryCTA from "./PrimaryCTA";

describe("PrimaryCTA anatomical interaction", () => {
  it("renders the CTA with workflow anatomy annotations around the button", () => {
    const html = renderToStaticMarkup(
      React.createElement(PrimaryCTA, { href: "/features" }, "Explore the Platform"),
    );

    expect(html).toContain("sn-cta-wrapper");
    expect(html).toContain("sn-cta-annotations");
    expect(html).toContain("Market state");
    expect(html).toContain("Market structure");
    expect(html).toContain("Strategy");
    expect(html).toContain("Risk");
    expect(html).toContain("Paper execution");
    expect(html).toContain("Explore the Platform");
    expect(html).toContain('href="/features"');
  });
});
