// =============================================================================
// StrikeNova Public Design System — Features Intelligence Story Sections
// =============================================================================
// Clean reimplementation derived from historical PR #46, ported onto the
// current design system. Only technically validated content is included:
// the Intelligence Stack, Deep Capability coverage, and Product Evidence
// panels (with strict illustrative-data marking). Founder-gated copy
// ("Why StrikeNova" principles, closing-CTA wording) is intentionally
// EXCLUDED and remains a separate product decision.
//
// Truthfulness contract: every sample metric in ProductEvidenceGrid renders
// through the Metric primitive with status="DEMO" + source="ILLUSTRATIVE",
// using Metric's built-in muted DEMO rendering. No sample value is ever
// presented as live market data.
// =============================================================================

import React from "react";
import { COLOR, TYPE, SPACE, RADIUS } from "./tokens";
import { Section, Container, CardGrid, FlexColumn, FlexRow } from "./layout";
import { Panel, OutlinePanel, SignalPanel } from "./surfaces";
import { Eyebrow, SectionTitle } from "./truth";
import { LinkButton } from "./buttons";
import { Metric } from "./Metric";

// -----------------------------------------------------------------------------
// Intelligence Stack — the analytical pipeline. Every layer maps to real
// StrikeNova engines (backend/app/...): market_data, intelligence/positioning,
// quant/iv, quant/greeks, quant/gex, quant/scenarios, the strategy surface,
// central_risk + final_risk_gate.
// -----------------------------------------------------------------------------

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

// -----------------------------------------------------------------------------
// Deep Capability coverage — GEX, volatility, Greeks, scenarios, capital &
// margin, paper rehearsal. All six are current, shipped functionality
// (backend/app/quant, opportunity, central_risk + the paper trading surface).
// -----------------------------------------------------------------------------

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

// -----------------------------------------------------------------------------
// Product Evidence — six product views with ILLUSTRATIVE sample data only.
// Every metric row is rendered through the Metric primitive with
// status="DEMO" + source="ILLUSTRATIVE" (see EvidenceMetricRow below).
// -----------------------------------------------------------------------------

const EVIDENCE_VIEWS = [
  {
    title: "Market View",
    label: "MARKET INTELLIGENCE",
    href: "/market-intelligence",
    color: COLOR.intelligence,
    rows: [
      ["Spot", "25,480", ""],
      ["PCR", "0.92", ""],
      ["IV", "18.2", "%"],
    ],
  },
  {
    title: "Positioning",
    label: "GEX / STRUCTURE",
    href: "/market-intelligence",
    color: COLOR.strategy,
    rows: [
      ["Gamma Flip", "25,450", ""],
      ["Call Wall", "25,600", ""],
      ["Put Wall", "25,300", ""],
      ["GEX Regime", "POSITIVE", ""],
    ],
  },
  {
    title: "Strategy",
    label: "STRATEGY LAB",
    href: "/strategy-lab",
    color: COLOR.info,
    rows: [
      ["Structure", "Bull Call", ""],
      ["Max Loss", "−45", "₹"],
      ["Breakeven", "25,495", ""],
    ],
  },
  {
    title: "Risk",
    label: "RISK / SCENARIO",
    href: "/strategy-lab",
    color: COLOR.negative,
    rows: [
      ["Spot −2%", "−18,400", "₹"],
      ["IV +5 pts", "+6,800", "₹"],
      ["Max Loss", "−45,000", "₹"],
    ],
  },
  {
    title: "Rehearsal",
    label: "PAPER TRADING",
    href: "/paper-trading",
    color: COLOR.positive,
    rows: [
      ["Capital", "5,00,000", "₹"],
      ["Positions", "3", ""],
      ["P&L", "+8,420", "₹"],
    ],
  },
  {
    title: "Review",
    label: "TRADE REVIEW",
    href: "/paper-trading",
    color: COLOR.info,
    rows: [
      ["Trades", "24", ""],
      ["Win Rate", "62.5", "%"],
      ["Avg R:R", "1.8:1", ""],
    ],
  },
];

/**
 * EvidenceMetricRow — renders one sample metric through the Metric primitive
 * with the mandatory truthfulness marking: status="DEMO" + source="ILLUSTRATIVE".
 */
function EvidenceMetricRow({ label, value, unit }) {
  return (
    <Metric
      label={label}
      value={value}
      unit={unit || undefined}
      status="DEMO"
      source="ILLUSTRATIVE"
      size="sm"
    />
  );
}

// -----------------------------------------------------------------------------
// Sections
// -----------------------------------------------------------------------------

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
                    <span style={{ fontSize: TYPE.bodySmall.size, color: COLOR.textMuted }}>
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
          eyebrow="PRODUCT EVIDENCE — ILLUSTRATIVE"
          title="One workflow, six useful views"
          subtitle="Example output views with illustrative data — not current market measurements. Open the product to see the real workflow."
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
                  aria-hidden="true"
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
                {view.rows.map(([label, value, unit], index) => (
                  <div
                    key={label}
                    style={{
                      padding: `${SPACE.small} ${SPACE.comp}`,
                      borderTop: index === 0 ? "none" : `1px solid ${COLOR.borderSubtle}`,
                    }}
                  >
                    <EvidenceMetricRow label={label} value={value} unit={unit} />
                  </div>
                ))}
              </div>
              <div style={{ marginTop: "auto" }}>
                <LinkButton
                  href={view.href}
                  variant="ghost"
                  size="sm"
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    borderColor: `${view.color}30`,
                    color: view.color,
                  }}
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
