import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import PrimaryCTA from "./PrimaryCTA";

describe("PrimaryCTA anatomical interaction", () => {
  it("renders stable anatomy annotations around the CTA", () => {
    const html = renderToStaticMarkup(
      React.createElement(PrimaryCTA, { href: "/features" }, "Explore the Platform"),
    );

    expect(html).toContain("sn-cta-wrapper");
    expect(html).toContain("sn-cta-annotations");
    expect(html).toContain("sn-cta-annotation--icon");
    expect(html).toContain("sn-cta-annotation--spacing");
    expect(html).toContain("sn-cta-annotation--surface");
    expect(html).toContain("sn-cta-annotation--radius");
    expect(html).toContain("sn-cta-annotation--direction");
    expect(html).toContain("ICON");
    expect(html).toContain("SPACING");
    expect(html).toContain("SURFACE");
    expect(html).toContain("RADIUS");
    expect(html).toContain("DIRECTION");
    expect(html).toContain("Explore the Platform");
    expect(html).toContain('href="/features"');
  });
});
