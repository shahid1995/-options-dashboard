"use client";
import { C, useIsMobile } from "@/lib/ui";
import { loginUrl } from "@/lib/api";
import { SectionHeading, CTASection, PAGE_MAX, sectionPad } from "@/components/public";

const STEPS = [
  {
    num: "01",
    title: "OBSERVE",
    desc: "Understand price, option chain, OI, volume, IV and Greeks. The platform streams a full option chain for eight Indian index derivatives in real time.",
    detail: "Each strike shows LTP, OI, change in OI, volume, IV and the full Greek stack — updated over WebSocket with automatic HTTP fallback.",
  },
  {
    num: "02",
    title: "ANALYZE",
    desc: "Study positioning, volatility and market structure. PCR, max pain, OI distribution and IV skew help you understand the forces behind the price.",
    detail: "Go beyond the raw chain to investigate put/call ratios, open interest clusters, and how implied volatility is pricing risk.",
  },
  {
    num: "03",
    title: "BUILD",
    desc: "Construct a strategy around the market view. Choose from 42 templates or build custom multi-leg strategies with full control over strikes and expiries.",
    detail: "Spreads, condors, butterflies, ratios, calendars — every combination available with full strike and expiry selection.",
  },
  {
    num: "04",
    title: "TEST",
    desc: "Analyze payoff, risk, Greeks and scenarios. The platform shows you max profit, max loss, breakevens and position Greeks before you commit.",
    detail: "Stress-test under spot, IV, time and rate changes using a Black-Scholes scenario model. Understand the risk profile from every angle.",
  },
  {
    num: "05",
    title: "PAPER TRADE",
    desc: "Simulate the strategy without risking real capital. Execute in a paper environment that mirrors real market conditions.",
    detail: "Track positions, P&L, capital and strategy performance over time — all without placing a single real broker order.",
  },
  {
    num: "06",
    title: "REVIEW",
    desc: "Study the result, execution and risk. Review trade history, per-strategy statistics and equity curves to improve over time.",
    detail: "Export trade history to CSV, review per-strategy win rates, and study execution quality against market conditions.",
  },
];

export default function HowItWorksClientPage() {
  const isMobile = useIsMobile();

  return (
    <>
      {/* Hero */}
      <section style={{ paddingTop: 72, paddingBottom: 32, textAlign: "center" }}>
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: "0 20px" }}>
          <SectionHeading
            level={1}
            tag="HOW IT WORKS"
            title="From Market Data to a Structured Trading Workflow."
            sub="A six-step process that separates observation from analysis, analysis from strategy construction, and strategy from execution."
          />
        </div>
      </section>

      {/* Steps */}
      <section style={sectionPad(isMobile)}>
        <div style={{ maxWidth: 800, margin: "0 auto" }}>
          {STEPS.map((step, i) => (
            <div
              key={step.num}
              style={{
                display: "flex",
                gap: isMobile ? 16 : 28,
                marginBottom: i < STEPS.length - 1 ? 40 : 0,
                alignItems: "flex-start",
              }}
            >
              {/* Step number */}
              <div
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: 14,
                  background: "rgba(201,161,90,0.1)",
                  border: "1px solid rgba(201,161,90,0.25)",
                  display: "grid",
                  placeItems: "center",
                  fontSize: 20,
                  fontWeight: 800,
                  color: C.gold,
                  flexShrink: 0,
                }}
              >
                {step.num}
              </div>

              {/* Content */}
              <div style={{ flex: 1, paddingTop: 4 }}>
                <h3 style={{ fontSize: 17, fontWeight: 700, color: C.text, margin: "0 0 8px", letterSpacing: 0.5 }}>
                  {step.title}
                </h3>
                <p style={{ fontSize: 14, color: C.muted, lineHeight: 1.65, margin: "0 0 8px" }}>
                  {step.desc}
                </p>
                <p style={{ fontSize: 14, color: C.muted, lineHeight: 1.6, margin: 0 }}>
                  {step.detail}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Closing statement */}
      <section style={{ borderTop: `1px solid ${C.border}`, background: "linear-gradient(180deg, rgba(18,22,31,0.5), rgba(11,14,20,0.2))" }}>
        <div style={sectionPad(isMobile)}>
          <div style={{ maxWidth: 640, margin: "0 auto", textAlign: "center" }}>
            <blockquote
              style={{
                fontSize: isMobile ? 18 : 22,
                fontWeight: 600,
                color: C.text,
                lineHeight: 1.5,
                margin: 0,
                padding: 0,
                borderLeft: "none",
                fontStyle: "normal",
              }}
            >
              &ldquo;Good trading is not just finding an entry. It is understanding the risk around the decision.&rdquo;
            </blockquote>
          </div>
        </div>
      </section>

      {/* CTA */}
      <CTASection
        headline={<>Ready to put it into practice?</>}
        primaryLabel="Get Started"
        primaryHref={loginUrl()}
        secondaryLabel="Explore the Platform"
        secondaryHref="/features"
      />
    </>
  );
}
