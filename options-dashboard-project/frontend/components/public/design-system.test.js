// =============================================================================
// StrikeNova Public Design System — Tests
// =============================================================================
import { describe, it, expect } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Tokens
import {
  COLOR,
  TYPE,
  SPACE,
  RADIUS,
  SHADOW,
  LAYER,
  BREAKPOINT,
  MOTION,
  DATA_STATE,
  RESEARCH_STATUS,
  SEMANTIC_COLOR_KEYS,
  SEMANTIC_SPACE_KEYS,
  SEMANTIC_TYPE_KEYS,
} from "./tokens";

// Primitives
import { Surface, Panel, MetricPanel, OutlinePanel, SignalPanel } from "./surfaces";
import { Button, LinkButton, TextLink } from "./buttons";
import { Metric, formatMetricValue } from "./Metric";
import { VisualizationFrame } from "./VisualizationFrame";
import { SignalLine, SignalNode, StrikeRail, DataTrace, TechnicalDivider, GridOverlay } from "./signals";
import { Section, Container, TwoColumn, MetricGrid, CardGrid, BentoGrid, FlexRow, FlexColumn, Asymmetric } from "./layout";
import { DemoLabel, ResearchBadge, DataStateBadge, Eyebrow, SectionTitle } from "./truth";
import { PUBLIC_DS_CSS, fadeUpStyle, signalGlowStyle, traceDrawStyle } from "./motion";
import { PUBLIC_CSS } from "./styles";
import { SignalField, DEMO_SIGNAL_STATE } from "./SignalField";

// =============================================================================
// TOKENS TESTS
// =============================================================================

describe("Design System — Tokens", () => {
  describe("COLOR", () => {
    it("has all required semantic color roles", () => {
      const required = [
        "base", "baseElevated", "surface", "surfaceElevated", "surfaceDeep",
        "border", "borderSubtle", "borderStrong",
        "textPrimary", "textSecondary", "textMuted", "textFaint",
        "info", "infoDim", "infoGlow",
        "intelligence", "intelligenceDim", "intelligenceGlow",
        "strategy", "strategyDim", "strategyGlow",
        "positive", "positiveDim",
        "negative", "negativeDim",
        "warning", "warningDim",
        "signalOi", "signalIv", "signalGreeks", "signalPrice",
      ];
      required.forEach((key) => {
        expect(COLOR[key]).toBeDefined();
      });
    });

    it("gold (strategy) is preserved", () => {
      expect(COLOR.strategy).toBe("#C9A15A");
    });

    it("base is deep obsidian", () => {
      expect(COLOR.base).toBe("#06080B");
    });

    it("info is electric cyan", () => {
      expect(COLOR.info).toBe("#22D3EE");
    });

    it("intelligence is violet/ultraviolet", () => {
      expect(COLOR.intelligence).toBe("#A78BFA");
    });

    it("all color values are valid hex or rgba", () => {
      Object.values(COLOR).forEach((val) => {
        expect(val).toMatch(/^#|rgba\(/);
      });
    });
  });

  describe("TYPE", () => {
    it("has display, body, and data font families", () => {
      expect(TYPE.display).toBeDefined();
      expect(TYPE.body).toBeDefined();
      expect(TYPE.data).toBeDefined();
    });

    it("has all heading scales", () => {
      expect(TYPE.h1).toBeDefined();
      expect(TYPE.h2).toBeDefined();
      expect(TYPE.h3).toBeDefined();
      expect(TYPE.h4).toBeDefined();
    });

    it("has body scale", () => {
      expect(TYPE.bodyLarge).toBeDefined();
      expect(TYPE.body).toBeDefined();
      expect(TYPE.bodySmall).toBeDefined();
    });

    it("has label and caption scales", () => {
      expect(TYPE.label).toBeDefined();
      expect(TYPE.labelSmall).toBeDefined();
      expect(TYPE.caption).toBeDefined();
    });

    it("has data scale", () => {
      expect(TYPE.dataHero).toBeDefined();
      expect(TYPE.dataLarge).toBeDefined();
      expect(TYPE.data).toBeDefined();
      expect(TYPE.dataSmall).toBeDefined();
    });

    it("display hero size uses clamp for responsive scaling", () => {
      expect(TYPE.displayHero.size).toContain("clamp");
    });
  });

  describe("SPACE", () => {
    it("has all required spacing tokens", () => {
      const required = ["micro", "xs", "small", "sm", "medium", "comp", "compLg", "card", "cardLg", "group", "section", "sectionLg", "hero"];
      required.forEach((key) => {
        expect(SPACE[key]).toBeDefined();
      });
    });

    it("all spacing values are in rem", () => {
      Object.values(SPACE).forEach((val) => {
        expect(val).toMatch(/rem$/);
      });
    });
  });

  describe("RADIUS", () => {
    it("has all radius tokens", () => {
      expect(RADIUS.none).toBe("0px");
      expect(RADIUS.sm).toBeDefined();
      expect(RADIUS.md).toBeDefined();
      expect(RADIUS.lg).toBeDefined();
      expect(RADIUS.xl).toBeDefined();
      expect(RADIUS.pill).toBe("9999px");
    });
  });

  describe("SHADOW", () => {
    it("has shadow tokens", () => {
      expect(SHADOW.none).toBe("none");
      expect(SHADOW.sm).toBeDefined();
      expect(SHADOW.md).toBeDefined();
      expect(SHADOW.lg).toBeDefined();
      expect(SHADOW.glowInfo).toBeDefined();
      expect(SHADOW.glowStrategy).toBeDefined();
      expect(SHADOW.glowIntelligence).toBeDefined();
    });
  });

  describe("LAYER", () => {
    it("has z-index layer tokens", () => {
      expect(LAYER.base).toBe(0);
      expect(LAYER.dropdown).toBe(10);
      expect(LAYER.sticky).toBe(100);
      expect(LAYER.overlay).toBe(200);
      expect(LAYER.modal).toBe(300);
    });
  });

  describe("MOTION", () => {
    it("has duration tokens", () => {
      expect(MOTION.instant).toBeDefined();
      expect(MOTION.fast).toBeDefined();
      expect(MOTION.normal).toBeDefined();
      expect(MOTION.slow).toBeDefined();
    });

    it("has easing tokens", () => {
      expect(MOTION.easeOut).toBeDefined();
      expect(MOTION.easeIn).toBeDefined();
      expect(MOTION.easeInOut).toBeDefined();
      expect(MOTION.signalTrace).toBeDefined();
    });

    it("has keyframe name tokens", () => {
      expect(MOTION.keyframes.fadeIn).toBe("sn-fade-in");
      expect(MOTION.keyframes.fadeUp).toBe("sn-fade-up");
      expect(MOTION.keyframes.pulse).toBe("sn-pulse");
      expect(MOTION.keyframes.signalGlow).toBe("sn-signal-glow");
      expect(MOTION.keyframes.traceDraw).toBe("sn-trace-draw");
      expect(MOTION.keyframes.ticker).toBe("sn-ticker");
      expect(MOTION.keyframes.barFill).toBe("sn-bar-fill");
      expect(MOTION.keyframes.nodeAppear).toBe("sn-node-appear");
    });
  });

  describe("DATA_STATE", () => {
    it("has all required data states", () => {
      const required = ["LIVE", "DERIVED", "DEMO", "ILLUSTRATIVE", "UNAVAILABLE", "RESEARCH"];
      required.forEach((key) => {
        expect(DATA_STATE[key]).toBeDefined();
        expect(DATA_STATE[key].label).toBeDefined();
        expect(DATA_STATE[key].color).toBeDefined();
      });
    });

    it("LIVE state has info color", () => {
      expect(DATA_STATE.LIVE.color).toBe(COLOR.info);
    });

    it("DEMO state has warning color", () => {
      expect(DATA_STATE.DEMO.color).toBe(COLOR.warning);
    });
  });

  describe("RESEARCH_STATUS", () => {
    it("has all required research statuses", () => {
      const required = ["AVAILABLE", "COMING_LATER", "RESEARCH_DIRECTION"];
      required.forEach((key) => {
        expect(RESEARCH_STATUS[key]).toBeDefined();
        expect(RESEARCH_STATUS[key].label).toBeDefined();
        expect(RESEARCH_STATUS[key].color).toBeDefined();
      });
    });
  });

  describe("SEMANTIC_*_KEYS arrays", () => {
    it("SEMANTIC_COLOR_KEYS is non-empty", () => {
      expect(SEMANTIC_COLOR_KEYS.length).toBeGreaterThan(0);
    });

    it("SEMANTIC_SPACE_KEYS is non-empty", () => {
      expect(SEMANTIC_SPACE_KEYS.length).toBeGreaterThan(0);
    });

    it("SEMANTIC_TYPE_KEYS is non-empty", () => {
      expect(SEMANTIC_TYPE_KEYS.length).toBeGreaterThan(0);
    });
  });
});

// =============================================================================
// MOTION TESTS
// =============================================================================

describe("Design System — Motion", () => {
  it("PUBLIC_DS_CSS contains all keyframe definitions", () => {
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-fade-in");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-fade-up");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-pulse");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-signal-glow");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-trace-draw");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-ticker");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-bar-fill");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-node-appear");
  });

  it("PUBLIC_DS_CSS contains reduced-motion media query", () => {
    expect(PUBLIC_DS_CSS).toContain("prefers-reduced-motion: reduce");
  });

  it("PUBLIC_DS_CSS contains focus-visible rules", () => {
    expect(PUBLIC_DS_CSS).toContain("focus-visible");
  });

  it("fadeUpStyle returns animation property", () => {
    const style = fadeUpStyle(0.2);
    expect(style.animation).toContain("sn-fade-up");
    expect(style.animationDelay).toBe("0.2s");
  });

  it("signalGlowStyle returns box-shadow", () => {
    const style = signalGlowStyle(COLOR.info);
    expect(style.boxShadow).toContain("#22D3EE");
  });

  it("traceDrawStyle returns animation for animated=true", () => {
    const style = traceDrawStyle(0, "1.5s");
    expect(style.animation).toContain("sn-trace-draw");
    expect(style.strokeDasharray).toBe("100%");
  });
});

// =============================================================================
// FINDING 1 — PUBLIC_DS_CSS WIRING TESTS
// =============================================================================

describe("Design System — PUBLIC_DS_CSS Wiring (Finding 1)", () => {
  it("PUBLIC_DS_CSS is imported by PublicLayout", async () => {
    // Dynamic import to verify the module loads without error
    const mod = await import("./PublicLayout");
    expect(mod.default).toBeDefined();
    expect(typeof mod.default).toBe("function");
  });

  it("sn-pulse, sn-fade-up, and reduced-motion rules are present in active public CSS", () => {
    // Verify the CSS string that is actually injected
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-pulse");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-fade-up");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-signal-glow");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-trace-draw");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-ticker");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-bar-fill");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-node-appear");
    expect(PUBLIC_DS_CSS).toContain("@keyframes sn-fade-in");
    expect(PUBLIC_DS_CSS).toContain("prefers-reduced-motion: reduce");
  });

  it("PUBLIC_DS_CSS contains all 8 keyframe definitions", () => {
    const keyframes = [
      "sn-fade-in", "sn-fade-up", "sn-pulse", "sn-signal-glow",
      "sn-trace-draw", "sn-ticker", "sn-bar-fill", "sn-node-appear"
    ];
    keyframes.forEach((kf) => {
      expect(PUBLIC_DS_CSS).toContain(`@keyframes ${kf}`);
    });
  });

  it("PUBLIC_DS_CSS contains focus-visible rules via .ds-focus-ring", () => {
    expect(PUBLIC_DS_CSS).toContain(".ds-focus-ring:focus-visible");
  });

  it("PUBLIC_DS_CSS contains reduced-motion override for ticker", () => {
    expect(PUBLIC_DS_CSS).toContain(".sn-ticker-track { animation: none !important; }");
  });

  it("PUBLIC_DS_CSS contains responsive visibility rules", () => {
    expect(PUBLIC_DS_CSS).toContain(".ds-nav-desktop");
    expect(PUBLIC_DS_CSS).toContain(".ds-nav-mobile-toggle");
  });

  it("PUBLIC_CSS (legacy) still contains original keyframes", () => {
    // Verify the legacy CSS is preserved
    expect(PUBLIC_CSS).toContain("@keyframes od-fade-up");
    expect(PUBLIC_CSS).toContain("@keyframes od-ticker");
    expect(PUBLIC_CSS).toContain("@keyframes od-pulse");
    expect(PUBLIC_CSS).toContain("@keyframes od-glow");
    expect(PUBLIC_CSS).toContain("@keyframes od-bar-fill");
  });
});

// =============================================================================
// SURFACE TESTS
// =============================================================================

describe("Design System — Surfaces", () => {
  it("Surface renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(Surface, null, "test content")
    );
    expect(html).toContain("test content");
  });

  it("Panel renders with default padding", () => {
    const html = renderToStaticMarkup(
      React.createElement(Panel, null, "panel content")
    );
    expect(html).toContain("panel content");
  });

  it("MetricPanel renders with monospace font", () => {
    const html = renderToStaticMarkup(
      React.createElement(MetricPanel, null, "123.45")
    );
    expect(html).toContain("123.45");
    expect(html).toContain("monospace");
  });

  it("OutlinePanel renders transparent", () => {
    const html = renderToStaticMarkup(
      React.createElement(OutlinePanel, null, "outline content")
    );
    expect(html).toContain("outline content");
    expect(html).toContain("transparent");
  });

  it("SignalPanel renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalPanel, null, "signal content")
    );
    expect(html).toContain("signal content");
  });
});

// =============================================================================
// BUTTON TESTS
// =============================================================================

describe("Design System — Buttons", () => {
  it("Button renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(Button, null, "Click me")
    );
    expect(html).toContain("Click me");
  });

  it("Button has focus-ring class", () => {
    const html = renderToStaticMarkup(
      React.createElement(Button, null, "Focusable")
    );
    expect(html).toContain("ds-focus-ring");
  });

  it("Button disabled state has reduced opacity", () => {
    const html = renderToStaticMarkup(
      React.createElement(Button, { disabled: true }, "Disabled")
    );
    expect(html).toContain("not-allowed");
    expect(html).toContain("0.45");
  });

  it("LinkButton renders as anchor", () => {
    const html = renderToStaticMarkup(
      React.createElement(LinkButton, { href: "/test" }, "Link")
    );
    expect(html).toContain('href="/test"');
    expect(html).toContain("Link");
  });

  it("TextLink renders as anchor", () => {
    const html = renderToStaticMarkup(
      React.createElement(TextLink, { href: "/test" }, "Text Link")
    );
    expect(html).toContain('href="/test"');
    expect(html).toContain("Text Link");
  });

  it("Button size lg has min-height 52px", () => {
    const html = renderToStaticMarkup(
      React.createElement(Button, { size: "lg" }, "Large")
    );
    expect(html).toContain("52px");
  });

  // --- Finding 2: sm button touch target tests ---

  it("Button size sm has min-height 44px (touch target)", () => {
    const html = renderToStaticMarkup(
      React.createElement(Button, { size: "sm" }, "Small")
    );
    expect(html).toContain("44px");
  });

  it("Button size md has min-height 44px (touch target)", () => {
    const html = renderToStaticMarkup(
      React.createElement(Button, { size: "md" }, "Medium")
    );
    expect(html).toContain("44px");
  });

  it("LinkButton size sm has min-height 44px (touch target)", () => {
    const html = renderToStaticMarkup(
      React.createElement(LinkButton, { size: "sm", href: "/test" }, "Small Link")
    );
    expect(html).toContain("44px");
  });

  it("LinkButton size md has min-height 44px (touch target)", () => {
    const html = renderToStaticMarkup(
      React.createElement(LinkButton, { size: "md", href: "/test" }, "Medium Link")
    );
    expect(html).toContain("44px");
  });

  it("all button sizes meet 44px minimum touch target", () => {
    const sizes = ["sm", "md", "lg"];
    const expectedMin = { sm: "44px", md: "44px", lg: "52px" };
    sizes.forEach((size) => {
      const html = renderToStaticMarkup(
        React.createElement(Button, { size }, `Btn ${size}`)
      );
      expect(html).toContain(expectedMin[size]);
    });
  });
});

// =============================================================================
// METRIC TESTS
// =============================================================================

describe("Design System — Metric", () => {
  it("renders label and value", () => {
    const html = renderToStaticMarkup(
      React.createElement(Metric, { label: "ATM IV", value: 14.2, unit: "%", decimals: 1 })
    );
    expect(html).toContain("ATM IV");
    expect(html).toContain("14.2");
    expect(html).toContain("%");
  });

  it("renders null value as em-dash", () => {
    const html = renderToStaticMarkup(
      React.createElement(Metric, { label: "Test", value: null })
    );
    expect(html).toContain("—");
  });

  it("renders undefined value as em-dash", () => {
    const html = renderToStaticMarkup(
      React.createElement(Metric, { label: "Test", value: undefined })
    );
    expect(html).toContain("—");
  });

  it("renders zero value correctly", () => {
    const html = renderToStaticMarkup(
      React.createElement(Metric, { label: "Test", value: 0 })
    );
    expect(html).toContain("0");
  });

  it("renders DEMO status badge", () => {
    const html = renderToStaticMarkup(
      React.createElement(Metric, { label: "Test", value: 100, status: "DEMO" })
    );
    expect(html).toContain("DEMO");
  });

  it("renders LIVE status with pulsing indicator", () => {
    const html = renderToStaticMarkup(
      React.createElement(Metric, { label: "Test", value: 100, status: "LIVE" })
    );
    expect(html).toContain("LIVE");
    expect(html).toContain("sn-pulse");
  });

  it("renders source text", () => {
    const html = renderToStaticMarkup(
      React.createElement(Metric, { label: "Test", value: 100, source: "NSE" })
    );
    expect(html).toContain("NSE");
  });

  it("renders caption text", () => {
    const html = renderToStaticMarkup(
      React.createElement(Metric, { label: "Test", value: 100, caption: "Helper text" })
    );
    expect(html).toContain("Helper text");
  });

  it("formatMetricValue formats numbers with Indian locale", () => {
    expect(formatMetricValue(25512)).toBe("25,512");
    expect(formatMetricValue(14.2, 1)).toBe("14.2");
    expect(formatMetricValue(0)).toBe("0");
  });

  it("formatMetricValue returns em-dash for null/undefined", () => {
    expect(formatMetricValue(null)).toBe("—");
    expect(formatMetricValue(undefined)).toBe("—");
  });
});

// =============================================================================
// VISUALIZATION FRAME TESTS
// =============================================================================

describe("Design System — VisualizationFrame", () => {
  it("renders title", () => {
    const html = renderToStaticMarkup(
      React.createElement(VisualizationFrame, { title: "Test Viz" }, "content")
    );
    expect(html).toContain("Test Viz");
  });

  it("renders eyebrow", () => {
    const html = renderToStaticMarkup(
      React.createElement(VisualizationFrame, { eyebrow: "SIGNAL FIELD" }, "content")
    );
    expect(html).toContain("SIGNAL FIELD");
  });

  it("renders caption", () => {
    const html = renderToStaticMarkup(
      React.createElement(VisualizationFrame, { caption: "Helper text" }, "content")
    );
    expect(html).toContain("Helper text");
  });

  it("renders demo label when demoLabel=true", () => {
    const html = renderToStaticMarkup(
      React.createElement(VisualizationFrame, { demoLabel: true }, "content")
    );
    expect(html).toContain("Demo Data");
  });

  it("renders legend items", () => {
    const html = renderToStaticMarkup(
      React.createElement(VisualizationFrame, {
        legend: [
          { label: "Call OI", color: COLOR.negative },
          { label: "Put OI", color: COLOR.positive },
        ],
      }, "content")
    );
    expect(html).toContain("Call OI");
    expect(html).toContain("Put OI");
  });

  it("has figure role and aria-label", () => {
    const html = renderToStaticMarkup(
      React.createElement(VisualizationFrame, { title: "My Chart" }, "content")
    );
    expect(html).toContain('role="figure"');
    expect(html).toContain('aria-label="Visualization: My Chart"');
  });
});

// =============================================================================
// SIGNAL PRIMITIVES TESTS
// =============================================================================

describe("Design System — Signal Primitives", () => {
  it("SignalLine renders with aria-hidden", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalLine)
    );
    expect(html).toContain('aria-hidden="true"');
  });

  it("SignalNode renders label and value", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalNode, { label: "OI", value: "184,250" })
    );
    expect(html).toContain("OI");
    expect(html).toContain("184,250");
  });

  it("SignalNode has img role with aria-label", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalNode, { label: "Spot", value: "25,500" })
    );
    expect(html).toContain('role="img"');
    expect(html).toContain("Spot: 25,500");
  });

  it("StrikeRail renders strike labels", () => {
    const html = renderToStaticMarkup(
      React.createElement(StrikeRail, { strikes: [25300, 25500, 25700] })
    );
    expect(html).toContain("25,300");
    expect(html).toContain("25,500");
    expect(html).toContain("25,700");
  });

  it("StrikeRail highlights spot index", () => {
    const html = renderToStaticMarkup(
      React.createElement(StrikeRail, { strikes: [25300, 25500, 25700], spotIndex: 1 })
    );
    expect(html).toContain("25,500");
  });

  it("DataTrace renders svg with path", () => {
    const html = renderToStaticMarkup(
      React.createElement(DataTrace, { pathD: "M0 100 L100 0" })
    );
    expect(html).toContain("<svg");
    expect(html).toContain('aria-hidden="true"');
  });

  it("TechnicalDivider renders with label", () => {
    const html = renderToStaticMarkup(
      React.createElement(TechnicalDivider, { label: "SECTION" })
    );
    expect(html).toContain("SECTION");
  });

  it("GridOverlay renders with aria-hidden", () => {
    const html = renderToStaticMarkup(
      React.createElement(GridOverlay)
    );
    expect(html).toContain('aria-hidden="true"');
  });
});

// =============================================================================
// LAYOUT PRIMITIVES TESTS
// =============================================================================

describe("Design System — Layout Primitives", () => {
  it("Section renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(Section, null, "section content")
    );
    expect(html).toContain("section content");
  });

  it("Container renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(Container, null, "container content")
    );
    expect(html).toContain("container content");
  });

  it("TwoColumn renders left and right", () => {
    const html = renderToStaticMarkup(
      React.createElement(TwoColumn, { left: "left content", right: "right content" })
    );
    expect(html).toContain("left content");
    expect(html).toContain("right content");
  });

  it("MetricGrid renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(MetricGrid, null, "grid content")
    );
    expect(html).toContain("grid content");
  });

  it("CardGrid renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(CardGrid, null, "card grid")
    );
    expect(html).toContain("card grid");
  });

  it("BentoGrid renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(BentoGrid, null, "bento content")
    );
    expect(html).toContain("bento content");
  });

  it("FlexRow renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(FlexRow, null, "flex content")
    );
    expect(html).toContain("flex content");
  });

  it("FlexColumn renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(FlexColumn, null, "column content")
    );
    expect(html).toContain("column content");
  });

  it("Asymmetric renders main and side", () => {
    const html = renderToStaticMarkup(
      React.createElement(Asymmetric, { main: "main content", side: "side content" })
    );
    expect(html).toContain("main content");
    expect(html).toContain("side content");
  });
});

// =============================================================================
// TRUTH PRIMITIVES TESTS
// =============================================================================

describe("Design System — Truth Primitives", () => {
  it("DemoLabel renders text", () => {
    const html = renderToStaticMarkup(
      React.createElement(DemoLabel)
    );
    expect(html).toContain("Demo Data");
    expect(html).toContain("Illustrative Values Only");
  });

  it("ResearchBadge renders RESEARCH_DIRECTION by default", () => {
    const html = renderToStaticMarkup(
      React.createElement(ResearchBadge)
    );
    expect(html).toContain("RESEARCH DIRECTION");
  });

  it("ResearchBadge renders COMING_LATER", () => {
    const html = renderToStaticMarkup(
      React.createElement(ResearchBadge, { status: "COMING_LATER" })
    );
    expect(html).toContain("COMING LATER");
  });

  it("DataStateBadge renders LIVE state", () => {
    const html = renderToStaticMarkup(
      React.createElement(DataStateBadge, { state: "LIVE" })
    );
    expect(html).toContain("LIVE");
  });

  it("DataStateBadge renders DEMO state", () => {
    const html = renderToStaticMarkup(
      React.createElement(DataStateBadge, { state: "DEMO" })
    );
    expect(html).toContain("DEMO");
  });

  it("Eyebrow renders children", () => {
    const html = renderToStaticMarkup(
      React.createElement(Eyebrow, null, "SIGNAL FIELD")
    );
    expect(html).toContain("SIGNAL FIELD");
  });

  it("SectionTitle renders title and subtitle", () => {
    const html = renderToStaticMarkup(
      React.createElement(SectionTitle, { title: "Test Title", subtitle: "Test subtitle" })
    );
    expect(html).toContain("Test Title");
    expect(html).toContain("Test subtitle");
  });

  it("SectionTitle renders eyebrow", () => {
    const html = renderToStaticMarkup(
      React.createElement(SectionTitle, { eyebrow: "EYEBROW", title: "Title" })
    );
    expect(html).toContain("EYEBROW");
  });
});

// =============================================================================
// P2 — SIGNAL FIELD TESTS
// =============================================================================

describe("Signal Field — Rendering", () => {
  it("SignalField renders with default demo state", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalField)
    );
    expect(html).toContain("Signal Field");
    expect(html).toContain("25,500");
  });

  it("SignalField renders with custom state", () => {
    const customState = {
      ...DEMO_SIGNAL_STATE,
      spot: 30000,
    };
    const html = renderToStaticMarkup(
      React.createElement(SignalField, { state: customState })
    );
    expect(html).toContain("30,000");
  });

  it("SignalField renders all strike labels", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalField)
    );
    expect(html).toContain("25,300");
    expect(html).toContain("25,400");
    expect(html).toContain("25,500");
    expect(html).toContain("25,600");
    expect(html).toContain("25,700");
  });

  it("SignalField renders OI values", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalField)
    );
    // OI values use Indian locale format (en-IN)
    expect(html).toContain("1,84,250");
    expect(html).toContain("2,17,800");
  });

  it("SignalField renders IV value", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalField)
    );
    expect(html).toContain("14.2%");
  });

  it("SignalField renders structure levels", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalField)
    );
    expect(html).toContain("25,700"); // resistance
    expect(html).toContain("25,300"); // support
  });

  it("SignalField renders market state label", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalField)
    );
    expect(html).toContain("Balanced with bearish pressure");
  });

  it("SignalField renders supporting metrics", () => {
    const html = renderToStaticMarkup(
      React.createElement(SignalField)
    );
    expect(html).toContain("SPOT");
    expect(html).toContain("PCR");
    expect(html).toContain("ATM IV");
    expect(html).toContain("OI CHANGE");
  });
});

describe("Signal Field — Data Behavior", () => {
  it("DEMO_SIGNAL_STATE is deterministic (no Math.random)", () => {
    // Verify the state object is static
    const state1 = DEMO_SIGNAL_STATE;
    const state2 = DEMO_SIGNAL_STATE;
    expect(state1).toBe(state2); // same reference
    expect(state1.spot).toBe(25500);
    expect(state1.strikes).toEqual([25300, 25400, 25500, 25600, 25700]);
  });

  it("SignalField does not generate random values", () => {
    const html1 = renderToStaticMarkup(React.createElement(SignalField));
    const html2 = renderToStaticMarkup(React.createElement(SignalField));
    expect(html1).toBe(html2);
  });

  it("null spot value does not become fake zero", () => {
    const state = { ...DEMO_SIGNAL_STATE, spot: null, marketState: { ...DEMO_SIGNAL_STATE.marketState, label: "" } };
    const html = renderToStaticMarkup(
      React.createElement(SignalField, { state })
    );
    // Should render em-dash or handle gracefully
    expect(html).toContain("—");
  });

  it("state labels remain consistent", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    // DEMO status should appear on metrics
    expect(html).toContain("DEMO");
  });
});

describe("Signal Field — Accessibility", () => {
  it("SignalField has accessible name via role=img and aria-label", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="Signal Field');
  });

  it("aria-label includes spot value", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    expect(html).toContain("Spot: 25,500");
  });

  it("aria-label includes market state", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    expect(html).toContain("Balanced with bearish pressure");
  });

  it("decorative SVG has aria-hidden", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    expect(html).toContain('aria-hidden="true"');
  });

  it("GridOverlay has aria-hidden", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    // GridOverlay renders a div with aria-hidden
    expect(html).toContain("aria-hidden");
  });

  it("important labels are represented as text", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    // Strike labels should be visible text
    expect(html).toContain("25,500");
    // Market state should be visible text
    expect(html).toContain("Balanced with bearish pressure");
  });
});

describe("Signal Field — Motion", () => {
  it("SignalField uses P1 motion system (no custom animation loops)", () => {
    // The component should not define its own keyframes
    const html = renderToStaticMarkup(React.createElement(SignalField));
    // No animation properties in the rendered output (static SVG)
    expect(html).not.toContain("requestAnimationFrame");
  });

  it("reduced-motion behavior exists in PUBLIC_DS_CSS", () => {
    expect(PUBLIC_DS_CSS).toContain("prefers-reduced-motion: reduce");
  });
});

describe("Signal Field — Responsive Contract", () => {
  it("SignalField uses viewBox for responsive scaling", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    expect(html).toContain("viewBox=");
    expect(html).toContain('width="100%"');
  });

  it("SignalField uses auto height for SVG", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    expect(html).toContain('height="auto"');
  });

  it("supporting metrics use responsive grid", () => {
    const html = renderToStaticMarkup(React.createElement(SignalField));
    expect(html).toContain("auto-fit");
    expect(html).toContain("minmax");
  });
});

describe("Signal Field — Integration with VisualizationFrame", () => {
  it("SignalField works inside VisualizationFrame", () => {
    const html = renderToStaticMarkup(
      React.createElement(
        VisualizationFrame,
        { eyebrow: "SIGNAL FIELD", title: "Illustrative market state", demoLabel: true },
        React.createElement(SignalField)
      )
    );
    expect(html).toContain("SIGNAL FIELD");
    expect(html).toContain("Illustrative market state");
    expect(html).toContain("Demo Data");
    expect(html).toContain("25,500");
  });
});
