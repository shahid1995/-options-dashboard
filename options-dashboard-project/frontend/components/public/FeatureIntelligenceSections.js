import React from "react";
import { COLOR, TYPE, SPACE, RADIUS } from "./tokens";
import { Container, Section, CardGrid, FlexColumn, FlexRow } from "./layout";
import { Panel, OutlinePanel, SignalPanel } from "./surfaces";
import { Eyebrow, SectionTitle } from "./truth";
import { LinkButton } from "./buttons";

const INTELLIGENCE_LAYERS = [
  { label: "MARKET DATA", detail: "Option chain · OI · volume", color: COLOR.info },
  { label: "POSITIONING", detail: "PCR · OI structure · migration", color: COLOR.intelligence },
  { label: "VOLATILITY", detail: "IV · skew · VIX · vega", color: COLOR.strategy },
  { label: "GREEKS", detail: "Delta · gamma · theta · vega", color: COLOR.positive },
  { label: "STRUCTURE", detail: "GEX · gamma flip · walls", color: COLOR.intelligence },
  { label: "SCENARIOS", detail: "Spot · IV · time shifts", color: COLOR.strategy },
  { label: "STRATEGY", detail: "Legs · payoff · breakevens", color: COLOR.info },
  { label: "RISK", detail: "Capital · margin · max loss", color: COLOR.negative },
];

const DEEP_CAPABILITIES = [
  {
    title: "Gamma Exposure",
    eyebrow: "POSITIONING",
    description: "Read dealer positioning and directional pressure instead of relying on price alone.",
    detail: "GEX · gamma flip · walls",
    color: COLOR.intelligence,
  },
  {
    title: "Volatility Intelligence",
    eyebrow: "VOLATILITY",
    description: "Combine IV, skew, VIX and vega to understand how volatility changes the trade.",
    detail: "IV · skew · VIX · vega",
    color: COLOR.strategy,
  },
  {
    title: "Greeks Analytics",
    eyebrow: "SENSITIVITY",
    description: "See how a position responds to spot, volatility and time before capital is committed.",
    detail: "Delta · gamma · theta · vega",
    color: COLOR.info,
  },
  {
    title: "Scenario Engine",
    eyebrow: "STRESS TESTING",
    description: "Reprice strategy outcomes across spot, IV and time changes to expose fragile assumptions.",
    detail: "Spot · IV · time",
    color: COLOR.positive,
  },
  {
    title: "Capital & Margin",
    eyebrow: "RISK",
    description: "Connect strategy structure to simulated capital, defined risk and margin requirements.",
    detail: "Capital · margin · max loss",
    color: COLOR.negative,
  },
  {
    title: "Trade Rehearsal",
    eyebrow: "EXECUTION",
    description: "Take an analyzed strategy into paper execution, positions and review without broker orders.",
    detail: "Orders · positions · P&L",
    color: COLOR.positive,
  },
];

const EVIDENCE_VIEWS = [
  {
    title: "Market View",
    label: "MARKET INTELLIGENCE",
    href: "/market-intelligence",
    color: COLOR.intelligence,
    rows: [
      ["Spot", "25,480"],
      ["PCR", "0.92"],
      ["IV", "18.2%"],
    ],
  },
  {
    title: "Positioning",
    label: "GEX / STRUCTURE",
    href: "/market-intelligence",
    color: COLOR.strategy,
    rows: [
      ["Gamma Flip", "25,450"],
      ["Call Wall", "25,600"],
      ["Put Wall", "25,300"],
    ],
  },
  {
    title: "Strategy",
    label: "STRATEGY LAB",
    href: "/strategy-lab",
    color: COLOR.info,
    rows: [
      ["Structure", "Bull Call"],
      ["Max Loss", "−₹45"],
      ["Breakeven", "25,495"],
    ],
  },
  {
    title: "Rehearsal",
    label: "PAPER TRADING",
    href: "/paper-trading",
    color: COLOR.positive,
    rows: [
      ["Capital", "₹5,00,000"],
      ["Positions", "3"],
      ["P&L", "+₹8,420"],
    ],
  },
];

const WHY_STRIKENOVA = [
  {
    title: "Structured",
    description: "Market information is organized into a connected workflow instead of isolated widgets.",
    color: COLOR.intelligence,
  },
  {
    title: "Risk-first",
    description: "Strategy analysis exposes payoff, breakevens and downside before execution is rehearsed.",
    color: COLOR.negative,
  },
  {
    title: "Explainable",
    description: "The workflow is grounded in observable positioning, volatility, Greeks and scenario inputs.",
    color: COLOR.strategy,
  },
  {
    title: "Rehearsable",
    description: "Paper execution turns an analytical decision into a repeatable process without broker orders.",
    color: COLOR.positive,
  },
];

export function IntelligenceStack() {
  return (
    <Section padding={SPACE.sectionLg} style={{ paddingTop: "2rem" }}>
      <Container maxWidth={1000}>
        <SectionTitle
          eyebrow="INTELLIGENCE STACK"
          title="From market data to structured decisions"
          subtitle="StrikeNova progressively turns raw option data into positioning context, strategy structure and risk-aware decisions."
          align="center"
        />

        <SignalPanel padding={SPACE.cardLg}>
          <FlexColumn gap={SPACE.comp}>
            {INTELLIGENCE_LAYERS.map((layer, index) => (
              <React.Fragment key={layer.label}>
                <OutlinePanel
                  padding={SPACE.comp}
                  border={`${layer.color}35`}
                  radius={RADIUS.md}
                  style={{ background: `${layer.color}08` }}
                >
                  <FlexRow justify="space-between" align="center" gap={SPACE.comp} wrap>
                    <FlexRow gap={SPACE.small} align="center" wrap={false}>
                      <span
                        aria-hidden="true"
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: layer.color,
                          boxShadow: `0 0 10px ${layer.color}45`,
                          flexShrink: 0,
                        }}
                      />
                      <span
                        style={{
                          fontSize: TYPE.labelSmall.size,
                          fontWeight: 700,
                          letterSpacing: TYPE.labelSmall.letterSpacing,
                          color: layer.color,
                          fontFamily: TYPE.data,
                        }}
                      >
                        {String(index + 1).padStart(2, "0")} · {layer.label}
                      </span>
                    </FlexRow>
                    <span
                      style={{
                        fontSize: TYPE.bodySmall.size,
                        color: COLOR.textMuted,
                      }}
                    >
                      {layer.detail}
                    </span>
                  </FlexRow>
                </OutlinePanel>
                {index < INTELLIGENCE_LAYERS.length - 1 && (
                  <div
                    aria-hidden="true"
                    style={{
                      width: 1,
                      height: 14,
                      marginLeft: 11,
                      background: COLOR.borderSubtle,
                    }}
                  />
                )}
              </React.Fragment>
            ))}
          </FlexColumn>
        </SignalPanel>
      </Container>
    </Section>
  );
}

export function DeepCapabilityGrid() {
  return (
    <Section padding={SPACE.sectionLg} style={{ paddingTop: "2rem" }}>
      <Container maxWidth={1100}>
        <SectionTitle
          eyebrow="GO DEEPER"
          title="The intelligence underneath the workflow"
          subtitle="Beyond the basic option chain: the analytical layers that help explain positioning, sensitivity and risk."
          align="center"
        />

        <CardGrid minItemWidth={320} gap={SPACE.compLg}>
          {DEEP_CAPABILITIES.map((item) => (
            <Panel
              key={item.title}
              padding={SPACE.cardLg}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: SPACE.comp,
                height: "100%",
                boxSizing: "border-box",
                borderTop: `3px solid ${item.color}`,
              }}
            >
              <Eyebrow color={item.color}>{item.eyebrow}</Eyebrow>
              <h3
                style={{
                  margin: 0,
                  fontSize: TYPE.h3.size,
                  lineHeight: TYPE.h3.lineHeight,
                  color: COLOR.textPrimary,
                }}
              >
                {item.title}
              </h3>
              <p
                style={{
                  margin: 0,
                  fontSize: TYPE.bodySmall.size,
                  lineHeight: TYPE.bodySmall.lineHeight,
                  color: COLOR.textMuted,
                }}
              >
                {item.description}
              </p>
              <span
                style={{
                  marginTop: "auto",
                  fontSize: TYPE.labelSmall.size,
                  color: item.color,
                  fontFamily: TYPE.data,
                }}
              >
                {item.detail}
              </span>
            </Panel>
          ))}
        </CardGrid>
      </Container>
    </Section>
  );
}

export function ProductEvidenceGrid() {
  return (
    <Section padding={SPACE.sectionLg} style={{ paddingTop: "2rem" }}>
      <Container maxWidth={1100}>
        <SectionTitle
          eyebrow="PRODUCT EVIDENCE"
          title="One workflow, four useful views"
          subtitle="The public experience should make the product legible before a visitor ever opens the app."
          align="center"
        />

        <CardGrid minItemWidth={320} gap={SPACE.compLg}>
          {EVIDENCE_VIEWS.map((view) => (
            <Panel
              key={view.title}
              padding={SPACE.compLg}
              style={{
                height: "100%",
                boxSizing: "border-box",
                display: "flex",
                flexDirection: "column",
                gap: SPACE.comp,
              }}
            >
              <FlexRow justify="space-between" align="center" gap={SPACE.small} wrap={false}>
                <Eyebrow color={view.color}>{view.label}</Eyebrow>
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: view.color,
                    boxShadow: `0 0 9px ${view.color}45`,
                    flexShrink: 0,
                  }}
                />
              </FlexRow>

              <h3
                style={{
                  margin: 0,
                  fontSize: TYPE.h3.size,
                  lineHeight: TYPE.h3.lineHeight,
                  color: COLOR.textPrimary,
                }}
              >
                {view.title}
              </h3>

              <div
                style={{
                  border: `1px solid ${COLOR.borderSubtle}`,
                  borderRadius: RADIUS.md,
                  overflow: "hidden",
                  background: COLOR.baseElevated,
                }}
              >
                {view.rows.map(([label, value], index) => (
                  <FlexRow
                    key={label}
                    justify="space-between"
                    align="center"
                    gap={SPACE.small}
                    wrap={false}
                    style={{
                      padding: `${SPACE.small} ${SPACE.comp}`,
                      borderTop: index === 0 ? "none" : `1px solid ${COLOR.borderSubtle}`,
                    }}
                  >
                    <span style={{ fontSize: TYPE.labelSmall.size, color: COLOR.textFaint }}>
                      {label}
                    </span>
                    <span
                      style={{
                        fontSize: TYPE.bodySmall.size,
                        fontWeight: 700,
                        color: view.color,
                        fontFamily: TYPE.data,
                      }}
                    >
                      {value}
                    </span>
                  </FlexRow>
                ))}
              </div>

              <div style={{ marginTop: "auto" }}>
                <LinkButton
                  href={view.href}
                  variant="ghost"
                  size="sm"
                  style={{ width: "100%", boxSizing: "border-box", borderColor: `${view.color}30`, color: view.color }}
                >
                  Explore {view.title} →
                </LinkButton>
              </div>
            </Panel>
          ))}
        </CardGrid>
      </Container>
    </Section>
  );
}

export function WhyStrikeNova() {
  return (
    <Section padding={SPACE.sectionLg} style={{ paddingTop: "2rem" }}>
      <Container maxWidth={1000}>
        <SectionTitle
          eyebrow="WHY STRIKENOVA"
          title="A workflow designed for serious analysis"
          subtitle="The platform is built around how a trade decision should be formed, not how a dashboard should look."
          align="center"
        />

        <CardGrid minItemWidth={220} gap={SPACE.compLg}>
          {WHY_STRIKENOVA.map((item) => (
            <Panel
              key={item.title}
              padding={SPACE.cardLg}
              style={{
                height: "100%",
                boxSizing: "border-box",
                borderTop: `2px solid ${item.color}`,
              }}
            >
              <FlexColumn gap={SPACE.small}>
                <span
                  style={{
                    fontSize: TYPE.h3.size,
                    fontWeight: 700,
                    color: item.color,
                  }}
                >
                  {item.title}
                </span>
                <span
                  style={{
                    fontSize: TYPE.bodySmall.size,
                    lineHeight: TYPE.bodySmall.lineHeight,
                    color: COLOR.textMuted,
                  }}
                >
                  {item.description}
                </span>
              </FlexColumn>
            </Panel>
          ))}
        </CardGrid>
      </Container>
    </Section>
  );
}
