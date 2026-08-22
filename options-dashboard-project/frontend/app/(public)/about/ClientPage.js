"use client";
import { C, useIsMobile } from "@/lib/ui";
import { loginUrl } from "@/lib/api";
import { SectionHeading, CTASection, PAGE_MAX, sectionPad } from "@/components/public";

const PRINCIPLES = [
  {
    title: "Data First",
    desc: "Every decision starts with market data. The platform provides raw chain data, computed analytics and derived metrics — never opinions about the market.",
  },
  {
    title: "Risk First",
    desc: "Before you trade, understand the risk. Payoff curves, max loss, breakevens and Greeks are available before any simulated or real execution.",
  },
  {
    title: "Structured Analysis",
    desc: "Combine OI, volume, IV, Greeks, PCR and market structure into a coherent view rather than relying on a single indicator.",
  },
  {
    title: "Test Before Committing Capital",
    desc: "Paper trading is built into the platform. Every strategy can be simulated before it is risked on real market conditions.",
  },
  {
    title: "Separate Analysis from Execution",
    desc: "The platform keeps analysis, strategy construction and execution as distinct phases — so each decision can be evaluated on its own merits.",
  },
  {
    title: "Transparency over Prediction",
    desc: "The platform shows what the data says, not what it might mean. No guaranteed-profit claims, no accuracy scores, no prediction promises.",
  },
];

export default function AboutClientPage() {
  const isMobile = useIsMobile();

  return (
    <>
      {/* Hero */}
      <section style={{ paddingTop: 72, paddingBottom: 32, textAlign: "center" }}>
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: "0 20px" }}>
          <SectionHeading
            level={1}
            tag="ABOUT"
            title="Built Around a Simple Idea."
            sub="Better trading decisions start with better understanding of the market."
          />
        </div>
      </section>

      {/* Philosophy */}
      <section style={sectionPad(isMobile)}>
        <div style={{ maxWidth: 800, margin: "0 auto" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
            {PRINCIPLES.map((p) => (
              <div
                key={p.title}
                className="od-card"
                style={{
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 12,
                  padding: "22px 20px",
                }}
              >
                <div style={{ fontSize: 15.5, fontWeight: 700, color: C.gold, marginBottom: 8 }}>{p.title}</div>
                <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.65 }}>{p.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Main message */}
      <section style={{ borderTop: `1px solid ${C.border}`, background: "linear-gradient(180deg, rgba(18,22,31,0.5), rgba(11,14,20,0.2))" }}>
        <div style={sectionPad(isMobile)}>
          <div style={{ maxWidth: 640, margin: "0 auto", textAlign: "center" }}>
            <p style={{ fontSize: 16, color: C.muted, lineHeight: 1.75, margin: 0 }}>
              Our goal is to build tools that help traders investigate the options market
              systematically and make their own informed decisions. The platform provides
              the data, the analysis tools and the testing environment &mdash; the trading
              decisions are yours.
            </p>
          </div>
        </div>
      </section>

      {/* Core philosophy */}
      <section style={sectionPad(isMobile)}>
        <div style={{ maxWidth: 700, margin: "0 auto", textAlign: "center" }}>
          <SectionHeading
            tag="OUR APPROACH"
            title={<>Better trading decisions don&rsquo;t come from having more numbers.<br />They come from understanding what those numbers mean together.</>}
          />
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 16, marginTop: 32 }}>
            {[
              { title: "Data First", desc: "Every decision starts with market data, not opinions." },
              { title: "Risk First", desc: "Understand the risk before committing capital." },
              { title: "Structured Analysis", desc: "Separate observation from strategy from execution." },
              { title: "Transparency", desc: "No black-box claims. No hidden logic. No prediction promises." },
            ].map((p) => (
              <div
                key={p.title}
                className="od-card"
                style={{
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 12,
                  padding: "20px 18px",
                  textAlign: "left",
                }}
              >
                <div style={{ fontSize: 15, fontWeight: 700, color: C.gold, marginBottom: 6 }}>{p.title}</div>
                <div style={{ fontSize: 13.5, color: C.muted, lineHeight: 1.6 }}>{p.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <CTASection
        headline={<>Explore the <span style={{ color: C.gold }}>platform</span></>}
        primaryLabel="Get Started"
        primaryHref={loginUrl()}
        secondaryLabel="How It Works"
        secondaryHref="/how-it-works"
      />
    </>
  );
}
