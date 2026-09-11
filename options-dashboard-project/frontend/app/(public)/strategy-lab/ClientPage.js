"use client";
import { C, useIsMobile, fmtIN } from "@/lib/ui";
import {
  COLOR,
  TYPE,
  SPACE,
  RADIUS,
  Section,
  Container,
  TwoColumn,
  MetricGrid,
  FlexRow,
  FlexColumn,
  Panel,
  MetricPanel,
  OutlinePanel,
  SignalPanel,
  Button,
  LinkButton,
  TextLink,
  Metric,
  VisualizationFrame,
  SignalLine,
  DataTrace,
  TechnicalDivider,
  DemoLabel,
  Eyebrow,
  SectionTitle,
} from "@/components/public";

// =============================================================================
// DEMO DATA — ILLUSTRATIVE VALUES ONLY
// =============================================================================

const DEMO_PAYOFF = [];
for (let s = 24500; s <= 26500; s += 100) {
  let pnl = 0;
  pnl += Math.min(0, s - 25500);
  pnl -= Math.min(0, s - 25700);
  pnl += Math.min(0, 25500 - s);
  pnl -= Math.min(0, 25300 - s);
  DEMO_PAYOFF.push({ strike: s, pnl: pnl * 65 });
}

const MAX_PROFIT = 3250;
const MAX_LOSS = -9750;
const BREAKEVEN_LOW = 25250;
const BREAKEVEN_HIGH = 25750;

const LEGS = [
  { action: "SELL", strike: 25500, type: "CE", ltp: 142.35, qty: 1 },
  { action: "BUY", strike: 25700, type: "CE", ltp: 68.10, qty: 1 },
  { action: "SELL", strike: 25500, type: "PE", ltp: 138.80, qty: 1 },
  { action: "BUY", strike: 25300, type: "PE", ltp: 64.55, qty: 1 },
];

const GREEKS = [
  { label: "Delta", value: "-0.02", unit: "", color: COLOR.textMuted },
  { label: "Gamma", value: "0.0003", unit: "", color: COLOR.textMuted },
  { label: "Theta", value: "+42.15", unit: "/day", color: COLOR.positive },
  { label: "Vega", value: "-18.40", unit: "", color: COLOR.negative },
];

const SCENARIOS = [
  { label: "Spot +200", value: "+₹1,240", color: COLOR.positive },
  { label: "Spot -200", value: "+₹1,180", color: COLOR.positive },
  { label: "IV +3%", value: "-₹552", color: COLOR.negative },
  { label: "IV -3%", value: "+₹552", color: COLOR.positive },
  { label: "7 Days Pass", value: "+₹295", color: COLOR.positive },
  { label: "Max Loss", value: "-₹9,750", color: COLOR.negative },
];

const STRIKES = [25300, 25400, 25500, 25600, 25700];
const SPOT = 25500;

// =============================================================================
// PAYOFF CHART (reused logic from original)
// =============================================================================

function PayoffChart() {
  const width = 600;
  const height = 240;
  const padding = { top: 24, right: 24, bottom: 36, left: 56 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  const minPnl = Math.min(...DEMO_PAYOFF.map((d) => d.pnl));
  const maxPnl = Math.max(...DEMO_PAYOFF.map((d) => d.pnl));
  const range = maxPnl - minPnl || 1;
  const minStrike = DEMO_PAYOFF[0].strike;
  const maxStrike = DEMO_PAYOFF[DEMO_PAYOFF.length - 1].strike;
  const strikeRange = maxStrike - minStrike;

  const points = DEMO_PAYOFF.map((d) => ({
    x: padding.left + ((d.strike - minStrike) / strikeRange) * plotW,
    y: padding.top + ((maxPnl - d.pnl) / range) * plotH,
  }));

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const zeroY = padding.top + ((maxPnl - 0) / range) * plotH;
  const beLowX = padding.left + ((BREAKEVEN_LOW - minStrike) / strikeRange) * plotW;
  const beHighX = padding.left + ((BREAKEVEN_HIGH - minStrike) / strikeRange) * plotW;

  const leftClip = `${padding.left} ${padding.top} ${beLowX - padding.left} ${plotH}`;
  const profitClip = `${beLowX} ${padding.top} ${beHighX - beLowX} ${plotH}`;
  const rightClip = `${beHighX} ${padding.top} ${width - padding.right - beHighX} ${plotH}`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      style={{ width: "100%", maxWidth: width, height: "auto" }}
      role="img"
      aria-label="Iron Condor payoff at expiry chart showing profit and loss across strike prices"
    >
      <defs>
        <clipPath id="payoff-left"><rect x={leftClip.split(" ")[0]} y={leftClip.split(" ")[1]} width={leftClip.split(" ")[2]} height={leftClip.split(" ")[3]} /></clipPath>
        <clipPath id="payoff-profit"><rect x={profitClip.split(" ")[0]} y={profitClip.split(" ")[1]} width={profitClip.split(" ")[2]} height={profitClip.split(" ")[3]} /></clipPath>
        <clipPath id="payoff-right"><rect x={rightClip.split(" ")[0]} y={rightClip.split(" ")[1]} width={rightClip.split(" ")[2]} height={rightClip.split(" ")[3]} /></clipPath>
      </defs>
      <line x1={padding.left} y1={zeroY} x2={width - padding.right} y2={zeroY} stroke={COLOR.textFaint} strokeWidth={0.5} strokeDasharray="4 4" />
      <line x1={beLowX} y1={padding.top} x2={beLowX} y2={height - padding.bottom} stroke={COLOR.strategy} strokeWidth={0.8} strokeDasharray="3 3" opacity={0.5} />
      <line x1={beHighX} y1={padding.top} x2={beHighX} y2={height - padding.bottom} stroke={COLOR.strategy} strokeWidth={0.8} strokeDasharray="3 3" opacity={0.5} />
      <path d={`${pathD} L${points[points.length - 1].x},${zeroY} L${points[0].x},${zeroY} Z`} fill={COLOR.negativeDim} clipPath="url(#payoff-left)" />
      <path d={`${pathD} L${points[points.length - 1].x},${zeroY} L${points[0].x},${zeroY} Z`} fill={COLOR.positiveDim} clipPath="url(#payoff-profit)" />
      <path d={`${pathD} L${points[points.length - 1].x},${zeroY} L${points[0].x},${zeroY} Z`} fill={COLOR.negativeDim} clipPath="url(#payoff-right)" />
      <path d={pathD} fill="none" stroke={COLOR.strategy} strokeWidth={2} strokeLinejoin="round" />
      <text x={padding.left} y={height - 10} fill={COLOR.textFaint} fontSize={10} fontFamily={TYPE.data}>{fmtIN(minStrike)}</text>
      <text x={width - padding.right} y={height - 10} fill={COLOR.textFaint} fontSize={10} fontFamily={TYPE.data} textAnchor="end">{fmtIN(maxStrike)}</text>
      <text x={padding.left - 6} y={padding.top + 4} fill={COLOR.textFaint} fontSize={10} fontFamily={TYPE.data} textAnchor="end">{fmtIN(maxPnl)}</text>
      <text x={padding.left - 6} y={height - padding.bottom + 4} fill={COLOR.textFaint} fontSize={10} fontFamily={TYPE.data} textAnchor="end">{fmtIN(minPnl)}</text>
    </svg>
  );
}

// =============================================================================
// MAIN PAGE COMPONENT
// =============================================================================

export default function StrategyLabClientPage() {
  const isMobile = useIsMobile();

  return (
    <>
      {/* ============================ HERO ============================ */}
      <Section
        padding="0"
        style={{
          background: `radial-gradient(ellipse 80% 60% at 50% 20%, ${COLOR.strategyDim}, transparent 60%), linear-gradient(180deg, ${COLOR.baseElevated}, ${COLOR.base})`,
          borderBottom: `1px solid ${COLOR.borderSubtle}`,
        }}
      >
        <Container maxWidth={1100} style={{ padding: isMobile ? "3rem 1.25rem 2.5rem" : "4.5rem 1.25rem 3.5rem", textAlign: "center" }}>
          {/* Eyebrow tag */}
          <FlexRow gap={SPACE.small} justify="center" style={{ marginBottom: SPACE.card }}>
            <span style={{ width: 24, height: 1, background: COLOR.strategy, alignSelf: "center" }} />
            <span style={{ fontSize: TYPE.labelSmall.size, fontWeight: 600, letterSpacing: "0.08em", color: COLOR.strategy, textTransform: "uppercase" }}>
              STRATEGY FORGE
            </span>
            <span style={{ width: 24, height: 1, background: COLOR.strategy, alignSelf: "center" }} />
          </FlexRow>

          {/* Hero headline */}
          <h1
            style={{
              fontSize: TYPE.h1.size,
              fontWeight: 800,
              color: COLOR.textPrimary,
              margin: `0 0 ${SPACE.comp}`,
              letterSpacing: TYPE.h1.letterSpacing,
              lineHeight: TYPE.h1.lineHeight,
            }}
          >
            Build the Strategy.{" "}
            <span style={{ color: COLOR.strategy }}>See the Payoff.</span>
          </h1>

          {/* Hero subtitle */}
          <p
            style={{
              fontSize: TYPE.bodyLarge.size,
              color: COLOR.textMuted,
              lineHeight: TYPE.bodyLarge.lineHeight,
              maxWidth: "38rem",
              margin: `0 auto ${SPACE.group}`,
            }}
          >
            Construct multi-leg strategies. Visualize payoff curves. See position
            Greeks. Understand risk scenarios — before committing capital.
          </p>

          {/* Hero CTAs */}
          <FlexRow gap={SPACE.medium} justify="center" wrap={isMobile}>
            <LinkButton variant="primary" size="lg" href="/paper-trading">
              Start Paper Trading <span aria-hidden>&rarr;</span>
            </LinkButton>
            <LinkButton variant="secondary" size="lg" href="/features">
              Explore the Platform
            </LinkButton>
          </FlexRow>

          {/* Supporting signal hints */}
          <FlexRow
            gap={SPACE.compLg}
            justify="center"
            wrap={isMobile}
            style={{ marginTop: SPACE.group, opacity: 0.7 }}
          >
            <FlexRow gap={SPACE.xs}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: COLOR.positive, display: "inline-block" }} />
              <span style={{ fontSize: TYPE.caption.size, color: COLOR.textMuted }}>Max Profit / Loss</span>
            </FlexRow>
            <FlexRow gap={SPACE.xs}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: COLOR.strategy, display: "inline-block" }} />
              <span style={{ fontSize: TYPE.caption.size, color: COLOR.textMuted }}>Breakevens</span>
            </FlexRow>
            <FlexRow gap={SPACE.xs}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: COLOR.intelligence, display: "inline-block" }} />
              <span style={{ fontSize: TYPE.caption.size, color: COLOR.textMuted }}>Greeks & Scenarios</span>
            </FlexRow>
          </FlexRow>
        </Container>
      </Section>

      {/* ============================ MAIN WORKSPACE ============================ */}
      <Section
        padding={SPACE.section}
        style={{
          background: COLOR.base,
        }}
      >
        <Container maxWidth={1100} style={{ padding: 0 }}>
          {/* Section header */}
          <SectionTitle
            eyebrow="INTERACTIVE WORKSPACE"
            title="Strategy Forge — Iron Condor Demo"
            subtitle="An Iron Condor on NIFTY 25,500 straddle with 200-point wings. All values below are illustrative."
          />

          {/* Demo label badge — top of workspace */}
          <div style={{ marginBottom: SPACE.card }}>
            <DemoLabel />
          </div>

          {/* ---- WORKSPACE PANEL ---- */}
          <SignalPanel
            padding={isMobile ? "1.25rem" : "2rem"}
            style={{ marginBottom: SPACE.group }}
          >
            {/* Strategy name + meta */}
            <FlexRow gap={SPACE.comp} align="center" wrap style={{ marginBottom: SPACE.card }}>
              <h3
                style={{
                  fontSize: TYPE.h3.size,
                  fontWeight: 700,
                  color: COLOR.strategy,
                  margin: 0,
                  letterSpacing: TYPE.h3.letterSpacing,
                }}
              >
                IRON CONDOR
              </h3>
              <span
                style={{
                  fontSize: TYPE.bodySmall.size,
                  color: COLOR.textMuted,
                }}
              >
                NIFTY &middot; 25,500 Straddle &middot; 200pt Wings
              </span>
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: TYPE.caption.size,
                  fontWeight: 600,
                  letterSpacing: "0.06em",
                  color: COLOR.info,
                  background: COLOR.infoDim,
                  border: `1px solid ${COLOR.info}30`,
                  borderRadius: RADIUS.sm,
                  padding: `${SPACE.xs} ${SPACE.small}`,
                  textTransform: "uppercase",
                }}
              >
                4 Legs
              </span>
            </FlexRow>

            {/* ======== TWO-COLUMN: LEGS + PAYOFF ======== */}
            <TwoColumn
              gap={SPACE.group}
              breakpoint={768}
              left={
                <FlexColumn gap={SPACE.comp}>
                  {/* Legs table */}
                  <Panel
                    padding={0}
                    style={{ overflow: "hidden" }}
                  >
                    <div
                      style={{
                        padding: `${SPACE.comp} ${SPACE.card}`,
                        borderBottom: `1px solid ${COLOR.borderSubtle}`,
                      }}
                    >
                      <span
                        style={{
                          fontSize: TYPE.label.size,
                          fontWeight: 600,
                          letterSpacing: "0.06em",
                          color: COLOR.textFaint,
                          textTransform: "uppercase",
                        }}
                      >
                        Strategy Legs
                      </span>
                    </div>
                    {/* Scrollable on mobile */}
                    <div style={{ overflowX: isMobile ? "auto" : "visible" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: TYPE.bodySmall.size, minWidth: isMobile ? 400 : "auto" }}>
                        <thead>
                          <tr style={{ color: COLOR.textFaint, fontSize: TYPE.caption.size }}>
                            <th scope="col" style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "left", fontWeight: 600, letterSpacing: "0.06em" }}>ACTION</th>
                            <th scope="col" style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "center", fontWeight: 600, letterSpacing: "0.06em" }}>STRIKE</th>
                            <th scope="col" style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "center", fontWeight: 600, letterSpacing: "0.06em" }}>TYPE</th>
                            <th scope="col" style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "center", fontWeight: 600, letterSpacing: "0.06em" }}>QTY</th>
                            <th scope="col" style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "right", fontWeight: 600, letterSpacing: "0.06em" }}>LTP</th>
                          </tr>
                        </thead>
                        <tbody>
                          {LEGS.map((leg, i) => (
                            <tr key={i} style={{ borderTop: `1px solid ${COLOR.borderSubtle}` }}>
                              <td style={{ padding: `${SPACE.small} ${SPACE.comp}` }}>
                                <span
                                  style={{
                                    display: "inline-block",
                                    fontSize: TYPE.labelSmall.size,
                                    fontWeight: 700,
                                    padding: `${SPACE.micro} ${SPACE.small}`,
                                    borderRadius: RADIUS.sm,
                                    background: leg.action === "SELL" ? COLOR.negativeDim : COLOR.positiveDim,
                                    color: leg.action === "SELL" ? COLOR.negative : COLOR.positive,
                                    border: `1px solid ${leg.action === "SELL" ? COLOR.negative + "30" : COLOR.positive + "30"}`,
                                    fontFamily: TYPE.data,
                                  }}
                                >
                                  {leg.action}
                                </span>
                              </td>
                              <td style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "center", fontWeight: 700, fontFamily: TYPE.data, fontVariantNumeric: "tabular-nums" }}>
                                {fmtIN(leg.strike)}
                              </td>
                              <td style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "center", color: leg.type === "CE" ? COLOR.info : COLOR.intelligence, fontWeight: 600, fontFamily: TYPE.data }}>
                                {leg.type}
                              </td>
                              <td style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "center", color: COLOR.textSecondary, fontFamily: TYPE.data }}>
                                {leg.qty}
                              </td>
                              <td style={{ padding: `${SPACE.small} ${SPACE.comp}`, textAlign: "right", fontVariantNumeric: "tabular-nums", fontFamily: TYPE.data, color: COLOR.textSecondary }}>
                                {leg.ltp.toFixed(2)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Panel>

                  {/* MetricPanels for max profit/loss/breakevens */}
                  <MetricGrid minItemWidth={140} gap={SPACE.small}>
                    <MetricPanel glow padding={SPACE.compLg}>
                      <Metric
                        label="Max Profit"
                        value={MAX_PROFIT}
                        unit="₹"
                        status="DEMO"
                        source="ILLUSTRATIVE"
                        size="sm"
                        color={COLOR.positive}
                      />
                    </MetricPanel>
                    <MetricPanel padding={SPACE.compLg}>
                      <Metric
                        label="Max Loss"
                        value={MAX_LOSS}
                        unit="₹"
                        status="DEMO"
                        source="ILLUSTRATIVE"
                        size="sm"
                        color={COLOR.negative}
                      />
                    </MetricPanel>
                    <MetricPanel padding={SPACE.compLg}>
                      <Metric
                        label="BE Low"
                        value={BREAKEVEN_LOW}
                        status="DEMO"
                        source="ILLUSTRATIVE"
                        size="sm"
                        color={COLOR.strategy}
                      />
                    </MetricPanel>
                    <MetricPanel padding={SPACE.compLg}>
                      <Metric
                        label="BE High"
                        value={BREAKEVEN_HIGH}
                        status="DEMO"
                        source="ILLUSTRATIVE"
                        size="sm"
                        color={COLOR.strategy}
                      />
                    </MetricPanel>
                  </MetricGrid>
                </FlexColumn>
              }
              right={
                <VisualizationFrame
                  eyebrow="PAYOFF AT EXPIRY"
                  title="Iron Condor Payoff Curve"
                  legend={[
                    { label: "Profit Zone", color: COLOR.positive },
                    { label: "Loss Zone", color: COLOR.negative },
                    { label: "Breakevens", color: COLOR.strategy },
                  ]}
                  demoLabel
                >
                  <PayoffChart />
                </VisualizationFrame>
              }
            />
          </SignalPanel>

          {/* ======== BOTTOM: GREEKS + SCENARIOS ======== */}
          <TwoColumn
            gap={SPACE.group}
            breakpoint={768}
            left={
              <Panel padding={0} style={{ overflow: "hidden" }}>
                <div
                  style={{
                    padding: `${SPACE.comp} ${SPACE.card}`,
                    borderBottom: `1px solid ${COLOR.borderSubtle}`,
                  }}
                >
                  <FlexRow gap={SPACE.xs} align="center">
                    <span
                      style={{
                        fontSize: TYPE.label.size,
                        fontWeight: 600,
                        letterSpacing: "0.06em",
                        color: COLOR.textFaint,
                        textTransform: "uppercase",
                      }}
                    >
                      Position Greeks
                    </span>
                    <span style={{ marginLeft: "auto" }}>
                      <DemoLabel style={{ fontSize: "0.625rem", padding: "0.0625rem 0.375rem" }} />
                    </span>
                  </FlexRow>
                </div>
                <MetricGrid minItemWidth={120} gap={0} style={{ padding: SPACE.card }}>
                  {GREEKS.map((g, i) => (
                    <div key={g.label} style={{ padding: SPACE.comp, borderLeft: i > 0 ? `1px solid ${COLOR.borderSubtle}` : "none" }}>
                      <Metric
                        label={g.label}
                        value={g.value}
                        unit={g.unit}
                        color={g.color}
                        status="DEMO"
                        source="ILLUSTRATIVE"
                        size="sm"
                      />
                    </div>
                  ))}
                </MetricGrid>
              </Panel>
            }
            right={
              <Panel padding={0} style={{ overflow: "hidden" }}>
                <div
                  style={{
                    padding: `${SPACE.comp} ${SPACE.card}`,
                    borderBottom: `1px solid ${COLOR.borderSubtle}`,
                  }}
                >
                  <FlexRow gap={SPACE.xs} align="center">
                    <span
                      style={{
                        fontSize: TYPE.label.size,
                        fontWeight: 600,
                        letterSpacing: "0.06em",
                        color: COLOR.textFaint,
                        textTransform: "uppercase",
                      }}
                    >
                      Risk / Scenarios
                    </span>
                    <span style={{ marginLeft: "auto" }}>
                      <DemoLabel style={{ fontSize: "0.625rem", padding: "0.0625rem 0.375rem" }} />
                    </span>
                  </FlexRow>
                </div>
                <MetricGrid minItemWidth={140} gap={SPACE.small} style={{ padding: SPACE.card }}>
                  {SCENARIOS.map((s) => (
                    <div key={s.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: `${SPACE.small} 0` }}>
                      <span style={{ fontSize: TYPE.bodySmall.size, color: COLOR.textSecondary }}>{s.label}</span>
                      <span
                        style={{
                          fontSize: TYPE.data.size,
                          fontWeight: 700,
                          color: s.color,
                          fontFamily: TYPE.data,
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {s.value}
                      </span>
                    </div>
                  ))}
                </MetricGrid>
              </Panel>
            }
          />
        </Container>
      </Section>

      {/* ============================ SUPPORTING EVIDENCE: IRON CONDOR ============================ */}
      <Section
        padding={SPACE.section}
        background={`linear-gradient(180deg, ${COLOR.base}, ${COLOR.baseElevated})`}
        style={{ borderTop: `1px solid ${COLOR.borderSubtle}` }}
      >
        <Container maxWidth={1100} style={{ padding: 0 }}>
          <SectionTitle
            eyebrow="SUPPORTING EVIDENCE"
            title="Iron Condor — Why It Works"
            subtitle="A neutral, range-bounded strategy with defined risk and defined reward. Ideal when you expect the underlying to stay within a range."
          />

          <MetricGrid minItemWidth={200} gap={SPACE.compLg}>
            <MetricPanel padding={SPACE.cardLg}>
              <Metric
                label="Strategy Type"
                value="Neutral / Range-Bound"
                status="DEMO"
                size="sm"
                color={COLOR.info}
              />
            </MetricPanel>
            <MetricPanel padding={SPACE.cardLg}>
              <Metric
                label="Ideal Condition"
                value="Low Volatility"
                status="DEMO"
                size="sm"
                color={COLOR.intelligence}
              />
            </MetricPanel>
            <MetricPanel padding={SPACE.cardLg}>
              <Metric
                label="Capital Required"
                value={MAX_LOSS}
                unit="₹ (max)"
                status="DEMO"
                size="sm"
                color={COLOR.negative}
              />
            </MetricPanel>
            <MetricPanel padding={SPACE.cardLg}>
              <Metric
                label="Profit Range"
                value={`${fmtIN(BREAKEVEN_LOW)} – ${fmtIN(BREAKEVEN_HIGH)}`}
                status="DEMO"
                size="sm"
                color={COLOR.positive}
              />
            </MetricPanel>
          </MetricGrid>
        </Container>
      </Section>

      {/* ============================ CTA ============================ */}
      <Section
        padding={SPACE.sectionLg}
        style={{
          background: `radial-gradient(ellipse 70% 80% at 50% 0%, ${COLOR.strategyDim}, transparent 60%), linear-gradient(180deg, ${COLOR.baseElevated}, ${COLOR.base})`,
          borderTop: `1px solid ${COLOR.border}`,
          textAlign: "center",
        }}
      >
        <Container maxWidth={700} style={{ padding: 0, textAlign: "center" }}>
          <h2
            style={{
              fontSize: TYPE.h2.size,
              fontWeight: 700,
              color: COLOR.textPrimary,
              margin: `0 0 ${SPACE.comp}`,
              letterSpacing: TYPE.h2.letterSpacing,
              lineHeight: TYPE.h2.lineHeight,
            }}
          >
            Ready to Forge Your{" "}
            <span style={{ color: COLOR.strategy }}>Strategy?</span>
          </h2>
          <p
            style={{
              fontSize: TYPE.body.size,
              color: COLOR.textMuted,
              lineHeight: TYPE.body.lineHeight,
              maxWidth: "32rem",
              margin: `0 auto ${SPACE.group}`,
            }}
          >
            Build, analyze, stress-test and paper-trade strategies with the full
            platform. Understand every dimension before committing capital.
          </p>
          <FlexRow gap={SPACE.medium} justify="center" wrap={isMobile}>
            <LinkButton variant="primary" size="lg" href="/paper-trading">
              Start Paper Trading <span aria-hidden>&rarr;</span>
            </LinkButton>
            <LinkButton variant="secondary" size="lg" href="/features">
              Explore Platform
            </LinkButton>
          </FlexRow>
        </Container>
      </Section>
    </>
  );
}
