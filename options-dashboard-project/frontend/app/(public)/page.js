"use client";
import { useIsMobile } from "@/lib/ui";
import { useAuthModal } from "@/components/public/AuthModalContext";
import { Section, Container } from "@/components/public/layout";
import { Panel } from "@/components/public/surfaces";
import { LinkButton } from "@/components/public/buttons";
import { DemoLabel, Eyebrow, SectionTitle } from "@/components/public/truth";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
import { CTASection } from "@/components/public";

import HomeHero from "@/components/public/HomeHero";
import PlatformPreview from "@/components/public/PlatformPreview";
import AnalyticalLayerGrid from "@/components/public/AnalyticalLayerGrid";
import SignalMetricOverview from "@/components/public/SignalMetricOverview";
import MarketIntelligenceGrid from "@/components/public/MarketIntelligenceGrid";
import EvidenceTrustSection from "@/components/public/EvidenceTrustSection";
import WorkflowTabs from "@/components/public/WorkflowTabs";
import PayoffMiniChart from "@/components/public/PayoffMiniChart";

// =============================================================================
// MARKET PROBLEM — Why options traders struggle
// =============================================================================
function MarketProblemSection() {
  const problems = [
    {
      title: "Fragmented Data",
      description: "Option chains, Greeks, OI, IV — scattered across screens with no unified analytical layer.",
    },
    {
      title: "Opaque Risk",
      description: "Payoff profiles, max loss, breakevens — hidden behind complex calculations most traders skip.",
    },
    {
      title: "Unstructured Workflow",
      description: "From market view to execution, there is no coherent analytical bridge between analysis and action.",
    },
  ];

  return (
    <Section>
      <Container maxWidth={1100}>
        <SectionTitle
          eyebrow="THE MARKET PROBLEM"
          title="Options trading demands structure. Most tools provide noise."
          subtitle="StrikeNova turns raw option chain data into a structured analytical workflow — from market state to execution."
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: SPACE.compLg }}>
          {problems.map((p) => (
            <div
              key={p.title}
              style={{
                padding: SPACE.cardLg,
                background: COLOR.surface,
                border: `1px solid ${COLOR.border}`,
                borderRadius: RADIUS.lg,
              }}
            >
              <h3 style={{ margin: 0, marginBottom: SPACE.small, fontSize: TYPE.h4.size, color: COLOR.textPrimary }}>
                {p.title}
              </h3>
              <p style={{ margin: 0, color: COLOR.textMuted, lineHeight: 1.7 }}>
                {p.description}
              </p>
            </div>
          ))}
        </div>
      </Container>
    </Section>
  );
}

// =============================================================================
// STRATEGY LAB TAB CONTENT
// =============================================================================
function StrategyMarketView() {
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>MARKET VIEW</h4>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>SPOT</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,500</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>PCR</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>0.92</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>ATM IV</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>14.2%</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>POSITIONING</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.info, fontFamily: TYPE.data }}>BALANCED</div>
        </div>
      </div>
      <DemoLabel style={{ fontSize: "0.625rem" }} />
    </div>
  );
}

function StrategyLegs() {
  const legs = [
    { action: "BUY", strike: "25,300", type: "PE" },
    { action: "SELL", strike: "25,400", type: "PE" },
    { action: "SELL", strike: "25,600", type: "CE" },
    { action: "BUY", strike: "25,700", type: "CE" },
  ];
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>IRON CONDOR</h4>
      <div style={{ display: "flex", flexDirection: "column", gap: SPACE.small }}>
        {legs.map((leg, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.small} ${SPACE.comp}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm }}>
            <span style={{ fontWeight: 700, color: leg.action === "BUY" ? COLOR.positive : COLOR.negative }}>{leg.action}</span>
            <span style={{ fontFamily: TYPE.data, color: COLOR.textPrimary }}>{leg.strike}</span>
            <span style={{ color: COLOR.textMuted }}>{leg.type}</span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: SPACE.comp }}><DemoLabel style={{ fontSize: "0.625rem" }} /></div>
    </div>
  );
}

function StrategyPayoff() {
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>PAYOFF</h4>
      <PayoffMiniChart />
    </div>
  );
}

function StrategyRisk() {
  const greeks = [
    { label: "DELTA", value: "-0.02" },
    { label: "GAMMA", value: "0.0003" },
    { label: "THETA", value: "+42.15" },
    { label: "VEGA", value: "-18.40" },
  ];
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>RISK</h4>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>MAX PROFIT</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>₹3,250</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>MAX LOSS</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>-₹9,750</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>BREAKEVEN LOW</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,250</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>BREAKEVEN HIGH</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,750</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: SPACE.comp, marginBottom: SPACE.comp }}>
        {greeks.map((g) => (
          <div key={g.label}>
            <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>{g.label}</div>
            <div style={{ fontSize: TYPE.dataSmall.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>{g.value}</div>
          </div>
        ))}
      </div>
      <DemoLabel style={{ fontSize: "0.625rem" }} />
    </div>
  );
}

// =============================================================================
// PAPER TRADING TAB CONTENT
// =============================================================================
function PaperDecision() {
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>DECISION</h4>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>SPOT</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,500</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>STRATEGY</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.strategy, fontFamily: TYPE.data }}>IRON CONDOR</div>
        </div>
      </div>
      <DemoLabel style={{ fontSize: "0.625rem" }} />
    </div>
  );
}

function PaperSimulation() {
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>SIMULATION</h4>
      <div style={{ display: "flex", flexDirection: "column", gap: SPACE.small, marginBottom: SPACE.compLg }}>
        <div style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.small} ${SPACE.comp}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm }}>
          <span style={{ color: COLOR.textMuted }}>Order Type</span>
          <span style={{ fontFamily: TYPE.data, color: COLOR.textPrimary }}>LIMIT</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.small} ${SPACE.comp}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm }}>
          <span style={{ color: COLOR.textMuted }}>Simulated Qty</span>
          <span style={{ fontFamily: TYPE.data, color: COLOR.textPrimary }}>2 Lot</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.small} ${SPACE.comp}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm }}>
          <span style={{ color: COLOR.textMuted }}>Simulated Capital</span>
          <span style={{ fontFamily: TYPE.data, color: COLOR.textPrimary }}>₹1,00,000</span>
        </div>
      </div>
      <DemoLabel style={{ fontSize: "0.625rem" }} />
    </div>
  );
}

function PaperPosition() {
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>POSITION</h4>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>OPEN P&L</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>+₹1,240</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>DELTA</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>-0.02</div>
        </div>
      </div>
      <DemoLabel style={{ fontSize: "0.625rem" }} />
    </div>
  );
}

function PaperReview() {
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>REVIEW</h4>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>TRADES</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>12</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>WIN RATE</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>67%</div>
        </div>
      </div>
      <DemoLabel style={{ fontSize: "0.625rem" }} />
    </div>
  );
}

// =============================================================================
// MAIN PAGE COMPONENT
// =============================================================================
export default function HomePage() {
  const isMobile = useIsMobile();
  const { open: openAuth } = useAuthModal();

  const strategyTabs = [
    { id: "market", label: "01 MARKET VIEW", content: <StrategyMarketView /> },
    { id: "strategy", label: "02 STRATEGY", content: <StrategyLegs /> },
    { id: "payoff", label: "03 PAYOFF", content: <StrategyPayoff /> },
    { id: "risk", label: "04 RISK", content: <StrategyRisk /> },
  ];

  const paperTabs = [
    { id: "decision", label: "01 DECISION", content: <PaperDecision /> },
    { id: "simulation", label: "02 SIMULATION", content: <PaperSimulation /> },
    { id: "position", label: "03 POSITION", content: <PaperPosition /> },
    { id: "review", label: "04 REVIEW", content: <PaperReview /> },
  ];

  return (
    <>
      {/* 01 — HERO */}
      <HomeHero onGetStarted={openAuth} />

      {/* Platform Preview */}
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: `0 ${SPACE.compLg} ${SPACE.section}` }}>
        <PlatformPreview />
      </div>

      {/* 02 — MARKET PROBLEM */}
      <MarketProblemSection />

      {/* 03 — ANALYTICAL LAYERS (Market Data) */}
      <Section style={{ borderTop: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="MARKET DATA"
            title="Eight analytical layers. One coherent system."
            subtitle="StrikeNova turns raw option chain data into a structured analytical workflow."
          />
          <AnalyticalLayerGrid />
        </Container>
      </Section>

      {/* 04 — SIGNAL FIELD (Market State) */}
      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="MARKET STATE"
            title="The market state in one view"
            subtitle="Key indicators, signal visualization, OI structure and Greeks in a single coherent display."
          />
          <SignalMetricOverview />
        </Container>
      </Section>

      {/* 05 — MARKET INTELLIGENCE (Analytics) */}
      <Section>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="ANALYTICS"
            title="Understand the forces behind the option chain."
            subtitle="Positioning, volatility, Greeks and market structure in one coherent view."
          />
          <MarketIntelligenceGrid />
          <div style={{ textAlign: "center", marginTop: SPACE.section }}>
            <LinkButton variant="primary" size="md" href="/market-intelligence" className="ds-focus-ring">
              Explore Market Intelligence <span aria-hidden="true">→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      {/* 05.5 — EVIDENCE & TRUST */}
      <EvidenceTrustSection />

      {/* 06 — STRATEGY LAB (Interactive) */}
      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="STRATEGY"
            title="Build the strategy. See the risk. Test the outcome."
            subtitle="From market view to payoff analysis in one structured workflow."
          />
          <WorkflowTabs tabs={strategyTabs} defaultTab="market" ariaLabel="Strategy Lab" />
          <div style={{ textAlign: "center", marginTop: SPACE.section }}>
            <LinkButton variant="primary" size="md" href="/strategy-lab" className="ds-focus-ring">
              Open Strategy Lab <span aria-hidden="true">→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      {/* 07 — RISK (Payoff Graph) */}
      <Section>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="RISK"
            title="Understand the risk before committing capital."
            subtitle="Payoff curves, max profit, max loss, breakevens, Greeks and scenarios."
          />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "2fr 1fr",
              gap: SPACE.cardLg,
              alignItems: "stretch",
            }}
          >
            <Panel padding={SPACE.cardLg}>
              <Eyebrow>Payoff Curve (ATM Iron Condor)</Eyebrow>
              <PayoffMiniChart />
            </Panel>
            <Panel padding={SPACE.cardLg}>
              <Eyebrow>Risk Metrics</Eyebrow>
              <div style={{ display: "flex", flexDirection: "column", gap: SPACE.compLg, marginTop: SPACE.comp }}>
                <div>
                  <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>MAX PROFIT</div>
                  <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>₹3,250</div>
                </div>
                <div>
                  <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>MAX LOSS</div>
                  <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>-₹9,750</div>
                </div>
                <div>
                  <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>BREAKEVENS</div>
                  <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,250 / 25,750</div>
                </div>
              </div>
              <div style={{ marginTop: SPACE.cardLg, textAlign: "center" }}>
                <DemoLabel style={{ fontSize: "0.625rem" }} />
              </div>
            </Panel>
          </div>
        </Container>
      </Section>

      {/* 08 — PAPER TRADING (Interactive) */}
      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="PAPER EXECUTION"
            title="Practice the workflow. Not your capital."
            subtitle="Decision, simulation, position management, P&L and review in one environment."
          />
          <WorkflowTabs tabs={paperTabs} defaultTab="decision" ariaLabel="Paper Trading" />
          <div style={{ textAlign: "center", marginTop: SPACE.section }}>
            <LinkButton variant="secondary" size="md" href="/paper-trading" className="ds-focus-ring">
              Learn More <span aria-hidden="true">→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      {/* 09 — FINAL CTA */}
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
