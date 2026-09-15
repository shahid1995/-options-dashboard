"use client";
import { useIsMobile } from "@/lib/ui";
import { useAuthModal } from "@/components/public/AuthModalContext";
import { Section, Container } from "@/components/public/layout";
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
    { index: "01", title: "Read the market", body: "Bring option-chain data, open interest, implied volatility and Greeks into one market context." },
    { index: "02", title: "Understand structure", body: "Use positioning, GEX, gamma-flip context and volatility signals to understand what is shaping the market." },
    { index: "03", title: "Build the decision", body: "Move from context to strategy, payoff, risk and paper execution without leaving the workflow." },
  ];
  return (
    <Section>
      <Container maxWidth={1100}>
        <SectionTitle eyebrow="WHY STRIKENOVA" title="From market data to structured decisions." subtitle="The product is designed as a connected workflow, not a collection of unrelated charts." />
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
          <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>PCR</div><div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>0.92</div></div>
          <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>ATM IV</div><div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>14.2%</div></div>
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
      <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>STRATEGY</div><div style={{ fontSize: "1.5rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data, lineHeight: 1.1 }}>IRON CONDOR</div><div style={{ fontSize: "0.75rem", color: COLOR.textMuted, marginTop: SPACE.small }}>Defined-risk, neutral strategy</div></div>
      <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.small }}>STRUCTURE</div><div style={{ display: "flex", flexDirection: "column", gap: SPACE.xs }}>{legs.map((leg, i) => <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.xs} ${SPACE.small}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm, fontFamily: TYPE.data, fontSize: "0.75rem" }}><span style={{ fontWeight: 700, color: leg.action === "BUY" ? COLOR.positive : COLOR.negative }}>{leg.action}</span><span style={{ color: COLOR.textPrimary }}>{leg.strike}</span><span style={{ color: COLOR.textMuted }}>{leg.type}</span></div>)}</div></div>
    </div>
  );
}

function StrategyPayoff() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.cardLg, alignItems: "start" }}>
      <div><Eyebrow>ILLUSTRATIVE PAYOFF</Eyebrow><PayoffMiniChart /></div>
      <div style={{ display: "flex", flexDirection: "column", gap: SPACE.comp }}>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MAX PROFIT</div><div style={{ fontSize: "1.5rem", fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>₹3,250</div></div>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MAX LOSS</div><div style={{ fontSize: "1.5rem", fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>-₹9,750</div></div>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>BREAKEVENS</div><div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,250 / 25,750</div></div>
      </div>
    </div>
  );
}

function StrategyRisk() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.cardLg }}>
      <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.small }}>DECISION BOUNDARIES</div><div style={{ display: "flex", flexDirection: "column", gap: SPACE.comp }}>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MAX PROFIT</div><div style={{ fontSize: "1.125rem", fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>₹3,250</div></div>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MAX LOSS</div><div style={{ fontSize: "1.125rem", fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>-₹9,750</div></div>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>BREAKEVEN</div><div style={{ fontSize: "1.125rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,250 / 25,750</div></div>
      </div></div>
      <div><div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.small }}>POSITION GREEKS</div><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.comp }}>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, color: COLOR.textFaint }}>DELTA</div><div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>-0.02</div></div>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, color: COLOR.textFaint }}>GAMMA</div><div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>0.0003</div></div>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, color: COLOR.textFaint }}>THETA</div><div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>+42.15</div></div>
        <div><div style={{ fontSize: "0.625rem", fontWeight: 600, color: COLOR.textFaint }}>VEGA</div><div style={{ fontSize: "1rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>-18.40</div></div>
      </div></div>
    </div>
  );
}

function RiskFirstSection() {
  const isMobile = useIsMobile();
  const boundaries = [
    ["MAX LOSS", "-45 pts", COLOR.negative],
    ["MAX PROFIT", "+55 pts", COLOR.positive],
    ["BREAKEVEN", "25,495", COLOR.strategy],
    ["REWARD / RISK", "1.22 : 1", COLOR.strategy],
  ];
  return (
    <Section>
      <Container maxWidth={1100}>
        <SectionTitle eyebrow="RISK FIRST" title="Know the payoff before you know the outcome." subtitle="Explore payoff shape, maximum profit, maximum loss, breakeven and reward-to-risk before putting capital behind an idea." />
        <div style={{ borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}`, padding: `${SPACE.section} 0` }}>
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "minmax(0, 1.65fr) minmax(280px, 0.75fr)", gap: isMobile ? SPACE.section : SPACE.cardLg, alignItems: "start" }}>
            <div>
              <Eyebrow>ILLUSTRATIVE EXPIRY PAYOFF · BULL CALL SPREAD</Eyebrow>
              <div style={{ marginTop: SPACE.comp, width: "100%", overflow: "hidden" }}>
                <svg viewBox="0 0 620 250" width="100%" height="250" role="img" aria-label="Illustrative Bull Call Spread payoff with negative 45 point maximum loss, 25,495 breakeven, 25,550 short strike and positive 55 point maximum profit.">
                  <line x1="48" y1="125" x2="590" y2="125" stroke={COLOR.border} strokeWidth="1.5" />
                  <line x1="48" y1="70" x2="590" y2="70" stroke={COLOR.borderSubtle} strokeWidth="1" strokeDasharray="3 4" />
                  <line x1="48" y1="170" x2="590" y2="170" stroke={COLOR.borderSubtle} strokeWidth="1" strokeDasharray="3 4" />
                  <path d="M48 170 L160 170 L286 125" fill="none" stroke={COLOR.negative} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
                  <path d="M48 170 L160 170 L286 125 L48 125 Z" fill={COLOR.negative} opacity="0.08" />
                  <path d="M286 125 L440 70 L590 70" fill="none" stroke={COLOR.positive} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M286 125 L440 70 L590 70 L590 125 L286 125 Z" fill={COLOR.positive} opacity="0.08" />
                  <line x1="286" y1="38" x2="286" y2="210" stroke={COLOR.strategy} strokeWidth="1" strokeDasharray="4 4" opacity="0.8" />
                  <line x1="300" y1="38" x2="300" y2="210" stroke={COLOR.borderSubtle} strokeWidth="1" strokeDasharray="2 5" opacity="0.8" />
                  <line x1="440" y1="38" x2="440" y2="210" stroke={COLOR.strategy} strokeWidth="1" strokeDasharray="4 4" opacity="0.65" />
                  <circle cx="300" cy="120" r="4" fill={COLOR.textPrimary} />
                  <text x="44" y="63" fill={COLOR.textFaint} fontSize="10" textAnchor="end" fontFamily="monospace">+55</text>
                  <text x="44" y="129" fill={COLOR.textFaint} fontSize="10" textAnchor="end" fontFamily="monospace">0</text>
                  <text x="44" y="174" fill={COLOR.textFaint} fontSize="10" textAnchor="end" fontFamily="monospace">-45</text>
                  <text x="160" y="216" fill={COLOR.textFaint} fontSize="10" textAnchor="middle" fontFamily="monospace">25,450</text>
                  <text x="286" y="232" fill={COLOR.strategy} fontSize="9" textAnchor="middle" fontFamily="monospace">BREAKEVEN 25,495</text>
                  <text x="300" y="216" fill={COLOR.textPrimary} fontSize="10" textAnchor="middle" fontFamily="monospace">SPOT 25,500</text>
                  <text x="440" y="232" fill={COLOR.strategy} fontSize="9" textAnchor="middle" fontFamily="monospace">SHORT 25,550</text>
                  <text x="590" y="216" fill={COLOR.textFaint} fontSize="10" textAnchor="end" fontFamily="monospace">25,650</text>
                  <text x="82" y="158" fill={COLOR.negative} fontSize="9" fontWeight="700">MAX LOSS</text>
                  <text x="475" y="63" fill={COLOR.positive} fontSize="9" fontWeight="700">MAX PROFIT · CAPPED</text>
                </svg>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: SPACE.cardLg, paddingTop: isMobile ? 0 : SPACE.comp }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.comp }}>
                {boundaries.map(([label, value, color]) => (
                  <div key={label} style={{ paddingTop: SPACE.small, borderTop: `1px solid ${COLOR.borderSubtle}` }}>
                    <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>{label}</div>
                    <div style={{ marginTop: SPACE.xs, fontSize: TYPE.data.size, fontWeight: 700, color, fontFamily: TYPE.data }}>{value}</div>
                  </div>
                ))}
              </div>
              <div style={{ borderTop: `1px solid ${COLOR.borderSubtle}`, paddingTop: SPACE.comp }}>
                <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint, marginBottom: SPACE.small }}>RISK BOUNDARIES</div>
                <div style={{ display: "grid", gap: SPACE.small }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: SPACE.small, color: COLOR.textSecondary, fontSize: "0.75rem" }}><span>Below 25,450</span><span style={{ fontFamily: TYPE.data, color: COLOR.negative }}>-45 pts</span></div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: SPACE.small, color: COLOR.textSecondary, fontSize: "0.75rem" }}><span>25,450 → 25,550</span><span style={{ fontFamily: TYPE.data, color: COLOR.strategy }}>Payoff rises linearly</span></div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: SPACE.small, color: COLOR.textSecondary, fontSize: "0.75rem" }}><span>Above 25,550</span><span style={{ fontFamily: TYPE.data, color: COLOR.positive }}>+55 pts capped</span></div>
                </div>
              </div>
            </div>
          </div>
          <div style={{ marginTop: SPACE.cardLg, borderTop: `1px solid ${COLOR.borderSubtle}`, paddingTop: SPACE.cardLg }}>
            <div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint, marginBottom: SPACE.comp }}>WHAT THIS MEANS</div>
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, minmax(0, 1fr))", gap: SPACE.cardLg }}>
              <div><div style={{ fontFamily: TYPE.data, fontSize: TYPE.caption.size, color: COLOR.strategy }}>01 · LOSS CAPPED</div><p style={{ margin: `${SPACE.xs} 0 0`, color: COLOR.textMuted, fontSize: "0.75rem", lineHeight: 1.6 }}>The initial 45-point debit defines the maximum expiry loss.</p></div>
              <div><div style={{ fontFamily: TYPE.data, fontSize: TYPE.caption.size, color: COLOR.strategy }}>02 · BREAKEVEN VISIBLE</div><p style={{ margin: `${SPACE.xs} 0 0`, color: COLOR.textMuted, fontSize: "0.75rem", lineHeight: 1.6 }}>Profit begins above 25,495 before costs, slippage or early exit.</p></div>
              <div><div style={{ fontFamily: TYPE.data, fontSize: TYPE.caption.size, color: COLOR.strategy }}>03 · PROFIT CAPPED</div><p style={{ margin: `${SPACE.xs} 0 0`, color: COLOR.textMuted, fontSize: "0.75rem", lineHeight: 1.6 }}>The short 25,550 call caps the payoff at 55 points.</p></div>
            </div>
          </div>
          <div style={{ marginTop: SPACE.comp }}><DemoLabel style={{ fontSize: "0.625rem" }} /></div>
        </div>
      </Container>
    </Section>
  );
}

function PaperDecision() {
  return <div><h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>DECIDE</h4><div style={{ display: "grid", gridTemplateColumns: "1.25fr 0.75fr", gap: SPACE.comp, marginBottom: SPACE.compLg }}><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>STRATEGY</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.strategy, fontFamily: TYPE.data }}>BULL CALL SPREAD</div><div style={{ fontSize: "0.75rem", color: COLOR.textMuted, marginTop: SPACE.xs }}>Buy 25,450 CE · Sell 25,550 CE</div></div><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>SPOT</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>25,500</div></div></div><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.comp }}><div style={{ paddingTop: SPACE.small, borderTop: `1px solid ${COLOR.borderSubtle}` }}><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>MAX LOSS</div><div style={{ marginTop: SPACE.xs, fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>-45 pts</div></div><div style={{ paddingTop: SPACE.small, borderTop: `1px solid ${COLOR.borderSubtle}` }}><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>REWARD / RISK</div><div style={{ marginTop: SPACE.xs, fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.strategy, fontFamily: TYPE.data }}>1.22 : 1</div></div></div><div style={{ marginTop: SPACE.comp }}><DemoLabel style={{ fontSize: "0.625rem" }} /></div></div>;
}

function PaperSimulation() {
  return <div><h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>EXECUTE</h4><div style={{ display: "flex", flexDirection: "column", gap: SPACE.small, marginBottom: SPACE.compLg }}>{[["Order Status", "FILLED"], ["Entry", "45.0 pts"], ["Quantity", "1 Lot"], ["Environment", "PAPER"]].map(([label, value]) => <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: `${SPACE.small} ${SPACE.comp}`, background: COLOR.baseElevated, borderRadius: RADIUS.sm }}><span style={{ color: COLOR.textMuted }}>{label}</span><span style={{ fontFamily: TYPE.data, fontWeight: 700, color: value === "FILLED" ? COLOR.strategy : COLOR.textPrimary }}>{value}</span></div>)}</div><div style={{ marginBottom: SPACE.comp }}><DemoLabel style={{ fontSize: "0.625rem" }} /></div><div style={{ paddingTop: SPACE.small, borderTop: `1px solid ${COLOR.borderSubtle}`, fontSize: TYPE.caption.size, color: COLOR.textFaint }}>SIMULATED EXECUTION · NO REAL BROKER ORDER</div></div>;
}

function PaperPosition() {
  return <div><h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>MANAGE</h4><div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: SPACE.comp, marginBottom: SPACE.compLg }}><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>ENTRY</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>45.0</div></div><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>CURRENT</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>58.5</div></div><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>UNREALIZED P&L</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>+13.5 pts</div></div></div><div style={{ display: "flex", gap: SPACE.small, flexWrap: "wrap", marginBottom: SPACE.compLg }}>{["HOLD", "EXIT", "REVIEW"].map((action) => <span key={action} style={{ padding: `${SPACE.xs} ${SPACE.small}`, border: `1px solid ${COLOR.borderSubtle}`, borderRadius: RADIUS.sm, color: action === "EXIT" ? COLOR.strategy : COLOR.textSecondary, fontFamily: TYPE.data, fontSize: TYPE.caption.size, letterSpacing: "0.04em" }}>{action}</span>)}</div><DemoLabel style={{ fontSize: "0.625rem" }} /></div>;
}

function PaperReview() {
  return <div><h4 style={{ margin: 0, marginBottom: SPACE.comp, color: COLOR.textPrimary }}>REVIEW</h4><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.comp, marginBottom: SPACE.compLg }}><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>OUTCOME</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>+13.5 pts</div></div><div><div style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>RESULT</div><div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>POSITIVE</div></div></div><div style={{ paddingTop: SPACE.small, borderTop: `1px solid ${COLOR.borderSubtle}`, color: COLOR.textMuted, fontSize: "0.75rem", lineHeight: 1.6, marginBottom: SPACE.compLg }}>Record the thesis, market context, execution result and what changed before the next decision.</div><DemoLabel style={{ fontSize: "0.625rem" }} /></div>;
}

export default function HomePage() {
  const { open: openAuth } = useAuthModal();

  const strategySteps = [
    { id: "market", number: "01", label: "MARKET VIEW", sublabel: "Understand the environment", content: <StrategyMarketView /> },
    { id: "strategy", number: "02", label: "STRATEGY", sublabel: "Choose the structure", content: <StrategyLegs /> },
    { id: "payoff", number: "03", label: "PAYOFF", sublabel: "See how it behaves", content: <StrategyPayoff /> },
    { id: "risk", number: "04", label: "RISK", sublabel: "Know the boundaries", content: <StrategyRisk /> },
  ];

  const paperSteps = [
    { id: "decision", number: "01", label: "DECIDE", sublabel: "Evaluate the opportunity", content: <PaperDecision /> },
    { id: "execution", number: "02", label: "EXECUTE", sublabel: "Simulate the order", content: <PaperSimulation /> },
    { id: "management", number: "03", label: "MANAGE", sublabel: "Monitor the position", content: <PaperPosition /> },
    { id: "review", number: "04", label: "REVIEW", sublabel: "Turn outcome into evidence", content: <PaperReview /> },
  ];

  return (
    <>
      <HomeHero onGetStarted={openAuth} />
      <TransitionSection />
      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}><SectionTitle eyebrow="MARKET STATE" title="Start with context, not isolated indicators." subtitle="See the market state, positioning and core option metrics together before moving into deeper analysis." /><SignalMetricOverview /></Container>
      </Section>
      <Section>
        <Container maxWidth={1100}><SectionTitle eyebrow="MARKET INTELLIGENCE" title="See what is shaping the market." subtitle="Positioning, volatility, Greeks and market structure become useful when read together." /><MarketIntelligenceGrid /><div style={{ textAlign: "center", marginTop: SPACE.section }}><LinkButton variant="primary" size="md" href="/market-intelligence" className="ds-focus-ring">Explore Market Intelligence <span aria-hidden="true">→</span></LinkButton></div></Container>
      </Section>
      <EvidenceTrustSection />
      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}><SectionTitle eyebrow="FROM CONTEXT TO STRATEGY" title="Build the strategy. See the payoff. Understand the risk." subtitle="Move through the decision workflow without losing the market context that informed it." /><WorkflowTabs steps={strategySteps} defaultStep="market" ariaLabel="Strategy Lab" /><div style={{ textAlign: "center", marginTop: SPACE.cardLg }}><LinkButton variant="primary" size="md" href="/strategy-lab" className="ds-focus-ring">Open Strategy Lab <span aria-hidden="true">→</span></LinkButton></div></Container>
      </Section>
      <RiskFirstSection />
      <Section style={{ background: COLOR.baseElevated, borderTop: `1px solid ${COLOR.border}`, borderBottom: `1px solid ${COLOR.border}` }}>
        <Container maxWidth={1100}>
          <SectionTitle eyebrow="PAPER EXECUTION" title="Practice the workflow. Not your capital." subtitle="Decision, execution, position management, P&L and review in one environment." />
          <WorkflowTabs steps={paperSteps} defaultStep="decision" ariaLabel="Paper Trading" />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: SPACE.cardLg, marginTop: SPACE.cardLg, paddingTop: SPACE.cardLg, borderTop: `1px solid ${COLOR.borderSubtle}` }}>
            <div><div style={{ fontFamily: TYPE.data, fontSize: TYPE.caption.size, color: COLOR.strategy }}>01 · SIMULATE</div><p style={{ margin: `${SPACE.xs} 0 0`, color: COLOR.textMuted, fontSize: "0.75rem", lineHeight: 1.6 }}>Test an execution idea before real capital is exposed.</p></div>
            <div><div style={{ fontFamily: TYPE.data, fontSize: TYPE.caption.size, color: COLOR.strategy }}>02 · MANAGE</div><p style={{ margin: `${SPACE.xs} 0 0`, color: COLOR.textMuted, fontSize: "0.75rem", lineHeight: 1.6 }}>Follow the position, P&L and exposure as the idea evolves.</p></div>
            <div><div style={{ fontFamily: TYPE.data, fontSize: TYPE.caption.size, color: COLOR.strategy }}>03 · LEARN</div><p style={{ margin: `${SPACE.xs} 0 0`, color: COLOR.textMuted, fontSize: "0.75rem", lineHeight: 1.6 }}>Turn each simulated outcome into evidence for the next decision.</p></div>
          </div>
          <div style={{ marginTop: SPACE.cardLg, paddingTop: SPACE.comp, borderTop: `1px solid ${COLOR.borderSubtle}`, display: "flex", justifyContent: "space-between", alignItems: "center", gap: SPACE.comp, flexWrap: "wrap" }}>
            <div><div style={{ fontFamily: TYPE.data, fontSize: TYPE.caption.size, color: COLOR.textFaint }}>PAPER ENVIRONMENT</div><div style={{ marginTop: SPACE.xs, color: COLOR.textMuted, fontSize: "0.75rem" }}>Simulated capital. No real broker orders. Built to test decisions before capital is at risk.</div></div>
            <LinkButton variant="secondary" size="md" href="/paper-trading" className="ds-focus-ring">Explore Paper Trading <span aria-hidden="true">→</span></LinkButton>
          </div>
        </Container>
      </Section>
      <CTASection headline={<><span style={{ color: COLOR.strategy }}>Trade with context.</span> Decide with structure.</>} body="Explore the StrikeNova workflow from market state to strategy, risk and paper execution." primaryLabel="Explore the Platform" primaryHref="/features" secondaryLabel="See How It Works" secondaryHref="/how-it-works" />
    </>
  );
}
