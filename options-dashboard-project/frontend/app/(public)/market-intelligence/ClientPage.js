"use client";
import { C, useIsMobile, fmtIN } from "@/lib/ui";
import { SectionHeading, FeatureCard, CTASection, PAGE_MAX, sectionPad, DEMO_LABEL_STYLE } from "@/components/public";

const DIMENSIONS = [
  { label: "PRICE", desc: "Spot, LTP across strikes and the current market level." },
  { label: "OI", desc: "Open interest on both sides, total and per-strike." },
  { label: "OI CHANGE", desc: "How positions shifted during the session." },
  { label: "VOLUME", desc: "Contract volume across strikes and expiries." },
  { label: "IV", desc: "Implied volatility at each strike and the ATM level." },
  { label: "GREEKS", desc: "Delta, gamma, theta and vega for every option." },
  { label: "VOLATILITY", desc: "IV skew, term structure and ATM IV trends." },
  { label: "MARKET STRUCTURE", desc: "Resistance, support and pivot levels from the chain." },
];

const FUTURE_RESEARCH = [
  { title: "GEX / Gamma Exposure", desc: "Gamma exposure analysis to understand market-maker hedging flows and their impact on price movements." },
  { title: "OI Migration", desc: "Track how open interest shifts across strikes over time to identify conviction levels." },
  { title: "Unusual Activity", desc: "Detect abnormally large OI or volume changes that may indicate institutional positioning." },
  { title: "Statistical Signals", desc: "Derive signals from OI, volume and volatility patterns using statistical methods." },
];

function BarDemo({ label, value, max, color }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontSize: 11.5, color: C.muted }}>{label}</span>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: C.text, fontVariantNumeric: "tabular-nums" }}>{fmtIN(value)}</span>
      </div>
      <div style={{ height: 8, background: "rgba(36,43,58,0.8)", borderRadius: 4, overflow: "hidden" }}>
        <div className="od-bar-fill" style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 4 }} />
      </div>
    </div>
  );
}

export default function MarketIntelligenceClientPage() {
  const isMobile = useIsMobile();

  return (
    <>
      {/* Hero */}
      <section style={{ paddingTop: 72, paddingBottom: 32, textAlign: "center" }}>
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: "0 20px" }}>
          <SectionHeading
            level={1}
            tag="MARKET INTELLIGENCE"
            title="See the Market Behind the Option Chain."
            sub="Combine price, positioning, volume, volatility and Greeks to build a more complete view of the options market."
          />
        </div>
      </section>

      {/* Dimensions */}
      <section style={sectionPad(isMobile)}>
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
            {DIMENSIONS.map((d) => (
              <div
                key={d.label}
                className="od-card"
                style={{
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 10,
                  padding: "16px 14px",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: C.gold, marginBottom: 6 }}>{d.label}</div>
                <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.5 }}>{d.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Demo Visualizations */}
      <section style={{ borderTop: `1px solid ${C.border}`, background: "linear-gradient(180deg, rgba(18,22,31,0.5), rgba(11,14,20,0.2))" }}>
        <div style={sectionPad(isMobile)}>
          <div style={{ maxWidth: PAGE_MAX, margin: "0 auto" }}>
            <div style={DEMO_LABEL_STYLE}>DEMO DATA &middot; ILLUSTRATIVE VALUES ONLY</div>

            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 20, marginBottom: 40 }}>
              {/* Positioning card */}
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "22px 20px" }}>
                <div style={{ fontSize: 11.5, letterSpacing: 1, color: C.faint, marginBottom: 16, fontWeight: 600 }}>POSITIONING</div>
                <BarDemo label="CALL OI" value={184250} max={210000} color={C.red} />
                <BarDemo label="PUT OI" value={217800} max={210000} color={C.green} />
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12, padding: "10px 0", borderTop: `1px solid ${C.border}` }}>
                  <span style={{ fontSize: 11, color: C.muted }}>PCR (OI)</span>
                  <span style={{ fontSize: 16, fontWeight: 800, color: C.green }}>1.18</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
                  <span style={{ fontSize: 11, color: C.muted }}>OI Shift</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: C.green }}>+12,400 PE &rarr;</span>
                </div>
              </div>

              {/* Volatility card */}
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "22px 20px" }}>
                <div style={{ fontSize: 11.5, letterSpacing: 1, color: C.faint, marginBottom: 16, fontWeight: 600 }}>VOLATILITY</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, textAlign: "center" }}>
                  <div>
                    <div style={{ fontSize: 11, letterSpacing: 1, color: C.faint, marginBottom: 4 }}>ATM IV</div>
                    <div style={{ fontSize: 20, fontWeight: 800, color: C.gold }}>14.2%</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, letterSpacing: 1, color: C.faint, marginBottom: 4 }}>VIX</div>
                    <div style={{ fontSize: 20, fontWeight: 800, color: C.text }}>13.8</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, letterSpacing: 1, color: C.faint, marginBottom: 4 }}>VEGA</div>
                    <div style={{ fontSize: 20, fontWeight: 800, color: C.red }}>-18.4</div>
                  </div>
                </div>
              </div>

              {/* Greeks card */}
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "22px 20px" }}>
                <div style={{ fontSize: 11.5, letterSpacing: 1, color: C.faint, marginBottom: 16, fontWeight: 600 }}>GREEKS (ATM)</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  {[
                    { label: "DELTA", value: "0.52", color: C.text },
                    { label: "GAMMA", value: "0.0018", color: C.text },
                    { label: "THETA", value: "-42.15", color: C.red },
                    { label: "VEGA", value: "18.40", color: C.green },
                  ].map((g) => (
                    <div key={g.label} style={{ textAlign: "center" }}>
                      <div style={{ fontSize: 11, letterSpacing: 1, color: C.faint, marginBottom: 4 }}>{g.label}</div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: g.color }}>{g.value}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Market Structure card */}
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "22px 20px" }}>
                <div style={{ fontSize: 11.5, letterSpacing: 1, color: C.faint, marginBottom: 16, fontWeight: 600 }}>MARKET STRUCTURE</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 12, color: C.muted }}>Resistance</span>
                    <span style={{ fontSize: 16, fontWeight: 700, color: C.red }}>{fmtIN(25700)}</span>
                  </div>
                  <div style={{ height: 1, background: C.border }} />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 12, color: C.muted }}>Pivot</span>
                    <span style={{ fontSize: 16, fontWeight: 700, color: C.gold }}>{fmtIN(25500)}</span>
                  </div>
                  <div style={{ height: 1, background: C.border }} />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 12, color: C.muted }}>Support</span>
                    <span style={{ fontSize: 16, fontWeight: 700, color: C.green }}>{fmtIN(25300)}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Future research section */}
            <div style={{ marginTop: 20 }}>
              <div
                style={{
                  fontSize: 13,
                  letterSpacing: 1,
                  color: C.muted,
                  marginBottom: 14,
                  fontStyle: "normal",
                }}
              >
                RESEARCH DIRECTION &middot; FUTURE CAPABILITIES
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 14 }}>
                {FUTURE_RESEARCH.map((r) => (
                  <div
                    key={r.title}
                    style={{
                      background: "rgba(18, 22, 31, 0.5)",
                      border: `1px dashed ${C.border}`,
                      borderRadius: 12,
                      padding: "20px 18px",
                    }}
                  >
                    <div style={{ fontSize: 14, fontWeight: 700, color: C.muted, marginBottom: 6 }}>{r.title}</div>
                    <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.6 }}>{r.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <CTASection
        headline={<>Investigate the market <span style={{ color: C.gold }}>systematically.</span></>}
        primaryLabel="Build a Strategy"
        primaryHref="/strategy-lab"
        secondaryLabel="Explore the Platform"
        secondaryHref="/features"
      />
    </>
  );
}
