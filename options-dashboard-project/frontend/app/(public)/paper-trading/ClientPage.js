"use client";
import { C, useIsMobile } from "@/lib/ui";
import {
  COLOR,
  TYPE,
  SPACE,
  RADIUS,
  SHADOW,
  MOTION,
  DATA_STATE,
} from "@/components/public";
import {
  DemoLabel,
  Eyebrow,
  SectionTitle,
} from "@/components/public/truth";
import {
  Surface,
  Panel,
  MetricPanel,
  OutlinePanel,
  SignalPanel,
} from "@/components/public/surfaces";
import {
  Button,
  LinkButton,
  TextLink,
} from "@/components/public/buttons";
import {
  Metric,
  formatMetricValue,
} from "@/components/public/Metric";
import {
  SignalLine,
  SignalNode,
  TechnicalDivider,
  GridOverlay,
} from "@/components/public/signals";
import {
  Section,
  Container,
  MetricGrid,
  CardGrid,
  FlexRow,
  FlexColumn,
} from "@/components/public/layout";
import { VisualizationFrame } from "@/components/public/VisualizationFrame";
import { useAuthModal } from "@/components/public/AuthModalContext";

// =============================================================================
// DETERMINISTIC DEMO DATA — ALL VALUES ILLUSTRATIVE
// No live data. No real orders. No real capital. No real performance.
// =============================================================================

const DEMO_COCKPIT = {
  capital: {
    starting: 500000,
    available: 387650,
    utilized: 112350,
    utilizationPct: 22.5,
  },
  pnl: {
    today: 4820,
    todayPct: 0.96,
    unrealized: 2150,
    realized: 2670,
    total: 18450,
  },
  orders: [
    { id: "DEMO-001", symbol: "NIFTY 25500 CE", side: "BUY", qty: 65, price: 142.5, status: "FILLED (SIM)", time: "09:32" },
    { id: "DEMO-002", symbol: "NIFTY 25700 CE", side: "SELL", qty: 65, price: 68.25, status: "FILLED (SIM)", time: "09:32" },
    { id: "DEMO-003", symbol: "BANKNIFTY 54000 PE", side: "BUY", qty: 30, price: 315.0, status: "FILLED (SIM)", time: "10:15" },
    { id: "DEMO-004", symbol: "BANKNIFTY 53500 PE", side: "SELL", qty: 30, price: 198.75, status: "FILLED (SIM)", time: "10:15" },
  ],
  positions: [
    {
      symbol: "NIFTY 25500 CE",
      side: "LONG",
      qty: 65,
      entry: 142.5,
      mark: 158.2,
      pnl: 1020.5,
      pnlPct: 11.1,
      status: "OPEN (SIM)",
      strategy: "Bull Call Spread",
    },
    {
      symbol: "NIFTY 25700 CE",
      side: "SHORT",
      qty: 65,
      entry: 68.25,
      mark: 61.8,
      pnl: 419.25,
      pnlPct: 9.4,
      status: "OPEN (SIM)",
      strategy: "Bull Call Spread",
    },
    {
      symbol: "BANKNIFTY 54000 PE",
      side: "LONG",
      qty: 30,
      entry: 315.0,
      mark: 298.5,
      pnl: -495.0,
      pnlPct: -5.2,
      status: "OPEN (SIM)",
      strategy: "Bull Put Spread",
    },
    {
      symbol: "BANKNIFTY 53500 PE",
      side: "SHORT",
      qty: 30,
      entry: 198.75,
      mark: 175.4,
      pnl: 700.5,
      pnlPct: 11.8,
      status: "OPEN (SIM)",
      strategy: "Bull Put Spread",
    },
  ],
  review: {
    totalTrades: 47,
    winRate: 68,
    avgWin: 3250,
    avgLoss: -1840,
    profitFactor: 1.76,
    maxDrawdown: -4200,
    sharpe: 1.42,
  },
};

// =============================================================================
// WORKFLOW SEQUENCE — DECISION → SIMULATION → ORDERS → POSITIONS → P&L → REVIEW
// =============================================================================

const WORKFLOW_STEPS = [
  { label: "DECISION", color: COLOR.strategy, desc: "Define your thesis" },
  { label: "SIMULATION", color: COLOR.intelligence, desc: "Model the outcome" },
  { label: "ORDERS", color: COLOR.info, desc: "Paper execution" },
  { label: "POSITIONS", color: COLOR.textPrimary, desc: "Track exposure" },
  { label: "P&L", color: COLOR.positive, desc: "Measure result" },
  { label: "REVIEW", color: COLOR.warning, desc: "Journal & learn" },
];

// =============================================================================
// POSITION CARD — Mobile-safe card replacing wide table
// =============================================================================

function PositionCard({ position }) {
  const isPositive = position.pnl >= 0;
  const pnlColor = isPositive ? COLOR.positive : COLOR.negative;
  const sideColor = position.side === "LONG" ? COLOR.positive : COLOR.negative;
  const sideBg = position.side === "LONG" ? COLOR.positiveDim : COLOR.negativeDim;

  return (
    <Surface
      padding={SPACE.card}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: SPACE.comp,
        minWidth: 0,
      }}
    >
      {/* Header row: symbol + side badge */}
      <FlexRow justify="space-between" align="center" gap={SPACE.small}>
        <div
          style={{
            fontSize: TYPE.bodySmall.size,
            fontWeight: 700,
            color: COLOR.textPrimary,
            fontFamily: TYPE.data,
            letterSpacing: "0.02em",
          }}
        >
          {position.symbol}
        </div>
        <span
          style={{
            fontSize: "0.625rem",
            fontWeight: 700,
            letterSpacing: "0.06em",
            color: sideColor,
            background: sideBg,
            border: `1px solid ${sideColor}40`,
            borderRadius: RADIUS.sm,
            padding: "0.125rem 0.5rem",
            textTransform: "uppercase",
            whiteSpace: "nowrap",
          }}
        >
          {position.side}
        </span>
      </FlexRow>

      {/* Strategy label */}
      <div
        style={{
          fontSize: TYPE.caption.size,
          color: COLOR.textFaint,
          letterSpacing: "0.04em",
        }}
      >
        {position.strategy}
      </div>

      {/* Metric grid — 2 columns on mobile, safe from overflow */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: SPACE.small,
        }}
      >
        <Metric
          label="Qty"
          value={position.qty}
          size="sm"
          status="DEMO"
          style={{ gap: "0.125rem" }}
        />
        <Metric
          label="Entry"
          value={position.entry}
          decimals={2}
          size="sm"
          status="DEMO"
          style={{ gap: "0.125rem" }}
        />
        <Metric
          label="Mark"
          value={position.mark}
          decimals={2}
          size="sm"
          status="DEMO"
          style={{ gap: "0.125rem" }}
        />
        <FlexColumn gap="0.125rem" align="flex-start">
          <span
            style={{
              fontSize: TYPE.caption.size,
              fontWeight: 600,
              letterSpacing: "0.06em",
              color: COLOR.textFaint,
              textTransform: "uppercase",
            }}
          >
            P&L
          </span>
          <span
            style={{
              fontSize: TYPE.data.size,
              fontWeight: 700,
              color: pnlColor,
              fontFamily: TYPE.data,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {isPositive ? "+" : ""}
            {formatMetricValue(position.pnl, 2)}
          </span>
          <span
            style={{
              fontSize: "0.6875rem",
              color: pnlColor,
              fontFamily: TYPE.data,
            }}
          >
            ({isPositive ? "+" : ""}
            {position.pnlPct}%)
          </span>
        </FlexColumn>
      </div>

      {/* Status badge */}
      <FlexRow justify="space-between" align="center">
        <span
          style={{
            fontSize: "0.625rem",
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: COLOR.warning,
            background: COLOR.warningDim,
            border: `1px solid ${COLOR.warning}40`,
            borderRadius: RADIUS.sm,
            padding: "0.125rem 0.5rem",
            textTransform: "uppercase",
          }}
        >
          {position.status}
        </span>
        <TextLink href="#" style={{ fontSize: "0.75rem" }}>
          Journal &rarr;
        </TextLink>
      </FlexRow>
    </Surface>
  );
}

// =============================================================================
// ORDER ROW — Compact, mobile-safe
// =============================================================================

function OrderRow({ order }) {
  const isBuy = order.side === "BUY";
  const sideColor = isBuy ? COLOR.positive : COLOR.negative;
  const sideBg = isBuy ? COLOR.positiveDim : COLOR.negativeDim;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto auto auto",
        gap: SPACE.comp,
        alignItems: "center",
        padding: `${SPACE.small} 0`,
        borderBottom: `1px solid ${COLOR.borderSubtle}`,
        fontSize: TYPE.bodySmall.size,
        fontFamily: TYPE.data,
        minWidth: 0,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            color: COLOR.textPrimary,
            fontWeight: 600,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {order.symbol}
        </div>
        <div style={{ color: COLOR.textFaint, fontSize: "0.6875rem" }}>
          {order.id} &middot; {order.time}
        </div>
      </div>
      <span
        style={{
          fontSize: "0.625rem",
          fontWeight: 700,
          letterSpacing: "0.06em",
          color: sideColor,
          background: sideBg,
          border: `1px solid ${sideColor}40`,
          borderRadius: RADIUS.sm,
          padding: "0.125rem 0.5rem",
          textTransform: "uppercase",
          whiteSpace: "nowrap",
        }}
      >
        {order.side}
      </span>
      <span
        style={{
          color: COLOR.textSecondary,
          fontVariantNumeric: "tabular-nums",
          whiteSpace: "nowrap",
        }}
      >
        {order.qty} @ {formatMetricValue(order.price, 2)}
      </span>
      <span
        style={{
          fontSize: "0.625rem",
          fontWeight: 600,
          letterSpacing: "0.04em",
          color: COLOR.info,
          background: COLOR.infoDim,
          border: `1px solid ${COLOR.info}30`,
          borderRadius: RADIUS.sm,
          padding: "0.125rem 0.5rem",
          textTransform: "uppercase",
          whiteSpace: "nowrap",
        }}
      >
        {order.status}
      </span>
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function PaperTradingClientPage() {
  const isMobile = useIsMobile();
  const { open: openAuth } = useAuthModal();

  return (
    <>
      {/* ===== HERO ===== */}
      <Section
        background={`radial-gradient(ellipse 80% 60% at 50% 0%, ${COLOR.strategyDim}, transparent 65%), linear-gradient(180deg, ${COLOR.baseElevated}, ${COLOR.base})`}
        padding={SPACE.hero}
        style={{ textAlign: "center" }}
      >
        <Container maxWidth={800}>
          <FlexColumn gap={SPACE.compLg} align="center">
            {/* Eyebrow */}
            <Eyebrow color={COLOR.strategy}>Rehearsal Cockpit</Eyebrow>

            {/* Hero title */}
            <h1
              style={{
                fontSize: TYPE.displayH1.size,
                fontWeight: TYPE.displayH1.weight,
                color: COLOR.textPrimary,
                lineHeight: TYPE.displayH1.lineHeight,
                letterSpacing: TYPE.displayH1.letterSpacing,
                margin: 0,
                fontFamily: TYPE.display,
              }}
            >
              Practice the decision{" "}
              <span style={{ color: COLOR.strategy }}>before risking capital</span>
            </h1>

            {/* Subtitle */}
            <p
              style={{
                fontSize: TYPE.bodyLarge.size,
                color: COLOR.textMuted,
                lineHeight: TYPE.bodyLarge.lineHeight,
                margin: 0,
                maxWidth: "36rem",
                fontFamily: TYPE.body,
              }}
            >
              A simulated environment to rehearse options strategies, test execution
              decisions, and build confidence — without placing real orders or
              touching real capital.
            </p>

            {/* CTA row */}
            <FlexRow gap={SPACE.medium} justify="center" wrap>
              <Button
                variant="primary"
                size="lg"
                onClick={openAuth}
                testId="hero-cta-primary"
              >
                Start Simulated Session
              </Button>
              <LinkButton
                variant="secondary"
                size="lg"
                href="/strategy-lab"
              >
                Build a Strategy
              </LinkButton>
            </FlexRow>

            {/* Demo badge */}
            <DemoLabel />
          </FlexColumn>
        </Container>
      </Section>

      {/* ===== WORKFLOW SEQUENCE ===== */}
      <Section>
        <Container maxWidth={900}>
          <SectionTitle
            eyebrow="The Rehearsal Pipeline"
            title="From decision to review — a connected sequence"
            subtitle="Every step in the cockpit is simulated. No real orders, no real capital, no real risk."
            align="center"
          />

          {/* Workflow steps */}
          <div
            style={{
              display: "flex",
              flexDirection: isMobile ? "column" : "row",
              alignItems: isMobile ? "stretch" : "center",
              justifyContent: "center",
              gap: isMobile ? SPACE.small : 0,
              flexWrap: "wrap",
            }}
          >
            {WORKFLOW_STEPS.map((step, i) => (
              <FlexRow
                key={step.label}
                gap={SPACE.small}
                align="center"
                justify="center"
                style={{ flex: isMobile ? "none" : "0 1 auto" }}
              >
                <Surface
                  padding={`${SPACE.medium} ${SPACE.compLg}`}
                  background={`${step.color}08`}
                  border={`${step.color}30`}
                  radius={RADIUS.md}
                  style={{
                    textAlign: "center",
                    minWidth: isMobile ? "auto" : "120px",
                    flex: isMobile ? "1" : "none",
                  }}
                >
                  <div
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 700,
                      letterSpacing: "0.08em",
                      color: step.color,
                      textTransform: "uppercase",
                      marginBottom: "0.25rem",
                    }}
                  >
                    {step.label}
                  </div>
                  <div
                    style={{
                      fontSize: TYPE.caption.size,
                      color: COLOR.textMuted,
                    }}
                  >
                    {step.desc}
                  </div>
                </Surface>
                {i < WORKFLOW_STEPS.length - 1 && (
                  <span
                    style={{
                      color: COLOR.textFaint,
                      fontSize: "0.875rem",
                      transform: isMobile ? "rotate(90deg)" : "none",
                      flexShrink: 0,
                    }}
                    aria-hidden="true"
                  >
                    &rarr;
                  </span>
                )}
              </FlexRow>
            ))}
          </div>
        </Container>
      </Section>

      {/* ===== COCKPIT COMPOSITION ===== */}
      <Section background={COLOR.baseElevated}>
        <Container maxWidth={1100}>
          {/* Section header */}
          <FlexColumn gap={SPACE.comp} style={{ marginBottom: SPACE.group }}>
            <FlexRow justify="space-between" align="center" wrap gap={SPACE.small}>
              <Eyebrow color={COLOR.warning}>Illustrative Cockpit View</Eyebrow>
              <DataStateBadge state="DEMO" />
            </FlexRow>
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
              Cockpit Composition
            </h2>
            <p
              style={{
                fontSize: TYPE.body.size,
                color: COLOR.textMuted,
                lineHeight: TYPE.body.lineHeight,
                margin: 0,
                maxWidth: "42rem",
              }}
            >
              All values below are simulated and illustrative. They demonstrate the
              workflow — not real performance, real orders, or real capital.
            </p>
          </FlexColumn>

          {/* ===== SIMULATED CAPITAL ===== */}
          <Panel
            padding={SPACE.cardLg}
            style={{ marginBottom: SPACE.group }}
          >
            <FlexColumn gap={SPACE.compLg}>
              <FlexRow justify="space-between" align="center" wrap gap={SPACE.small}>
                <div>
                  <div
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      color: COLOR.textFaint,
                      textTransform: "uppercase",
                      marginBottom: SPACE.xs,
                    }}
                  >
                    Simulated Capital
                  </div>
                  <div
                    style={{
                      fontSize: TYPE.displayHero.size,
                      fontWeight: TYPE.displayHero.weight,
                      color: COLOR.strategy,
                      fontFamily: TYPE.data,
                      fontVariantNumeric: "tabular-nums",
                      lineHeight: 1.1,
                    }}
                  >
                    &#8377;{formatMetricValue(DEMO_COCKPIT.capital.starting)}
                  </div>
                </div>
                <DemoLabel />
              </FlexRow>

              <MetricGrid minItemWidth={140} gap={SPACE.comp}>
                <Metric
                  label="Available (Sim)"
                  value={`&#8377;${formatMetricValue(DEMO_COCKPIT.capital.available)}`}
                  status="DEMO"
                  size="md"
                  color={COLOR.textPrimary}
                />
                <Metric
                  label="Utilized (Sim)"
                  value={`&#8377;${formatMetricValue(DEMO_COCKPIT.capital.utilized)}`}
                  status="DEMO"
                  size="md"
                  color={COLOR.textSecondary}
                />
                <Metric
                  label="Utilization"
                  value={`${DEMO_COCKPIT.capital.utilizationPct}%`}
                  status="DEMO"
                  size="md"
                  color={COLOR.warning}
                />
              </MetricGrid>

              {/* Utilization bar */}
              <div
                style={{
                  height: "6px",
                  background: COLOR.surfaceDeep,
                  borderRadius: RADIUS.pill,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${DEMO_COCKPIT.capital.utilizationPct}%`,
                    height: "100%",
                    background: `linear-gradient(90deg, ${COLOR.strategy}, ${COLOR.warning})`,
                    borderRadius: RADIUS.pill,
                    transition: "width 0.6s ease",
                  }}
                />
              </div>
            </FlexColumn>
          </Panel>

          {/* ===== P&L PANEL ===== */}
          <Panel
            padding={SPACE.cardLg}
            style={{ marginBottom: SPACE.group }}
          >
            <FlexColumn gap={SPACE.compLg}>
              <FlexRow justify="space-between" align="center" wrap gap={SPACE.small}>
                <div>
                  <div
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      color: COLOR.textFaint,
                      textTransform: "uppercase",
                      marginBottom: SPACE.xs,
                    }}
                  >
                    P&L (Illustrative)
                  </div>
                  <FlexRow gap={SPACE.small} align="baseline">
                    <span
                      style={{
                        fontSize: TYPE.displayHero.size,
                        fontWeight: TYPE.displayHero.weight,
                        color: COLOR.positive,
                        fontFamily: TYPE.data,
                        fontVariantNumeric: "tabular-nums",
                        lineHeight: 1.1,
                      }}
                    >
                      +&#8377;{formatMetricValue(DEMO_COCKPIT.pnl.today)}
                    </span>
                    <span
                      style={{
                        fontSize: TYPE.body.size,
                        color: COLOR.positive,
                        fontFamily: TYPE.data,
                      }}
                    >
                      (+{DEMO_COCKPIT.pnl.todayPct}%)
                    </span>
                  </FlexRow>
                </div>
                <DataStateBadge state="ILLUSTRATIVE" />
              </FlexRow>

              <MetricGrid minItemWidth={120} gap={SPACE.comp}>
                <Metric
                  label="Unrealized (Sim)"
                  value={`&#8377;${formatMetricValue(DEMO_COCKPIT.pnl.unrealized)}`}
                  status="DEMO"
                  size="md"
                  color={COLOR.positive}
                />
                <Metric
                  label="Realized (Sim)"
                  value={`&#8377;${formatMetricValue(DEMO_COCKPIT.pnl.realized)}`}
                  status="DEMO"
                  size="md"
                  color={COLOR.positive}
                />
                <Metric
                  label="Total Session P&L"
                  value={`&#8377;${formatMetricValue(DEMO_COCKPIT.pnl.total)}`}
                  status="DEMO"
                  size="md"
                  color={COLOR.textPrimary}
                />
              </MetricGrid>
            </FlexColumn>
          </Panel>

          {/* ===== ORDER ACTIONS ===== */}
          <Panel
            padding={SPACE.cardLg}
            style={{ marginBottom: SPACE.group }}
          >
            <FlexColumn gap={SPACE.compLg}>
              <FlexRow justify="space-between" align="center" wrap gap={SPACE.small}>
                <div>
                  <div
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      color: COLOR.textFaint,
                      textTransform: "uppercase",
                      marginBottom: SPACE.xs,
                    }}
                  >
                    Recent Orders (Simulated)
                  </div>
                  <div
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                    }}
                  >
                    Paper execution — no real broker orders placed
                  </div>
                </div>
                <span
                  style={{
                    fontSize: "0.625rem",
                    fontWeight: 600,
                    letterSpacing: "0.06em",
                    color: COLOR.info,
                    background: COLOR.infoDim,
                    border: `1px solid ${COLOR.info}30`,
                    borderRadius: RADIUS.sm,
                    padding: "0.125rem 0.5rem",
                    textTransform: "uppercase",
                  }}
                >
                  SIMULATED
                </span>
              </FlexRow>

              <div style={{ overflow: "hidden" }}>
                {DEMO_COCKPIT.orders.map((order) => (
                  <OrderRow key={order.id} order={order} />
                ))}
              </div>
            </FlexColumn>
          </Panel>

          {/* ===== POSITION CARDS (replaces wide table) ===== */}
          <div style={{ marginBottom: SPACE.group }}>
            <FlexColumn gap={SPACE.comp} style={{ marginBottom: SPACE.group }}>
              <FlexRow justify="space-between" align="center" wrap gap={SPACE.small}>
                <div>
                  <div
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      color: COLOR.textFaint,
                      textTransform: "uppercase",
                      marginBottom: SPACE.xs,
                    }}
                  >
                    Open Positions (Illustrative)
                  </div>
                  <div
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                    }}
                  >
                    Each card represents a simulated position — no real exposure
                  </div>
                </div>
                <DataStateBadge state="DEMO" />
              </FlexRow>
            </FlexColumn>

            <CardGrid minItemWidth={280} gap={SPACE.compLg}>
              {DEMO_COCKPIT.positions.map((pos) => (
                <PositionCard key={pos.symbol} position={pos} />
              ))}
            </CardGrid>
          </div>

          {/* ===== REVIEW / JOURNAL ===== */}
          <Panel
            padding={SPACE.cardLg}
            style={{ marginBottom: SPACE.group }}
          >
            <FlexColumn gap={SPACE.compLg}>
              <FlexRow justify="space-between" align="center" wrap gap={SPACE.small}>
                <div>
                  <div
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      color: COLOR.textFaint,
                      textTransform: "uppercase",
                      marginBottom: SPACE.xs,
                    }}
                  >
                    Session Review (Illustrative)
                  </div>
                  <div
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                    }}
                  >
                    Performance metrics from simulated trading — not real results
                  </div>
                </div>
                <DataStateBadge state="ILLUSTRATIVE" />
              </FlexRow>

              <MetricGrid minItemWidth={120} gap={SPACE.comp}>
                <Metric
                  label="Total Trades (Sim)"
                  value={DEMO_COCKPIT.review.totalTrades}
                  status="DEMO"
                  size="md"
                  color={COLOR.textPrimary}
                />
                <Metric
                  label="Win Rate (Sim)"
                  value={`${DEMO_COCKPIT.review.winRate}%`}
                  status="DEMO"
                  size="md"
                  color={COLOR.positive}
                />
                <Metric
                  label="Avg Win (Sim)"
                  value={`&#8377;${formatMetricValue(DEMO_COCKPIT.review.avgWin)}`}
                  status="DEMO"
                  size="md"
                  color={COLOR.positive}
                />
                <Metric
                  label="Avg Loss (Sim)"
                  value={`&#8377;${formatMetricValue(DEMO_COCKPIT.review.avgLoss)}`}
                  status="DEMO"
                  size="md"
                  color={COLOR.negative}
                />
                <Metric
                  label="Profit Factor"
                  value={DEMO_COCKPIT.review.profitFactor}
                  decimals={2}
                  status="DEMO"
                  size="md"
                  color={COLOR.info}
                />
                <Metric
                  label="Max Drawdown (Sim)"
                  value={`&#8377;${formatMetricValue(DEMO_COCKPIT.review.maxDrawdown)}`}
                  status="DEMO"
                  size="md"
                  color={COLOR.negative}
                />
                <Metric
                  label="Sharpe (Sim)"
                  value={DEMO_COCKPIT.review.sharpe}
                  decimals={2}
                  status="DEMO"
                  size="md"
                  color={COLOR.intelligence}
                />
              </MetricGrid>

              <TechnicalDivider label="Journal" />

              <Surface
                padding={SPACE.card}
                background={COLOR.surfaceDeep}
                border={COLOR.borderSubtle}
              >
                <FlexColumn gap={SPACE.small}>
                  <div
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.7,
                    }}
                  >
                    <strong style={{ color: COLOR.textSecondary }}>
                      [DEMO ENTRY] 2025-09-11 — Bull Call Spread on NIFTY:
                    </strong>{" "}
                    Entered 25500/25700 call spread based on support at 25300 and
                    PCR &gt; 1.15. Thesis: range-bound to mild bullish. Max risk
                    defined. <em style={{ color: COLOR.textFaint }}>(Illustrative journal entry)</em>
                  </div>
                  <div
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.7,
                    }}
                  >
                    <strong style={{ color: COLOR.textSecondary }}>
                      [DEMO ENTRY] 2025-09-11 — Bull Put Spread on BANKNIFTY:
                    </strong>{" "}
                    Sold 53500 PE against 54000 PE. IV rank elevated — premium
                    selling opportunity. Stop: break below 53200.{" "}
                    <em style={{ color: COLOR.textFaint }}>(Illustrative journal entry)</em>
                  </div>
                </FlexColumn>
              </Surface>
            </FlexColumn>
          </Panel>
        </Container>
      </Section>

      {/* ===== HIGHLY VISIBLE DISCLAIMER ===== */}
      <Section
        background={`linear-gradient(180deg, ${COLOR.baseElevated}, ${COLOR.base})`}
        style={{ borderTop: `2px solid ${COLOR.warning}40` }}
      >
        <Container maxWidth={800}>
          <Surface
            padding={SPACE.cardLg}
            background={COLOR.warningDim}
            border={`${COLOR.warning}50`}
            radius={RADIUS.lg}
            style={{
              textAlign: "center",
              boxShadow: SHADOW.glowStrategy,
            }}
          >
            <FlexColumn gap={SPACE.comp} align="center">
              <div
                style={{
                  fontSize: "2rem",
                  color: COLOR.warning,
                  lineHeight: 1,
                }}
                aria-hidden="true"
              >
                &#9888;
              </div>
              <h2
                style={{
                  fontSize: TYPE.h3.size,
                  fontWeight: TYPE.h3.weight,
                  color: COLOR.warning,
                  margin: 0,
                  letterSpacing: TYPE.h3.letterSpacing,
                  lineHeight: TYPE.h3.lineHeight,
                }}
              >
                No Real-Money Orders Are Placed
              </h2>
              <p
                style={{
                  fontSize: TYPE.body.size,
                  color: COLOR.textSecondary,
                  lineHeight: 1.7,
                  margin: 0,
                  maxWidth: "38rem",
                }}
              >
                This is a <strong style={{ color: COLOR.textPrimary }}>simulated rehearsal environment</strong>.
                All orders, positions, P&L, and performance metrics are{" "}
                <strong style={{ color: COLOR.textPrimary }}>illustrative</strong>.
                No real broker orders are placed. No real capital is at risk.
                No real account balances are shown. Past paper-trading
                performance is not indicative of real trading outcomes.
              </p>
              <FlexRow gap={SPACE.small} justify="center" wrap>
                <DataStateBadge state="DEMO" />
                <DataStateBadge state="ILLUSTRATIVE" />
              </FlexRow>
            </FlexColumn>
          </Surface>
        </Container>
      </Section>

      {/* ===== CTA ===== */}
      <Section>
        <Container maxWidth={700} style={{ textAlign: "center" }}>
          <FlexColumn gap={SPACE.compLg} align="center">
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
              Ready to{" "}
              <span style={{ color: COLOR.strategy }}>rehearse</span>?
            </h2>
            <p
              style={{
                fontSize: TYPE.body.size,
                color: COLOR.textMuted,
                lineHeight: 1.7,
                margin: 0,
              }}
            >
              Start a simulated session. Test your strategies. Build confidence.
              No real money required.
            </p>
            <FlexRow gap={SPACE.medium} justify="center" wrap>
              <Button
                variant="primary"
                size="lg"
                onClick={openAuth}
                testId="cta-primary"
              >
                Start Simulated Session &rarr;
              </Button>
              <LinkButton
                variant="secondary"
                size="lg"
                href="/strategy-lab"
              >
                Build a Strategy
              </LinkButton>
            </FlexRow>
            <DemoLabel />
          </FlexColumn>
        </Container>
      </Section>
    </>
  );
}

// =============================================================================
// DATA STATE BADGE (local helper)
// =============================================================================

function DataStateBadge({ state }) {
  const s = DATA_STATE[state];
  if (!s) return null;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.25rem",
        fontSize: "0.625rem",
        fontWeight: 600,
        letterSpacing: "0.06em",
        color: s.color,
        textTransform: "uppercase",
        background: `${s.color}10`,
        border: `1px solid ${s.color}30`,
        borderRadius: RADIUS.sm,
        padding: "0.125rem 0.5rem",
      }}
    >
      {state === "LIVE" && (
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: s.color,
            boxShadow: `0 0 4px ${s.color}`,
            animation: "sn-pulse 1.6s ease-in-out infinite",
          }}
        />
      )}
      {s.label}
    </span>
  );
}
