// =============================================================================
// PlatformPreview — Floating miniature platform preview (DEMO · ILLUSTRATIVE)
// =============================================================================
"use client";
import React from "react";
import { COLOR, TYPE, SPACE, RADIUS, SHADOW } from "@/components/public/tokens";
import { DemoLabel } from "@/components/public/truth";
import { useIsMobile } from "@/lib/ui";

export default function PlatformPreview() {
  const isMobile = useIsMobile();

  const metrics = [
    { label: "SPOT", value: "25,500" },
    { label: "PCR", value: "0.92" },
    { label: "ATM IV", value: "14.2%" },
    { label: "OI CHANGE", value: "+8.4%" },
  ];

  const greeks = [
    { label: "DELTA", value: "-0.02" },
    { label: "GAMMA", value: "0.0003" },
    { label: "THETA", value: "+42.15" },
    { label: "VEGA", value: "-18.40" },
  ];

  return (
    <div
      style={{
        width: "100%",
        maxWidth: 720,
        marginTop: SPACE.section,
        background: `linear-gradient(180deg, ${COLOR.surface}, ${COLOR.surfaceDeep})`,
        border: `1px solid ${COLOR.border}`,
        borderRadius: RADIUS.xl,
        padding: isMobile ? SPACE.card : SPACE.cardLg,
        boxShadow: SHADOW.lg,
        position: "relative",
        overflow: "hidden",
        transform: "perspective(1000px) rotateX(1deg)",
      }}
      className="sn-fade"
      role="figure"
      aria-label="Platform preview, illustrative data"
    >
      {/* Header bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: SPACE.compLg,
        }}
      >
        <span
          style={{
            fontSize: TYPE.labelSmall.size,
            fontWeight: 800,
            letterSpacing: "0.12em",
            color: COLOR.textPrimary,
          }}
        >
          STRIKENOVA
        </span>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.375rem",
            fontSize: TYPE.caption.size,
            color: COLOR.textFaint,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: COLOR.info,
              boxShadow: `0 0 6px ${COLOR.info}`,
            }}
          />
          MARKET STATE
        </span>
      </div>

      {/* Key metrics row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)",
          gap: SPACE.comp,
          marginBottom: SPACE.cardLg,
        }}
      >
        {metrics.map((m) => (
          <div key={m.label}>
            <div
              style={{
                fontSize: TYPE.caption.size,
                fontWeight: 600,
                letterSpacing: "0.06em",
                color: COLOR.textFaint,
                textTransform: "uppercase",
                marginBottom: SPACE.xs,
              }}
            >
              {m.label}
            </div>
            <div
              style={{
                fontSize: TYPE.data.size,
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

      {/* Signal visualization placeholder */}
      <div
        style={{
          background: COLOR.baseElevated,
          border: `1px solid ${COLOR.borderSubtle}`,
          borderRadius: RADIUS.md,
          padding: SPACE.card,
          marginBottom: SPACE.cardLg,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            fontSize: TYPE.caption.size,
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: COLOR.textFaint,
            marginBottom: SPACE.comp,
          }}
        >
          SIGNAL FIELD
        </div>
        {/* Mini OI bars */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: "0.25rem",
            height: 60,
            justifyContent: "center",
          }}
        >
          {[40, 65, 85, 70, 55, 90, 75, 50].map((h, i) => (
            <div
              key={i}
              style={{
                width: "100%",
                height: `${h}%`,
                background: i < 4 ? COLOR.negative : COLOR.positive,
                opacity: 0.7,
                borderRadius: "2px 2px 0 0",
              }}
            />
          ))}
        </div>
        {/* Strike labels */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginTop: SPACE.xs,
          }}
        >
          {[25.3, 25.4, 25.5, 25.6, 25.7].map((s) => (
            <span
              key={s}
              style={{
                fontSize: "0.625rem",
                color: COLOR.textFaint,
                fontFamily: TYPE.data,
              }}
            >
              {s}k
            </span>
          ))}
        </div>
      </div>

      {/* Greeks row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: SPACE.comp,
        }}
      >
        {greeks.map((g) => (
          <div key={g.label}>
            <div
              style={{
                fontSize: TYPE.caption.size,
                fontWeight: 600,
                letterSpacing: "0.06em",
                color: COLOR.textFaint,
                textTransform: "uppercase",
                marginBottom: SPACE.xs,
              }}
            >
              {g.label}
            </div>
            <div
              style={{
                fontSize: TYPE.dataSmall.size,
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

      {/* DEMO label */}
      <div style={{ marginTop: SPACE.cardLg, textAlign: "center" }}>
        <DemoLabel style={{ fontSize: "0.625rem" }} />
      </div>
    </div>
  );
}
