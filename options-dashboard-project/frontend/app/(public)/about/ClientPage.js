"use client";
import { useIsMobile } from "@/lib/ui";
import { useAuthModal } from "@/components/public/AuthModalContext";
import { Container, Section, FlexRow, FlexColumn, MetricGrid } from "@/components/public/layout";
import { Panel, OutlinePanel } from "@/components/public/surfaces";
import { LinkButton } from "@/components/public/buttons";
import { DemoLabel, ResearchBadge, Eyebrow, SectionTitle } from "@/components/public/truth";
import { SignalLine, TechnicalDivider } from "@/components/public/signals";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
import { CTASection, PAGE_MAX } from "@/components/public";

const PHILOSOPHY = [
  {
    title: "DATA FIRST",
    desc: "Every decision starts with market data. The platform provides raw chain data, computed analytics and derived metrics — never opinions about the market.",
    color: COLOR.info,
  },
  {
    title: "RISK FIRST",
    desc: "Before you trade, understand the risk. Payoff curves, max loss, breakevens and Greeks are available before any simulated or real execution.",
    color: COLOR.negative,
  },
  {
    title: "STRUCTURED ANALYSIS",
    desc: "Combine OI, volume, IV, Greeks, PCR and market structure into a coherent view rather than relying on a single indicator.",
    color: COLOR.intelligence,
  },
  {
    title: "TRANSPARENCY",
    desc: "The platform shows what the data says, not what it might mean. No black-box claims. No hidden logic. No prediction promises.",
    color: COLOR.strategy,
  },
];

const NOT_BUILDING = [
  "NOT A SIGNAL-SELLING SERVICE",
  "NOT A GUARANTEED-PROFIT SYSTEM",
  "NOT A BLACK BOX",
  "NOT A SUBSTITUTE FOR RISK MANAGEMENT",
];

const FUTURE_DIRECTIONS = [
  { title: "GEX / Gamma Exposure", desc: "Gamma exposure analysis to understand market-maker hedging flows.", status: "RESEARCH_DIRECTION" },
  { title: "Statistical Signals", desc: "Signals derived from OI, volume and volatility patterns.", status: "RESEARCH_DIRECTION" },
  { title: "Advanced Positioning", desc: "Deeper analysis of institutional positioning and flow.", status: "COMING_LATER" },
  { title: "OI Migration Tracking", desc: "Track how open interest shifts across strikes over time.", status: "COMING_LATER" },
];

export default function AboutClientPage() {
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
            background: `radial-gradient(ellipse 60% 50% at 30% 20%, ${COLOR.intelligenceDim}, transparent 60%),
                         radial-gradient(ellipse 40% 40% at 70% 80%, ${COLOR.strategyDim}, transparent 60%)`,
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
          <Eyebrow color={COLOR.intelligence}>ABOUT STRIKENOVA</Eyebrow>
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
            Built to make options analysis
            <br />
            <span style={{ color: COLOR.strategy }}>more structured.</span>
          </h1>
          <p
            style={{
              color: COLOR.textSecondary,
              fontSize: TYPE.bodyLarge.size,
              lineHeight: TYPE.bodyLarge.lineHeight,
              maxWidth: "42ch",
              margin: "0 auto",
            }}
          >
            Option-chain data contains enormous information. Raw information does not
            automatically create a repeatable decision process. StrikeNova exists to
            close that gap.
          </p>
        </div>
      </header>

      {/* ════════════════════════════════════════════════════════════════════════
          WHY STRIKENOVA EXISTS
          ════════════════════════════════════════════════════════════════════════ */}
      <Section>
        <Container maxWidth={PAGE_MAX}>
          <SectionTitle
            eyebrow="WHY STRIKENOVA EXISTS"
            title="Data → Intelligence → Strategy → Risk → Rehearsal → Review"
            subtitle="A structured process that separates observation from analysis, analysis from strategy, and strategy from execution."
          />

          {/* Conceptual flow */}
          <div
            style={{
              display: "flex",
              flexDirection: isMobile ? "column" : "row",
              alignItems: "center",
              justifyContent: "center",
              gap: isMobile ? SPACE.small : SPACE.comp,
              marginBottom: SPACE.section,
              flexWrap: "wrap",
            }}
          >
            {["DATA", "INTELLIGENCE", "STRATEGY", "RISK", "REHEARSAL", "REVIEW"].map(
              (item, i, arr) => (
                <FlexRow key={item} gap={SPACE.small} align="center">
                  <span
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 700,
                      letterSpacing: "0.06em",
                      color: COLOR.textMuted,
                      textTransform: "uppercase",
                    }}
                  >
                    {item}
                  </span>
                  {i < arr.length - 1 && (
                    <span style={{ color: COLOR.textFaint, fontSize: 14 }}>
                      {isMobile ? "↓" : "→"}
                    </span>
                  )}
                </FlexRow>
              )
            )}
          </div>

          <Panel padding={SPACE.cardLg}>
            <p
              style={{
                fontSize: TYPE.bodyLarge.size,
                color: COLOR.textSecondary,
                lineHeight: 1.8,
                margin: 0,
                textAlign: "center",
                maxWidth: "50ch",
                marginLeft: "auto",
                marginRight: "auto",
              }}
            >
              Our goal is to build tools that help traders investigate the options market
              systematically and make their own informed decisions. The platform provides
              the data, the analysis tools and the testing environment — the trading
              decisions are yours.
            </p>
          </Panel>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          PRODUCT PHILOSOPHY
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
            eyebrow="PRODUCT PHILOSOPHY"
            title="Four principles that guide the product."
          />

          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)",
              gap: SPACE.cardLg,
            }}
          >
            {PHILOSOPHY.map((p) => (
              <Panel key={p.title} padding={SPACE.cardLg}>
                <FlexRow gap={SPACE.small} align="center" style={{ marginBottom: SPACE.comp }}>
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: p.color,
                      boxShadow: `0 0 8px ${p.color}40`,
                    }}
                  />
                  <h3
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 700,
                      letterSpacing: "0.06em",
                      color: p.color,
                      textTransform: "uppercase",
                      margin: 0,
                    }}
                  >
                    {p.title}
                  </h3>
                </FlexRow>
                <p
                  style={{
                    fontSize: TYPE.body.size,
                    color: COLOR.textSecondary,
                    lineHeight: 1.7,
                    margin: 0,
                  }}
                >
                  {p.desc}
                </p>
              </Panel>
            ))}
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          WHAT STRIKENOVA IS NOT
          ════════════════════════════════════════════════════════════════════════ */}
      <Section>
        <Container maxWidth={PAGE_MAX}>
          <SectionTitle
            eyebrow="WHAT STRIKENOVA IS NOT"
            title="Trust through clarity."
            subtitle="We believe in being explicit about what this product is — and what it is not."
          />

          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)",
              gap: SPACE.comp,
            }}
          >
            {NOT_BUILDING.map((item) => (
              <OutlinePanel key={item} padding={SPACE.card} border={COLOR.negativeDim}>
                <FlexRow gap={SPACE.small} align="center">
                  <span
                    style={{
                      fontSize: 14,
                      color: COLOR.negative,
                      fontWeight: 700,
                    }}
                  >
                    ✕
                  </span>
                  <span
                    style={{
                      fontSize: TYPE.body.size,
                      fontWeight: 600,
                      color: COLOR.textSecondary,
                    }}
                  >
                    {item}
                  </span>
                </FlexRow>
              </OutlinePanel>
            ))}
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          FUTURE DIRECTION
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
            eyebrow="FUTURE DIRECTION"
            title="What we are building next."
            subtitle="Research directions and future capabilities. No release dates promised."
          />

          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)",
              gap: SPACE.comp,
            }}
          >
            {FUTURE_DIRECTIONS.map((item) => (
              <Panel key={item.title} padding={SPACE.cardLg}>
                <FlexRow gap={SPACE.small} align="center" style={{ marginBottom: SPACE.small }}>
                  <ResearchBadge status={item.status} />
                </FlexRow>
                <h3
                  style={{
                    fontSize: TYPE.h4.size,
                    fontWeight: 700,
                    color: COLOR.textPrimary,
                    margin: `0 0 ${SPACE.xs}`,
                  }}
                >
                  {item.title}
                </h3>
                <p
                  style={{
                    fontSize: TYPE.bodySmall.size,
                    color: COLOR.textMuted,
                    lineHeight: 1.6,
                    margin: 0,
                  }}
                >
                  {item.desc}
                </p>
              </Panel>
            ))}
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          FINAL CTA
          ════════════════════════════════════════════════════════════════════════ */}
      <CTASection
        headline={
          <>
            Explore the <span style={{ color: COLOR.strategy }}>StrikeNova</span> workflow.
          </>
        }
        body="Understand the market, build strategies, test decisions and practice — all in one structured environment."
        primaryLabel="Get Started"
        primaryOnClick={openAuth}
        secondaryLabel="How It Works"
        secondaryHref="/how-it-works"
      />
    </>
  );
}
