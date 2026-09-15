// =============================================================================
// HomeHero — Homepage V2 hero: clear product promise + visible analytical system
// =============================================================================
"use client";
import React from "react";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
import { LinkButton } from "@/components/public/buttons";
import { useIsMobile } from "@/lib/ui";
import PrimaryCTA from "./PrimaryCTA";
import SecondaryCTA from "./SecondaryCTA";

function HeroSignal({ label, value, detail, emphasis }) {
  return (
    <div
      style={{
        minWidth: 0,
        padding: SPACE.comp,
        border: `1px solid ${COLOR.border}`,
        background: COLOR.surface,
        borderRadius: RADIUS.md,
      }}
    >
      <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint, letterSpacing: "0.08em" }}>
        {label}
      </div>
      <div
        style={{
          marginTop: SPACE.xs,
          fontFamily: TYPE.data,
          fontSize: TYPE.data.size,
          fontWeight: 700,
          color: emphasis || COLOR.textPrimary,
        }}
      >
        {value}
      </div>
      <div style={{ marginTop: SPACE.xs, fontSize: TYPE.caption.size, color: COLOR.textMuted }}>
        {detail}
      </div>
    </div>
  );
}

export default function HomeHero({ onGetStarted }) {
  const isMobile = useIsMobile();

  return (
    <header
      style={{
        position: "relative",
        overflow: "hidden",
        background: COLOR.base,
        borderBottom: `1px solid ${COLOR.border}`,
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `linear-gradient(${COLOR.borderSubtle} 1px, transparent 1px), linear-gradient(90deg, ${COLOR.borderSubtle} 1px, transparent 1px)`,
          backgroundSize: "48px 48px",
          maskImage: "linear-gradient(to bottom, black 0%, transparent 78%)",
          WebkitMaskImage: "linear-gradient(to bottom, black 0%, transparent 78%)",
          opacity: 0.42,
          pointerEvents: "none",
        }}
      />

      <div
        style={{
          position: "relative",
          maxWidth: 1200,
          margin: "0 auto",
          padding: isMobile ? `${SPACE.sectionLg} ${SPACE.compLg}` : `${SPACE.hero} ${SPACE.compLg} ${SPACE.sectionLg}`,
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "minmax(0, 1.05fr) minmax(360px, 0.95fr)",
          gap: isMobile ? SPACE.sectionLg : SPACE.section,
          alignItems: "center",
        }}
      >
        <div className="sn-fade">
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: SPACE.small,
              marginBottom: SPACE.compLg,
              color: COLOR.textFaint,
              fontSize: TYPE.labelSmall.size,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
            }}
          >
            <span
              aria-hidden="true"
              style={{ width: 7, height: 7, borderRadius: "50%", background: COLOR.strategy }}
            />
            Market Intelligence Command Center
          </div>

          <h1
            style={{
              margin: 0,
              fontSize: TYPE.displayH1.size,
              lineHeight: 1.02,
              fontWeight: TYPE.displayH1.weight,
              letterSpacing: TYPE.displayH1.letterSpacing,
              color: COLOR.textPrimary,
              maxWidth: "13ch",
            }}
          >
            See the market beneath the option chain.
          </h1>

          <p
            style={{
              margin: `${SPACE.compLg} 0 0`,
              color: COLOR.textMuted,
              fontSize: TYPE.bodyLarge.size,
              lineHeight: 1.7,
              maxWidth: "54ch",
            }}
          >
            StrikeNova brings positioning, volatility, Greeks, risk and strategy analysis into one structured decision workflow.
          </p>

          <div
            style={{
              display: "flex",
              flexDirection: isMobile ? "column" : "row",
              alignItems: isMobile ? "stretch" : "center",
              gap: SPACE.comp,
              marginTop: SPACE.cardLg,
            }}
          >
            <PrimaryCTA href="/features">
              Explore the Platform
            </PrimaryCTA>
            <SecondaryCTA href="/how-it-works">
              See How It Works
            </SecondaryCTA>
          </div>

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: SPACE.compLg,
              marginTop: SPACE.cardLg,
              color: COLOR.textFaint,
              fontSize: TYPE.caption.size,
            }}
          >
            <span>Market state</span>
            <span>Market structure</span>
            <span>Strategy</span>
            <span>Risk</span>
            <span>Paper execution</span>
          </div>
        </div>

        <div
          aria-label="Illustrative StrikeNova market intelligence preview"
          style={{
            padding: SPACE.comp,
            background: COLOR.surface,
            border: `1px solid ${COLOR.borderStrong || COLOR.border}`,
            borderRadius: RADIUS.lg,
            boxShadow: "0 24px 70px rgba(0, 0, 0, 0.20)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: `0 ${SPACE.small} ${SPACE.comp}`,
              borderBottom: `1px solid ${COLOR.border}`,
            }}
          >
            <div>
              <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint, letterSpacing: "0.08em" }}>NIFTY</div>
              <div style={{ marginTop: SPACE.xs, fontFamily: TYPE.data, fontWeight: 700, color: COLOR.textPrimary }}>25,500</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>MARKET STATE</div>
              <div style={{ marginTop: SPACE.xs, fontFamily: TYPE.dataSmall, fontWeight: 700, color: COLOR.info }}>BALANCED</div>
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(2, 1fr)",
              gap: SPACE.small,
              paddingTop: SPACE.comp,
            }}
          >
            <HeroSignal label="CALL OI" value="12.4M" detail="Concentration 25,600" />
            <HeroSignal label="PUT OI" value="11.1M" detail="Concentration 25,400" />
            <HeroSignal label="GEX" value="+18.4M" detail="Structure context" emphasis={COLOR.strategy} />
            <HeroSignal label="ATM IV" value="14.2%" detail="Implied volatility" />
          </div>

          <div
            style={{
              marginTop: SPACE.small,
              padding: `${SPACE.comp} ${SPACE.comp}`,
              border: `1px solid ${COLOR.border}`,
              borderRadius: RADIUS.md,
              background: COLOR.baseElevated,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: SPACE.comp }}>
              <span style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>GAMMA FLIP</span>
              <span style={{ fontFamily: TYPE.dataSmall, color: COLOR.textPrimary }}>25,470</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: SPACE.comp, marginTop: SPACE.small }}>
              <span style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>POSITIONING</span>
              <span style={{ fontFamily: TYPE.dataSmall, color: COLOR.info }}>BALANCED</span>
            </div>
          </div>

          <div
            style={{
              marginTop: SPACE.small,
              padding: `${SPACE.small} ${SPACE.comp}`,
              borderTop: `1px solid ${COLOR.border}`,
              color: COLOR.textFaint,
              fontSize: "0.625rem",
              letterSpacing: "0.04em",
            }}
          >
            Illustrative interface preview — not live market data.
          </div>
        </div>
      </div>

      <div
        style={{
          position: "relative",
          maxWidth: 1200,
          margin: "0 auto",
          padding: `0 ${SPACE.compLg} ${SPACE.compLg}`,
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)",
            gap: SPACE.small,
          }}
        >
          <div style={{ padding: SPACE.comp, borderTop: `1px solid ${COLOR.border}` }}>
            <div style={{ color: COLOR.textPrimary, fontWeight: 700 }}>From data</div>
            <div style={{ marginTop: SPACE.xs, color: COLOR.textMuted, fontSize: TYPE.caption.size }}>Option chain, OI, IV and Greeks.</div>
          </div>
          <div style={{ padding: SPACE.comp, borderTop: `1px solid ${COLOR.border}` }}>
            <div style={{ color: COLOR.textPrimary, fontWeight: 700 }}>To context</div>
            <div style={{ marginTop: SPACE.xs, color: COLOR.textMuted, fontSize: TYPE.caption.size }}>Market state and positioning structure.</div>
          </div>
          <div style={{ padding: SPACE.comp, borderTop: `1px solid ${COLOR.border}` }}>
            <div style={{ color: COLOR.textPrimary, fontWeight: 700 }}>To decisions</div>
            <div style={{ marginTop: SPACE.xs, color: COLOR.textMuted, fontSize: TYPE.caption.size }}>Strategy, payoff, risk and paper execution.</div>
          </div>
        </div>
      </div>
    </header>
  );
}
