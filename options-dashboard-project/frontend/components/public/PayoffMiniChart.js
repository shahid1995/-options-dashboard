// =============================================================================
// PayoffMiniChart — Lightweight inline SVG payoff curve
// =============================================================================
"use client";
import React from "react";
import { COLOR, TYPE, SPACE } from "@/components/public/tokens";

/**
 * PayoffMiniChart — deterministic illustrative payoff curve.
 * Shows profit/loss zones, zero axis, strike labels, breakeven indicators.
 */
export default function PayoffMiniChart() {
  // Illustrative Iron Condor payoff data
  const width = 600;
  const height = 200;
  const padding = { top: 30, right: 30, bottom: 40, left: 50 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;
  const zeroY = padding.top + plotH / 2;

  // Strike prices
  const strikes = [25250, 25300, 25400, 25500, 25600, 25700, 25750];
  const minStrike = strikes[0];
  const maxStrike = strikes[strikes.length - 1];
  const strikeRange = maxStrike - minStrike;

  // Payoff values at each strike (illustrative Iron Condor)
  const payoffs = [-9750, -9750, 3250, 3250, 3250, -9750, -9750];
  const maxProfit = 3250;
  const maxLoss = -9750;
  const absMax = Math.max(Math.abs(maxProfit), Math.abs(maxLoss));

  // Convert to SVG coordinates
  const points = strikes.map((s, i) => {
    const x = padding.left + ((s - minStrike) / strikeRange) * plotW;
    const y = zeroY - (payoffs[i] / absMax) * (plotH / 2) * 0.85;
    return { x, y, strike: s, payoff: payoffs[i] };
  });

  // Build path
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  // Fill path (profit zone above zero)
  const fillPath = `${linePath} L${points[points.length - 1].x},${zeroY} L${points[0].x},${zeroY} Z`;

  // Breakeven levels
  const breakevens = [25250, 25750];

  return (
    <div style={{ width: "100%" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="auto"
        role="img"
        aria-label="Payoff diagram. Max profit ₹3,250. Max loss -₹9,750. Breakevens at 25,250 and 25,750."
        style={{ overflow: "visible" }}
      >
        {/* Grid lines */}
        {[0.25, 0.5, 0.75].map((frac) => {
          const y = padding.top + frac * plotH;
          return (
            <line
              key={`h-${frac}`}
              x1={padding.left}
              y1={y}
              x2={width - padding.right}
              y2={y}
              stroke={COLOR.borderSubtle}
              strokeWidth="1"
              opacity="0.3"
            />
          );
        })}

        {/* Zero axis */}
        <line
          x1={padding.left}
          y1={zeroY}
          x2={width - padding.right}
          y2={zeroY}
          stroke={COLOR.border}
          strokeWidth="1.5"
        />

        {/* Fill area (profit zone) */}
        <path d={fillPath} fill={COLOR.positiveDim} stroke="none" />

        {/* Payoff line */}
        <path
          d={linePath}
          fill="none"
          stroke={COLOR.textPrimary}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Breakeven markers */}
        {breakevens.map((be) => {
          const x = padding.left + ((be - minStrike) / strikeRange) * plotW;
          return (
            <g key={be}>
              <line
                x1={x}
                y1={padding.top}
                x2={x}
                y2={height - padding.bottom}
                stroke={COLOR.warning}
                strokeWidth="1"
                strokeDasharray="4 3"
                opacity="0.6"
              />
              <text
                x={x}
                y={height - padding.bottom + 14}
                textAnchor="middle"
                fill={COLOR.warning}
                fontSize="9"
                fontFamily={TYPE.data}
              >
                {be.toLocaleString("en-IN")}
              </text>
            </g>
          );
        })}

        {/* Strike labels */}
        {[25300, 25500, 25700].map((s) => {
          const x = padding.left + ((s - minStrike) / strikeRange) * plotW;
          return (
            <text
              key={s}
              x={x}
              y={height - padding.bottom + 28}
              textAnchor="middle"
              fill={COLOR.textFaint}
              fontSize="9"
              fontFamily={TYPE.data}
            >
              {s.toLocaleString("en-IN")}
            </text>
          );
        })}

        {/* Axis labels */}
        <text
          x={padding.left - 8}
          y={padding.top}
          textAnchor="end"
          fill={COLOR.positive}
          fontSize="9"
          fontFamily={TYPE.data}
        >
          PROFIT
        </text>
        <text
          x={padding.left - 8}
          y={zeroY - 4}
          textAnchor="end"
          fill={COLOR.textFaint}
          fontSize="9"
          fontFamily={TYPE.data}
        >
          0
        </text>
        <text
          x={padding.left - 8}
          y={height - padding.bottom}
          textAnchor="end"
          fill={COLOR.negative}
          fontSize="9"
          fontFamily={TYPE.data}
        >
          LOSS
        </text>
      </svg>

      {/* Accessible text alternative */}
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          gap: SPACE.cardLg,
          marginTop: SPACE.comp,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>
          Max Profit: <span style={{ color: COLOR.positive, fontWeight: 700 }}>₹3,250</span>
        </span>
        <span style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>
          Max Loss: <span style={{ color: COLOR.negative, fontWeight: 700 }}>-₹9,750</span>
        </span>
        <span style={{ fontSize: TYPE.caption.size, color: COLOR.textFaint }}>
          Breakevens: <span style={{ color: COLOR.warning, fontWeight: 700 }}>25,250 / 25,750</span>
        </span>
      </div>
    </div>
  );
}
