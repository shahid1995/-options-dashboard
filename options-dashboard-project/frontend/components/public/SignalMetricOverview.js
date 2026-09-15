// =============================================================================
// Market State Console — Premium financial intelligence presentation
// Data → Relationship → Interpretation
// =============================================================================
"use client";
import React from "react";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
import { DemoLabel } from "@/components/public/truth";
import { useIsMobile } from "@/lib/ui";

// Market state metadata
const MARKET_STATE = {
  label: "BALANCED",
  strength: 68,
  direction: "NEUTRAL",
  volatility: "MODERATE",
  positioning: "BALANCED",
  risk: "CONTROLLED",
};

const MARKET_READ = "Balanced positioning with positive gamma and moderate implied volatility. Price remains above the gamma flip, suggesting a relatively contained near-term structure.";

export default function SignalMetricOverview() {
  const isMobile = useIsMobile();

  return (
    <div
      style={{
        background: COLOR.surface,
        border: `1px solid ${COLOR.border}`,
        borderRadius: RADIUS.xl,
        padding: isMobile ? SPACE.card : SPACE.cardLg,
        display: "flex",
        flexDirection: "column",
        gap: SPACE.cardLg,
      }}
    >
      {/* ═══ DOMINANT MARKET STATE ═══ */}
      <div>
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.08em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
            marginBottom: SPACE.comp,
          }}
        >
          Market State
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: SPACE.comp,
            marginBottom: SPACE.small,
          }}
        >
          <span
            style={{
              fontSize: "clamp(1.75rem, 3vw, 2.25rem)",
              fontWeight: 700,
              color: COLOR.textPrimary,
              fontFamily: TYPE.data,
              letterSpacing: "-0.02em",
              lineHeight: 1,
            }}
          >
            {MARKET_STATE.label}
          </span>
          <span
            style={{
              fontSize: TYPE.bodySmall.size,
              color: COLOR.textMuted,
              fontFamily: TYPE.data,
            }}
          >
            strength {MARKET_STATE.strength}/100
          </span>
        </div>
        {/* Spectrum */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: SPACE.small,
          }}
        >
          <span
            style={{
              fontSize: "0.625rem",
              color: COLOR.textFaint,
              fontFamily: TYPE.data,
              letterSpacing: "0.04em",
            }}
          >
            BEARISH
          </span>
          <div
            style={{
              flex: 1,
              height: 2,
              background: `linear-gradient(to right, ${COLOR.textFaint}, ${COLOR.strategy}, ${COLOR.textFaint})`,
              position: "relative",
            }}
          >
            <div
              style={{
                position: "absolute",
                left: `${MARKET_STATE.strength}%`,
                top: "50%",
                transform: "translate(-50%, -50%)",
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: COLOR.strategy,
                border: `2px solid ${COLOR.surface}`,
              }}
            />
          </div>
          <span
            style={{
              fontSize: "0.625rem",
              color: COLOR.textFaint,
              fontFamily: TYPE.data,
              letterSpacing: "0.04em",
            }}
          >
            BULLISH
          </span>
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: COLOR.borderSubtle }} />

      {/* ═══ MARKET STRUCTURE ═══ */}
      <div>
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.08em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
            marginBottom: SPACE.comp,
          }}
        >
          Market Structure
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)",
            gap: 0,
          }}
        >
          {[
            { label: "CALL OI", value: "12.4M" },
            { label: "PUT OI", value: "11.1M" },
            { label: "PCR", value: "1.04" },
            { label: "OI IMBALANCE", value: "+5.8%" },
          ].map((m, i) => (
            <div
              key={m.label}
              style={{
                padding: SPACE.comp,
                borderRight: i < 3 ? `1px solid ${COLOR.borderSubtle}` : "none",
                borderRightWidth: isMobile && i % 2 === 1 ? 0 : undefined,
              }}
            >
              <div
                style={{
                  fontSize: "0.625rem",
                  fontWeight: 600,
                  letterSpacing: "0.06em",
                  color: COLOR.textFaint,
                  marginBottom: SPACE.xs,
                }}
              >
                {m.label}
              </div>
              <div
                style={{
                  fontSize: "1.125rem",
                  fontWeight: 700,
                  color: COLOR.textPrimary,
                  fontFamily: TYPE.data,
                }}
              >
                {m.value}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ═══ VOLATILITY REGIME ═══ */}
      <div>
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.08em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
            marginBottom: SPACE.comp,
          }}
        >
          Volatility Regime
        </div>
        <div
          style={{
            display: "flex",
            gap: SPACE.cardLg,
            flexWrap: "wrap",
            marginBottom: SPACE.comp,
          }}
        >
          <div>
            <div
              style={{
                fontSize: "0.625rem",
                fontWeight: 600,
                letterSpacing: "0.06em",
                color: COLOR.textFaint,
                marginBottom: SPACE.xs,
              }}
            >
              ATM IV
            </div>
            <div
              style={{
                fontSize: "1rem",
                fontWeight: 700,
                color: COLOR.textPrimary,
                fontFamily: TYPE.data,
              }}
            >
              14.2%
            </div>
          </div>
          <div>
            <div
              style={{
                fontSize: "0.625rem",
                fontWeight: 600,
                letterSpacing: "0.06em",
                color: COLOR.textFaint,
                marginBottom: SPACE.xs,
              }}
            >
              INDIA VIX
            </div>
            <div
              style={{
                fontSize: "1rem",
                fontWeight: 700,
                color: COLOR.textPrimary,
                fontFamily: TYPE.data,
              }}
            >
              13.8
            </div>
          </div>
          <div>
            <div
              style={{
                fontSize: "0.625rem",
                fontWeight: 600,
                letterSpacing: "0.06em",
                color: COLOR.textFaint,
                marginBottom: SPACE.xs,
              }}
            >
              IV REGIME
            </div>
            <div
              style={{
                fontSize: "1rem",
                fontWeight: 700,
                color: COLOR.textPrimary,
                fontFamily: TYPE.data,
              }}
            >
              NORMAL
            </div>
          </div>
        </div>
        {/* Volatility scale */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: SPACE.small,
          }}
        >
          <span
            style={{
              fontSize: "0.625rem",
              color: COLOR.textFaint,
              fontFamily: TYPE.data,
              letterSpacing: "0.04em",
            }}
          >
            LOW
          </span>
          <div
            style={{
              flex: 1,
              height: 2,
              background: `linear-gradient(to right, ${COLOR.textFaint}, ${COLOR.strategy}, ${COLOR.textFaint})`,
              position: "relative",
            }}
          >
            <div
              style={{
                position: "absolute",
                left: "45%",
                top: "50%",
                transform: "translate(-50%, -50%)",
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: COLOR.strategy,
                border: `2px solid ${COLOR.surface}`,
              }}
            />
          </div>
          <span
            style={{
              fontSize: "0.625rem",
              color: COLOR.textFaint,
              fontFamily: TYPE.data,
              letterSpacing: "0.04em",
            }}
          >
            HIGH
          </span>
        </div>
      </div>

      {/* ═══ GAMMA / POSITIONING ═══ */}
      <div>
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.08em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
            marginBottom: SPACE.comp,
          }}
        >
          Gamma & Positioning
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: SPACE.small,
            flexWrap: "wrap",
            fontFamily: TYPE.data,
            fontSize: "0.875rem",
            color: COLOR.textMuted,
          }}
        >
          <span style={{ color: COLOR.textFaint }}>25,400</span>
          <span style={{ color: COLOR.borderSubtle }}>────────</span>
          <span style={{ color: COLOR.strategy, fontWeight: 700 }}>25,470</span>
          <span style={{ color: COLOR.borderSubtle }}>──────</span>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: COLOR.textPrimary,
              display: "inline-block",
            }}
          />
          <span style={{ color: COLOR.textPrimary, fontWeight: 700 }}>25,500</span>
          <span style={{ color: COLOR.borderSubtle }}>──────</span>
          <span style={{ color: COLOR.textFaint }}>25,600</span>
        </div>
        <div
          style={{
            display: "flex",
            gap: SPACE.small,
            marginTop: SPACE.xs,
            fontFamily: TYPE.data,
            fontSize: "0.625rem",
            color: COLOR.textFaint,
            letterSpacing: "0.04em",
          }}
        >
          <span marginLeft="25,400" />
          <span style={{ color: COLOR.strategy }}>GAMMA FLIP</span>
          <span flex={1} />
          <span>SPOT</span>
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: COLOR.borderSubtle }} />

      {/* ═══ MARKET READ ═══ */}
      <div>
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.08em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
            marginBottom: SPACE.small,
          }}
        >
          Market Read
        </div>
        <p
          style={{
            fontSize: TYPE.bodySmall.size,
            color: COLOR.textSecondary,
            lineHeight: 1.65,
            margin: 0,
          }}
        >
          {MARKET_READ}
        </p>
      </div>

      {/* ═══ DECISION CONTEXT ═══ */}
      <div>
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.08em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
            marginBottom: SPACE.comp,
          }}
        >
          Decision Context
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)",
            gap: SPACE.comp,
          }}
        >
          {[
            { label: "DIRECTION", value: "NEUTRAL" },
            { label: "VOLATILITY", value: "MODERATE" },
            { label: "POSITIONING", value: "BALANCED" },
            { label: "RISK", value: "CONTROLLED" },
          ].map((d) => (
            <div
              key={d.label}
              style={{
                padding: `${SPACE.small} ${SPACE.comp}`,
                background: COLOR.baseElevated,
                border: `1px solid ${COLOR.borderSubtle}`,
                borderRadius: RADIUS.sm,
              }}
            >
              <div
                style={{
                  fontSize: "0.5625rem",
                  fontWeight: 600,
                  letterSpacing: "0.08em",
                  color: COLOR.textFaint,
                  marginBottom: SPACE.xs,
                }}
              >
                {d.label}
              </div>
              <div
                style={{
                  fontSize: "0.8125rem",
                  fontWeight: 700,
                  color: COLOR.textPrimary,
                  fontFamily: TYPE.data,
                }}
              >
                {d.value}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ═══ GREEKS ═══ */}
      <div>
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.08em",
            color: COLOR.textFaint,
            textTransform: "uppercase",
            marginBottom: SPACE.comp,
          }}
        >
          Greeks
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)",
            gap: SPACE.comp,
          }}
        >
          {[
            { name: "Delta", value: "-0.02" },
            { name: "Gamma", value: "0.0003" },
            { name: "Theta", value: "+42.15" },
            { name: "Vega", value: "-18.40" },
          ].map((g) => (
            <div key={g.name}>
              <div
                style={{
                  fontSize: "0.625rem",
                  fontWeight: 600,
                  letterSpacing: "0.06em",
                  color: COLOR.textFaint,
                  marginBottom: SPACE.xs,
                }}
              >
                {g.name}
              </div>
              <div
                style={{
                  fontSize: "1rem",
                  fontWeight: 700,
                  color: COLOR.textPrimary,
                  fontFamily: TYPE.data,
                }}
              >
                {g.value}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Demo label */}
      <div style={{ textAlign: "center", paddingTop: SPACE.small }}>
        <DemoLabel style={{ fontSize: "0.625rem" }} />
      </div>
    </div>
  );
}
