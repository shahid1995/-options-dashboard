"use client";
import { C, useIsMobile, fmtIN } from "@/lib/ui";
import { SectionHeading, CTASection, PAGE_MAX, sectionPad, DEMO_LABEL_STYLE } from "@/components/public";

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
  { action: "SELL", strike: 25500, type: "CE", ltp: 142.35 },
  { action: "BUY", strike: 25700, type: "CE", ltp: 68.10 },
  { action: "SELL", strike: 25500, type: "PE", ltp: 138.80 },
  { action: "BUY", strike: 25300, type: "PE", ltp: 64.55 },
];

const GREEKS = [
  { label: "Delta", value: "-0.02", color: C.muted },
  { label: "Gamma", value: "0.0003", color: C.muted },
  { label: "Theta", value: "+42.15", color: C.green },
  { label: "Vega", value: "-18.40", color: C.red },
];

const WORKFLOW = [
  { num: "01", title: "BUILD", desc: "Select strategy template or add legs manually." },
  { num: "02", title: "ANALYZE", desc: "Review payoff curve, max profit, max loss and breakevens." },
  { num: "03", title: "STRESS TEST", desc: "Scenario and Greeks analysis under spot, IV and time shifts." },
  { num: "04", title: "PAPER TRADE", desc: "Execute the strategy in a simulated environment." },
  { num: "05", title: "REVIEW", desc: "Study execution, P&L and strategy performance over time." },
];

function PayoffChart() {
  const width = 600;
  const height = 200;
  const padding = { top: 20, right: 20, bottom: 30, left: 50 };
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

  // Clip rectangles: left loss zone, profit zone, right loss zone
  const leftClip = `${padding.left} ${padding.top} ${beLowX - padding.left} ${plotH}`;
  const profitClip = `${beLowX} ${padding.top} ${beHighX - beLowX} ${plotH}`;
  const rightClip = `${beHighX} ${padding.top} ${width - padding.right - beHighX} ${plotH}`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", maxWidth: width, height: "auto" }} role="img" aria-label="Iron Condor payoff at expiry chart showing profit and loss across strike prices">
      <defs>
        <clipPath id="payoff-left"><rect x={leftClip.split(" ")[0]} y={leftClip.split(" ")[1]} width={leftClip.split(" ")[2]} height={leftClip.split(" ")[3]} /></clipPath>
        <clipPath id="payoff-profit"><rect x={profitClip.split(" ")[0]} y={profitClip.split(" ")[1]} width={profitClip.split(" ")[2]} height={profitClip.split(" ")[3]} /></clipPath>
        <clipPath id="payoff-right"><rect x={rightClip.split(" ")[0]} y={rightClip.split(" ")[1]} width={rightClip.split(" ")[2]} height={rightClip.split(" ")[3]} /></clipPath>
      </defs>
      <line x1={padding.left} y1={zeroY} x2={width - padding.right} y2={zeroY} stroke={C.faint} strokeWidth={0.5} strokeDasharray="4 4" />
      <line x1={beLowX} y1={padding.top} x2={beLowX} y2={height - padding.bottom} stroke={C.gold} strokeWidth={0.8} strokeDasharray="3 3" opacity={0.5} />
      <line x1={beHighX} y1={padding.top} x2={beHighX} y2={height - padding.bottom} stroke={C.gold} strokeWidth={0.8} strokeDasharray="3 3" opacity={0.5} />
      <path d={`${pathD} L${points[points.length - 1].x},${zeroY} L${points[0].x},${zeroY} Z`} fill="rgba(225,82,82,0.12)" clipPath="url(#payoff-left)" />
      <path d={`${pathD} L${points[points.length - 1].x},${zeroY} L${points[0].x},${zeroY} Z`} fill="rgba(76,175,125,0.12)" clipPath="url(#payoff-profit)" />
      <path d={`${pathD} L${points[points.length - 1].x},${zeroY} L${points[0].x},${zeroY} Z`} fill="rgba(225,82,82,0.12)" clipPath="url(#payoff-right)" />
      <path d={pathD} fill="none" stroke={C.gold} strokeWidth={2} strokeLinejoin="round" />
      <text x={padding.left} y={height - 6} fill={C.faint} fontSize={10}>{fmtIN(minStrike)}</text>
      <text x={width - padding.right} y={height - 6} fill={C.faint} fontSize={10} textAnchor="end">{fmtIN(maxStrike)}</text>
      <text x={padding.left - 4} y={padding.top + 4} fill={C.faint} fontSize={10} textAnchor="end">{fmtIN(maxPnl)}</text>
      <text x={padding.left - 4} y={height - padding.bottom + 4} fill={C.faint} fontSize={10} textAnchor="end">{fmtIN(minPnl)}</text>
    </svg>
  );
}

export default function StrategyLabClientPage() {
  const isMobile = useIsMobile();

  return (
    <>
      {/* Hero */}
      <section style={{ paddingTop: 72, paddingBottom: 32, textAlign: "center" }}>
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: "0 20px" }}>
          <SectionHeading
            level={1}
            tag="STRATEGY LAB"
            title="Build the Strategy. See the Risk. Test the Outcome."
            sub="A strategy should not be judged only by its entry price. Understand payoff, max profit, max loss, breakevens, Greeks, price scenarios, volatility scenarios and time decay — before committing capital."
          />
        </div>
      </section>

      {/* Demo Strategy */}
      <section style={sectionPad(isMobile)}>
        <div style={{ maxWidth: 900, margin: "0 auto" }}>
          <div style={DEMO_LABEL_STYLE}>DEMO DATA &middot; ILLUSTRATIVE VALUES ONLY</div>

          {/* Strategy header */}
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20, flexWrap: "wrap" }}>
            <h3 style={{ fontSize: 18, fontWeight: 800, color: C.gold, margin: 0 }}>IRON CONDOR</h3>
            <span style={{ fontSize: 13, color: C.muted }}>NIFTY &middot; 25,500 Straddle &middot; 200pt Wings</span>
          </div>

          {/* Legs table */}
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, overflow: isMobile ? "auto" : "hidden", marginBottom: 24 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ color: C.faint, fontSize: 11, letterSpacing: 1 }}>
                  <th scope="col" style={{ padding: "10px 16px", textAlign: "left" }}>ACTION</th>
                  <th scope="col" style={{ padding: "10px 16px" }}>STRIKE</th>
                  <th scope="col" style={{ padding: "10px 16px" }}>TYPE</th>
                  <th scope="col" style={{ padding: "10px 16px", textAlign: "right" }}>LTP</th>
                </tr>
              </thead>
              <tbody>
                {LEGS.map((leg, i) => (
                  <tr key={i} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: "10px 16px" }}>
                      <span
                        style={{
                          display: "inline-block",
                          fontSize: 10.5,
                          fontWeight: 700,
                          padding: "2px 8px",
                          borderRadius: 4,
                          background: leg.action === "SELL" ? "rgba(225,82,82,0.15)" : "rgba(76,175,125,0.15)",
                          color: leg.action === "SELL" ? C.red : C.green,
                          border: `1px solid ${leg.action === "SELL" ? "rgba(225,82,82,0.3)" : "rgba(76,175,125,0.3)"}`,
                        }}
                      >
                        {leg.action}
                      </span>
                    </td>
                    <td style={{ padding: "10px 16px", textAlign: "center", fontWeight: 700 }}>{fmtIN(leg.strike)}</td>
                    <td style={{ padding: "10px 16px", textAlign: "center", color: leg.type === "CE" ? C.green : C.red }}>{leg.type}</td>
                    <td style={{ padding: "10px 16px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{leg.ltp.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Metrics */}
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 14, marginBottom: 24 }}>
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 18px", textAlign: "center" }}>
              <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>MAX PROFIT</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: C.green }}>+&#x20B9;{fmtIN(MAX_PROFIT)}</div>
            </div>
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 18px", textAlign: "center" }}>
              <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>MAX LOSS</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: C.red }}>&#x20B9;{fmtIN(MAX_LOSS)}</div>
            </div>
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 18px", textAlign: "center" }}>
              <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>BREAKEVEN LOW</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: C.gold }}>{fmtIN(BREAKEVEN_LOW)}</div>
            </div>
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: "16px 18px", textAlign: "center" }}>
              <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>BREAKEVEN HIGH</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: C.gold }}>{fmtIN(BREAKEVEN_HIGH)}</div>
            </div>
          </div>

          {/* Payoff chart */}
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "24px 20px", marginBottom: 24 }}>
            <div style={{ fontSize: 11.5, letterSpacing: 1, color: C.faint, marginBottom: 14 }}>PAYOFF AT EXPIRY</div>
            <div style={{ display: "flex", justifyContent: "center", overflow: "hidden" }}>
              <PayoffChart />
            </div>
          </div>

          {/* Greeks */}
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "18px 20px" }}>
            <div style={{ fontSize: 11.5, letterSpacing: 1, color: C.faint, marginBottom: 14 }}>POSITION GREEKS</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, textAlign: "center" }}>
              {GREEKS.map((g) => (
                <div key={g.label}>
                  <div style={{ fontSize: 11, letterSpacing: 1, color: C.faint, marginBottom: 4 }}>{g.label}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: g.color }}>{g.value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Workflow */}
      <section style={{ borderTop: `1px solid ${C.border}`, background: "linear-gradient(180deg, rgba(18,22,31,0.5), rgba(11,14,20,0.2))" }}>
        <div style={sectionPad(isMobile)}>
          <SectionHeading tag="WORKFLOW" title="From idea to reviewed trade" />
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: isMobile ? 12 : 16, maxWidth: 900, margin: "0 auto" }}>
            {WORKFLOW.map((step, i) => (
              <div key={step.num} style={{ display: "flex", alignItems: "center", gap: isMobile ? 8 : 12 }}>
                <div className="od-card" style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "20px 18px", width: isMobile ? "calc(50% - 6px)" : 150, textAlign: "center" }}>
                  <div style={{ fontSize: 10, letterSpacing: 1.5, color: C.gold, marginBottom: 6 }}>{step.num}</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 6 }}>{step.title}</div>
                  <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.5 }}>{step.desc}</div>
                </div>
                {i < WORKFLOW.length - 1 && !isMobile && (
                  <span style={{ color: C.faint, fontSize: 18 }}>&rarr;</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <CTASection
        headline={<>Open the <span style={{ color: C.gold }}>Strategy Lab</span></>}
        body="Build, analyze, stress-test and paper-trade strategies with the full platform."
        primaryLabel="Try Paper Trading"
        primaryHref="/paper-trading"
        secondaryLabel="Explore the Platform"
        secondaryHref="/features"
      />
    </>
  );
}
