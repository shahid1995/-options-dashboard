// =============================================================================
// HomeHero — Premium hero composition with branding, tagline, CTAs
// =============================================================================
"use client";
import React from "react";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "@/components/public/tokens";
import { LinkButton } from "@/components/public/buttons";
import { useIsMobile } from "@/lib/ui";

export default function HomeHero({ onGetStarted }) {
  const isMobile = useIsMobile();

  return (
    <header style={{ position: "relative", overflow: "hidden" }}>
      {/* Background gradient */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse 50% 40% at 20% 10%, ${COLOR.strategyDim}, transparent 60%),
                       radial-gradient(ellipse 40% 30% at 80% 80%, ${COLOR.intelligenceDim}, transparent 60%),
                       linear-gradient(180deg, ${COLOR.base}, ${COLOR.baseElevated})`,
          pointerEvents: "none",
        }}
      />

      <div
        style={{
          position: "relative",
          maxWidth: 1100,
          margin: "0 auto",
          padding: isMobile ? `${SPACE.sectionLg} 1.25rem` : `${SPACE.hero} 1.25rem`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: SPACE.section,
        }}
      >
        {/* Brand mark */}
        <span
          style={{
            fontSize: TYPE.labelSmall.size,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
          }}
        >
          StrikeNova
        </span>

        {/* H1 */}
        <h1
          style={{
            margin: 0,
            fontSize: TYPE.displayH1.size,
            lineHeight: TYPE.displayH1.lineHeight,
            fontWeight: TYPE.displayH1.weight,
            letterSpacing: TYPE.displayH1.letterSpacing,
            color: COLOR.textPrimary,
            textAlign: "center",
            maxWidth: "20ch",
          }}
          className="sn-fade"
        >
          OPTIONS INTELLIGENCE
          <br />
          <span style={{ color: COLOR.strategy }}>FOR STRUCTURED DECISIONS.</span>
        </h1>

        {/* Supporting message */}
        <p
          style={{
            color: COLOR.textSecondary,
            fontSize: TYPE.bodyLarge.size,
            lineHeight: TYPE.bodyLarge.lineHeight,
            textAlign: "center",
            maxWidth: "40ch",
            margin: 0,
          }}
        >
          See the forces behind the option chain.
          <br />
          Understand positioning, volatility and risk.
        </p>

        {/* CTAs — primary dominates */}
        <div
          style={{
            display: "flex",
            flexDirection: isMobile ? "column" : "row",
            alignItems: "center",
            gap: SPACE.comp,
            marginTop: SPACE.comp,
          }}
        >
          <LinkButton
            variant="primary"
            size="lg"
            href="/features"
            style={{ minWidth: 200 }}
          >
            Explore StrikeNova <span aria-hidden>→</span>
          </LinkButton>
          <LinkButton variant="secondary" size="lg" href="/strategy-lab">
            Strategy Lab
          </LinkButton>
        </div>
      </div>
    </header>
  );
}
