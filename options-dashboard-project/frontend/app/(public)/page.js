"use client";
import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { C, SYMBOLS, LOT_SIZES, fmtIN, useIsMobile } from "@/lib/ui";
import { SectionHeading, CTASection, PAGE_MAX, sectionPad } from "@/components/public";
import { useAuthModal } from "@/components/public/AuthModalContext";

// ──────────────────────────────────────────────────────────────────────────────
// Mock data (clearly decorative — not live)
// ──────────────────────────────────────────────────────────────────────────────

const MOCK_BASE = {
  NIFTY: 25512, BANKNIFTY: 54680, FINNIFTY: 26175, MIDCPNIFTY: 13340,
  NIFTYNXT50: 79240, SENSEX: 82960, BANKEX: 61850, SENSEX50: 17820,
};
const MOCK_STEP = {
  NIFTY: 100, BANKNIFTY: 250, FINNIFTY: 100, MIDCPNIFTY: 100,
  NIFTYNXT50: 250, SENSEX: 100, BANKEX: 250, SENSEX50: 50,
};
const INDEX_NAMES = {
  NIFTY: "Nifty 50", BANKNIFTY: "Bank Nifty", FINNIFTY: "Financial Services Nifty",
  MIDCPNIFTY: "Nifty Midcap Select", NIFTYNXT50: "Nifty Next 50",
  SENSEX: "BSE Sensex", BANKEX: "BSE Bankex", SENSEX50: "BSE Sensex 50",
};
const EXCHANGES = {
  NIFTY: "NSE", BANKNIFTY: "NSE", FINNIFTY: "NSE", MIDCPNIFTY: "NSE",
  NIFTYNXT50: "NSE", SENSEX: "BSE", BANKEX: "BSE", SENSEX50: "BSE",
};

const PLATFORM_PILLARS = [
  { num: "01", icon: "\u25C8", title: "Market Intelligence", desc: "Understand positioning, volatility, Greeks and market structure instead of looking at isolated numbers.", href: "/market-intelligence" },
  { num: "02", icon: "\u221A", title: "Strategy Lab", desc: "Build multi-leg option strategies and understand their payoff, Greeks and risk before committing capital.", href: "/strategy-lab" },
  { num: "03", icon: "\u25B3", title: "Paper Trading", desc: "Practice the complete trading workflow without risking real capital.", href: "/paper-trading" },
  { num: "04", icon: "\u223F", title: "Analytics", desc: "Review trades, outcomes and performance to identify what is working and what needs improvement.", href: "/features#analytics" },
];

const WORKFLOW_STEPS = [
  { num: "01", title: "Observe", desc: "Price, option chain, OI, volume, IV and Greeks." },
  { num: "02", title: "Analyze", desc: "Positioning, volatility and market structure." },
  { num: "03", title: "Build", desc: "Construct a strategy around the market view." },
  { num: "04", title: "Test", desc: "Payoff, risk, Greeks and scenarios." },
  { num: "05", title: "Review", desc: "Study the result, execution and risk." },
];

// ──────────────────────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────────────────────

function MockChain() {
  const [state, setState] = useState({ idx: 0, spot: MOCK_BASE.NIFTY, prevSpot: MOCK_BASE.NIFTY });

  useEffect(() => {
    const t = setInterval(() => {
      setState((prev) => {
        const idx = (prev.idx + 1) % SYMBOLS.length;
        const sym = SYMBOLS[idx];
        const drift = (Math.random() - 0.5) * MOCK_STEP[sym] * 1.3;
        return { idx, spot: MOCK_BASE[sym] + drift, prevSpot: prev.spot };
      });
    }, 2600);
    return () => clearInterval(t);
  }, []);

  const sym = SYMBOLS[state.idx];
  const atm = Math.round(state.spot / MOCK_STEP[sym]) * MOCK_STEP[sym];
  const chgPct = state.prevSpot ? ((state.spot - state.prevSpot) / state.prevSpot) * 100 : 0;
  const up = chgPct >= 0;

  const rows = [];
  for (let i = -3; i <= 3; i++) {
    const strike = atm + i * MOCK_STEP[sym];
    const callLtp = Math.max(0, state.spot - strike) + 38 + ((strike / MOCK_STEP[sym]) % 5) * 7;
    const putLtp = Math.max(0, strike - state.spot) + 34 + ((strike / MOCK_STEP[sym] + 2) % 5) * 6;
    const callOi = ((strike / MOCK_STEP[sym]) % 7) / 6;
    const putOi = ((strike / MOCK_STEP[sym] + 3) % 7) / 6;
    rows.push({ strike, callLtp, putLtp, callOi, putOi, atm: strike === atm });
  }

  return (
    <div
      className="od-card"
      style={{
        width: "100%", maxWidth: 430,
        background: "linear-gradient(180deg, rgba(23, 28, 39, 0.9), rgba(18, 22, 31, 0.95))",
        border: `1px solid ${C.border}`,
        borderRadius: 14,
        boxShadow: "0 24px 60px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(201, 161, 90, 0.06)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 4, background: C.green, boxShadow: "0 0 8px rgba(76,175,125,0.9)", animation: "od-glow 2s ease-in-out infinite" }} />
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: 0.5 }}>{sym}</span>
          <span style={{ fontSize: 11, color: C.faint, letterSpacing: 1 }}>{EXCHANGES[sym]} INDEX</span>
        </div>
        <div style={{ fontSize: 11, color: C.muted, display: "flex", alignItems: "center", gap: 6 }}>
          <span className="od-pulse" style={{ color: C.green, fontSize: 10 }}>&#9679;</span> LIVE
        </div>
      </div>

      {/* Spot */}
      <div style={{ padding: "10px 16px", display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: `1px solid ${C.border}` }}>
        <div>
          <div style={{ fontSize: 11, color: C.faint, letterSpacing: 1 }}>SPOT</div>
          <div style={{ fontSize: 21, fontWeight: 800, color: C.gold }}>{fmtIN(state.spot, 2)}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: up ? C.green : C.red }}>
            {up ? "\u25B2" : "\u25BC"} {up ? "+" : ""}{chgPct.toFixed(2)}%
          </div>
          <div style={{ fontSize: 11, color: C.faint }}>vs previous tick</div>
        </div>
      </div>

      {/* Chain table */}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
        <thead>
          <tr style={{ color: C.faint, fontSize: 10.5, letterSpacing: 0.5 }}>
            <th scope="col" style={{ padding: "7px 16px", textAlign: "left" }}>CALLS</th>
            <th scope="col" style={{ padding: 7, textAlign: "center", color: C.gold }}>STRIKE</th>
            <th scope="col" style={{ padding: "7px 16px", textAlign: "right" }}>PUTS</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.strike} style={{ borderTop: `1px solid ${C.border}`, background: r.atm ? "rgba(201,161,90,0.07)" : "transparent" }}>
              <td style={{ padding: "5px 16px", position: "relative" }}>
                <div style={{ position: "absolute", top: 1, bottom: 1, right: 0, width: `${r.callOi * 100}%`, background: "rgba(225,82,82,0.16)", borderRadius: 2 }} />
                <span style={{ position: "relative", color: r.strike < state.spot ? C.green : C.muted, fontWeight: r.strike < state.spot ? 600 : 400 }}>{fmtIN(r.callLtp, 2)}</span>
              </td>
              <td style={{ padding: "5px 7px", textAlign: "center", fontWeight: 700, color: r.atm ? C.gold : C.text }}>{fmtIN(r.strike)}</td>
              <td style={{ padding: "5px 16px", textAlign: "right", position: "relative" }}>
                <div style={{ position: "absolute", top: 1, bottom: 1, left: 0, width: `${r.putOi * 100}%`, background: "rgba(76,175,125,0.16)", borderRadius: 2 }} />
                <span style={{ position: "relative", color: r.strike > state.spot ? C.red : C.muted, fontWeight: r.strike > state.spot ? 600 : 400 }}>{fmtIN(r.putLtp, 2)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Footer */}
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "10px 16px", borderTop: `1px solid ${C.border}`, fontSize: 11, color: C.muted }}>
        <span>MAX PAIN <span style={{ color: C.gold, fontWeight: 700 }}>{fmtIN(atm)}</span></span>
        <span>PCR (OI) <span style={{ color: C.text, fontWeight: 700 }}>1.08</span></span>
        <span>SESSION <span style={{ color: C.green, fontWeight: 700 }}>OPEN</span></span>
      </div>
    </div>
  );
}

function TickerTape() {
  const items = [...SYMBOLS, ...SYMBOLS].map((sym, i) => ({
    sym,
    lot: LOT_SIZES[sym],
    val: MOCK_BASE[sym] + (i % 2 === 0 ? 14 : -9),
    key: `${sym}-${i}`,
  }));
  return (
    <div style={{ borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}`, background: "rgba(18,22,31,0.6)", overflow: "hidden" }}>
      <div className="od-ticker-track">
        {items.map((it) => (
          <span key={it.key} style={{ display: "inline-flex", alignItems: "baseline", gap: 8, padding: "9px 22px", fontSize: 12, whiteSpace: "nowrap" }}>
            <span style={{ color: C.text, fontWeight: 700, letterSpacing: 0.5 }}>{it.sym}</span>
            <span style={{ color: C.gold, fontVariantNumeric: "tabular-nums" }}>{fmtIN(it.val, 2)}</span>
            <span style={{ color: C.faint, fontSize: 11 }}>LOT {it.lot}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Login error banner (reads ?login_error from URL)
// ──────────────────────────────────────────────────────────────────────────────

function LoginErrorBannerInner() {
  const params = useSearchParams();
  const error = params.get("login_error");
  if (!error) return null;
  return (
    <div
      className="od-fade"
      style={{
        maxWidth: 540,
        marginBottom: 18,
        fontSize: 13,
        color: C.red,
        border: `1px solid ${C.red}`,
        borderRadius: 8,
        padding: "8px 14px",
        background: "rgba(225,82,82,0.08)",
      }}
    >
      Login failed: {error}. Please try again.
    </div>
  );
}

function LoginErrorBanner() {
  return (
    <Suspense fallback={null}>
      <LoginErrorBannerInner />
    </Suspense>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────────────

export default function HomePage() {
  const isMobile = useIsMobile();
  const { open: openAuth } = useAuthModal();

  return (
    <>
      {/* ── 1. HERO ─────────────────────────────────────────────────────── */}
      <header style={{ position: "relative", overflow: "hidden" }}>
        <div
          style={{
            position: "absolute", inset: 0,
            background:
              "radial-gradient(ellipse 60% 50% at 28% 12%, rgba(201,161,90,0.14), transparent 60%), radial-gradient(ellipse 40% 40% at 82% 70%, rgba(76,175,125,0.06), transparent 60%), repeating-linear-gradient(0deg, rgba(201,161,90,0.025) 0 1px, transparent 1px 46px), repeating-linear-gradient(90deg, rgba(201,161,90,0.025) 0 1px, transparent 1px 46px)",
            pointerEvents: "none",
          }}
        />
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: isMobile ? "64px 20px" : "96px 20px 84px", display: "flex", alignItems: "center", gap: 56, flexWrap: "wrap", position: "relative" }}>
          <div style={{ flex: "1 1 400px", minWidth: 0 }}>
            <h1
              className="od-fade"
              style={{
                margin: "0 0 18px",
                fontSize: isMobile ? 36 : 54,
                lineHeight: 1.08,
                letterSpacing: -1.5,
                fontWeight: 800,
              }}
            >
              From Market Data to
              <br />
              Structured Decisions.
            </h1>

            <p
              className="od-fade"
              style={{
                color: C.muted,
                fontSize: 16,
                lineHeight: 1.7,
                maxWidth: 540,
                margin: "0 0 28px",
                animationDelay: "0.12s",
              }}
            >
              Analyze the options market. Build strategies. Understand risk.
              Test and practice — all in one workflow.
            </p>

            <LoginErrorBanner />

            <div className="od-fade" style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 34, animationDelay: "0.2s" }}>
              <a className="od-btn-gold" href="/features">
                Explore the Platform <span aria-hidden>&rarr;</span>
              </a>
              <button onClick={openAuth} className="od-btn-ghost" data-testid="hero-get-started-btn">
                Start Paper Trading
              </button>
            </div>
          </div>

          <div className="od-fade" style={{ animationDelay: "0.18s", flex: "0 1 460px", display: "flex", justifyContent: "center" }}>
            <MockChain />
          </div>
        </div>
      </header>

      <TickerTape />

      {/* ── 2. THE PROBLEM ──────────────────────────────────────────────── */}
      <section style={sectionPad(isMobile)}>
        <SectionHeading
          tag="THE PROBLEM"
          title={<>The problem isn&rsquo;t lack of market data.<br />It&rsquo;s knowing what to do with it.</>}
          sub="Traders have access to price, open interest, volume, IV, Greeks and volatility. The challenge is turning those data points into a coherent decision."
        />
        {/* Data inputs converging into a decision */}
        <div style={{ maxWidth: 700, margin: "0 auto", position: "relative" }}>
          {/* Left column — raw data inputs */}
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr 1fr" : "1fr 1fr 1fr", gap: 10, marginBottom: 20 }}>
            {["Option Chain", "OI", "OI Change", "Volume", "IV", "Greeks"].map((item) => (
              <div
                key={item}
                style={{
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  padding: "10px 14px",
                  fontSize: 13,
                  fontWeight: 600,
                  color: C.muted,
                  textAlign: "center",
                }}
              >
                {item}
              </div>
            ))}
          </div>

          {/* Convergence arrows */}
          <div style={{ textAlign: "center", color: C.faint, fontSize: 20, padding: "8px 0" }}>
            &darr;
          </div>

          {/* Middle — analysis */}
          <div style={{ display: "flex", justifyContent: "center", gap: isMobile ? 10 : 20, marginBottom: 20, flexWrap: "wrap" }}>
            {['Price', 'Strategy'].map((item) => (
              <div
                key={item}
                style={{
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  padding: "10px 24px",
                  fontSize: 13,
                  fontWeight: 600,
                  color: C.text,
                  textAlign: "center",
                }}
              >
                {item}
              </div>
            ))}
          </div>

          {/* Convergence arrows */}
          <div style={{ textAlign: "center", color: C.faint, fontSize: 20, padding: "8px 0" }}>
            &darr;
          </div>

          {/* Bottom — the decision point */}
          <div style={{ display: "flex", justifyContent: "center" }}>
            <div
              style={{
                background: "rgba(201,161,90,0.08)",
                border: `1px solid rgba(201,161,90,0.3)`,
                borderRadius: 12,
                padding: "16px 40px",
                fontSize: 16,
                fontWeight: 700,
                color: C.gold,
                textAlign: "center",
                letterSpacing: 1,
              }}
            >
              RISK
            </div>
          </div>
        </div>
      </section>

      {/* ── 3. THE PLATFORM ─────────────────────────────────────────────── */}
      <section style={{ borderTop: `1px solid ${C.border}`, background: "linear-gradient(180deg, rgba(18,22,31,0.5), rgba(11,14,20,0.2))" }}>
        <div style={sectionPad(isMobile)}>
          <SectionHeading
            tag="THE PLATFORM"
            title="Four pillars of structured trading"
            sub="Each capability builds on the previous one. Together they form a complete workflow from observation to review."
          />
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 16, maxWidth: 800, margin: "0 auto" }}>
            {PLATFORM_PILLARS.map((pillar) => (
              <a
                key={pillar.num}
                href={pillar.href}
                className="od-card"
                style={{
                  display: "block",
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 12,
                  padding: "28px 24px",
                  textDecoration: "none",
                  transition: "border-color 0.2s",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.gold; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.border; }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                  <span style={{ fontSize: 11, letterSpacing: 1.5, color: C.gold, fontWeight: 700 }}>{pillar.num}</span>
                  <span style={{ fontSize: 16, color: C.gold }}>{pillar.icon}</span>
                </div>
                <div style={{ fontSize: 18, fontWeight: 700, color: C.text, marginBottom: 8 }}>{pillar.title}</div>
                <div style={{ fontSize: 14, color: C.muted, lineHeight: 1.6 }}>{pillar.desc}</div>
              </a>
            ))}
          </div>
        </div>
      </section>

      {/* ── 4. THE WORKFLOW ─────────────────────────────────────────────── */}
      <section style={sectionPad(isMobile)}>
        <SectionHeading
          tag="THE WORKFLOW"
          title="Five steps from data to decision"
          sub="A structured process that separates observation from analysis, analysis from strategy, and strategy from execution."
        />
        <div style={{ display: "flex", flexDirection: isMobile ? "column" : "row", alignItems: isMobile ? "stretch" : "center", justifyContent: "center", gap: isMobile ? 0 : 14, maxWidth: 900, margin: "0 auto" }}>
          {WORKFLOW_STEPS.map((step, i) => (
            <div key={step.num} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
              <div
                className="od-card"
                style={{
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 12,
                  padding: isMobile ? "18px 20px" : "22px 18px",
                  width: isMobile ? "100%" : 150,
                  textAlign: "center",
                  flexShrink: 0,
                }}
              >
                <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.gold, marginBottom: 6 }}>{step.num}</div>
                <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 6 }}>{step.title}</div>
                <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.5 }}>{step.desc}</div>
              </div>
              {i < WORKFLOW_STEPS.length - 1 && (
                <div style={{ color: C.faint, fontSize: 18, padding: isMobile ? "8px 0" : "0", textAlign: "center" }}>
                  {isMobile ? "\u2193" : "\u2192"}
                </div>
              )}
            </div>
          ))}
        </div>
        <div style={{ textAlign: "center", marginTop: 24 }}>
          <a className="od-link" href="/how-it-works" style={{ fontSize: 14 }}>See the full six-step workflow &rarr;</a>
        </div>
      </section>

      {/* ── 5. SUPPORTED MARKETS ────────────────────────────────────────── */}
      <section style={{ borderTop: `1px solid ${C.border}`, background: "linear-gradient(180deg, rgba(18,22,31,0.5), rgba(11,14,20,0.2))" }}>
        <div style={sectionPad(isMobile)}>
          <SectionHeading
            tag="SUPPORTED MARKETS"
            title="Eight index option chains"
            sub="NSE and BSE index derivatives under the current SEBI framework."
          />
          <div style={{ maxWidth: 680, margin: "0 auto", background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ color: C.muted, fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textAlign: "left", borderBottom: `2px solid ${C.border}` }}>
                  <th scope="col" style={{ padding: "12px 18px" }}>SYMBOL</th>
                  <th scope="col" style={{ padding: "12px 18px" }}>UNDERLYING</th>
                  <th scope="col" style={{ padding: "12px 18px" }}>EXCHANGE</th>
                </tr>
              </thead>
              <tbody>
                {SYMBOLS.map((s) => (
                  <tr key={s} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: "11px 18px", fontWeight: 800, color: C.gold, letterSpacing: 0.5 }}>{s}</td>
                    <td style={{ padding: "11px 18px", color: C.muted }}>{INDEX_NAMES[s]}</td>
                    <td style={{ padding: "11px 18px", color: C.muted }}>{EXCHANGES[s]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ── 6. FINAL CTA ────────────────────────────────────────────────── */}
      <CTASection
        headline={<>Build a more <span style={{ color: C.gold }}>structured trading workflow.</span></>}
        body="Explore the platform, understand the workflow and practice your strategies before putting capital at risk."
        primaryLabel="Get Started"
        primaryOnClick={openAuth}
        secondaryLabel="Explore the Platform"
        secondaryHref="/features"
      />
    </>
  );
}
