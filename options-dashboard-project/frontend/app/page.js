"use client";
import { useEffect, useState } from "react";
import { loginUrl } from "@/lib/api";
import { C, SYMBOLS, LOT_SIZES, fmtIN, useIsMobile } from "@/lib/ui";

// ---------- decorative mock data (landing page only) ----------
const MOCK_BASE = {
  NIFTY: 25512,
  BANKNIFTY: 54680,
  FINNIFTY: 26175,
  MIDCPNIFTY: 13340,
  NIFTYNXT50: 79240,
  SENSEX: 82960,
  BANKEX: 61850,
  SENSEX50: 17820,
};
const MOCK_STEP = {
  NIFTY: 100,
  BANKNIFTY: 250,
  FINNIFTY: 100,
  MIDCPNIFTY: 100,
  NIFTYNXT50: 250,
  SENSEX: 100,
  BANKEX: 250,
  SENSEX50: 50,
};
const INDEX_NAMES = {
  NIFTY: "Nifty 50",
  BANKNIFTY: "Nifty Bank",
  FINNIFTY: "Nifty Financial Services",
  MIDCPNIFTY: "Nifty Midcap Select",
  NIFTYNXT50: "Nifty Next 50",
  SENSEX: "BSE Sensex",
  BANKEX: "BSE Bankex",
  SENSEX50: "BSE Sensex 50",
};
const EXCHANGES = { NIFTY: "NSE", BANKNIFTY: "NSE", FINNIFTY: "NSE", MIDCPNIFTY: "NSE", NIFTYNXT50: "NSE", SENSEX: "BSE", BANKEX: "BSE", SENSEX50: "BSE" };

const FEATURES = [
  {
    icon: "⚡",
    title: "Live Option Chain",
    desc: "Every strike on both sides, streaming. OI bars, chg OI, volume, IV and the full Greek stack update in real time over WebSocket, with automatic HTTP fallback.",
  },
  {
    icon: "▦",
    title: "Eight Index Chains",
    desc: "NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 plus BSE SENSEX, BANKEX and SENSEX50 — switch chains in one tap. Correct lot sizes baked in.",
  },
  {
    icon: "◈",
    title: "Market Analytics",
    desc: "Put/Call ratio, max pain strike and total OI on each side — computed live from the chain, with tooltips explaining what each number is telling you.",
  },
  {
    icon: "★",
    title: "Watchlist & Alerts",
    desc: "Pin any strike with a star, set LTP ≥ / ≤ price alerts, and get a browser notification the moment one fires.",
  },
  {
    icon: "∿",
    title: "Strategy Lab",
    desc: "42 one-click strategies — spreads, condors, ratios, butterflies and calendars — built straight from the live chain with payoff graphs, position Greeks and target-price P&L.",
  },
  {
    icon: "₹",
    title: "Paper Trading",
    desc: "A ₹5,00,000 simulated portfolio. Track equity over time (market-hours only), per-strategy win rates, and export your trade history to CSV.",
  },
];

const STEPS = [
  {
    num: "01",
    title: "Log in with Upstox",
    desc: "One click, official Upstox OAuth. Your password never touches this app — only a session token from your own brokerage account.",
  },
  {
    num: "02",
    title: "Pick a chain & expiry",
    desc: "Any of the eight index chains, any listed expiry. The live feed takes over the moment the dashboard opens.",
  },
  {
    num: "03",
    title: "Watch, alert, paper-trade",
    desc: "Spot, PCR, max pain, OI — all moving live. Validate any strategy on paper before risking a single rupee.",
  },
];

const CSS = `
html { scroll-behavior: smooth; }
@keyframes od-ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes od-fade-up { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
@keyframes od-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@keyframes od-glow { 0%, 100% { box-shadow: 0 0 0 0 rgba(201, 161, 90, 0.28); } 50% { box-shadow: 0 0 0 8px rgba(201, 161, 90, 0); } }
.od-fade { animation: od-fade-up 0.7s cubic-bezier(0.22, 1, 0.36, 1) both; }
.od-pulse { animation: od-pulse 1.6s ease-in-out infinite; }
.od-btn-gold {
  display: inline-flex; align-items: center; gap: 8px;
  background: ${C.gold}; color: #0B0E14;
  padding: 12px 22px; border-radius: 8px; font-weight: 700; font-size: 14.5;
  text-decoration: none; border: 1px solid ${C.gold};
  transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.od-btn-gold:hover { background: #D9B36A; box-shadow: 0 6px 24px rgba(201, 161, 90, 0.35); transform: translateY(-1px); }
.od-btn-ghost {
  display: inline-flex; align-items: center; gap: 8px;
  background: transparent; color: ${C.text};
  padding: 12px 22px; border-radius: 8px; font-weight: 600; font-size: 14.5;
  text-decoration: none; border: 1px solid ${C.border};
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}
.od-btn-ghost:hover { border-color: ${C.gold}; background: rgba(201, 161, 90, 0.07); transform: translateY(-1px); }
.od-link { color: ${C.muted}; text-decoration: none; font-size: 13.5; transition: color 0.15s ease; }
.od-link:hover { color: ${C.gold}; }
.od-card { transition: transform 0.18s ease, border-color 0.18s ease; }
.od-card:hover { transform: translateY(-3px); border-color: rgba(201, 161, 90, 0.45) !important; }
.od-ticker-track { display: flex; width: max-content; animation: od-ticker 36s linear infinite; }
.od-ticker-track:hover { animation-play-state: paused; }
`;

// Animated mock chain card (purely decorative)
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
  const step = MOCK_STEP[sym];
  const atm = Math.round(state.spot / step) * step;
  const chgPct = state.prevSpot ? ((state.spot - state.prevSpot) / state.prevSpot) * 100 : 0;
  const up = chgPct >= 0;

  const rows = [];
  for (let i = -3; i <= 3; i++) {
    const strike = atm + i * step;
    const callLtp = Math.max(0, state.spot - strike) + 38 + ((strike / step) % 5) * 7;
    const putLtp = Math.max(0, strike - state.spot) + 34 + ((strike / step + 2) % 5) * 6;
    const callOi = ((strike / step) % 7) / 6;
    const putOi = ((strike / step + 3) % 7) / 6;
    rows.push({ strike, callLtp, putLtp, callOi, putOi, atm: strike === atm });
  }

  return (
    <div
      className="od-card"
      style={{
        width: "100%",
        maxWidth: 430,
        background: "linear-gradient(180deg, rgba(23, 28, 39, 0.9), rgba(18, 22, 31, 0.95))",
        border: "1px solid #242B3A",
        borderRadius: 14,
        boxShadow: "0 24px 60px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(201, 161, 90, 0.06)",
        overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 4, background: C.green, boxShadow: "0 0 8px rgba(76,175,125,0.9)", animation: "od-glow 2s ease-in-out infinite" }} />
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: 0.5 }}>{sym}</span>
          <span style={{ fontSize: 10.5, color: C.faint, letterSpacing: 1 }}>{EXCHANGES[sym]} INDEX</span>
        </div>
        <div style={{ fontSize: 11, color: C.muted, display: "flex", alignItems: "center", gap: 6 }}>
          <span className="od-pulse" style={{ color: C.green, fontSize: 10 }}>●</span> LIVE
        </div>
      </div>

      <div style={{ padding: "10px 16px", display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: `1px solid ${C.border}` }}>
        <div>
          <div style={{ fontSize: 10, color: C.faint, letterSpacing: 1 }}>SPOT</div>
          <div style={{ fontSize: 21, fontWeight: 800, color: C.gold }}>{fmtIN(state.spot, 2)}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: up ? C.green : C.red }}>{up ? "▲" : "▼"} {up ? "+" : ""}{chgPct.toFixed(2)}%</div>
          <div style={{ fontSize: 10, color: C.faint }}>vs previous tick</div>
        </div>
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
        <thead>
          <tr style={{ color: C.faint, fontSize: 9.5, letterSpacing: 0.5 }}>
            <th style={{ padding: "7px 16px", textAlign: "left" }}>CALLS</th>
            <th style={{ padding: 7, textAlign: "center", color: C.gold }}>STRIKE</th>
            <th style={{ padding: "7px 16px", textAlign: "right" }}>PUTS</th>
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

      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "10px 16px", borderTop: `1px solid ${C.border}`, fontSize: 10.5, color: C.muted }}>
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
            <span style={{ color: C.faint, fontSize: 10.5 }}>LOT {it.lot}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function SectionHeading({ tag, title, sub }) {
  return (
    <div style={{ textAlign: "center", maxWidth: 640, margin: "0 auto 44px" }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <span style={{ width: 26, height: 1, background: `linear-gradient(90deg, transparent, ${C.gold})` }} />
        <span style={{ fontSize: 11, letterSpacing: 2, color: C.gold, fontWeight: 700 }}>{tag}</span>
        <span style={{ width: 26, height: 1, background: `linear-gradient(90deg, ${C.gold}, transparent)` }} />
      </div>
      <h2 style={{ fontSize: 30, margin: "0 0 12px", letterSpacing: -0.5 }}>{title}</h2>
      {sub && <p style={{ color: C.muted, fontSize: 14.5, lineHeight: 1.65, margin: 0 }}>{sub}</p>}
    </div>
  );
}

function FeatureCard({ icon, title, desc }) {
  return (
    <div
      className="od-card"
      style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "22px 20px", display: "flex", flexDirection: "column", gap: 10 }}
    >
      <div style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(201,161,90,0.1)", border: "1px solid rgba(201,161,90,0.25)", display: "grid", placeItems: "center", fontSize: 18, color: C.gold }}>
        {icon}
      </div>
      <div style={{ fontSize: 15, fontWeight: 700 }}>{title}</div>
      <div style={{ fontSize: 12.5, color: C.muted, lineHeight: 1.6 }}>{desc}</div>
    </div>
  );
}

export default function Home() {
  const [loginError, setLoginError] = useState(null);
  const isMobile = useIsMobile();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setLoginError(params.get("login_error"));
  }, []);

  return (
    <>
      <style>{CSS}</style>

      {/* ---------- Nav ---------- */}
      <nav
        style={{
          position: "sticky",
          top: 0,
          zIndex: 50,
          background: "rgba(11, 14, 20, 0.82)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        <div style={{ maxWidth: 1100, margin: "0 auto", padding: "12px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
          <a href="/" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
            <span style={{ width: 30, height: 30, borderRadius: 8, background: C.gold, color: "#0B0E14", display: "grid", placeItems: "center", fontWeight: 900, fontSize: 13, letterSpacing: -0.5 }}>
              OD
            </span>
            <span>
              <span style={{ display: "block", fontSize: 13, fontWeight: 800, letterSpacing: 1.2, color: C.text }}>OPTIONS DASHBOARD</span>
              <span style={{ display: "block", fontSize: 9.5, color: C.faint, letterSpacing: 1 }}>NSE · BSE INDEX OPTIONS</span>
            </span>
          </a>

          {!isMobile && (
            <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
              <a className="od-link" href="#features">Features</a>
              <a className="od-link" href="#indices">Indices</a>
              <a className="od-link" href="#how">How it works</a>
              <a className="od-link" href="/dashboard">Option Chain</a>
              <a className="od-link" href="/paper">Paper Trading</a>
            </div>
          )}

          <a className="od-btn-gold" href={loginUrl()} style={{ padding: "8px 16px", fontSize: 13 }}>
            Log in <span aria-hidden>→</span>
          </a>
        </div>
      </nav>

      {/* ---------- Hero ---------- */}
      <header style={{ position: "relative", overflow: "hidden" }}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "radial-gradient(ellipse 60% 50% at 28% 12%, rgba(201,161,90,0.14), transparent 60%), radial-gradient(ellipse 40% 40% at 82% 70%, rgba(76,175,125,0.06), transparent 60%), repeating-linear-gradient(0deg, rgba(201,161,90,0.025) 0 1px, transparent 1px 46px), repeating-linear-gradient(90deg, rgba(201,161,90,0.025) 0 1px, transparent 1px 46px)",
            pointerEvents: "none",
          }}
        />
        <div style={{ maxWidth: 1100, margin: "0 auto", padding: isMobile ? "64px 20px" : "96px 20px 84px", display: "flex", alignItems: "center", gap: 56, flexWrap: "wrap", position: "relative" }}>
          <div style={{ flex: "1 1 400px", minWidth: 0 }}>
            <div className="od-fade" style={{ display: "inline-flex", alignItems: "center", gap: 8, border: "1px solid rgba(201,161,90,0.3)", background: "rgba(201,161,90,0.07)", borderRadius: 999, padding: "5px 14px", fontSize: 10.5, letterSpacing: 1.5, color: C.gold, fontWeight: 700, marginBottom: 22 }}>
              <span className="od-pulse" style={{ color: C.green, fontSize: 9 }}>●</span>
              POWERED BY UPSTOX · NSE &amp; BSE INDEX OPTIONS
            </div>

            <h1 className="od-fade" style={{ margin: "0 0 18px", fontSize: isMobile ? 38 : 56, lineHeight: 1.06, letterSpacing: -1.5, fontWeight: 800, animationDelay: "0.08s" }}>
              Every strike.
              <br />
              Both sides.
              <br />
              <span style={{ color: C.gold }}>Live.</span>
            </h1>

            <p className="od-fade" style={{ color: C.muted, fontSize: 15.5, lineHeight: 1.7, maxWidth: 540, margin: "0 0 28px", animationDelay: "0.16s" }}>
              A real-time index options terminal for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX and SENSEX50 — WebSocket feed, max pain &amp; PCR analytics, watchlist alerts, and a 27-strategy paper trading lab. Log in once with your Upstox account.
            </p>

            {loginError && (
              <div className="od-fade" style={{ animationDelay: "0.2s", maxWidth: 540, marginBottom: 18, fontSize: 13, color: C.red, border: `1px solid ${C.red}`, borderRadius: 8, padding: "8px 14px", background: "rgba(225,82,82,0.08)" }}>
                Login failed: {loginError}. Please try again.
              </div>
            )}

            <div className="od-fade" style={{ animationDelay: "0.24s", display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 34 }}>
              <a className="od-btn-gold" href={loginUrl()}>
                Launch Option Chain <span aria-hidden>→</span>
              </a>
              <a className="od-btn-ghost" href="/paper">
                Try Paper Trading
              </a>
            </div>

            <div className="od-fade" style={{ animationDelay: "0.3s", display: "flex", gap: 28, flexWrap: "wrap", fontSize: 12, color: C.muted }}>
              <span><span style={{ color: C.text, fontWeight: 800, fontSize: 16 }}>8</span> index chains</span>
              <span><span style={{ color: C.text, fontWeight: 800, fontSize: 16 }}>42</span> built-in strategies</span>
              <span><span style={{ color: C.text, fontWeight: 800, fontSize: 16 }}>Live</span> WebSocket feed</span>
            </div>
          </div>

          <div className="od-fade" style={{ animationDelay: "0.18s", flex: "0 1 460px", display: "flex", justifyContent: "center" }}>
            <MockChain />
          </div>
        </div>
      </header>

      <TickerTape />

      {/* ---------- Features ---------- */}
      <section id="features" style={{ maxWidth: 1100, margin: "0 auto", padding: isMobile ? "72px 20px" : "96px 20px" }}>
        <SectionHeading
          tag="WHY THIS TERMINAL"
          title="Everything an options trader needs, in one dark screen"
          sub="Built for the way index options actually trade — live data, honest analytics, and a safe place to test ideas before putting money behind them."
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
          {FEATURES.map((f) => (
            <FeatureCard key={f.title} icon={f.icon} title={f.title} desc={f.desc} />
          ))}
        </div>
      </section>

      {/* ---------- Indices ---------- */}
      <section id="indices" style={{ borderTop: `1px solid ${C.border}`, background: "linear-gradient(180deg, rgba(18,22,31,0.5), rgba(11,14,20,0.2))" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", padding: isMobile ? "72px 20px" : "96px 20px" }}>
          <SectionHeading
            tag="COVERAGE"
            title="All eight index option chains"
            sub="NSE and BSE index derivatives, with the correct lot sizes for the current SEBI framework (effective 30 Dec 2025)."
          />
          <div style={{ maxWidth: 720, margin: "0 auto", background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ color: C.faint, fontSize: 10.5, letterSpacing: 1, textAlign: "left" }}>
                  <th style={{ padding: "11px 18px" }}>SYMBOL</th>
                  <th style={{ padding: "11px 18px" }}>UNDERLYING</th>
                  <th style={{ padding: "11px 18px" }}>EXCHANGE</th>
                  <th style={{ padding: "11px 18px", textAlign: "right" }}>LOT SIZE</th>
                </tr>
              </thead>
              <tbody>
                {SYMBOLS.map((s) => (
                  <tr key={s} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: "10px 18px", fontWeight: 800, color: C.gold, letterSpacing: 0.5 }}>{s}</td>
                    <td style={{ padding: "10px 18px", color: C.muted }}>{INDEX_NAMES[s]}</td>
                    <td style={{ padding: "10px 18px", color: C.muted }}>{EXCHANGES[s]}</td>
                    <td style={{ padding: "10px 18px", textAlign: "right", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{LOT_SIZES[s]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ---------- How it works ---------- */}
      <section id="how" style={{ maxWidth: 1100, margin: "0 auto", padding: isMobile ? "72px 20px" : "96px 20px" }}>
        <SectionHeading
          tag="GET STARTED"
          title="Live in under a minute"
          sub="No signup form, no credit card, no password stored. Just your own Upstox account."
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
          {STEPS.map((s) => (
            <div key={s.num} className="od-card" style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: "24px 22px" }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: "rgba(201,161,90,0.35)", letterSpacing: 1, marginBottom: 10 }}>{s.num}</div>
              <div style={{ fontSize: 15.5, fontWeight: 700, marginBottom: 8 }}>{s.title}</div>
              <div style={{ fontSize: 12.5, color: C.muted, lineHeight: 1.6 }}>{s.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ---------- Final CTA ---------- */}
      <section style={{ padding: isMobile ? "16px 20px 80px" : "24px 20px 100px" }}>
        <div
          style={{
            maxWidth: 900,
            margin: "0 auto",
            textAlign: "center",
            padding: isMobile ? "48px 24px" : "72px 48px",
            borderRadius: 18,
            background:
              "radial-gradient(ellipse 70% 90% at 50% 0%, rgba(201,161,90,0.16), transparent 65%), linear-gradient(180deg, #12161F, #0B0E14)",
            border: "1px solid rgba(201,161,90,0.25)",
            boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
          }}
        >
          <h2 style={{ margin: "0 0 14px", fontSize: isMobile ? 28 : 38, letterSpacing: -0.5 }}>
            Stop guessing. <span style={{ color: C.gold }}>Watch the chain.</span>
          </h2>
          <p style={{ color: C.muted, fontSize: 14.5, maxWidth: 520, margin: "0 auto 30px", lineHeight: 1.7 }}>
            See what the market is pricing before you act. Alerts when it matters, analytics that explain themselves, and a paper account to prove your edge first.
          </p>
          <a className="od-btn-gold" href={loginUrl()} style={{ fontSize: 15, padding: "14px 30px" }}>
            Launch Option Chain <span aria-hidden>→</span>
          </a>
          <div style={{ marginTop: 18, fontSize: 11.5, color: C.faint }}>
            Free with your own Upstox account · Sessions expire daily at 3:30 AM IST — re-login takes one click.
          </div>
        </div>
      </section>

      {/* ---------- Footer ---------- */}
      <footer style={{ borderTop: `1px solid ${C.border}`, padding: "40px 20px 28px" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", flexWrap: "wrap", gap: 32, justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ maxWidth: 320 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
              <span style={{ width: 26, height: 26, borderRadius: 7, background: C.gold, color: "#0B0E14", display: "grid", placeItems: "center", fontWeight: 900, fontSize: 11 }}>
                OD
              </span>
              <span style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: 1.2 }}>OPTIONS DASHBOARD</span>
            </div>
            <p style={{ fontSize: 12, color: C.faint, lineHeight: 1.65, margin: 0 }}>
              For education and research only — not investment advice. Market data via Upstox. Options trading involves substantial risk; past performance is not indicative of future results.
            </p>
          </div>
          <div style={{ display: "flex", gap: 48, flexWrap: "wrap" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              <div style={{ fontSize: 10.5, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>PRODUCT</div>
              <a className="od-link" href="/dashboard">Option Chain</a>
              <a className="od-link" href="/paper">Paper Trading</a>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              <div style={{ fontSize: 10.5, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>EXPLORE</div>
              <a className="od-link" href="#features">Features</a>
              <a className="od-link" href="#indices">Indices</a>
              <a className="od-link" href="#how">How it works</a>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              <div style={{ fontSize: 10.5, letterSpacing: 1.5, color: C.faint, marginBottom: 4 }}>ACCOUNT</div>
              <a className="od-link" href={loginUrl()}>Log in with Upstox</a>
            </div>
          </div>
        </div>
        <div style={{ maxWidth: 1100, margin: "28px auto 0", paddingTop: 20, borderTop: `1px solid ${C.border}`, fontSize: 11, color: C.faint, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <span>© {new Date().getFullYear()} Options Dashboard</span>
          <span>NSE &amp; BSE index derivatives · Powered by Upstox</span>
        </div>
      </footer>
    </>
  );
}
