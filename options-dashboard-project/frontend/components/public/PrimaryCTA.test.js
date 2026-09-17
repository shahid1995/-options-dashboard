import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import PrimaryCTA from "./PrimaryCTA";

// The anatomical CTA hover/annotation treatment (ICON/SPACING/SURFACE/RADIUS/
// DIRECTION labels around the button) was intentionally rejected in the
// design-system audit. These tests assert the accepted primary-CTA behavior
// only: accessible label, destination, focus-ring affordance and the
// directional arrow cue. They must never assert anatomy annotations.
describe("PrimaryCTA — accepted behavior", () => {
  const renderCTA = (props = {}, children = "Explore the Platform") =>
    renderToStaticMarkup(
      React.createElement(PrimaryCTA, { href: "/features", ...props }, children),
    );

  it("renders an anchor with the correct label and destination", () => {
    const html = renderCTA();
    expect(html).toContain("Explore the Platform");
    expect(html).toContain('href="/features"');
    expect(html).toContain("<a ");
  });

  it("uses the accepted primary CTA class hooks", () => {
    const html = renderCTA();
    expect(html).toContain("sn-cta-primary");
    expect(html).toContain("sn-cta-label");
    expect(html).toContain("ds-focus-ring");
  });

  it("includes the directional arrow affordance", () => {
    const html = renderCTA();
    expect(html).toContain("sn-cta-arrow");
    expect(html).toContain("<svg");
  });

  it("does not render rejected anatomy annotations", () => {
    const html = renderCTA();
    expect(html).not.toContain("sn-cta-annotations");
    expect(html).not.toContain("sn-cta-annotation");
    expect(html).not.toContain("SPACING");
    expect(html).not.toContain("SURFACE");
    expect(html).not.toContain("RADIUS");
    expect(html).not.toContain("DIRECTION");
  });

  it("renders custom labels and destinations", () => {
    const html = renderCTA({ href: "/strategy-lab" }, "Open Strategy Lab");
    expect(html).toContain("Open Strategy Lab");
    expect(html).toContain('href="/strategy-lab"');
  });
});
