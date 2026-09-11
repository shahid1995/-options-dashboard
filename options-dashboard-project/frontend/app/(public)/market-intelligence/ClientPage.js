"use client";

import { useIsMobile } from "@/lib/ui";
import {
  // P1 Primitives
  COLOR,
  TYPE,
  SPACE,
  RADIUS,
  SHADOW,
  DATA_STATE,
  RESEARCH_STATUS,
  // Surfaces
  SignalPanel,
  Panel,
  OutlinePanel,
  // Layout
  Container,
  MetricGrid,
  CardGrid,
  TwoColumn,
  FlexRow,
  // Truth
  DemoLabel,
  ResearchBadge,
  Eyebrow,
  SectionTitle,
  // Buttons
  LinkButton,
  TextLink,
  // Metric
  Metric,
  // P2 SignalField
  SignalField,
  DEMO_SIGNAL_STATE,
  // Signal primitives
  SignalLine,
  TechnicalDivider,
} from "@/components/public";

// =============================================================================
// MARKET INTELLIGENCE DIMENSIONS
// =============================================================================

const DIMENSIONS = [
  {
    label: "PRICE",
    icon: "P",
    color: COLOR.textPrimary,
    desc: "Spot, LTP across strikes and the current market level — the reference point for every derivative calculation.",
  },
  {
    label: "OI",
    icon: "O",
    color: COLOR.signalOi,
    desc: "Open interest on both sides, total and per-strike. Shows where positions have been placed.",
  },
  {
    label: "IV",
    icon: "V",
    color: COLOR.signalIv,
    desc: "Implied volatility at each strike and the ATM level — how the market prices future uncertainty.",
  },
  {
    label: "ΔOI",
    icon: "Δ",
    color: COLOR.info,
    desc: "How positions shifted during the session. New positions, unwound positions, and net change.",
  },
  {
    label: "GREEKS",
    icon: "Γ",
    color: COLOR.signalGreeks,
    desc: "Delta, gamma, theta and vega for every option — the sensitivity coefficients of each position.",
  },
  {
    label: "STRUCTURE",
    icon: "S",
    color: COLOR.strategy,
    desc: "Resistance, support and pivot levels derived from the chain — the skeleton of the market.",
  },
];

// =============================================================================
// RESEARCH DIRECTION — FUTURE EXTENSIONS
// =============================================================================

const RESEARCH_EXTENSIONS = [
  {
    title: "Gamma Exposure (GEX)",
    desc: "Aggregate gamma per strike to understand market-maker hedging flows and how they suppress or amplify price movements.",
    status: "RESEARCH_DIRECTION",
  },
  {
    title: "Positioning Conviction",
    desc: "Track OI migration across sessions to distinguish between new positioning and position unwinding.",
    status: "RESEARCH_DIRECTION",
  },
  {
    title: "Volatility Regime",
    desc: "Classify the current volatility environment (contango / backwardation, skew direction) to inform strategy selection.",
    status: "RESEARCH_DIRECTION",
  },
  {
    title: "Statistical Signals",
    desc: "Derive composite signals from OI, volume, volatility, and price patterns using statistical methods.",
    status: "RESEARCH_DIRECTION",
  },
];

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function MarketIntelligenceClientPage() {
  const isMobile = useIsMobile();

  return (
    <>
      {/* ===== HERO ===== */}
      <section
        style={{
          paddingTop: isMobile ? SPACE.hero : "6.5rem",
          paddingBottom: isMobile ? "2.5rem" : "3.5rem",
          textAlign: "center",
          position: "relative",
          overflow: "hidden",
          background:
            "radial-gradient(ellipse 70% 50% at 50% 0%, rgba(167,139,250,0.06), transparent 60%)",
        }}
      >
        <Container maxWidth={1100}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: isMobile ? SPACE.comp : SPACE.group,
            }}
          >
            {/* Tag */}
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.625rem",
              }}
            >
              <span
                style={{
                  width: 28,
                  height: 1,
                  background: `linear-gradient(90deg, transparent, ${COLOR.intelligence})`,
                }}
              />
              <span
                style={{
                  fontSize: TYPE.label.size,
                  letterSpacing: "0.12em",
                  color: COLOR.intelligence,
                  fontWeight: 700,
                  textTransform: "uppercase",
                }}
              >
                Market Intelligence
              </span>
              <span
                style={{
                  width: 28,
                  height: 1,
                  background: `linear-gradient(90deg, ${COLOR.intelligence}, transparent)`,
                }}
              />
            </div>

            {/* Title */}
            <h1
              style={{
                fontSize: TYPE.displayH1.size,
                fontWeight: TYPE.displayH1.weight,
                letterSpacing: TYPE.displayH1.letterSpacing,
                lineHeight: TYPE.displayH1.lineHeight,
                color: COLOR.textPrimary,
                margin: 0,
                maxWidth: "50rem",
              }}
            >
              The Signal Field: Where Market Data Becomes Market State.
            </h1>

            {/* Subtitle */}
            <p
              style={{
                fontSize: TYPE.bodyLarge.size,
                color: COLOR.textMuted,
                lineHeight: TYPE.bodyLarge.lineHeight,
                margin: 0,
                maxWidth: "42rem",
              }}
            >
              Combine price, positioning, volatility, Greeks, and structure into a single
              analytical view. The Signal Field is the natural home for understanding what
              the options market is telling you — before you build a strategy.
            </p>

            {/* Demo label */}
            <DemoLabel />
          </div>
        </Container>
      </section>

      {/* ===== SIGNAL FIELD — CENTERPIECE ===== */}
      <section
        style={{
          paddingTop: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingBottom: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingLeft: "1.25rem",
          paddingRight: "1.25rem",
        }}
      >
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="Signal Field"
            title="A Market-Native Composition"
            subtitle="Price, OI, IV, ΔOI, Greeks, and Structure converge into a single market state. Every element is illustrative — the composition is the point."
            align="center"
          />

          <SignalPanel
            padding={isMobile ? "1.5rem" : "2.5rem"}
            style={{ marginBottom: isMobile ? SPACE.section : SPACE.sectionLg }}
          >
            <SignalField />
          </SignalPanel>

          {/* Market State Summary */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: SPACE.comp,
              textAlign: "center",
            }}
          >
            <Eyebrow color={COLOR.info}>Market State</Eyebrow>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: SPACE.small,
                flexWrap: "wrap",
                justifyContent: "center",
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background:
                    DEMO_SIGNAL_STATE.marketState.bias === "neutral"
                      ? COLOR.info
                      : DEMO_SIGNAL_STATE.marketState.bias === "bullish"
                      ? COLOR.positive
                      : COLOR.negative,
                  boxShadow: `0 0 8px ${
                    DEMO_SIGNAL_STATE.marketState.bias === "neutral"
                      ? COLOR.info
                      : DEMO_SIGNAL_STATE.marketState.bias === "bullish"
                      ? COLOR.positive
                      : COLOR.negative
                  }`,
                }}
              />
              <span
                style={{
                  fontSize: TYPE.h4.size,
                  fontWeight: TYPE.h4.weight,
                  color: COLOR.textPrimary,
                  fontFamily: TYPE.data,
                }}
              >
                {DEMO_SIGNAL_STATE.marketState.label}
              </span>
            </div>
            <p
              style={{
                fontSize: TYPE.bodySmall.size,
                color: COLOR.textMuted,
                lineHeight: TYPE.bodySmall.lineHeight,
                margin: 0,
                maxWidth: "36rem",
              }}
            >
              The market state is a synthesis of all six dimensions. It is not a signal to trade on — it is a
              contextual reading that informs strategy selection.
            </p>
          </div>
        </Container>
      </section>

      {/* ===== DIMENSIONS — THE INPUTS ===== */}
      <section
        style={{
          paddingTop: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingBottom: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingLeft: "1.25rem",
          paddingRight: "1.25rem",
          background:
            "linear-gradient(180deg, rgba(11,14,20,0.2), rgba(18,22,31,0.5), rgba(11,14,20,0.2))",
        }}
      >
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="Dimensions"
            title="Six Inputs, One Market State"
            subtitle="Each dimension contributes a distinct signal. Together they form the analytical foundation."
            align="center"
          />

          <CardGrid minItemWidth={300} gap={SPACE.compLg}>
            {DIMENSIONS.map((dim) => (
              <Panel
                key={dim.label}
                padding={SPACE.cardLg}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: SPACE.comp,
                  transition: "border-color 0.18s ease, transform 0.18s ease",
                }}
                className="od-card"
              >
                {/* Header row */}
                <div style={{ display: "flex", alignItems: "center", gap: SPACE.comp }}>
                  <span
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: RADIUS.md,
                      background: `${dim.color}15`,
                      border: `1px solid ${dim.color}30`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: TYPE.data.size,
                      fontWeight: 700,
                      color: dim.color,
                      fontFamily: TYPE.data,
                      flexShrink: 0,
                    }}
                  >
                    {dim.icon}
                  </span>
                  <span
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 700,
                      letterSpacing: "0.08em",
                      color: dim.color,
                      textTransform: "uppercase",
                    }}
                  >
                    {dim.label}
                  </span>
                </div>

                {/* Description */}
                <p
                  style={{
                    fontSize: TYPE.bodySmall.size,
                    color: COLOR.textMuted,
                    lineHeight: TYPE.bodySmall.lineHeight,
                    margin: 0,
                  }}
                >
                  {dim.desc}
                </p>
              </Panel>
            ))}
          </CardGrid>
        </Container>
      </section>

      {/* ===== MARKET STATE COMPOSITION ===== */}
      <section
        style={{
          paddingTop: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingBottom: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingLeft: "1.25rem",
          paddingRight: "1.25rem",
        }}
      >
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="Composition"
            title="From Dimensions to Market State"
            subtitle="The Signal Field doesn't just display data — it synthesizes it. Here's how each input contributes to the final market state assessment."
            align="center"
          />

          {/* Visual composition flow */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: SPACE.cardLg,
              marginBottom: isMobile ? SPACE.section : SPACE.sectionLg,
            }}
          >
            {/* Flow: Dimensions → Market State */}
            <Panel
              padding={isMobile ? SPACE.card : SPACE.cardLg}
              style={{
                background: COLOR.surfaceDeep,
                border: `1px solid ${COLOR.border}`,
              }}
            >
              <div
                style={{
                  display: "flex",
                  flexDirection: isMobile ? "column" : "row",
                  alignItems: isMobile ? "flex-start" : "center",
                  gap: isMobile ? SPACE.comp : SPACE.section,
                }}
              >
                {/* Input dimensions */}
                <div
                  style={{
                    flex: "1 1 0",
                    display: "flex",
                    flexDirection: "column",
                    gap: SPACE.small,
                  }}
                >
                  <Eyebrow color={COLOR.textMuted}>Inputs</Eyebrow>
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: SPACE.small,
                    }}
                  >
                    {DIMENSIONS.map((dim) => (
                      <span
                        key={dim.label}
                        style={{
                          fontSize: TYPE.caption.size,
                          fontWeight: 600,
                          letterSpacing: "0.04em",
                          color: dim.color,
                          background: `${dim.color}10`,
                          border: `1px solid ${dim.color}25`,
                          borderRadius: RADIUS.sm,
                          padding: "0.25rem 0.5rem",
                          fontFamily: TYPE.data,
                          textTransform: "uppercase",
                        }}
                      >
                        {dim.label}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Arrow */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: COLOR.textFaint,
                    fontSize: TYPE.h3.size,
                    flexShrink: 0,
                  }}
                >
                  {isMobile ? "↓" : "→"}
                </div>

                {/* Output: Market State */}
                <div
                  style={{
                    flex: "1 1 0",
                    display: "flex",
                    flexDirection: "column",
                    gap: SPACE.small,
                  }}
                >
                  <Eyebrow color={COLOR.info}>Output</Eyebrow>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: SPACE.small,
                    }}
                  >
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        background:
                          DEMO_SIGNAL_STATE.marketState.bias === "neutral"
                            ? COLOR.info
                            : DEMO_SIGNAL_STATE.marketState.bias === "bullish"
                            ? COLOR.positive
                            : COLOR.negative,
                        boxShadow: `0 0 10px ${
                          DEMO_SIGNAL_STATE.marketState.bias === "neutral"
                            ? COLOR.info
                            : DEMO_SIGNAL_STATE.marketState.bias === "bullish"
                            ? COLOR.positive
                            : COLOR.negative
                        }`,
                      }}
                    />
                    <span
                      style={{
                        fontSize: TYPE.h4.size,
                        fontWeight: 700,
                        color: COLOR.textPrimary,
                        fontFamily: TYPE.data,
                      }}
                    >
                      MARKET STATE
                    </span>
                  </div>
                  <p
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.6,
                      margin: 0,
                    }}
                  >
                    A synthesized reading: {DEMO_SIGNAL_STATE.marketState.label.toLowerCase()}.
                    Confidence: {DEMO_SIGNAL_STATE.marketState.confidence}.
                  </p>
                </div>
              </div>
            </Panel>
          </div>

          <TwoColumn
            gap={isMobile ? SPACE.section : SPACE.sectionLg}
            left={
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: SPACE.cardLg,
                }}
              >
                {/* Positioning */}
                <Panel padding={SPACE.cardLg}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: SPACE.comp,
                    }}
                  >
                    <Eyebrow color={COLOR.signalOi}>Positioning</Eyebrow>
                    <DemoLabel style={{ fontSize: "0.625rem" }} />
                  </div>
                  <p
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.65,
                      margin: 0,
                    }}
                  >
                    Open interest distribution reveals where participants have placed their
                    bets. High OI at a strike suggests conviction — it acts as a magnet or
                    a wall. The PCR (Put/Call Ratio) summarizes directional bias.
                  </p>
                  <MetricGrid minItemWidth={120} style={{ marginTop: SPACE.compLg }}>
                    <Metric
                      label="CALL OI"
                      value="1,84,250"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.negative}
                    />
                    <Metric
                      label="PUT OI"
                      value="2,17,800"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.positive}
                    />
                    <Metric
                      label="PCR (OI)"
                      value="1.18"
                      decimals={2}
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                    />
                  </MetricGrid>
                </Panel>

                {/* OI Change */}
                <Panel padding={SPACE.cardLg}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: SPACE.comp,
                    }}
                  >
                    <Eyebrow color={COLOR.info}>OI Change</Eyebrow>
                    <DemoLabel style={{ fontSize: "0.625rem" }} />
                  </div>
                  <p
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.65,
                      margin: 0,
                    }}
                  >
                    Change-in-OI shows what happened during the session. New OI buildup
                    indicates fresh positioning; OI unwinding suggests profit-taking or
                    stop-losses. The direction of change matters as much as the magnitude.
                  </p>
                  <MetricGrid minItemWidth={120} style={{ marginTop: SPACE.compLg }}>
                    <Metric
                      label="ΔOI DIRECTION"
                      value="PE"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.positive}
                    />
                    <Metric
                      label="ΔOI VALUE"
                      value="+12,400"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.positive}
                    />
                    <Metric
                      label="BIAS"
                      value="bearish"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.warning}
                    />
                  </MetricGrid>
                </Panel>
              </div>
            }
            right={
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: SPACE.cardLg,
                }}
              >
                {/* Volatility */}
                <Panel padding={SPACE.cardLg}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: SPACE.comp,
                    }}
                  >
                    <Eyebrow color={COLOR.signalIv}>Volatility</Eyebrow>
                    <DemoLabel style={{ fontSize: "0.625rem" }} />
                  </div>
                  <p
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.65,
                      margin: 0,
                    }}
                  >
                    Implied volatility reflects how the market prices future uncertainty.
                    ATM IV, skew direction, and term structure together define the volatility
                    regime — critical for choosing between premium-selling and
                    premium-buying strategies.
                  </p>
                  <MetricGrid minItemWidth={120} style={{ marginTop: SPACE.compLg }}>
                    <Metric
                      label="ATM IV"
                      value="14.2%"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.intelligence}
                    />
                    <Metric
                      label="VIX"
                      value="13.8"
                      decimals={1}
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                    />
                    <Metric
                      label="SKEW"
                      value="put skew"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.intelligence}
                    />
                  </MetricGrid>
                </Panel>

                {/* Greeks & Structure */}
                <Panel padding={SPACE.cardLg}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: SPACE.comp,
                    }}
                  >
                    <Eyebrow color={COLOR.signalGreeks}>Greeks & Structure</Eyebrow>
                    <DemoLabel style={{ fontSize: "0.625rem" }} />
                  </div>
                  <p
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.65,
                      margin: 0,
                    }}
                  >
                    Greeks quantify sensitivity: delta (directional), gamma (convexity),
                    theta (time decay), vega (volatility). Structure levels — resistance,
                    pivot, support — provide the spatial framework for strategy construction.
                  </p>
                  <MetricGrid minItemWidth={120} style={{ marginTop: SPACE.compLg }}>
                    <Metric
                      label="DELTA"
                      value="-0.02"
                      decimals={2}
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                    />
                    <Metric
                      label="GAMMA"
                      value="0.0003"
                      decimals={4}
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                    />
                    <Metric
                      label="RESISTANCE"
                      value="25,700"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.negative}
                    />
                    <Metric
                      label="PIVOT"
                      value="25,500"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.strategy}
                    />
                    <Metric
                      label="SUPPORT"
                      value="25,300"
                      status="DEMO"
                      source="ILLUSTRATIVE"
                      size="sm"
                      color={COLOR.positive}
                    />
                  </MetricGrid>
                </Panel>
              </div>
            }
          />
        </Container>
      </section>

      {/* ===== RESEARCH DIRECTION ===== */}
      <section
        style={{
          paddingTop: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingBottom: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingLeft: "1.25rem",
          paddingRight: "1.25rem",
          background:
            "linear-gradient(180deg, rgba(11,14,20,0.2), rgba(18,22,31,0.5))",
        }}
      >
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="Research Direction"
            title="Future Extensions"
            subtitle="The Signal Field is a foundation. These are the analytical capabilities we're building toward."
            align="center"
          />

          <CardGrid minItemWidth={280} gap={SPACE.compLg}>
            {RESEARCH_EXTENSIONS.map((ext) => (
              <OutlinePanel
                key={ext.title}
                padding={SPACE.cardLg}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: SPACE.comp,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <ResearchBadge status={ext.status} />
                </div>
                <h4
                  style={{
                    fontSize: TYPE.h4.size,
                    fontWeight: TYPE.h4.weight,
                    color: COLOR.textPrimary,
                    margin: 0,
                    letterSpacing: TYPE.h4.letterSpacing,
                  }}
                >
                  {ext.title}
                </h4>
                <p
                  style={{
                    fontSize: TYPE.bodySmall.size,
                    color: COLOR.textMuted,
                    lineHeight: 1.65,
                    margin: 0,
                  }}
                >
                  {ext.desc}
                </p>
              </OutlinePanel>
            ))}
          </CardGrid>
        </Container>
      </section>

      {/* ===== CTA ===== */}
      <section
        style={{
          paddingTop: isMobile ? SPACE.section : SPACE.sectionLg,
          paddingBottom: isMobile ? "3rem" : "4rem",
          paddingLeft: "1.25rem",
          paddingRight: "1.25rem",
        }}
      >
        <Container maxWidth={900}>
          <Panel
            padding={isMobile ? "2.5rem 1.5rem" : "4rem 3rem"}
            radius={RADIUS.xl}
            shadow={SHADOW.lg}
            style={{
              textAlign: "center",
              background:
                "radial-gradient(ellipse 70% 90% at 50% 0%, rgba(201,161,90,0.12), transparent 65%), linear-gradient(180deg, #12161F, #0B0E14)",
              border: "1px solid rgba(201,161,90,0.20)",
            }}
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: SPACE.cardLg,
              }}
            >
              <Eyebrow color={COLOR.strategy}>Next Step</Eyebrow>
              <h2
                style={{
                  fontSize: TYPE.displayH2.size,
                  fontWeight: TYPE.displayH2.weight,
                  letterSpacing: TYPE.displayH2.letterSpacing,
                  lineHeight: TYPE.displayH2.lineHeight,
                  color: COLOR.textPrimary,
                  margin: 0,
                }}
              >
                Turn Intelligence Into Strategy.
              </h2>
              <p
                style={{
                  fontSize: TYPE.bodyLarge.size,
                  color: COLOR.textMuted,
                  lineHeight: TYPE.bodyLarge.lineHeight,
                  margin: 0,
                  maxWidth: "36rem",
                }}
              >
                The Signal Field shows you what the market is saying. The Strategy Lab
                helps you build a structured response. Combine legs, analyze payoffs, and
                paper-trade before committing capital.
              </p>
              <div
                style={{
                  display: "flex",
                  gap: SPACE.comp,
                  flexWrap: "wrap",
                  justifyContent: "center",
                }}
              >
                <LinkButton
                  href="/strategy-lab"
                  variant="primary"
                  size="lg"
                  testId="cta-strategy-lab"
                >
                  Build a Strategy &rarr;
                </LinkButton>
                <LinkButton
                  href="/features"
                  variant="secondary"
                  size="lg"
                  testId="cta-features"
                >
                  Explore Features
                </LinkButton>
              </div>
            </div>
          </Panel>
        </Container>
      </section>
    </>
  );
}
