"use client";

import {
  COLOR,
  TYPE,
  SPACE,
  RADIUS,
} from "@/components/public/tokens";
import {
  Section,
  Container,
  Asymmetric,
  FlexRow,
  FlexColumn,
  BentoGrid,
} from "@/components/public/layout";
import {
  Surface,
  Panel,
  SignalPanel,
  OutlinePanel,
} from "@/components/public/surfaces";
import {
  SignalLine,
  SignalNode,
  GridOverlay,
  TechnicalDivider,
  DataTrace,
} from "@/components/public/signals";
import {
  Button,
  LinkButton,
  TextLink,
} from "@/components/public/buttons";
import {
  DemoLabel,
  ResearchBadge,
  Eyebrow,
  SectionTitle,
} from "@/components/public/truth";
import {
  fadeUpStyle,
  traceDrawStyle,
} from "@/components/public/motion";
import { VisualizationFrame } from "@/components/public/VisualizationFrame";

// =============================================================================
// Capability Atlas Page — Redesign
// =============================================================================

const CAPABILITIES = [
  {
    id: "market-intelligence",
    label: "MARKET INTELLIGENCE",
    href: "/market-intelligence",
    color: COLOR.intelligence,
    accent: "intelligence",
    tagline: "Live positioning. Real-time signals.",
    description:
      "Full call/put chain with open interest, volume, IV and Greeks — streaming over WebSocket to show you what the market is doing right now.",
    metrics: [
      { label: "LIVE CHAIN", value: "STREAM" },
      { label: "OI TRACKING", value: "PER-STRIKE" },
      { label: "VOLATILITY", value: "IV SKEW" },
    ],
    highlights: [
      { label: "Option Chain", desc: "Call/put with LTP, OI, volume, IV and Greeks" },
      { label: "PCR", desc: "Put/Call ratio for directional sentiment" },
      { label: "Max Pain", desc: "Least-loss strike for option writers" },
    ],
  },
  {
    id: "strategy-lab",
    label: "STRATEGY LAB",
    href: "/strategy-lab",
    color: COLOR.strategy,
    accent: "strategy",
    tagline: "Build. Analyze. Test.",
    description:
      "Construct multi-leg strategies, run payoff analysis, stress-test under spot, IV and time shifts — with position Greeks and scenario modeling.",
    metrics: [
      { label: "TEMPLATES", value: "42" },
      { label: "PAYOFF", value: "VISUAL" },
      { label: "GREEKS", value: "AGGREGATE" },
    ],
    highlights: [
      { label: "Strategy Builder", desc: "Multi-leg strategies across strikes and expiries" },
      { label: "Payoff Analysis", desc: "Max profit, max loss and breakevens" },
      { label: "Scenario Testing", desc: "Stress-test under spot, IV and time changes" },
    ],
  },
  {
    id: "risk-payoff",
    label: "RISK / PAYOFF",
    href: "/strategy-lab",
    color: COLOR.negative,
    accent: "negative",
    tagline: "Know your downside before you commit.",
    description:
      "Visual payoff curves with clear max profit, max loss and breakeven points — so you understand the risk profile before committing capital.",
    metrics: [
      { label: "MAX PROFIT", value: "CAPPED" },
      { label: "MAX LOSS", value: "DEFINED" },
      { label: "BREAKEVENS", value: "EXACT" },
    ],
    highlights: [
      { label: "Risk Profile", desc: "Clear max profit/loss before entry" },
      { label: "Breakevens", desc: "Where the strategy turns profitable" },
      { label: "Position Greeks", desc: "Aggregate delta, gamma, theta, vega" },
    ],
  },
  {
    id: "paper-trading",
    label: "PAPER TRADING",
    href: "/paper-trading",
    color: COLOR.positive,
    accent: "positive",
    tagline: "Rehearse without risk.",
    description:
      "Simulated capital, orders, positions and P&L. Test every strategy in a zero-risk environment with full trade history and performance metrics.",
    metrics: [
      { label: "CAPITAL", value: "SIMULATED" },
      { label: "ORDERS", value: "REALISTIC" },
      { label: "P&L", value: "LIVE" },
    ],
    highlights: [
      { label: "Simulated Orders", desc: "Realistic fills without broker orders" },
      { label: "Positions", desc: "Open/closed with real-time P&L" },
      { label: "Trade Journal", desc: "Full history with CSV export" },
    ],
  },
];

const RESEARCH_CAPABILITIES = [
  {
    title: "Gamma Exposure (GEX)",
    desc: "Market-maker hedging flow analysis to understand directional pressure from dealer positioning.",
  },
  {
    title: "Statistical Signals",
    desc: "Derived signals from OI, volume and volatility patterns using statistical methods.",
  },
  {
    title: "OI Migration",
    desc: "Track how open interest shifts across strikes over time to identify conviction levels.",
  },
  {
    title: "Unusual Activity Detection",
    desc: "Flag abnormally large OI or volume changes that may indicate institutional positioning.",
  },
];

// =============================================================================
// Sub-components
// =============================================================================

function CapabilityModule({ cap, index }) {
  return (
    <Panel
      padding="2rem"
      style={{
        position: "relative",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        gap: SPACE.compLg,
        height: "100%",
        borderLeft: `3px solid ${cap.color}`,
      }}
    >
      {/* Grid overlay for signal field feel */}
      <GridOverlay color={COLOR.borderSubtle} spacing={32} style={{ opacity: 0.15 }} />

      {/* Header */}
      <FlexColumn style={{ gap: SPACE.small, position: "relative", zIndex: 1 }}>
        <FlexRow gap={SPACE.small} align="center">
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: cap.color,
              boxShadow: `0 0 8px ${cap.color}40`,
            }}
          />
          <Eyebrow color={cap.color}>{cap.label}</Eyebrow>
        </FlexRow>
        <h3
          style={{
            fontSize: TYPE.h3.size,
            fontWeight: 700,
            color: COLOR.textPrimary,
            margin: 0,
            letterSpacing: TYPE.h3.letterSpacing,
            lineHeight: TYPE.h3.lineHeight,
          }}
        >
          {cap.tagline}
        </h3>
        <p
          style={{
            fontSize: TYPE.bodySmall.size,
            color: COLOR.textMuted,
            lineHeight: TYPE.bodySmall.lineHeight,
            margin: 0,
          }}
        >
          {cap.description}
        </p>
      </FlexColumn>

      {/* Divider */}
      <SignalLine orientation="horizontal" color={cap.color} style={{ opacity: 0.3 }} />

      {/* Metrics row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: SPACE.comp,
          position: "relative",
          zIndex: 1,
        }}
      >
        {cap.metrics.map((m, i) => (
          <div key={i} style={{ textAlign: "center" }}>
            <div
              style={{
                fontSize: TYPE.labelSmall.size,
                fontWeight: 600,
                letterSpacing: TYPE.labelSmall.letterSpacing,
                color: COLOR.textFaint,
                marginBottom: SPACE.xs,
              }}
            >
              {m.label}
            </div>
            <div
              style={{
                fontSize: TYPE.data.size,
                fontWeight: 700,
                color: cap.color,
                fontFamily: TYPE.data.fontFamily,
              }}
            >
              {m.value}
            </div>
          </div>
        ))}
      </div>

      {/* Highlights */}
      <FlexColumn
        gap={SPACE.small}
        style={{ position: "relative", zIndex: 1, flex: 1 }}
      >
        {cap.highlights.map((h, i) => (
          <OutlinePanel
            key={i}
            padding={SPACE.comp}
            border={`${cap.color}20`}
            radius={RADIUS.md}
            style={{ background: `${cap.color}08` }}
          >
            <FlexRow gap={SPACE.small} align="flex-start">
              <span
                style={{
                  width: 4,
                  height: 4,
                  borderRadius: "50%",
                  background: cap.color,
                  marginTop: "0.5rem",
                  flexShrink: 0,
                }}
              />
              <FlexColumn style={{ gap: 2 }}>
                <span
                  style={{
                    fontSize: TYPE.bodySmall.size,
                    fontWeight: 600,
                    color: COLOR.textSecondary,
                    fontFamily: TYPE.data.fontFamily,
                  }}
                >
                  {h.label}
                </span>
                <span
                  style={{
                    fontSize: "0.8125rem",
                    color: COLOR.textMuted,
                    lineHeight: 1.5,
                  }}
                >
                  {h.desc}
                </span>
              </FlexColumn>
            </FlexRow>
          </OutlinePanel>
        ))}
      </FlexColumn>

      {/* CTA */}
      <div style={{ position: "relative", zIndex: 1 }}>
        <LinkButton
          href={cap.href}
          variant="ghost"
          size="md"
          style={{
            width: "100%",
            borderColor: `${cap.color}30`,
            color: cap.color,
          }}
        >
          Explore {cap.label.split("/")[0].trim()} →
        </LinkButton>
      </div>
    </Panel>
  );
}

function AtlasConnector() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: `${SPACE.compLg} 0`,
        position: "relative",
      }}
      aria-hidden="true"
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: SPACE.compLg,
          width: "100%",
          maxWidth: 700,
        }}
      >
        <SignalLine orientation="horizontal" color={COLOR.intelligence} style={{ flex: 1, opacity: 0.4 }} />
        <SignalNode color={COLOR.info} size={12} pulsing />
        <SignalLine orientation="horizontal" dashed color={COLOR.border} style={{ flex: 1, opacity: 0.4 }} />
        <SignalNode color={COLOR.strategy} size={12} pulsing />
        <SignalLine orientation="horizontal" color={COLOR.strategy} style={{ flex: 1, opacity: 0.4 }} />
      </div>
    </div>
  );
}

function ResearchPanel() {
  return (
    <SignalPanel
      padding="2.5rem"
      style={{
        borderStyle: "dashed",
        borderWidth: "1px",
        borderColor: `${COLOR.intelligence}40`,
      }}
    >
      <GridOverlay color={COLOR.intelligence} spacing={48} style={{ opacity: 0.08 }} />

      <FlexColumn gap={SPACE.compLg} style={{ position: "relative", zIndex: 1 }}>
        <FlexRow justify="space-between" align="center" gap={SPACE.comp}>
          <FlexRow gap={SPACE.small} align="center">
            <ResearchBadge status="RESEARCH_DIRECTION" />
            <Eyebrow color={COLOR.intelligence}>FUTURE CAPABILITIES</Eyebrow>
          </FlexRow>
          <span
            style={{
              fontSize: TYPE.labelSmall.size,
              color: COLOR.textFaint,
              letterSpacing: TYPE.labelSmall.letterSpacing,
              fontFamily: TYPE.data.fontFamily,
            }}
          >
            ROADMAP · V1.3+
          </span>
        </FlexRow>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: SPACE.comp,
          }}
        >
          {RESEARCH_CAPABILITIES.map((r, i) => (
            <OutlinePanel
              key={i}
              padding={SPACE.compLg}
              border={`${COLOR.intelligence}25`}
              radius={RADIUS.lg}
              style={{ background: `${COLOR.intelligence}05` }}
            >
              <FlexColumn gap={SPACE.xs}>
                <span
                  style={{
                    fontSize: TYPE.bodySmall.size,
                    fontWeight: 700,
                    color: COLOR.intelligence,
                  }}
                >
                  {r.title}
                </span>
                <span
                  style={{
                    fontSize: "0.8125rem",
                    color: COLOR.textMuted,
                    lineHeight: 1.6,
                  }}
                >
                  {r.desc}
                </span>
              </FlexColumn>
            </OutlinePanel>
          ))}
        </div>
      </FlexColumn>
    </SignalPanel>
  );
}

function CapabilityFlow() {
  const flows = [
    { from: COLOR.intelligence, to: COLOR.strategy, label: "SIGNAL → STRATEGY" },
    { from: COLOR.strategy, to: COLOR.negative, label: "STRATEGY → RISK" },
    { from: COLOR.negative, to: COLOR.positive, label: "RISK → REHEARSAL" },
  ];

  return (
    <FlexRow
      gap={SPACE.comp}
      justify="center"
      align="center"
      style={{ padding: `${SPACE.section} 0 ${SPACE.compLg}`, flexWrap: "wrap" }}
    >
      {flows.map((f, i) => (
        <FlexRow key={i} gap={SPACE.xs} align="center">
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: f.from,
              boxShadow: `0 0 6px ${f.from}50`,
            }}
          />
          <span
            style={{
              fontSize: TYPE.labelSmall.size,
              color: COLOR.textFaint,
              letterSpacing: "0.08em",
              fontFamily: TYPE.data.fontFamily,
            }}
          >
            {f.label}
          </span>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: f.to,
              boxShadow: `0 0 6px ${f.to}50`,
            }}
          />
        </FlexRow>
      ))}
    </FlexRow>
  );
}

// =============================================================================
// Main Page
// =============================================================================

export default function FeaturesClientPage() {
  return (
    <>
      {/* ─────────────────────────────────────────────────────────────────────
          HERO
          ───────────────────────────────────────────────────────────────────── */}
      <Section
        padding={SPACE.sectionLg}
        style={{
          paddingTop: "5.5rem",
          paddingBottom: "4rem",
          textAlign: "center",
          background:
            "radial-gradient(ellipse 80% 60% at 50% 20%, rgba(167,139,250,0.08), transparent 70%)",
        }}
      >
        <Container maxWidth={800}>
          <FlexColumn gap={SPACE.compLg} align="center">
            {/* Tag */}
            <FlexRow gap={SPACE.small} align="center">
              <SignalLine
                orientation="horizontal"
                color={COLOR.intelligence}
                length={32}
              />
              <Eyebrow color={COLOR.intelligence}>FEATURES</Eyebrow>
              <SignalLine
                orientation="horizontal"
                color={COLOR.intelligence}
                length={32}
              />
            </FlexRow>

            {/* Title */}
            <h1
              style={{
                fontSize: TYPE.displayH1.size,
                fontWeight: TYPE.displayH1.weight,
                color: COLOR.textPrimary,
                margin: 0,
                letterSpacing: TYPE.displayH1.letterSpacing,
                lineHeight: TYPE.displayH1.lineHeight,
                fontFamily: TYPE.display.fontFamily,
              }}
            >
              Capability Atlas
            </h1>

            {/* Subtitle */}
            <p
              style={{
                fontSize: TYPE.bodyLarge.size,
                color: COLOR.textMuted,
                lineHeight: TYPE.bodyLarge.lineHeight,
                maxWidth: 540,
                margin: 0,
                fontFamily: TYPE.body.fontFamily,
              }}
            >
              StrikeNova connects market intelligence, strategy design, risk
              analysis and paper-trading rehearsal into one continuous workflow.
            </p>

            {/* Hero signal line decoration */}
            <FlexRow gap={SPACE.comp} align="center">
              {[
                COLOR.intelligence,
                COLOR.info,
                COLOR.strategy,
                COLOR.positive,
              ].map((c, i) => (
                <SignalLine
                  key={i}
                  orientation="horizontal"
                  color={c}
                  length={48}
                  style={{ opacity: 0.4 }}
                />
              ))}
            </FlexRow>
          </FlexColumn>
        </Container>
      </Section>

      {/* ─────────────────────────────────────────────────────────────────────
          CAPABILITY ATLAS — Asymmetric Composition
          ───────────────────────────────────────────────────────────────────── */}
      <Section
        padding={SPACE.sectionLg}
        style={{
          paddingTop: "2rem",
          paddingBottom: "4rem",
          background:
            "linear-gradient(180deg, transparent, rgba(11,14,20,0.4) 30%, rgba(11,14,20,0.4) 70%, transparent)",
        }}
      >
        <Container maxWidth={1100}>
          {/* Section heading */}
          <SectionTitle
            eyebrow="THE ATLAS"
            title="How capabilities connect"
            subtitle="Each module feeds into the next. Intelligence informs strategy. Strategy defines risk. Risk is rehearsed in simulation."
            align="center"
          />

          {/* Atlas connector decoration */}
          <AtlasConnector />

          {/* Primary capability grid — asymmetric bento-style layout */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(2, 1fr)",
              gridTemplateRows: "auto auto",
              gap: SPACE.compLg,
              gridTemplateAreas: `
                "mi strat"
                "risk paper"
              `,
            }}
          >
            <div style={{ gridArea: "mi" }}>
              <CapabilityModule cap={CAPABILITIES[0]} index={0} />
            </div>
            <div style={{ gridArea: "strat" }}>
              <CapabilityModule cap={CAPABILITIES[1]} index={1} />
            </div>
            <div style={{ gridArea: "risk" }}>
              <CapabilityModule cap={CAPABILITIES[2]} index={2} />
            </div>
            <div style={{ gridArea: "paper" }}>
              <CapabilityModule cap={CAPABILITIES[3]} index={3} />
            </div>
          </div>

          {/* Flow indicator */}
          <CapabilityFlow />
        </Container>
      </Section>

      {/* ─────────────────────────────────────────────────────────────────────
          VISUALIZATION DEMO — Signal Field
          ───────────────────────────────────────────────────────────────────── */}
      <Section padding={SPACE.sectionLg} style={{ paddingTop: "2rem" }}>
        <Container maxWidth={900}>
          <VisualizationFrame
            eyebrow="SIGNAL FIELD"
            title="One signal, one source"
            caption="Every module derives from the same live data stream — eliminating conflicting signals from separate tools."
            legend={[
              { label: "Market Intelligence", color: COLOR.intelligence },
              { label: "Strategy Lab", color: COLOR.strategy },
              { label: "Risk Analysis", color: COLOR.negative },
              { label: "Paper Trading", color: COLOR.positive },
            ]}
            demoLabel
          >
            <div style={{ minHeight: 200, position: "relative" }}>
              <GridOverlay spacing={32} />
              {/* Signal nodes positioned on the demo visualization */}
              <SignalNode
                label="INTEL"
                value="LIVE"
                x={120}
                y={80}
                color={COLOR.intelligence}
                pulsing
              />
              <SignalNode
                label="STRATEGY"
                value="42"
                x={300}
                y={60}
                color={COLOR.strategy}
                pulsing
              />
              <SignalNode
                label="RISK"
                value="DEFINED"
                x={480}
                y={100}
                color={COLOR.negative}
                pulsing
              />
              <SignalNode
                label="REHEARSAL"
                value="SAFE"
                x={660}
                y={70}
                color={COLOR.positive}
                pulsing
              />
              {/* Connecting signal lines */}
              <SignalLine
                orientation="horizontal"
                color={COLOR.intelligence}
                length="100%"
                style={{
                  position: "absolute",
                  top: "50%",
                  left: 0,
                  opacity: 0.3,
                }}
              />
            </div>
          </VisualizationFrame>
        </Container>
      </Section>

      {/* ─────────────────────────────────────────────────────────────────────
          RESEARCH / FUTURE AREA
          ───────────────────────────────────────────────────────────────────── */}
      <Section padding={SPACE.sectionLg} style={{ paddingTop: "2rem" }}>
        <Container maxWidth={1100}>
          <ResearchPanel />
        </Container>
      </Section>

      {/* ─────────────────────────────────────────────────────────────────────
          CTA
          ───────────────────────────────────────────────────────────────────── */}
      <Section padding={SPACE.sectionLg} style={{ paddingTop: "2rem" }}>
        <Container maxWidth={700}>
          <SignalPanel padding="3rem" style={{ textAlign: "center" }}>
            <GridOverlay color={COLOR.strategy} spacing={40} style={{ opacity: 0.08 }} />

            <FlexColumn
              gap={SPACE.compLg}
              align="center"
              style={{ position: "relative", zIndex: 1 }}
            >
              <Eyebrow color={COLOR.strategy}>START YOUR WORKFLOW</Eyebrow>

              <h2
                style={{
                  fontSize: TYPE.h2.size,
                  fontWeight: TYPE.h2.weight,
                  color: COLOR.textPrimary,
                  margin: 0,
                  letterSpacing: TYPE.h2.letterSpacing,
                  lineHeight: TYPE.h2.lineHeight,
                }}
              >
                Choose where to begin
              </h2>

              <p
                style={{
                  fontSize: TYPE.body.size,
                  color: COLOR.textMuted,
                  lineHeight: TYPE.body.lineHeight,
                  maxWidth: 480,
                  margin: 0,
                }}
              >
                Start with market data, strategy design, or paper trading — every
                entry point connects to the full workflow.
              </p>

              <FlexRow
                gap={SPACE.comp}
                justify="center"
                style={{ flexWrap: "wrap" }}
              >
                <LinkButton href="/market-intelligence" variant="primary" size="lg">
                  Market Intelligence →
                </LinkButton>
                <LinkButton href="/strategy-lab" variant="secondary" size="lg">
                  Strategy Lab →
                </LinkButton>
                <LinkButton href="/paper-trading" variant="ghost" size="lg">
                  Paper Trading →
                </LinkButton>
              </FlexRow>
            </FlexColumn>
          </SignalPanel>
        </Container>
      </Section>
    </>
  );
}
