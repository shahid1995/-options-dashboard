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
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: SPACE.comp,
          }}
        >
          {steps.map((step) => (
            <div
              key={step.index}
              style={{
                padding: SPACE.cardLg,
                background: COLOR.surface,
                border: `1px solid ${COLOR.border}`,
                borderRadius: RADIUS.lg,
              }}
            >
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
        {[
          ["Order Type", "LIMIT"],
          ["Simulated Qty", "2 Lot"],
          ["Simulated Capital", "₹1,00,000"],
        ].map(([label, value]) => (
          <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.small} ${SPACE.comp}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm }}>
            <span style={{ color: COLOR.textMuted }}>{label}</span>
            <span style={{ fontFamily: TYPE.data, color: COLOR.textPrimary }}>{value}</span>
          </div>
        ))}
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
      <HomeHero onGetStarted={openAuth} />

      <Section style={{ paddingTop: 0 }}>
        <Container maxWidth={1100}>
          <div style={{ marginTop: `-${SPACE.sectionLg}`, position: "relative" }}>
            <PlatformPreview />
          </div>
        </Container>
      </Section>

      <TransitionSection />

      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="MARKET STATE"
            title="Start with context, not isolated indicators."
            subtitle="See the market state, positioning and core option metrics together before moving into deeper analysis."
          />
          <SignalMetricOverview />
        </Container>
      </Section>

      <Section>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="MARKET INTELLIGENCE"
            title="See what is shaping the market."
            subtitle="Positioning, volatility, Greeks and market structure become useful when read together."
          />
          <MarketIntelligenceGrid />
          <div style={{ textAlign: "center", marginTop: SPACE.section }}>
            <LinkButton variant="primary" size="md" href="/market-intelligence" className="ds-focus-ring">
              Explore Market Intelligence <span aria-hidden="true">→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      <EvidenceTrustSection />

      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="FROM CONTEXT TO STRATEGY"
            title="Build the strategy. See the payoff. Understand the risk."
            subtitle="Move through the decision workflow without losing the market context that informed it."
          />
          <WorkflowTabs tabs={strategyTabs} defaultTab="market" ariaLabel="Strategy Lab" />
          <div style={{ textAlign: "center", marginTop: SPACE.section }}>
            <LinkButton variant="primary" size="md" href="/strategy-lab" className="ds-focus-ring">
              Open Strategy Lab <span aria-hidden="true">→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      <Section>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="RISK FIRST"
            title="Know the payoff before you know the outcome."
            subtitle="Explore payoff shape, maximum profit, maximum loss, breakevens and Greeks before putting capital behind an idea."
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
              <Eyebrow>ILLUSTRATIVE PAYOFF</Eyebrow>
              <PayoffMiniChart />
            </Panel>
            <Panel padding={SPACE.cardLg}>
              <Eyebrow>RISK METRICS</Eyebrow>
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

      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle
            eyebrow="PAPER WORKFLOW"
            title="Practice the decision process. Not your capital."
            subtitle="Carry the same workflow into simulation, position management and review."
          />
          <WorkflowTabs tabs={paperTabs} defaultTab="decision" ariaLabel="Paper Trading" />
          <div style={{ textAlign: "center", marginTop: SPACE.section }}>
            <LinkButton variant="secondary" size="md" href="/paper-trading" className="ds-focus-ring">
              Explore Paper Trading <span aria-hidden="true">→</span>
            </LinkButton>
          </div>
        </Container>
      </Section>

      <CTASection
        headline={
          <>
            Turn market data into a structured decision.
          </>
        }
        body="Explore StrikeNova, understand the workflow, and practice your strategies before putting capital at risk."
        primaryLabel="Explore the Platform"
        primaryHref="/features"
        secondaryLabel="See How It Works"
        secondaryHref="/how-it-works"
      />
    </>
  );
}
