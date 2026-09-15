// =============================================================================
// WorkflowTabs — Decision Workflow: analytical progression interface
// 01 MARKET VIEW → 02 STRATEGY → 03 PAYOFF → 04 RISK
// =============================================================================
"use client";
import React, { useState } from "react";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "@/components/public/tokens";
import { useIsMobile } from "@/lib/ui";
import { DemoLabel } from "@/components/public/truth";

/** @typedef {{ id: string, number: string, label: string, sublabel: string, content: React.ReactNode }} WorkflowStep */

function Metric({ label, value, accent = false, note }) {
  return (
    <div>
      <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>
        {label}
      </div>
      <div style={{ fontSize: "1.125rem", fontWeight: 700, color: accent ? COLOR.strategy : COLOR.textPrimary, fontFamily: TYPE.data }}>
        {value}
      </div>
      {note && <div style={{ marginTop: SPACE.xs, fontSize: "0.6875rem", color: COLOR.textMuted, lineHeight: 1.45 }}>{note}</div>}
    </div>
  );
}

function StrategyMarketPanel() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE.cardLg }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: SPACE.cardLg }}>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>NIFTY SPOT</div>
          <div style={{ fontSize: "clamp(1.75rem, 4vw, 2.25rem)", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data, lineHeight: 1 }}>25,500</div>
          <div style={{ marginTop: SPACE.small, color: COLOR.textMuted, fontSize: "0.75rem" }}>Illustrative market snapshot</div>
        </div>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>MARKET STATE</div>
          <div style={{ fontSize: "clamp(1.75rem, 4vw, 2.25rem)", fontWeight: 700, color: COLOR.strategy, fontFamily: TYPE.data, lineHeight: 1 }}>BALANCED</div>
          <div style={{ marginTop: SPACE.small, color: COLOR.textMuted, fontSize: "0.75rem" }}>Neutral structure with moderate volatility</div>
        </div>
      </div>

      <div style={{ height: 1, background: COLOR.borderSubtle }} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: SPACE.comp }}>
        <Metric label="PCR" value="1.04" />
        <Metric label="ATM IV" value="14.2%" />
        <Metric label="CALL OI" value="12.4M" />
        <Metric label="PUT OI" value="11.1M" />
        <Metric label="GEX" value="+18.4M" accent />
        <Metric label="GAMMA FLIP" value="25,470" />
        <Metric label="INDIA VIX" value="13.8" />
        <Metric label="VOL REGIME" value="NORMAL" />
      </div>

      <div style={{ paddingTop: SPACE.comp }}>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.08em", color: COLOR.textFaint, marginBottom: SPACE.small }}>MARKET READ</div>
        <p style={{ margin: 0, color: COLOR.textSecondary, fontSize: "0.8125rem", lineHeight: 1.7 }}>
          Positive gamma with spot above the gamma flip suggests a relatively contained structure in this illustrative scenario. The next step is to choose a structure that matches the intended market view.
        </p>
      </div>
    </div>
  );
}

function StrategyStructurePanel() {
  const legs = [
    { action: "BUY", strike: "25,450", type: "CE" },
    { action: "SELL", strike: "25,550", type: "CE" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE.cardLg }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: SPACE.cardLg }}>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.xs }}>STRUCTURE</div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data, lineHeight: 1.1 }}>BULL CALL SPREAD</div>
          <div style={{ marginTop: SPACE.small, color: COLOR.textMuted, fontSize: "0.75rem", lineHeight: 1.5 }}>Defined-risk bullish structure using a debit spread.</div>
        </div>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.small }}>MARKET FIT</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: SPACE.xs }}>
            {["Bullish bias", "Risk capped", "1.22 : 1 R/R"].map((item, i) => (
              <span key={item} style={{ display: "inline-flex", padding: `${SPACE.xs} ${SPACE.small}`, border: `1px solid ${COLOR.borderSubtle}`, color: i === 2 ? COLOR.strategy : COLOR.textSecondary, fontFamily: TYPE.data, fontSize: "0.6875rem", borderRadius: RADIUS.sm }}>
                {item}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div style={{ height: 1, background: COLOR.borderSubtle }} />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) minmax(0, 0.8fr)", gap: SPACE.cardLg }}>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, marginBottom: SPACE.small }}>OPTION LEGS</div>
          <div style={{ display: "flex", flexDirection: "column", gap: SPACE.xs }}>
            {legs.map((leg) => (
              <div key={`${leg.action}-${leg.strike}`} style={{ display: "grid", gridTemplateColumns: "60px 1fr 40px", alignItems: "center", gap: SPACE.small, padding: `${SPACE.small} ${SPACE.comp}`, borderTop: `1px solid ${COLOR.borderSubtle}` }}>
                <span style={{ fontWeight: 700, color: leg.action === "BUY" ? COLOR.strategy : COLOR.textMuted, fontFamily: TYPE.data, fontSize: "0.75rem" }}>{leg.action}</span>
                <span style={{ color: COLOR.textPrimary, fontFamily: TYPE.data }}>{leg.strike}</span>
                <span style={{ color: COLOR.textMuted, fontFamily: TYPE.data }}>{leg.type}</span>
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.comp }}>
          <Metric label="DEBIT" value="45 pts" />
          <Metric label="SPREAD WIDTH" value="100 pts" />
          <Metric label="MAX PROFIT" value="+55 pts" accent />
          <Metric label="MAX LOSS" value="-45 pts" />
        </div>
      </div>

      <div style={{ paddingTop: SPACE.small }}>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.08em", color: COLOR.textFaint, marginBottom: SPACE.small }}>WHY THIS STRUCTURE?</div>
        <p style={{ margin: 0, color: COLOR.textSecondary, fontSize: "0.8125rem", lineHeight: 1.7 }}>
          The example risks 45 points to target 55 points. That produces a reward-to-risk ratio of 55 ÷ 45 = <strong style={{ color: COLOR.strategy }}>1.22 : 1</strong> before costs, slippage or early-exit effects.
        </p>
      </div>
    </div>
  );
}

function StrategyPayoffPanel() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE.cardLg }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.65fr) minmax(240px, 0.7fr)", gap: SPACE.cardLg, alignItems: "start" }}>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.08em", color: COLOR.textFaint, marginBottom: SPACE.small }}>ILLUSTRATIVE EXPIRY PAYOFF · BULL CALL SPREAD</div>
          <div style={{ width: "100%", overflow: "hidden" }}>
            <svg viewBox="0 0 620 250" width="100%" height="250" role="img" aria-label="Illustrative bull call spread payoff. Maximum loss is negative 45 points, breakeven is 25,495, short strike is 25,550, and maximum profit is positive 55 points.">
              {/* Reference grid */}
              <line x1="48" y1="125" x2="590" y2="125" stroke={COLOR.border} strokeWidth="1.5" />
              <line x1="48" y1="55" x2="590" y2="55" stroke={COLOR.borderSubtle} strokeWidth="1" strokeDasharray="3 4" />
              <line x1="48" y1="195" x2="590" y2="195" stroke={COLOR.borderSubtle} strokeWidth="1" strokeDasharray="3 4" />

              {/* Defined downside: flat loss until long strike */}
              <path d="M48 195 L160 195 L300 125" fill="none" stroke={COLOR.negative} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
              <path d="M48 195 L160 195 L300 125 L48 125 Z" fill={COLOR.negative} opacity="0.09" />

              {/* Rising payoff between strikes, then capped at max profit */}
              <path d="M300 125 L403 55 L590 55" fill="none" stroke={COLOR.positive} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M300 125 L403 55 L590 55 L590 125 L300 125 Z" fill={COLOR.positive} opacity="0.09" />

              {/* Key levels */}
              <line x1="300" y1="38" x2="300" y2="210" stroke={COLOR.strategy} strokeWidth="1" strokeDasharray="4 4" opacity="0.8" />
              <line x1="310" y1="38" x2="310" y2="210" stroke={COLOR.borderSubtle} strokeWidth="1" strokeDasharray="2 5" opacity="0.8" />
              <line x1="403" y1="38" x2="403" y2="210" stroke={COLOR.strategy} strokeWidth="1" strokeDasharray="4 4" opacity="0.65" />
              <circle cx="310" cy="118" r="4" fill={COLOR.textPrimary} />

              {/* Value labels */}
              <text x="44" y="48" fill={COLOR.textFaint} fontSize="10" textAnchor="end" fontFamily="monospace">+55</text>
              <text x="44" y="129" fill={COLOR.textFaint} fontSize="10" textAnchor="end" fontFamily="monospace">0</text>
              <text x="44" y="199" fill={COLOR.textFaint} fontSize="10" textAnchor="end" fontFamily="monospace">-45</text>

              {/* Strike / spot labels */}
              <text x="160" y="216" fill={COLOR.textFaint} fontSize="10" textAnchor="middle" fontFamily="monospace">25,450</text>
              <text x="300" y="232" fill={COLOR.strategy} fontSize="9" textAnchor="middle" fontFamily="monospace">BREAKEVEN 25,495</text>
              <text x="310" y="216" fill={COLOR.textPrimary} fontSize="10" textAnchor="middle" fontFamily="monospace">SPOT 25,500</text>
              <text x="403" y="232" fill={COLOR.strategy} fontSize="9" textAnchor="middle" fontFamily="monospace">SHORT 25,550</text>
              <text x="590" y="216" fill={COLOR.textFaint} fontSize="10" textAnchor="end" fontFamily="monospace">25,650</text>

              <text x="82" y="182" fill={COLOR.negative} fontSize="9" fontWeight="700">MAX LOSS</text>
              <text x="467" y="48" fill={COLOR.positive} fontSize="9" fontWeight="700">MAX PROFIT · CAPPED</text>
            </svg>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: SPACE.comp }}>
          <Metric label="MAX PROFIT" value="+55 pts" accent />
          <Metric label="MAX LOSS" value="-45 pts" />
          <Metric label="BREAKEVEN" value="25,495" />
          <Metric label="REWARD / RISK" value="1.22 : 1" accent />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: SPACE.comp, borderTop: `1px solid ${COLOR.borderSubtle}`, paddingTop: SPACE.comp }}>
        <Metric label="BELOW 25,450" value="-45 pts" note="Maximum defined loss at expiry" />
        <Metric label="25,495 BREAKEVEN" value="0 pts" note="Profit begins above this level" />
        <Metric label="ABOVE 25,550" value="+55 pts" note="Maximum profit at expiry" accent />
      </div>
    </div>
  );
}

function StrategyRiskPanel() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACE.cardLg }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: SPACE.cardLg }}>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.08em", color: COLOR.textFaint, marginBottom: SPACE.small }}>DECISION BOUNDARIES</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.cardLg }}>
            <Metric label="MAX LOSS" value="-45 pts" />
            <Metric label="MAX PROFIT" value="+55 pts" accent />
            <Metric label="BREAKEVEN" value="25,495" />
            <Metric label="RISK / REWARD" value="1 : 1.22" accent />
          </div>
        </div>
        <div>
          <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.08em", color: COLOR.textFaint, marginBottom: SPACE.small }}>POSITION GREEKS</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: SPACE.cardLg }}>
            <Metric label="DELTA" value="+0.18" />
            <Metric label="GAMMA" value="0.0003" />
            <Metric label="THETA" value="-7.15" />
            <Metric label="VEGA" value="+10.40" />
          </div>
        </div>
      </div>

      <div style={{ height: 1, background: COLOR.borderSubtle }} />

      <div>
        <div style={{ fontSize: "0.625rem", fontWeight: 600, letterSpacing: "0.08em", color: COLOR.textFaint, marginBottom: SPACE.small }}>RISK NOTES</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: SPACE.comp }}>
          {[
            ["LOSS IS CAPPED", "The long call limits downside to the initial debit at expiry."],
            ["PROFIT IS CAPPED", "The short call limits upside once the spread reaches full width."],
            ["R/R IS EXPLICIT", "55 points of upside are targeted against 45 points of defined risk."],
          ].map(([title, body]) => (
            <div key={title} style={{ paddingTop: SPACE.comp, borderTop: `1px solid ${COLOR.borderSubtle}` }}>
              <div style={{ fontSize: "0.625rem", fontWeight: 700, letterSpacing: "0.06em", color: COLOR.textSecondary, marginBottom: SPACE.xs }}>{title}</div>
              <div style={{ fontSize: "0.75rem", lineHeight: 1.6, color: COLOR.textMuted }}>{body}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * WorkflowTabs — accessible analytical workflow interface.
 *
 * @param {{ steps: WorkflowStep[], defaultStep: string, ariaLabel: string }} props
 */
export default function WorkflowTabs({ steps, defaultStep, ariaLabel }) {
  const isMobile = useIsMobile();
  const [activeStep, setActiveStep] = useState(defaultStep || steps[0]?.id);

  const activeContent = steps.find((s) => s.id === activeStep)?.content;
  const strategyIds = ["market", "strategy", "payoff", "risk"];
  const isStrategyWorkflow = strategyIds.every((id) => steps.some((step) => step.id === id));

  const displayedContent = isStrategyWorkflow
    ? {
        market: <StrategyMarketPanel />,
        strategy: <StrategyStructurePanel />,
        payoff: <StrategyPayoffPanel />,
        risk: <StrategyRiskPanel />,
      }[activeStep]
    : activeContent;

  return (
    <div>
      <div
        role="tablist"
        aria-label={ariaLabel}
        style={{
          display: "flex",
          gap: 0,
          marginBottom: SPACE.cardLg,
          flexDirection: isMobile ? "column" : "row",
        }}
      >
        {steps.map((step, index) => {
          const isActive = step.id === activeStep;
          const isLast = index === steps.length - 1;

          return (
            <React.Fragment key={step.id}>
              <button
                role="tab"
                aria-selected={isActive}
                aria-controls={`tabpanel-${step.id}`}
                id={`tab-${step.id}`}
                onClick={() => setActiveStep(step.id)}
                className="ds-focus-ring"
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: isMobile ? "flex-start" : "center",
                  textAlign: "left",
                  padding: `${SPACE.comp} ${SPACE.compLg}`,
                  background: "transparent",
                  border: "none",
                  borderBottom: isMobile ? "none" : `2px solid ${isActive ? COLOR.strategy : "transparent"}`,
                  borderLeft: isMobile ? `2px solid ${isActive ? COLOR.strategy : COLOR.border}` : "none",
                  cursor: "pointer",
                  transition: `border-color ${MOTION.fast}, background ${MOTION.fast}`,
                  borderRadius: 0,
                  minHeight: "auto",
                  gap: SPACE.xs,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: SPACE.small, width: "100%" }}>
                  <span style={{ fontSize: "0.625rem", fontWeight: 700, fontFamily: TYPE.data, color: isActive ? COLOR.strategy : COLOR.textFaint, letterSpacing: "0.04em", transition: `color ${MOTION.fast}` }}>
                    {step.number}
                  </span>
                  <span style={{ fontSize: TYPE.caption.size, fontWeight: 700, letterSpacing: "0.06em", fontFamily: TYPE.data, textTransform: "uppercase", color: isActive ? COLOR.textPrimary : COLOR.textMuted, transition: `color ${MOTION.fast}` }}>
                    {step.label}
                  </span>
                </div>
                <span style={{ fontSize: "0.6875rem", color: isActive ? COLOR.textSecondary : COLOR.textFaint, lineHeight: 1.4, transition: `color ${MOTION.fast}` }}>
                  {step.sublabel}
                </span>
              </button>

              {!isLast && !isMobile && (
                <div style={{ display: "flex", alignItems: "center", paddingBottom: "2rem", flexShrink: 0 }} aria-hidden="true">
                  <div style={{ width: "2rem", height: 1, background: COLOR.borderSubtle }} />
                  <svg width="6" height="8" viewBox="0 0 6 8" fill="none" style={{ marginLeft: -1 }} aria-hidden="true">
                    <path d="M0 0 L6 4 L0 8 Z" fill={COLOR.borderSubtle} />
                  </svg>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      <div role="tabpanel" id={`tabpanel-${activeStep}`} aria-labelledby={`tab-${activeStep}`}>
        {displayedContent}
      </div>

      <div style={{ textAlign: "center", marginTop: SPACE.cardLg }}>
        <DemoLabel style={{ fontSize: "0.625rem" }} />
      </div>
    </div>
  );
}
