"use client";
import { C } from "@/lib/ui";
import { SectionHeading, FeatureCard, CTASection, PAGE_MAX, sectionPad } from "@/components/public";

const MARKET_FEATURES = [
  { icon: "\u26A1", title: "Live Option Chain", desc: "Full call/put chain with LTP, OI, volume, IV and Greeks for every strike, streaming over WebSocket." },
  { icon: "\u25C8", title: "Open Interest", desc: "Total and per-strike OI on both sides, with change-in-OI tracking per session." },
  { icon: "\u25B2", title: "Volume", desc: "Contract-level and total volume across strikes and expiries, with OI bar visualizations." },
  { icon: "\u223F", title: "Implied Volatility", desc: "IV per strike and ATM IV to gauge how the market is pricing risk." },
  { icon: "\u0394", title: "Greeks", desc: "Delta, gamma, theta and vega computed for every option in the chain." },
  { icon: "\u25CE", title: "PCR", desc: "Put/Call ratio from OI and volume — a quick read on directional sentiment." },
  { icon: "\u25C6", title: "Max Pain", desc: "The strike where option writers face the least loss at expiry." },
  { icon: "\u2605", title: "Watchlist", desc: "Pin any strike with a star and monitor it across sessions." },
  { icon: "\u23F0", title: "Price Alerts", desc: "Set LTP price alerts and get browser notifications when they fire." },
];

const STRATEGY_FEATURES = [
  { icon: "\u221A", title: "Strategy Builder", desc: "Build strategies with multiple legs across strikes and expiries." },
  { icon: "\u2637", title: "Strategy Templates", desc: "42 one-click templates: spreads, condors, butterflies, ratios and calendars." },
  { icon: "\u223E", title: "Payoff Analysis", desc: "Visual payoff curve with max profit, max loss and breakeven points." },
  { icon: "\u2195", title: "Max Profit & Loss", desc: "Clear risk profile for every strategy before you commit capital." },
  { icon: "\u2261", title: "Breakevens", desc: "See exactly where the strategy turns profitable or unprofitable." },
  { icon: "\u0394", title: "Position Greeks", desc: "Aggregate delta, gamma, theta and vega across all legs." },
  { icon: "\u2248", title: "Scenario Analysis", desc: "Stress-test under spot, IV, time and rate changes with a Black-Scholes model." },
];

const TRADING_FEATURES = [
  { icon: "\u25CB", title: "Paper Trading", desc: "Simulated capital, orders, positions and P&L — no broker orders placed." },
  { icon: "\u229E", title: "Orders", desc: "View all paper orders with status, fill details and execution history." },
  { icon: "\u25B3", title: "Positions", desc: "Open and closed positions with real-time P&L and valuation." },
  { icon: "\u25A3", title: "Portfolio", desc: "Total equity, available cash, margin utilization and performance metrics." },
  { icon: "\u00B1", title: "P&L", desc: "Realized and unrealized profit/loss at account, strategy and position levels." },
  { icon: "\u20B9", title: "Capital & Margin", desc: "Server-authoritative capital summary with premium outlay, margin and estimates." },
  { icon: "\u23F0", title: "Trade History", desc: "Full journal of closed trades with per-strategy statistics and CSV export." },
];

const ANALYTICS_FEATURES = [
  { icon: "\u222F", title: "OI Analysis", desc: "Open interest distribution across strikes to identify positioning and support/resistance zones." },
  { icon: "\u21C4", title: "Flow Analysis", desc: "Track changes in OI to understand whether positions are being built or unwound." },
  { icon: "\u223F", title: "Volatility Analysis", desc: "Compare IV across strikes and expiries to identify vol skew and term structure." },
  { icon: "\u2571", title: "Market Structure", desc: "Identify resistance, support and pivot levels from the option chain data." },
];

const FUTURE_CAPABILITIES = [
  { icon: "\u0393", title: "Gamma / GEX Research", desc: "Gamma exposure analysis to understand market-maker hedging flows." },
  { icon: "\u27F3", title: "Statistical Signals", desc: "Signals derived from OI, volume and volatility patterns." },
  { icon: "\u222F", title: "Advanced Positioning", desc: "Deeper analysis of institutional positioning and flow." },
  { icon: "\u21C4", title: "Market Intelligence", desc: "Additional dimensions for understanding market forces." },
];

function FeatureGroup({ heading, features, id }) {
  return (
    <div style={{ marginBottom: 48 }} id={id}>
      <h3
        style={{
          fontSize: 13,
          letterSpacing: 2,
          color: C.gold,
          fontWeight: 700,
          marginBottom: 18,
          textTransform: "uppercase",
        }}
      >
        {heading}
      </h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
        {features.map((f) => (
          <FeatureCard key={f.title} icon={f.icon} title={f.title} desc={f.desc} />
        ))}
      </div>
    </div>
  );
}

export default function FeaturesClientPage() {
  return (
    <>
      {/* Hero */}
      <section style={{ paddingTop: 72, paddingBottom: 24, textAlign: "center" }}>
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: "0 20px" }}>
          <SectionHeading
            level={1}
            tag="FEATURES"
            title="Everything You Need to Analyze Options."
            sub="A complete toolkit for understanding, building, testing and paper-trading options strategies on Indian index derivatives."
          />
        </div>
      </section>

      {/* Feature groups */}
      <section style={{ paddingBottom: 24 }}>
        <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: "0 20px" }}>
          <FeatureGroup heading="Market Intelligence" features={MARKET_FEATURES} />
          <FeatureGroup heading="Strategy & Risk" features={STRATEGY_FEATURES} />
          <FeatureGroup heading="Trading" features={TRADING_FEATURES} />
          <FeatureGroup heading="Analytics" features={ANALYTICS_FEATURES} id="analytics" />

          {/* Research Direction — future capabilities */}
          <div style={{ marginTop: 8 }}>
            <h3
              style={{
                fontSize: 12,
                letterSpacing: 2,
                color: C.faint,
                fontWeight: 600,
                marginBottom: 14,
                textTransform: "uppercase",
                fontStyle: "italic",
              }}
            >
              Research Direction
            </h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
              {FUTURE_CAPABILITIES.map((f) => (
                <div
                  key={f.title}
                  style={{
                    background: "rgba(18, 22, 31, 0.5)",
                    border: `1px dashed ${C.border}`,
                    borderRadius: 12,
                    padding: "22px 20px",
                  }}
                >
                  <div style={{ fontSize: 15.5, fontWeight: 700, color: C.muted, marginBottom: 8 }}>{f.title}</div>
                  <div style={{ fontSize: 13, color: C.faint, lineHeight: 1.6 }}>{f.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <CTASection
        headline={<>Ready to explore <span style={{ color: C.gold }}>the platform</span>?</>}
        primaryLabel="Get Started"
        primaryHref={"/paper-trading"}
        secondaryLabel="How It Works"
        secondaryHref="/how-it-works"
      />
    </>
  );
}
