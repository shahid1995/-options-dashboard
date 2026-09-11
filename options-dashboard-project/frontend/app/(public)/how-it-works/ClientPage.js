"use client";
import { useIsMobile } from "@/lib/ui";
import { useAuthModal } from "@/components/public/AuthModalContext";
import {
  SignalField,
  DEMO_SIGNAL_STATE,
} from "@/components/public/SignalField";
import { VisualizationFrame } from "@/components/public/VisualizationFrame";
import { Container, Section, FlexRow, FlexColumn, MetricGrid } from "@/components/public/layout";
import { Panel, SignalPanel } from "@/components/public/surfaces";
import { LinkButton } from "@/components/public/buttons";
import { DemoLabel, Eyebrow, SectionTitle } from "@/components/public/truth";
import { SignalLine, SignalNode, TechnicalDivider, GridOverlay } from "@/components/public/signals";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "@/components/public/tokens";
import { CTASection, PAGE_MAX } from "@/components/public";

const WORKFLOW_STAGES = [
  {
    num: "01",
    title: "OBSERVE",
    desc: "Price, option chain, OI, volume, IV and Greeks.",
    detail: "Raw market observation — the foundation of every decision.",
    color: COLOR.info,
    visual: "CHAIN",
  },
  {
    num: "02",
    title: "ANALYZE",
    desc: "Positioning, volatility, structure and market relationships.",
    detail: "Interpret the signals — understand what the market is telling you.",
    color: COLOR.intelligence,
    visual: "SIGNALS",
  },
  {
    num: "03",
    title: "BUILD",
    desc: "Construct a strategy around the market view.",
    detail: "Turn analysis into a structured multi-leg options strategy.",
    color: COLOR.strategy,
    visual: "LEGS",
  },
  {
    num: "04",
    title: "TEST",
    desc: "Payoff, risk, Greeks and scenarios.",
    detail: "Understand the outcome before committing capital.",
    color: COLOR.warning,
    visual: "PAYOFF",
  },
  {
    num: "05",
    title: "PAPER TRADE",
    desc: "Simulate without risking real capital.",
    detail: "Execute in a paper environment that mirrors market conditions.",
    color: COLOR.positive,
    visual: "SIM",
  },
  {
    num: "06",
    title: "REVIEW",
    desc: "Trade outcome, execution review, journal, learning loop.",
    detail: "Study results and refine the process over time.",
    color: COLOR.textSecondary,
    visual: "JOURNAL",
  },
];

function WorkflowRail() {
  return (
    <div style={{ position: "relative" }}>
      {/* Continuous rail line */}
      <div
        style={{
          position: "absolute",
          left: 28,
          top: 56,
          bottom: 56,
          width: 2,
          background: `linear-gradient(180deg, ${COLOR.info}, ${COLOR.intelligence}, ${COLOR.strategy}, ${COLOR.warning}, ${COLOR.positive}, ${COLOR.textSecondary})`,
          opacity: 0.4,
        }}
        aria-hidden="true"
      />

      <FlexColumn gap={SPACE.cardLg}>
        {WORKFLOW_STAGES.map((stage, i) => (
          <div
            key={stage.num}
            style={{
              display: "flex",
              gap: SPACE.cardLg,
              alignItems: "flex-start",
              position: "relative",
            }}
          >
            {/* Signal node */}
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: "50%",
                background: `${stage.color}15`,
                border: `2px solid ${stage.color}`,
                display: "grid",
                placeItems: "center",
                flexShrink: 0,
                position: "relative",
                zIndex: 1,
              }}
              aria-hidden="true"
            >
              <span
                style={{
                  fontSize: TYPE.caption.size,
                  fontWeight: 700,
                  color: stage.color,
                  letterSpacing: "0.06em",
                }}
              >
                {stage.num}
              </span>
            </div>

            {/* Content */}
            <Panel padding={SPACE.cardLg} style={{ flex: 1 }}>
              <FlexRow gap={SPACE.comp} align="center" style={{ marginBottom: SPACE.small }}>
                <h3
                  style={{
                    fontSize: TYPE.h3.size,
                    fontWeight: 700,
                    color: COLOR.textPrimary,
                    margin: 0,
                    letterSpacing: "-0.01em",
                  }}
                >
                  {stage.title}
                </h3>
                <span
                  style={{
                    fontSize: TYPE.caption.size,
                    fontWeight: 600,
                    letterSpacing: "0.06em",
                    color: stage.color,
                    textTransform: "uppercase",
                    background: `${stage.color}10`,
                    border: `1px solid ${stage.color}30`,
                    borderRadius: RADIUS.sm,
                    padding: "0.125rem 0.5rem",
                  }}
                >
                  {stage.visual}
                </span>
              </FlexRow>
              <p
                style={{
                  fontSize: TYPE.body.size,
                  color: COLOR.textSecondary,
                  lineHeight: 1.7,
                  margin: `0 0 ${SPACE.xs}`,
                }}
              >
                {stage.desc}
              </p>
              <p
                style={{
                  fontSize: TYPE.bodySmall.size,
                  color: COLOR.textMuted,
                  lineHeight: 1.6,
                  margin: 0,
                }}
              >
                {stage.detail}
              </p>
            </Panel>
          </div>
        ))}
      </FlexColumn>
    </div>
  );
}

export default function HowItWorksClientPage() {
  const isMobile = useIsMobile();
  const { open: openAuth } = useAuthModal();

  return (
    <>
      {/* ════════════════════════════════════════════════════════════════════════
          HERO
          ════════════════════════════════════════════════════════════════════════ */}
      <header style={{ position: "relative", overflow: "hidden" }}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: `radial-gradient(ellipse 60% 50% at 50% 20%, ${COLOR.strategyDim}, transparent 60%),
                         radial-gradient(ellipse 40% 40% at 80% 80%, ${COLOR.intelligenceDim}, transparent 60%)`,
            pointerEvents: "none",
          }}
        />

        <div
          style={{
            position: "relative",
            maxWidth: PAGE_MAX,
            margin: "0 auto",
            padding: isMobile ? `${SPACE.sectionLg} 1.25rem` : `${SPACE.hero} 1.25rem`,
            textAlign: "center",
          }}
        >
          <Eyebrow color={COLOR.strategy}>HOW IT WORKS</Eyebrow>
          <h1
            style={{
              margin: `${SPACE.comp} 0 ${SPACE.compLg}`,
              fontSize: TYPE.displayH1.size,
              lineHeight: TYPE.displayH1.lineHeight,
              fontWeight: TYPE.displayH1.weight,
              letterSpacing: TYPE.displayH1.letterSpacing,
              color: COLOR.textPrimary,
            }}
          >
            From market observation
            <br />
            <span style={{ color: COLOR.strategy }}>to structured decision.</span>
          </h1>
          <p
            style={{
              color: COLOR.textSecondary,
              fontSize: TYPE.bodyLarge.size,
              lineHeight: TYPE.bodyLarge.lineHeight,
              maxWidth: "40ch",
              margin: "0 auto",
            }}
          >
            StrikeNova separates observation from analysis, analysis from strategy,
            and strategy from execution — so each decision can be evaluated on its own merits.
          </p>
        </div>
      </header>

      {/* ════════════════════════════════════════════════════════════════════════
          CANONICAL WORKFLOW RAIL
          ════════════════════════════════════════════════════════════════════════ */}
      <Section>
        <Container maxWidth={PAGE_MAX}>
          <SectionTitle
            eyebrow="THE WORKFLOW"
            title="Six stages from data to decision."
            subtitle="Each stage builds on the previous one. Together they form a complete workflow from observation to review."
          />

          <WorkflowRail />
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          SIGNAL FIELD — ILLUSTRATIVE MARKET STATE
          ════════════════════════════════════════════════════════════════════════ */}
      <Section
        style={{
          background: COLOR.baseElevated,
          borderTop: `1px solid ${COLOR.border}`,
          borderBottom: `1px solid ${COLOR.border}`,
        }}
      >
        <Container maxWidth={PAGE_MAX}>
          <SectionTitle
            eyebrow="ILLUSTRATIVE STATE"
            title="What the workflow produces."
            subtitle="A synthesized view of positioning, volatility, structure and market state. This example uses illustrative data."
          />

          <VisualizationFrame
            eyebrow="SIGNAL FIELD"
            title="Illustrative market state"
            demoLabel
            caption="This is an illustrative visualization. Data is not live."
          >
            <SignalField />
          </VisualizationFrame>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          STAGE DETAILS
          ════════════════════════════════════════════════════════════════════════ */}
      <Section>
        <Container maxWidth={PAGE_MAX}>
          <SectionTitle
            eyebrow="STAGE BREAKDOWN"
            title="What happens at each stage."
          />

          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)",
              gap: SPACE.cardLg,
            }}
          >
            {WORKFLOW_STAGES.map((stage) => (
              <Panel key={stage.num} padding={SPACE.cardLg}>
                <FlexRow gap={SPACE.small} align="center" style={{ marginBottom: SPACE.comp }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: stage.color,
                      boxShadow: `0 0 8px ${stage.color}40`,
                    }}
                  />
                  <span
                    style={{
                      fontSize: TYPE.caption.size,
                      fontWeight: 700,
                      letterSpacing: "0.06em",
                      color: stage.color,
                      textTransform: "uppercase",
                    }}
                  >
                    {stage.num} {stage.title}
                  </span>
                </FlexRow>
                <p
                  style={{
                    fontSize: TYPE.bodySmall.size,
                    color: COLOR.textMuted,
                    lineHeight: 1.65,
                    margin: 0,
                  }}
                >
                  {stage.desc}
                </p>
              </Panel>
            ))}
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          CTAs
          ════════════════════════════════════════════════════════════════════════ */}
      <Section
        style={{
          background: COLOR.baseElevated,
          borderTop: `1px solid ${COLOR.border}`,
        }}
      >
        <Container maxWidth={PAGE_MAX}>
          <FlexRow gap={SPACE.cardLg} justify="center" wrap={true}>
            <LinkButton variant="primary" size="lg" href="/market-intelligence">
              Explore Market Intelligence <span aria-hidden>→</span>
            </LinkButton>
            <LinkButton variant="secondary" size="lg" href="/strategy-lab">
              Open Strategy Lab
            </LinkButton>
            <LinkButton variant="ghost" size="lg" href="/paper-trading">
              Start Paper Trading
            </LinkButton>
          </FlexRow>
        </Container>
      </Section>
    </>
  );
}
