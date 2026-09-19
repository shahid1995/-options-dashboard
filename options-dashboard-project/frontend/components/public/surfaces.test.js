import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { Panel } from "./surfaces";

// =============================================================================
// Panel — box-sizing invariant
// =============================================================================
// Regression coverage for the defect diagnosed by historical PR #45: Panel
// used content-box sizing, so a full-height (height: 100%) card's padding and
// border extended beyond its allocated grid track. Panel now sets
// box-sizing: border-box by default; the caller-style override remains the
// final layer, so callers can still override boxSizing explicitly.
// =============================================================================

const renderPanel = (props = {}, style = {}) =>
  renderToStaticMarkup(
    React.createElement(Panel, { ...props, style }, "content"),
  );

describe("Panel — box-sizing invariant", () => {
  it("sets box-sizing: border-box by default", () => {
    const html = renderPanel();
    expect(html).toMatch(/box-sizing:\s*border-box/);
  });

  it("keeps border-box for the full-height capability-card pattern (padding + accent border inside the box)", () => {
    // CapabilityModule pattern: Panel + padding + height 100% + accent border.
    const html = renderPanel(
      { padding: "2rem" },
      { height: "100%", borderLeft: "3px solid #A78BFA" },
    );
    expect(html).toMatch(/box-sizing:\s*border-box/);
    expect(html).toMatch(/height:\s*100%/);
    expect(html).toMatch(/border-left:\s*3px solid/);
    expect(html).toMatch(/padding:\s*2rem/);
  });

  it("preserves existing Panel behavior otherwise", () => {
    const html = renderPanel({ padding: "1.5rem" }, { opacity: 0.5 });
    expect(html).toMatch(/border-radius/); // radius retained
    expect(html).toMatch(/box-shadow/); // shadow retained
    expect(html).toContain("content"); // children render
    expect(html).toMatch(/opacity:\s*0\.5/); // caller style passthrough retained
  });

  it("allows callers to override box-sizing via style (escape hatch intact)", () => {
    const html = renderPanel({}, { boxSizing: "content-box" });
    expect(html).toMatch(/box-sizing:\s*content-box/);
  });
});
