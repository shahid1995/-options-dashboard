"use client";
import { C, useIsMobile } from "@/lib/ui";
import { loginUrl } from "@/lib/api";
import { SectionHeading, FeatureCard, CTASection, PAGE_MAX, sectionPad, DEMO_LABEL_STYLE } from "@/components/public";

const CAPABILITIES = [
  { icon: "\u229E", title: "Simulated Orders", desc: "Place paper orders that are filled at market prices without touching a real broker." },
  { icon: "\u25B3", title: "Positions", desc: "Track open positions with real-time P&L and mark-to-market valuation." },
  { icon: "\u00B1", title: "P&L Tracking", desc: "Realized and unrealized profit/loss at account, strategy and position levels." },
  { icon: "\u26A0", title: "Risk Monitoring", desc: "View capital utilization, margin estimates and strategy-level risk profiles." },
  { icon: "\u2261", title: "Strategy Performance", desc: "Per-strategy win rates, returns and trade counts over time." },
  { icon: "\u23F0", title: "Trade History", desc: "Full journal of closed trades with entry/exit details and CSV export." },
];

export default function PaperTradingClientPage() {
  const isMobile = useIsMobile();

  return (
    <>
      {/* Hero */}
      <section style={{ paddingTop: 72, paddingBottom: 32, textAlign: "center" }}>
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: "0 20px" }}>
          <SectionHeading
            level={1}
            tag="PAPER TRADING"
            title="Practice the Workflow. Not Your Capital."
            sub="Paper trading allows you to test strategies and execution decisions with simulated capital before committing real money."
          />
        </div>
      </section>

      {/* Conceptual Workflow */}
      <section style={sectionPad(isMobile)}>
        <div style={{ maxWidth: 640, margin: "0 auto" }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
            {[
              { label: "REAL MARKET DATA", color: C.text },
              { label: "YOUR STRATEGY", color: C.text },
              { label: "PAPER EXECUTION", color: C.gold },
              { label: "POSITION MANAGEMENT", color: C.text },
              { label: "PERFORMANCE REVIEW", color: C.text },
            ].map((step, i, arr) => (
              <div key={step.label} style={{ display: "flex", flexDirection: "column", alignItems: "center", width: "100%" }}>
                <div
                  style={{
                    background: step.color === C.gold ? "rgba(201,161,90,0.08)" : C.surface,
                    border: `1px solid ${step.color === C.gold ? "rgba(201,161,90,0.3)" : C.border}`,
                    borderRadius: 10,
                    padding: "12px 28px",
                    fontSize: 14,
                    fontWeight: 600,
                    color: step.color,
                    textAlign: "center",
                    width: isMobile ? "100%" : 280,
                  }}
                >
                  {step.label}
                </div>
                {i < arr.length - 1 && (
                  <div style={{ color: C.faint, fontSize: 16, padding: "6px 0" }}>&darr;</div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Demo Dashboard */}
      <section style={sectionPad(isMobile)}>
        <div style={{ maxWidth: 700, margin: "0 auto" }}>
          <div style={DEMO_LABEL_STYLE}>DEMO DATA &middot; ILLUSTRATIVE VALUES ONLY</div>

          {/* Metrics */}
          <div
            style={{
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: 14,
              padding: isMobile ? "24px 18px" : "32px 28px",
              marginBottom: 24,
            }}
          >
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 24, textAlign: "center" }}>
              <div>
                <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>SIMULATED CAPITAL</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: C.gold }}>&#x20B9;5,00,000</div>
              </div>
              <div>
                <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>TODAY&apos;S P&L</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: C.green }}>+&#x20B9;4,820</div>
              </div>
              <div>
                <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>OPEN POSITIONS</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: C.text }}>4</div>
              </div>
              <div>
                <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>WIN RATE</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: C.gold }}>68%</div>
              </div>
            </div>
          </div>

          {/* Illustrative positions */}
          <div
            style={{
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: 12,
              overflow: "hidden",
              marginBottom: 24,
            }}
          >
            <div style={{ padding: "12px 18px", borderBottom: `1px solid ${C.border}`, fontSize: 11.5, letterSpacing: 1, color: C.faint }}>
              SAMPLE POSITIONS
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ color: C.faint, fontSize: 11, letterSpacing: 0.5 }}>
                  <th scope="col" style={{ padding: "8px 16px", textAlign: "left" }}>STRATEGY</th>
                  <th scope="col" style={{ padding: "8px 16px" }}>LEG</th>
                  <th scope="col" style={{ padding: "8px 16px" }}>ACTION</th>
                  <th scope="col" style={{ padding: "8px 16px", textAlign: "right" }}>P&L</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { strategy: "Iron Condor", leg: "NIFTY 25500 CE", action: "SELL", pnl: "+1,840", color: C.green },
                  { strategy: "Iron Condor", leg: "NIFTY 25700 CE", action: "BUY", pnl: "-320", color: C.red },
                  { strategy: "Bull Put Spread", leg: "BANKNIFTY 54000 PE", action: "SELL", pnl: "+2,450", color: C.green },
                  { strategy: "Bull Put Spread", leg: "BANKNIFTY 53500 PE", action: "BUY", pnl: "-850", color: C.red },
                ].map((row, i) => (
                  <tr key={i} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: "10px 16px", fontSize: 13 }}>{row.strategy}</td>
                    <td style={{ padding: "10px 16px", textAlign: "center", fontSize: 13 }}>{row.leg}</td>
                    <td style={{ padding: "10px 16px", textAlign: "center" }}>
                      <span
                        style={{
                          fontSize: 10.5,
                          fontWeight: 700,
                          padding: "2px 8px",
                          borderRadius: 4,
                          background: row.action === "SELL" ? "rgba(225,82,82,0.15)" : "rgba(76,175,125,0.15)",
                          color: row.action === "SELL" ? C.red : C.green,
                        }}
                      >
                        {row.action}
                      </span>
                    </td>
                    <td style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: row.color, fontVariantNumeric: "tabular-nums" }}>&#x20B9;{row.pnl}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section style={{ borderTop: `1px solid ${C.border}`, background: "linear-gradient(180deg, rgba(18,22,31,0.5), rgba(11,14,20,0.2))" }}>
        <div style={sectionPad(isMobile)}>
          <SectionHeading
            tag="CAPABILITIES"
            title="What paper trading includes"
            sub="A complete simulated trading environment that mirrors real market conditions without placing actual broker orders."
          />
          <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
            {CAPABILITIES.map((f) => (
              <FeatureCard key={f.title} icon={f.icon} title={f.title} desc={f.desc} />
            ))}
          </div>
        </div>
      </section>

      {/* Disclaimer */}
      <section style={sectionPad(isMobile)}>
        <div
          style={{
            maxWidth: 700,
            margin: "0 auto",
            padding: "24px 24px",
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            background: "rgba(18, 22, 31, 0.5)",
          }}
        >
          <div style={{ fontSize: 11.5, letterSpacing: 1, color: C.faint, marginBottom: 10 }}>IMPORTANT DISCLAIMER</div>
          <p style={{ fontSize: 14, color: C.muted, lineHeight: 1.7, margin: 0 }}>
            Paper trading is simulated. It does not represent actual execution or guarantee future trading results.
            No real broker orders are placed. Past paper-trading performance is not indicative of real trading outcomes.
          </p>
        </div>
      </section>

      {/* CTA */}
      <CTASection
        headline={<>Start <span style={{ color: C.gold }}>paper trading</span> today</>}
        body="Test your strategies with simulated capital before committing real money."
        primaryLabel="Get Started"
        primaryHref={loginUrl()}
        secondaryLabel="Build a Strategy"
        secondaryHref="/strategy-lab"
      />
    </>
  );
}
