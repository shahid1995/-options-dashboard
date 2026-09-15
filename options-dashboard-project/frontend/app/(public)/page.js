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
import SignalMetricOverview from "@/components/public/SignalMetricOverview";
import MarketIntelligenceGrid from "@/components/public/MarketIntelligenceGrid";
import EvidenceTrustSection from "@/components/public/EvidenceTrustSection";
import WorkflowTabs from "@/components/public/WorkflowTabs";

import PayoffMiniChart from "@/components/public/PayoffMiniChart";

function TransitionSection() {
  const steps = [
    {
      index: "01",
      title: "Read the market",
      body: "Bring option-chain data, open interest, implied volatility and Greeks into one market context.",
    },
    {
      index: "02",
      title: "Understand structure",
      body: "Use positioning, GEX, gamma-flip context and volatility signals to understand what is shaping the market.",
    },
    {
      index: "03",
      title: "Build the decision",
      body: "Move from context to strategy, payoff, risk and paper execution without leaving the workflow.",
    },
  ];

  return (
    <Section>
      <Container maxWidth={1100}>
        <SectionTitle
          eyebrow="WHY STRIKENOVA"
          title="From market data to structured decisions."
          subtitle="The product is designed as a connected workflow, not a collection of unrelated charts."
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: SPACE.comp }}>
          {steps.map((step) => (
            <div key={step.index} style={{ padding: SPACE.cardLg, background: COLOR.surface, border: `1px solid ${COLOR.border}`, borderRadius: RADIUS.lg }}>
              <div style={{ fontFamily: TYPE.data, color: COLOR.strategy, fontSize: TYPE.caption.size }}>{step.index}</div>
              <h3 style={{ margin: `${SPACE.small} 0`, color: COLOR.textPrimary, fontSize: TYPE.h4.size }}>{step.title}</h3>
              <p style={{ margin: 0, color: COLOR.textMuted, lineHeight: 1.7 }}>{step.body}</p>
            </div>
          ))}
        </div>
      </Container>
    </Section>
  );
}

function StrategyMarketView() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.cardLg }}>
      <div>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>NIFTY</div>
        <div style={{ fontSize: "2rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data, lineHeight: 1.1 }}>25,500</div>
        <div style={{ display: "flex", gap: SPACE.cardLg, marginTop: SPACE.comp }}>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>PCR</div>
            <div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>0.92</div>
          </div>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>ATM IV</div>
            <div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>14.2%</div>
          </div>
        </div>
      </div>
      <div>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MARKET STATE</div>
        <div style={{ fontSize: "2rem", fontWeight: 700, color: COLOR.info, fontFamily: TYPE.data, lineHeight: 1.1 }}>BALANCED</div>
        <div style={{ fontSize: "0.75rem", color: COLOR.textMuted, marginTop: SPACE.comp }}>Positioning is neutral with moderate volatility</div>
      </div>
    </div>
  );
}

function StrategyLegs() {
  const legs = [
    { action: "SELL", strike: "25,600", type: "CE" },
    { action: "BUY", strike: "25,700", type: "CE" },
    { action: "SELL", strike: "25,400", type: "PE" },
    { action: "BUY", strike: "25,300", type: "PE" },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.cardLg }}>
      <div>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>STRATEGY</div>
        <div style={{ fontSize: "1.5rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data, lineHeight: 1.1 }}>IRON CONDOR</div>
        <div style={{ fontSize: "0.75rem", color: COLOR.textMuted, marginTop: SPACE.small }}>Defined-risk, neutral strategy</div>
      </div>
      <div>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.small }}>STRUCTURE</div>
        <div style={{ display: "flex", flexDirection: "column", gap: SPACE.xs }}>
          {legs.map((leg, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.xs} ${SPACE.small}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm, fontFamily: TYPE.data, fontSize: "0.75rem" }}>
              <span style={{ fontWeight: 700, color: leg.action === "BUY" ? COLOR.positive : COLOR.negative }}>{leg.action}</span>
              <span style={{ color: COLOR.textPrimary }}>{leg.strike}</span>
              <span style={{ color: COLOR.textMuted }}>{leg.type}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StrategyPayoff() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.cardLg, alignItems: "start" }}>
      <div>
        <Eyebrow>ILLUSTRATIVE PAYOFF</Eyebrow>
        <PayoffMiniChart />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: SPACE.comp }}>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MAX PROFIT</div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>₹3,250</div>
        </div>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MAX LOSS</div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>-₹9,750</div>
        </div>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>BREAKEVENS</div>
          <div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,250 / 25,750</div>
        </div>
      </div>
    </div>
  );
}

function StrategyRisk() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.cardLg }}>
      <div>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.small }}>DECISION BOUNDARIES</div>
        <div style={{ display: "flex", flexDirection: "column", gap: SPACE.comp }}>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MAX PROFIT</div>
            <div style={{ fontSize: "1.125rem", fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>₹3,250</div>
          </div>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MAX LOSS</div>
            <div style={{ fontSize: "1.125rem", fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>-₹9,750</div>
          </div>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>BREAKEVEN</div>
            <div style={{ fontSize: "1.125rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,250 / 25,750</div>
          </div>
        </div>
      </div>
      <div>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.small }}>POSITION GREEKS</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.comp }}>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>DELTA</div>
            <div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>-0.02</div>
          </div>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>GAMMA</div>
            <div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>0.0003</div>
          </div>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>THETA</div>
            <div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>+42.15</div>
          </div>
          <div>
            <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>VEGA</div>
            <div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>-18.40</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PaperDecision() {
  return <div><h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>DECISION</h4><div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>SPOT</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,500</div></div><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>STRATEGY</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.strategy, fontFamily: TYPE.data }}>IRON CONDOR</div></div></div><DemoLabel style={{ fontSize: "0.625rem" }} /></div>;
}

function PaperSimulation() {
  return (
    <div>
      <h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>SIMULATION</h4>
      <div style={{ display: "flex", flexDirection: "column", gap: SPACE.small, marginBottom: SPACE.compLg }}>
        {[["Order Type", "LIMIT"], ["Simulated Qty", "2 Lot"], ["Simulated Capital", "₹1,00,000"]].map(([label, value]) => <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.small} ${SPACE.comp}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm }}><span style={{ color: COLOR.textMuted }}>{label}</span><span style={{ fontFamily: TYPE.data, color: COLOR.textPrimary }}>{value}</span></div>)}
      </div>
      <DemoLabel style={{ fontSize: "0.625rem" }} />
    </div>
  );
}

function PaperPosition() {
  return <div><h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>POSITION</h4><div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>OPEN P&L</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>+₹1,240</div></div><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>DELTA</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>-0.02</div></div></div><DemoLabel style={{ fontSize: "0.625rem" }} /></div>;
}

function PaperReview() {
  return <div><h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>REVIEW</h4><div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>TRADES</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>12</div></div><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>WIN RATE</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>67%</div></div></div><DemoLabel style={{ fontSize: "0.625rem" }} /></div>;
}

export default function HomePage() {
  const isMobile = useIsMobile();
  const { open: openAuth } = useAuthModal();

  const strategySteps = [
    { id: "market", number: "01", label: "MARKET VIEW", sublabel: "Understand the environment", content: <StrategyMarketView /> },
    { id: "strategy", number: "02", label: "STRATEGY", sublabel: "Choose the structure", content: <StrategyLegs /> },
    { id: "payoff", number: "03", label: "PAYOFF", sublabel: "See how it behaves", content: <StrategyPayoff /> },
    { id: "risk", number: "04", label: "RISK", sublabel: "Know the boundaries", content: <StrategyRisk /> },
  ];

  const paperSteps = [
    { id: "decision", number: "01", label: "DECISION", sublabel: "Evaluate the opportunity", content: <PaperDecision /> },
    { id: "simulation", number: "02", label: "SIMULATION", sublabel: "Test the approach", content: <PaperSimulation /> },
    { id: "position", number: "03", label: "POSITION", sublabel: "Manage exposure", content: <PaperPosition /> },
    { id: "review", number: "04", label: "REVIEW", sublabel: "Assess performance", content: <PaperReview /> },
  ];

  return (
    <>
      <HomeHero onGetStarted={openAuth} />

      <TransitionSection />

      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle eyebrow="MARKET STATE" title="Start with context, not isolated indicators." subtitle="See the market state, positioning and core option metrics together before moving into deeper analysis." />
          <SignalMetricOverview />
        </Container>
      </Section>

      <Section>
        <Container maxWidth={1100}>
          <SectionTitle eyebrow="MARKET INTELLIGENCE" title="See what is shaping the market." subtitle="Positioning, volatility, Greeks and market structure become useful when read together." />
          <MarketIntelligenceGrid />
          <div style={{ textAlign: "center", marginTop: SPACE.section }}><LinkButton variant="primary" size="md" href="/market-intelligence" className="ds-focus-ring">Explore Market Intelligence <span aria-hidden="true">→</span></LinkButton></div>
        </Container>
      </Section>

      <EvidenceTrustSection />

      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle eyebrow="FROM CONTEXT TO STRATEGY" title="Build the strategy. See the payoff. Understand the risk." subtitle="Move through the decision workflow without losing the market context that informed it." />
          <WorkflowTabs steps={strategySteps} defaultStep="market" ariaLabel="Strategy Lab" />
          <div style={{ textAlign: "center", marginTop: SPACE.cardLg }}><LinkButton variant="primary" size="md" href="/strategy-lab" className="ds-focus-ring">Open Strategy Lab <span aria-hidden="true">→</span></LinkButton></div>
        </Container>
      </Section>

      <Section>
        <Container maxWidth={1100}>
          <SectionTitle eyebrow="RISK FIRST" title="Know the payoff before you know the outcome." subtitle="Explore payoff shape, maximum profit, maximum loss, breakevens and Greeks before putting capital behind an idea." />
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "2fr 1fr", gap: SPACE.cardLg, alignItems: "stretch" }}>
            <Panel padding={SPACE.cardLg}><Eyebrow>ILLUSTRATIVE PAYOFF</Eyebrow><PayoffMiniChart /></Panel>
            <Panel padding={SPACE.cardLg}>
              <Eyebrow>RISK METRICS</Eyebrow>
              <div style={{ display: "flex", flexDirection: "column", gap: SPACE.compLg, marginTop: SPACE.comp }}>
                <div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>MAX PROFIT</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>₹3,250</div></div>
                <div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>MAX LOSS</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>-₹9,750</div></div>
                <div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>BREAKEVENS</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,250 / 25,750</div></div>
              </div>
              <div style={{ marginTop: SPACE.cardLg, textAlign: "center" }}><DemoLabel style={{ fontSize: "0.625rem" }} /></div>
            </Panel>
          </div>
        </Container>
      </Section>

      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle eyebrow="PAPER EXECUTION" title="Practice the workflow. Not your capital." subtitle="Decision, simulation, position management, P&L and review in one environment." />
          <WorkflowTabs steps={paperSteps} defaultStep="decision" ariaLabel="Paper Trading" />
          <div style={{ textAlign: "center", marginTop: SPACE.section }}><LinkButton variant="secondary" size="md" href="/paper-trading" className="ds-focus-ring">Explore Paper Trading <span aria-hidden="true">→</span></LinkButton></div>
        </Container>
      </Section>

      <CTASection
        headline={<><span style={{ color: COLOR.strategy }}>Trade with context.</span> Decide with structure.</>}
        body="Explore the StrikeNova workflow from market state to strategy, risk and paper execution."
        primaryLabel="Explore the Platform"
        primaryHref="/features"
        secondaryLabel="See How It Works"
        secondaryHref="/how-it-works"
      />
    </>
  );
}
