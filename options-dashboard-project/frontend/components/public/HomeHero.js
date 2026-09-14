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
    <header
      style={{
        position: "relative",
        overflow: "hidden",
        background: COLOR.baseElevated,
      }}
    >
      {/* Subtle grid overlay - restrained, no gradient glow */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `linear-gradient(${COLOR.borderSubtle} 1px, transparent 1px), linear-gradient(90deg, ${COLOR.borderSubtle} 1px, transparent 1px)`,
          backgroundSize: "40px 40px",
          maskImage: "radial-gradient(ellipse 80% 60% at 50% 50%, black 30%, transparent 70%)",
          WebkitMaskImage: "radial-gradient(ellipse 80% 60% at 50% 50%, black 30%, transparent 70%)",
          pointerEvents: "none",
          opacity: 0.5,
        }}
      />

      {/* Subtle corner accent lines */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 120,
          height: 120,
          borderTop: `1px solid ${COLOR.strategy}`,
          borderLeft: `1px solid ${COLOR.strategy}`,
          borderTopLeftRadius: RADIUS.lg,
          opacity: 0.3,
          pointerEvents: "none",
        }}
      />
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          bottom: 0,
          right: 0,
          width: 120,
          height: 120,
          borderBottom: `1px solid ${COLOR.border}`,
          borderRight: `1px solid ${COLOR.border}`,
          borderBottomRightRadius: RADIUS.lg,
          opacity: 0.2,
          pointerEvents: "none",
        }}
      />

      <div
        className="sn-fade"
        style={{
          position: "relative",
          maxWidth: 1000,
          margin: "0 auto",
          padding: isMobile ? `${SPACE.sectionLg} ${SPACE.compLg}` : `${SPACE.hero} ${SPACE.compLg}`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: SPACE.cardLg,
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

        {/* H1 - restrained, no colored accent span */}
        <h1
          style={{
            margin: 0,
            fontSize: TYPE.displayH1.size,
            lineHeight: TYPE.displayH1.lineHeight,
            fontWeight: TYPE.displayH1.weight,
            letterSpacing: TYPE.displayH1.letterSpacing,
            color: COLOR.textPrimary,
            textAlign: "center",
            maxWidth: "18ch",
          }}
        >
          Options Intelligence
          <br />
          <span style={{ color: COLOR.textSecondary }}>for Structured Decisions.</span>
        </h1>

        {/* Supporting message */}
        <p
          style={{
            color: COLOR.textMuted,
            fontSize: TYPE.bodyLarge.size,
            lineHeight: TYPE.bodyLarge.lineHeight,
            textAlign: "center",
            maxWidth: "42ch",
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
            className="ds-focus-ring"
            style={{ minWidth: 200 }}
          >
            Explore StrikeNova <span aria-hidden="true">→</span>
          </LinkButton>
          <LinkButton
            variant="secondary"
            size="lg"
            href="/strategy-lab"
            className="ds-focus-ring"
          >
            Strategy Lab
          </LinkButton>
        </div>
      </div>
    </header>
  );
}
