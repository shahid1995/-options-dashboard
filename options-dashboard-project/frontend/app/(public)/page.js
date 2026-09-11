"use client";
import { useIsMobile } from "@/lib/ui";
import { useAuthModal } from "@/components/public/AuthModalContext";
import {
  SignalField,
  DEMO_SIGNAL_STATE,
} from "@/components/public/SignalField";
import { VisualizationFrame } from "@/components/public/VisualizationFrame";
import { Metric } from "@/components/public/Metric";
import { Container, Section, FlexRow, FlexColumn, MetricGrid } from "@/components/public/layout";
import { Panel, SignalPanel } from "@/components/public/surfaces";
import { Button, LinkButton } from "@/components/public/buttons";
import { DemoLabel, Eyebrow, SectionTitle } from "@/components/public/truth";
import { SignalLine, StrikeRail } from "@/components/public/signals";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "@/components/public/tokens";
import { CTASection, PAGE_MAX } from "@/components/public";

export default function HomePage() {
  const isMobile = useIsMobile();
  const { open: openAuth } = useAuthModal();

  return (
    <>
      {/* ════════════════════════════════════════════════════════════════════════
          SECTION 01 — SIGNAL FIELD HERO
          ════════════════════════════════════════════════════════════════════════ */}
      <header style={{ position: "relative", overflow: "hidden" }}>
        {/* Background gradient */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: `radial-gradient(ellipse 50% 40% at 20% 10%, ${COLOR.strategyDim}, transparent 60%),
                         radial-gradient(ellipse 40% 30% at 80% 80%, ${COLOR.intelligenceDim}, transparent 60%),
                         linear-gradient(180deg, ${COLOR.base}, ${COLOR.baseElevated})`,
            pointerEvents: "none",
          }}
        />

        <div
          style={{
            position: "relative",
            maxWidth: PAGE_MAX,
            margin: "0 auto",
            padding: isMobile ? `${SPACE.sectionLg} 1.25rem` : `${SPACE.hero} 1.25rem`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: SPACE.section,
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

          {/* H1 */}
          <h1
            style={{
              margin: 0,
              fontSize: TYPE.displayH1.size,
              lineHeight: TYPE.displayH1.lineHeight,
              fontWeight: TYPE.displayH1.weight,
              letterSpacing: TYPE.displayH1.letterSpacing,
              color: COLOR.textPrimary,
              textAlign: "center",
              maxWidth: "20ch",
            }}
            className="sn-fade"
          >
            Options Intelligence
            <br />
            <span style={{ color: COLOR.strategy }}>for Structured Decisions.</span>
          </h1>

          {/* Supporting message */}
          <p
            style={{
              color: COLOR.textSecondary,
              fontSize: TYPE.bodyLarge.size,
              lineHeight: TYPE.bodyLarge.lineHeight,
              textAlign: "center",
              maxWidth: "40ch",
              margin: 0,
            }}
          >
            See the forces behind the option chain.
            <br />
            Understand positioning, volatility and risk.
            <br />
            <span style={{ color: COLOR.strategy }}>Build. Test. Review.</span>
          </p>

          {/* CTAs */}
          <FlexRow gap={SPACE.comp} style={{ marginTop: SPACE.comp }}>
            <LinkButton variant="primary" size="lg" href="/features">
              Explore StrikeNova <span aria-hidden>→</span>
            </LinkButton>
            <LinkButton variant="secondary" size="lg" href="/strategy-lab">
              Strategy Lab
            </LinkButton>
          </FlexRow>

          {/* Signal Field */}
          <div
            style={{
              width: "100%",
              maxWidth: 720,
              marginTop: SPACE.section,
            }}
            className="sn-fade"
          >
            <VisualizationFrame
              eyebrow="SIGNAL FIELD"
              title="Illustrative market state"
              demoLabel
              caption="This is an illustrative visualization of an options market. Data is not live."
            >
              <SignalField />
            </VisualizationFrame>
          </div>
        </div>
      </header>

      {/* ════════════════════════════════════════════════════════════════════════
          SECTION 02 — THE MARKET IS MORE THAN PRICE
          ════════════════════════════════════════════════════════════════════════ */}
      <Section
        style={{
          borderTop: `1px solid ${COLOR.border}`,
        }}
      >
        <Container maxWidth={PAGE_MAX}>
          <SectionTitle
            eyebrow="THE MARKET IS MORE THAN PRICE"
            title="Eight analytical layers. One coherent system."
            subtitle="StrikeNova turns raw option chain data into a structured analytical workflow."
          />

          {/* Layer visualization */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: SPACE.small,
              marginBottom: SPACE.section,
            }}
          >
            {[
              { label: "PRICE", color: COLOR.signalPrice, width: "100%" },
              { label: "OPEN INTEREST", color: COLOR.signalOi, width: "92%" },
              { label: "OI CHANGE", color: COLOR.info, width: "85%" },
              { label: "VOLUME", color: COLOR.textMuted, width: "78%" },
              { label: "IMPLIED VOLATILITY", color: COLOR.signalIv, width: "95%" },
              { label: "GREEKS", color: COLOR.signalGreeks, width: "88%" },
              { label: "MARKET STRUCTURE", color: COLOR.intelligence, width: "90%" },
            ].map((layer, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: SPACE.comp,
                }}
              >
                <span
                  style={{
                    fontSize: TYPE.caption.size,
                    fontWeight: 600,
                    color: COLOR.textFaint,
                    width: 140,
                    flexShrink: 0,
                    textAlign: "right",
                  }}
                >
                  {layer.label}
                </span>
                <div
                  style={{
                    width: layer.width,
                    height: 4,
                    borderRadius: RADIUS.pill,
                    background: `linear-gradient(90deg, ${layer.color}, ${layer.color}40)`,
                    opacity: 0.8,
                  }}
                />
              </div>
            ))}

            {/* Convergence arrow */}
            <div
              style={{
                textAlign: "center",
                color: COLOR.textFaint,
                fontSize: 20,
                padding: `${SPACE.comp} 0`,
              }}
            >
              ↓
            </div>

            {/* Market state output */}
            <div
              style={{
                display: "flex",
                justifyContent: "center",
              }}
            >
              <Panel
                padding={SPACE.cardLg}
                background={COLOR.surface}
                style={{
                  borderColor: COLOR.borderStrong,
                  textAlign: "center",
                }}
              >
                <Eyebrow color={COLOR.intelligence}>Market State</Eyebrow>
                <p
                  style={{
                    color: COLOR.textSecondary,
                    fontSize: TYPE.body.size,
                    margin: `${SPACE.small} 0 0`,
                    maxWidth: "30ch",
                  }}
                >
                  Synthesized from all analytical layers into a coherent decision framework.
                </p>
              </Panel>
            </div>
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          SECTION 03 — MARKET INTELLIGENCE
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
            eyebrow="MARKET INTELLIGENCE"
            title="Understand the forces behind the option chain."
            subtitle="Positioning, volatility, Greeks and market structure in one coherent view."
          />

          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)",
              gap: SPACE.cardLg,
              marginBottom: SPACE.section,
            }}
          >
            {/* Positioning */}
            <Panel padding={SPACE.cardLg}>
              <Eyebrow color={COLOR.signalOi}>Positioning</Eyebrow>
              <p
                style={{
                  color: COLOR.textSecondary,
                  fontSize: TYPE.body.size,
                  lineHeight: 1.7,
                  margin: `${SPACE.comp} 0 0`,
                }}
              >
                Track open interest distribution across strikes to identify where market participants are positioned.
              </p>
            </Panel>

            {/* Volatility */}
            <Panel padding={SPACE.cardLg}>
              <Eyebrow color={COLOR.signalIv}>Volatility</Eyebrow>
              <p
                style={{
                  color: COLOR.textSecondary,
                  fontSize: TYPE.body.size,
                  lineHeight: 1.7,
                  margin: `${SPACE.comp} 0 0`,
                }}
              >
                Analyze implied volatility across strikes and expiries to understand how the market prices risk.
              </p>
            </Panel>

            {/* Greeks */}
            <Panel padding={SPACE.cardLg}>
              <Eyebrow color={COLOR.signalGreeks}>Greeks</Eyebrow>
              <p
                style={{
                  color: COLOR.textSecondary,
                  fontSize: TYPE.body.size,
                  lineHeight: 1.7,
                  margin: `${SPACE.comp} 0 0`,
                }}
              >
                Delta, gamma, theta and vega computed for every option in the chain.
              </p>
            </Panel>

            {/* Structure */}
            <Panel padding={SPACE.cardLg}>
              <Eyebrow color={COLOR.intelligence}>Structure</Eyebrow>
              <p
                style={{
                  color: COLOR.textSecondary,
                  fontSize: TYPE.body.size,
                  lineHeight: 1.7,
                  margin: `${SPACE.comp} 0 0`,
                }}
              >
                Identify resistance, support and pivot levels derived from option chain data.
              </p>
            </Panel>
          </div>

          <div style={{ textAlign: "center" }}>
            <LinkButton variant="primary" size="md" href="/market-intelligence">
              Explore Market Intelligence <span aria-hidden>→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          SECTION 04 — STRATEGY LAB
          ════════════════════════════════════════════════════════════════════════ */}
      <Section>
        <Container maxWidth={PAGE_MAX}>
          <SectionTitle
            eyebrow="STRATEGY LAB"
            title="Build the strategy. See the risk. Test the outcome."
            subtitle="From market view to payoff analysis in one structured workflow."
          />

          {/* Transformation flow */}
          <div
            style={{
              display: "flex",
              flexDirection: isMobile ? "column" : "row",
              alignItems: "stretch",
              justifyContent: "center",
              gap: isMobile ? SPACE.comp : SPACE.cardLg,
              marginBottom: SPACE.section,
              flexWrap: "wrap",
            }}
          >
            {[
              { step: "01", title: "MARKET VIEW", desc: "Analyze positioning and volatility" },
              { step: "02", title: "STRATEGY", desc: "Build multi-leg option strategies" },
              { step: "03", title: "PAYOFF", desc: "Visualize profit/loss at expiry" },
              { step: "04", title: "RISK", desc: "Max profit, max loss, breakevens, Greeks" },
            ].map((item, i, arr) => (
              <div
                key={item.step}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  flex: "1 1 0",
                  minWidth: 140,
                }}
              >
                <Panel
                  padding={SPACE.cardLg}
                  style={{
                    textAlign: "center",
                    height: "100%",
                    width: "100%",
                  }}
                >
                  <span
                    style={{
                      fontSize: TYPE.caption.size,
                      fontWeight: 700,
                      letterSpacing: "0.08em",
                      color: COLOR.strategy,
                      display: "block",
                      marginBottom: SPACE.small,
                    }}
                  >
                    {item.step}
                  </span>
                  <span
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 700,
                      color: COLOR.textPrimary,
                      display: "block",
                      marginBottom: SPACE.xs,
                    }}
                  >
                    {item.title}
                  </span>
                  <span
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.5,
                    }}
                  >
                    {item.desc}
                  </span>
                </Panel>
                {i < arr.length - 1 && !isMobile && (
                  <span
                    style={{
                      color: COLOR.textFaint,
                      fontSize: 18,
                      alignSelf: "center",
                    }}
                  >
                    →
                  </span>
                )}
              </div>
            ))}
          </div>

          <div style={{ textAlign: "center" }}>
            <LinkButton variant="primary" size="md" href="/strategy-lab">
              Open Strategy Lab <span aria-hidden>→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          SECTION 05 — RISK BEFORE CAPITAL
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
            eyebrow="RISK BEFORE CAPITAL"
            title="Understand the risk before committing capital."
            subtitle="Payoff curves, max profit, max loss, breakevens, Greeks and scenarios."
          />

          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "repeat(4, 1fr)",
              gap: SPACE.comp,
              marginBottom: SPACE.section,
            }}
          >
            <Metric label="MAX PROFIT" value="₹3,250" status="DEMO" size="md" />
            <Metric label="MAX LOSS" value="-₹9,750" status="DEMO" size="md" />
            <Metric label="BREAKEVEN LOW" value="25,250" status="DEMO" size="md" />
            <Metric label="BREAKEVEN HIGH" value="25,750" status="DEMO" size="md" />
          </div>

          <Panel padding={SPACE.cardLg} style={{ marginBottom: SPACE.section }}>
            <Eyebrow>Position Greeks (ATM Iron Condor)</Eyebrow>
            <MetricGrid minItemWidth={120} style={{ marginTop: SPACE.comp }}>
              <Metric label="DELTA" value="-0.02" status="DEMO" size="sm" />
              <Metric label="GAMMA" value="0.0003" status="DEMO" size="sm" />
              <Metric label="THETA" value="+42.15" status="DEMO" size="sm" />
              <Metric label="VEGA" value="-18.40" status="DEMO" size="sm" />
            </MetricGrid>
          </Panel>

          <div style={{ textAlign: "center" }}>
            <p
              style={{
                fontSize: TYPE.caption.size,
                color: COLOR.textFaint,
                margin: 0,
              }}
            >
              All values are illustrative. Paper trading is simulated and does not represent actual execution.
            </p>
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          SECTION 06 — PAPER TRADING
          ════════════════════════════════════════════════════════════════════════ */}
      <Section>
        <Container maxWidth={PAGE_MAX}>
          <SectionTitle
            eyebrow="PAPER TRADING"
            title="Practice the workflow. Not your capital."
            subtitle="Decision, simulation, position management, P&L and review in one environment."
          />

          <div
            style={{
              display: "flex",
              flexDirection: isMobile ? "column" : "row",
              alignItems: "stretch",
              justifyContent: "center",
              gap: isMobile ? SPACE.comp : SPACE.cardLg,
              marginBottom: SPACE.section,
              flexWrap: "wrap",
            }}
          >
            {[
              { step: "01", title: "DECISION", desc: "Market view and strategy selection" },
              { step: "02", title: "SIMULATION", desc: "Execute with simulated capital" },
              { step: "03", title: "POSITION", desc: "Track open positions and P&L" },
              { step: "04", title: "REVIEW", desc: "Study execution and performance" },
            ].map((item, i, arr) => (
              <div
                key={item.step}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  flex: "1 1 0",
                  minWidth: 140,
                }}
              >
                <Panel
                  padding={SPACE.cardLg}
                  style={{
                    textAlign: "center",
                    height: "100%",
                    width: "100%",
                  }}
                >
                  <span
                    style={{
                      fontSize: TYPE.caption.size,
                      fontWeight: 700,
                      letterSpacing: "0.08em",
                      color: COLOR.info,
                      display: "block",
                      marginBottom: SPACE.small,
                    }}
                  >
                    {item.step}
                  </span>
                  <span
                    style={{
                      fontSize: TYPE.label.size,
                      fontWeight: 700,
                      color: COLOR.textPrimary,
                      display: "block",
                      marginBottom: SPACE.xs,
                    }}
                  >
                    {item.title}
                  </span>
                  <span
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      color: COLOR.textMuted,
                      lineHeight: 1.5,
                    }}
                  >
                    {item.desc}
                  </span>
                </Panel>
                {i < arr.length - 1 && !isMobile && (
                  <span
                    style={{
                      color: COLOR.textFaint,
                      fontSize: 18,
                      alignSelf: "center",
                    }}
                  >
                    →
                  </span>
                )}
              </div>
            ))}
          </div>

          <div style={{ textAlign: "center" }}>
            <p
              style={{
                fontSize: TYPE.caption.size,
                color: COLOR.textFaint,
                margin: `0 0 ${SPACE.comp}`,
              }}
            >
              No real broker orders are placed. Paper trading is for educational purposes.
            </p>
            <LinkButton variant="secondary" size="md" href="/paper-trading">
              Learn More <span aria-hidden>→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          SECTION 07 — WORKFLOW
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
            eyebrow="THE WORKFLOW"
            title="Six steps from market data to structured decision."
            subtitle="A canonical process that separates observation from analysis, analysis from strategy, and strategy from execution."
          />

          <div
            style={{
              display: "flex",
              flexDirection: isMobile ? "column" : "row",
              alignItems: isMobile ? "stretch" : "center",
              justifyContent: "center",
              gap: isMobile ? SPACE.comp : SPACE.cardLg,
              flexWrap: "wrap",
            }}
          >
            {[
              { num: "01", title: "OBSERVE", desc: "Price, chain, OI, volume, IV, Greeks" },
              { num: "02", title: "ANALYZE", desc: "Positioning, volatility, structure" },
              { num: "03", title: "BUILD", desc: "Construct strategy around market view" },
              { num: "04", title: "TEST", desc: "Payoff, risk, Greeks, scenarios" },
              { num: "05", title: "PAPER TRADE", desc: "Simulate without risking capital" },
              { num: "06", title: "REVIEW", desc: "Study execution and performance" },
            ].map((step, i, arr) => (
              <div
                key={step.num}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  flex: isMobile ? "1 1 auto" : "0 1 120",
                }}
              >
                <Panel
                  padding={SPACE.card}
                  style={{
                    textAlign: "center",
                    width: isMobile ? "100%" : 120,
                  }}
                >
                  <span
                    style={{
                      fontSize: TYPE.caption.size,
                      fontWeight: 700,
                      letterSpacing: "0.08em",
                      color: COLOR.strategy,
                      display: "block",
                      marginBottom: SPACE.xs,
                    }}
                  >
                    {step.num}
                  </span>
                  <span
                    style={{
                      fontSize: TYPE.bodySmall.size,
                      fontWeight: 700,
                      color: COLOR.textPrimary,
                      display: "block",
                    }}
                  >
                    {step.title}
                  </span>
                </Panel>
                {i < arr.length - 1 && (
                  <span
                    style={{
                      color: COLOR.textFaint,
                      fontSize: 16,
                      padding: isMobile ? "0" : "0",
                      textAlign: "center",
                    }}
                  >
                    {isMobile ? "↓" : "→"}
                  </span>
                )}
              </div>
            ))}
          </div>
        </Container>
      </Section>

      {/* ════════════════════════════════════════════════════════════════════════
          SECTION 08 — FINAL CTA
          ════════════════════════════════════════════════════════════════════════ */}
      <CTASection
        headline={
          <>
            Enter the <span style={{ color: COLOR.strategy }}>StrikeNova</span> workflow.
          </>
        }
        body="Explore the platform, understand the workflow, and practice your strategies before putting capital at risk."
        primaryLabel="Get Started"
        primaryOnClick={openAuth}
        secondaryLabel="Explore the Platform"
        secondaryHref="/features"
      />
    </>
  );
}
