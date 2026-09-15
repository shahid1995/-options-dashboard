import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { evidenceTrustContent } from "./EvidenceTrustContent";

// Mock next/link before importing the component
vi.mock("next/link", () => ({
  default: ({ children, ...props }) => React.createElement("a", props, children),
}));

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import EvidenceTrustSection from "./EvidenceTrustSection";

const SECTION_MARKER = "EVIDENCE & TRUST";
const PAPER_TRADING_MARKER = "Paper Trading Only";
const UNCERTAINTY_MARKER = "Uncertainty Is Inherent";

describe("EvidenceTrustContent", () => {
  describe("content contract", () => {
    it('should have eyebrow text "EVIDENCE & TRUST"', () => {
      expect(evidenceTrustContent.eyebrow).toBe("EVIDENCE & TRUST");
    });

    it("should have paper-trading boundary statement", () => {
      const paperPoint = evidenceTrustContent.points.find(p => p.title === "Paper Trading Only");
      expect(paperPoint).toBeDefined();
      expect(paperPoint.body).toContain("paper-only");
      expect(paperPoint.body).toContain("No real capital is at risk");
    });

    it("should have uncertainty/risk statement", () => {
      const uncertaintyPoint = evidenceTrustContent.points.find(p => p.title === "Uncertainty Is Inherent");
      expect(uncertaintyPoint).toBeDefined();
      expect(uncertaintyPoint.body).toContain("uncertain");
      expect(uncertaintyPoint.body).toContain("risk");
    });

    it("should have decision-support framing", () => {
      const decisionPoint = evidenceTrustContent.points.find(p => p.title === "Decision-Support, Not Decision-Making");
      expect(decisionPoint).toBeDefined();
      expect(decisionPoint.body).toContain("trading decision is always yours");
    });

    it("should have transparency language", () => {
      const transparencyPoint = evidenceTrustContent.points.find(p => p.title === "Transparency Over Hype");
      expect(transparencyPoint).toBeDefined();
      expect(transparencyPoint.body).toContain("methods, assumptions, and limitations");
    });

    it("should NOT claim guaranteed accuracy", () => {
      const allText = JSON.stringify(evidenceTrustContent).toLowerCase();
      expect(allText).not.toContain("guaranteed accuracy");
      expect(allText).not.toContain("guaranteed returns");
    });

    it("should NOT claim live trading capability", () => {
      const allText = JSON.stringify(evidenceTrustContent).toLowerCase();
      expect(allText).not.toContain("live trading");
    });

    it("should NOT claim prediction capability", () => {
      const allText = JSON.stringify(evidenceTrustContent).toLowerCase();
      expect(allText).not.toContain("predict the market");
    });

    it("should have CTA linking to /about", () => {
      expect(evidenceTrustContent.ctaHref).toBe("/about");
      expect(evidenceTrustContent.ctaLabel).toContain("Learn More");
    });

    it("should have disclaimer about paper trading", () => {
      expect(evidenceTrustContent.disclaimer).toContain("paper-trading");
      expect(evidenceTrustContent.disclaimer).toContain("hypothetical");
    });

    it("should have exactly 4 points", () => {
      expect(evidenceTrustContent.points).toHaveLength(4);
    });

    it("should NOT use technical jargon in trust messaging", () => {
      const allText = JSON.stringify(evidenceTrustContent).toLowerCase();
      expect(allText).not.toContain("bsm");
      expect(allText).not.toContain("greeks engine");
    });
  });
});

describe("EvidenceTrustSection component", () => {
  it("renders without errors", () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    expect(html).toBeTruthy();
  });

  it('renders "EVIDENCE & TRUST" eyebrow text', () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    expect(html).toContain("EVIDENCE &amp; TRUST");
  });

  it("renders paper-trading boundary statement", () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    expect(html).toContain("Paper Trading Only");
    expect(html).toContain("paper-only");
  });

  it("renders uncertainty/risk disclaimer", () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    expect(html).toContain("Uncertainty Is Inherent");
    expect(html).toContain("inherently uncertain");
  });

  it("renders decision-support framing", () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    expect(html).toContain("Decision-Support, Not Decision-Making");
    expect(html).toContain("trading decision is always yours");
  });

  it("renders transparency language", () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    expect(html).toContain("Transparency Over Hype");
  });

  it("renders CTA link to /about", () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    expect(html).toContain('href="/about"');
    expect(html).toContain("Learn More About StrikeNova");
  });

  it("does NOT render claims of guaranteed accuracy or live trading", () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    const lower = html.toLowerCase();
    expect(lower).not.toContain("guaranteed accuracy");
    expect(lower).not.toContain("guaranteed returns");
    expect(lower).not.toContain("live trading");
  });

  it("renders exactly 4 point cards", () => {
    const html = renderToStaticMarkup(React.createElement(EvidenceTrustSection));
    const pointTitles = ["Decision-Support", "Paper Trading Only", "Transparency", "Uncertainty Is Inherent"];
    pointTitles.forEach(title => {
      expect(html).toContain(title);
    });
  });
});
