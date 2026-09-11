// =============================================================================
// StrikeNova Public Design System — SignalField
// =============================================================================
// The signature StrikeNova visualization: a market-native composition of
// pricing, positioning, volatility, greeks, structure, and market state.
//
// Composes P1 primitives: SignalNode, StrikeRail, SignalLine, GridOverlay,
// DataTrace, Metric, VisualizationFrame, tokens, motion.
//
// No live data. No network. No Math.random(). Fully deterministic.
// =============================================================================

import React from "react";
import { COLOR, TYPE, SPACE, RADIUS, SHADOW, MOTION } from "./tokens";
import { SignalNode, StrikeRail, SignalLine, GridOverlay, DataTrace } from "./signals";
import { Metric } from "./Metric";
import { DemoLabel } from "./truth";

// =============================================================================
// DETERMINISTIC DEMO STATE
// =============================================================================
// All values are illustrative. No live data. No randomness.

export const DEMO_SIGNAL_STATE = {
  spot: 25500,
  strikes: [25300, 25400, 25500, 25600, 25700],
  spotIndex: 2,
  oi: {
    call: 184250,
    put: 217800,
    pcr: 1.18,
    concentration: "25,500",
  },
  oiChange: {
    direction: "PE",
    value: "+12,400",
    bias: "bearish",
  },
  iv: {
    atm: "14.2%",
    vix: "13.8",
    skew: "slight put skew",
    state: "elevated",
    byStrike: [
      { strike: 25300, value: 15.8 },
      { strike: 25400, value: 14.9 },
      { strike: 25500, value: 14.2 },
      { strike: 25600, value: 14.6 },
      { strike: 25700, value: 15.4 },
    ],
  },
  greeks: {
    delta: "-0.02",
    gamma: "0.0003",
    theta: "+42.15",
    vega: "-18.40",
  },
  structure: {
    resistance: 25700,
    pivot: 25500,
    support: 25300,
  },
  marketState: {
    label: "Balanced with bearish pressure",
    bias: "neutral",
    confidence: "illustrative",
  },
};

// =============================================================================
// SIGNAL FIELD COMPONENT
// =============================================================================

export function SignalField({ state = DEMO_SIGNAL_STATE, style, ...rest }) {
  const { spot, strikes, spotIndex, oi, oiChange, iv, greeks, structure, marketState } = state;

  // Compute layout dimensions
  const width = 600;
  const height = 320;
  const padding = { top: 50, right: 30, bottom: 50, left: 50 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  // Compute strike positions
  const strikeRange = strikes[strikes.length - 1] - strikes[0];
  const strikePositions = strikes.map((s) => ({
    x: padding.left + ((s - strikes[0]) / strikeRange) * plotW,
    y: padding.top + plotH / 2,
    value: s,
    isSpot: s === spot,
  }));

  // Compute OI bar heights (normalized)
  const maxOi = Math.max(oi.call, oi.put);
  const callBarH = (oi.call / maxOi) * (plotH * 0.35);
  const putBarH = (oi.put / maxOi) * (plotH * 0.35);

  // Compute OI Y-axis ticks (5 ticks from 0 to maxOi)
  const oiTicks = [0, 50000, 100000, 150000, 200000, 250000];

  // Compute IV curve points
  const ivValues = iv.byStrike.map((d) => d.value);
  const ivMin = Math.min(...ivValues) - 0.5;
  const ivMax = Math.max(...ivValues) + 0.5;
  const ivRange = ivMax - ivMin;
  const ivPlotTop = padding.top + 10;
  const ivPlotBottom = padding.top + plotH * 0.4;
  const ivPlotH = ivPlotBottom - ivPlotTop;
  const ivPoints = iv.byStrike.map((d, i) => {
    const x = padding.left + (i / (iv.byStrike.length - 1)) * plotW;
    const y = ivPlotBottom - ((d.value - ivMin) / ivRange) * ivPlotH;
    return { x, y, strike: d.strike, value: d.value };
  });
  const ivPathD = ivPoints.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");

  // Compute structure levels
  const structureY = padding.top + plotH * 0.75;

  // Find strike positions for structure connections
  const supportStrike = strikePositions.find((s) => s.value === structure.support);
  const pivotStrike = strikePositions.find((s) => s.value === structure.pivot);
  const resistanceStrike = strikePositions.find((s) => s.value === structure.resistance);

  return (
    <div
      style={{
        width: "100%",
        position: "relative",
        fontFamily: TYPE.data,
        ...style,
      }}
      role="img"
      aria-label={`Signal Field, illustrative data. Spot: ${spot ? spot.toLocaleString("en-IN") : "—"}. ${marketState ? marketState.label : ""}.`}
      {...rest}
    >
      {/* Grid overlay */}
      <GridOverlay spacing={32} color={COLOR.borderSubtle} />

      {/* Main SVG canvas */}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="auto"
        style={{ position: "relative", overflow: "visible" }}
        aria-hidden="true"
      >
        {/* --- Layer 1: Spot reference line --- */}
        <line
          x1={padding.left + ((spot - strikes[0]) / strikeRange) * plotW}
          y1={padding.top}
          x2={padding.left + ((spot - strikes[0]) / strikeRange) * plotW}
          y2={height - padding.bottom}
          stroke={COLOR.strategy}
          strokeWidth={1}
          strokeDasharray="4 4"
          opacity={0.4}
        />

        {/* --- Layer 2: Strike rail --- */}
        <line
          x1={padding.left}
          y1={padding.top + plotH / 2}
          x2={width - padding.right}
          y2={padding.top + plotH / 2}
          stroke={COLOR.borderSubtle}
          strokeWidth={1}
        />

        {/* Strike markers */}
        {strikePositions.map((pos, i) => (
          <g key={i}>
            <circle
              cx={pos.x}
              cy={pos.y}
              r={pos.isSpot ? 5 : 3}
              fill={pos.isSpot ? COLOR.strategy : COLOR.textMuted}
              opacity={pos.isSpot ? 1 : 0.6}
            />
            <text
              x={pos.x}
              y={pos.y + 18}
              textAnchor="middle"
              fill={pos.isSpot ? COLOR.strategy : COLOR.textFaint}
              fontSize={10}
              fontFamily={TYPE.data}
              fontWeight={pos.isSpot ? 700 : 400}
            >
              {pos.value ? pos.value.toLocaleString("en-IN") : "—"}
            </text>
          </g>
        ))}

        {/* --- Layer 3: OI bars with Y-axis --- */}
        {/* Y-axis ticks and labels */}
        {oiTicks.map((tick) => {
          const y = padding.top + plotH / 2 - (tick / maxOi) * (plotH * 0.35);
          return (
            <g key={tick}>
              <line
                x1={padding.left - 5}
                y1={y}
                x2={padding.left}
                y2={y}
                stroke={COLOR.borderSubtle}
                strokeWidth={1}
              />
              <text
                x={padding.left - 8}
                y={y + 3}
                textAnchor="end"
                fill={COLOR.textFaint}
                fontSize={8}
                fontFamily={TYPE.data}
              >
                {tick >= 1000 ? `${tick / 1000}k` : tick}
              </text>
            </g>
          );
        })}

        {/* Baseline */}
        <line
          x1={padding.left}
          y1={padding.top + plotH / 2}
          x2={width - padding.right}
          y2={padding.top + plotH / 2}
          stroke={COLOR.borderSubtle}
          strokeWidth={1}
          opacity={0.5}
        />

        {/* Call OI bar (left side) */}
        <rect
          x={padding.left + plotW * 0.15 - 20}
          y={padding.top + plotH / 2 - callBarH}
          width={16}
          height={callBarH}
          fill={COLOR.negative}
          opacity={0.7}
          rx={2}
        />
        <text
          x={padding.left + plotW * 0.15 - 12}
          y={padding.top + plotH / 2 - callBarH - 6}
          textAnchor="middle"
          fill={COLOR.negative}
          fontSize={9}
          fontFamily={TYPE.data}
        >
          {oi.call.toLocaleString("en-IN")}
        </text>

        {/* Put OI bar (right side) */}
        <rect
          x={padding.left + plotW * 0.85 - 20}
          y={padding.top + plotH / 2 - putBarH}
          width={16}
          height={putBarH}
          fill={COLOR.positive}
          opacity={0.7}
          rx={2}
        />
        <text
          x={padding.left + plotW * 0.85 - 12}
          y={padding.top + plotH / 2 - putBarH - 6}
          textAnchor="middle"
          fill={COLOR.positive}
          fontSize={9}
          fontFamily={TYPE.data}
        >
          {oi.put.toLocaleString("en-IN")}
        </text>

        {/* OI Legend */}
        <text
          x={padding.left + plotW * 0.15 - 12}
          y={padding.top + plotH / 2 + 16}
          textAnchor="middle"
          fill={COLOR.negative}
          fontSize={8}
          fontFamily={TYPE.data}
          fontWeight={600}
        >
          CALL OI
        </text>
        <text
          x={padding.left + plotW * 0.85 - 12}
          y={padding.top + plotH / 2 + 16}
          textAnchor="middle"
          fill={COLOR.positive}
          fontSize={8}
          fontFamily={TYPE.data}
          fontWeight={600}
        >
          PUT OI
        </text>
        <text
          x={padding.left + plotW / 2}
          y={padding.top + plotH / 2 + 16}
          textAnchor="middle"
          fill={COLOR.textFaint}
          fontSize={8}
          fontFamily={TYPE.data}
        >
          OPEN INTEREST · CONTRACTS
        </text>

        {/* --- Layer 4: IV curve (implied volatility by strike) --- */}
        <path
          d={ivPathD}
          fill="none"
          stroke={COLOR.intelligence}
          strokeWidth={2}
          opacity={0.8}
        />
        {ivPoints.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={3} fill={COLOR.intelligence} />
        ))}
        <text
          x={padding.left + plotW / 2}
          y={ivPlotTop - 6}
          textAnchor="middle"
          fill={COLOR.intelligence}
          fontSize={10}
          fontFamily={TYPE.data}
          fontWeight={600}
        >
          IMPLIED VOLATILITY · DEMO
        </text>

        {/* --- Layer 5: Structure levels with guide lines --- */}
        {/* Support guide line */}
        {supportStrike && (
          <line
            x1={supportStrike.x}
            y1={supportStrike.y}
            x2={supportStrike.x}
            y2={structureY + 20}
            stroke={COLOR.positive}
            strokeWidth={1}
            strokeDasharray="2 2"
            opacity={0.4}
          />
        )}
        {/* Resistance guide line */}
        {resistanceStrike && (
          <line
            x1={resistanceStrike.x}
            y1={resistanceStrike.y}
            x2={resistanceStrike.x}
            y2={structureY - 20}
            stroke={COLOR.negative}
            strokeWidth={1}
            strokeDasharray="2 2"
            opacity={0.4}
          />
        )}
        {/* Pivot guide line */}
        {pivotStrike && (
          <line
            x1={pivotStrike.x}
            y1={pivotStrike.y}
            x2={pivotStrike.x}
            y2={structureY}
            stroke={COLOR.strategy}
            strokeWidth={1}
            strokeDasharray="2 2"
            opacity={0.4}
          />
        )}

        {/* Resistance */}
        <line
          x1={padding.left}
          y1={structureY - 20}
          x2={width - padding.right}
          y2={structureY - 20}
          stroke={COLOR.negative}
          strokeWidth={1}
          strokeDasharray="2 4"
          opacity={0.5}
        />
        <text x={width - padding.right} y={structureY - 24} textAnchor="end" fill={COLOR.negative} fontSize={8} fontFamily={TYPE.data}>
          R {structure.resistance.toLocaleString("en-IN")}
        </text>
        {/* Pivot */}
        <line
          x1={padding.left}
          y1={structureY}
          x2={width - padding.right}
          y2={structureY}
          stroke={COLOR.strategy}
          strokeWidth={1}
          strokeDasharray="4 4"
          opacity={0.5}
        />
        <text x={width - padding.right} y={structureY - 4} textAnchor="end" fill={COLOR.strategy} fontSize={8} fontFamily={TYPE.data}>
          P {structure.pivot.toLocaleString("en-IN")}
        </text>
        {/* Support */}
        <line
          x1={padding.left}
          y1={structureY + 20}
          x2={width - padding.right}
          y2={structureY + 20}
          stroke={COLOR.positive}
          strokeWidth={1}
          strokeDasharray="2 4"
          opacity={0.5}
        />
        <text x={width - padding.right} y={structureY + 32} textAnchor="end" fill={COLOR.positive} fontSize={8} fontFamily={TYPE.data}>
          S {structure.support.toLocaleString("en-IN")}
        </text>

        {/* --- Layer 6: Market state indicator --- */}
        <circle
          cx={width / 2}
          cy={height - padding.bottom + 10}
          r={4}
          fill={marketState.bias === "neutral" ? COLOR.info : marketState.bias === "bullish" ? COLOR.positive : COLOR.negative}
        />
        <text
          x={width / 2 + 10}
          y={height - padding.bottom + 14}
          fill={COLOR.textMuted}
          fontSize={9}
          fontFamily={TYPE.data}
        >
          {marketState.label}
        </text>
      </svg>

      {/* --- Greeks breakdown (responsive, full names) --- */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: SPACE.comp,
          marginTop: SPACE.comp,
        }}
      >
        <div>
          <div style={{ fontSize: TYPE.caption.size, fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, textTransform: "uppercase" }}>Delta</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>{greeks.delta}</div>
          <div style={{ fontSize: "0.6875rem", color: COLOR.textFaint }}>Price sensitivity</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, textTransform: "uppercase" }}>Gamma</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.textPrimary, fontFamily: TYPE.data }}>{greeks.gamma}</div>
          <div style={{ fontSize: "0.6875rem", color: COLOR.textFaint }}>Delta change</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, textTransform: "uppercase" }}>Theta</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.positive, fontFamily: TYPE.data }}>{greeks.theta}</div>
          <div style={{ fontSize: "0.6875rem", color: COLOR.textFaint }}>Time decay</div>
        </div>
        <div>
          <div style={{ fontSize: TYPE.caption.size, fontWeight: 600, letterSpacing: "0.06em", color: COLOR.textFaint, textTransform: "uppercase" }}>Vega</div>
          <div style={{ fontSize: TYPE.data.size, fontWeight: 700, color: COLOR.negative, fontFamily: TYPE.data }}>{greeks.vega}</div>
          <div style={{ fontSize: "0.6875rem", color: COLOR.textFaint }}>Volatility sensitivity</div>
        </div>
      </div>

      {/* --- Supporting metrics below the visualization --- */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: SPACE.comp,
          marginTop: SPACE.comp,
        }}
      >
        <Metric label="SPOT" value={spot} status="DEMO" source="ILLUSTRATIVE" size="sm" />
        <Metric label="PCR (OI)" value={oi.pcr} decimals={2} status="DEMO" source="ILLUSTRATIVE" size="sm" />
        <Metric label="ATM IV" value={iv.atm} status="DEMO" source="ILLUSTRATIVE" size="sm" />
        <Metric label="OI CHANGE" value={oiChange.value} status="DEMO" source="ILLUSTRATIVE" size="sm" />
      </div>
    </div>
  );
}
