// StrikeNova Primary CTA — Anatomical interaction
// Hover/focus reveals the button's workflow anatomy: market state → strategy → risk → paper execution
// Self-contained component for homepage hero CTA.
// Anchor-driven geometry with refined connector system.

"use client";
import React, { useState, useRef, useEffect, useCallback } from "react";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "./tokens";

const DOT_R = 3;
const STROKE_WIDTH = 2;
const LABEL_FONT = `${TYPE.data}`;
const LABEL_SIZE = "9px";
const LABEL_WEIGHT = "600";
const LABEL_SPACING = "0.06em";
const LABEL_COLOR = COLOR.textSecondary;

const CTA_CSS = `
.sn-cta-wrapper {
  position: relative;
  display: inline-block;
  padding: 48px 60px;
}
.sn-cta-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.875rem 1.75rem;
  background: ${COLOR.strategy};
  color: #0B0E14;
  border: 1px solid ${COLOR.strategy};
  border-radius: ${RADIUS.md};
  font-family: inherit;
  font-weight: 600;
  font-size: 0.9375rem;
  line-height: 1;
  text-decoration: none;
  cursor: pointer;
  position: relative;
  overflow: visible;
  transition: background ${MOTION.fast} ${MOTION.easeOut},
              border-color ${MOTION.fast} ${MOTION.easeOut},
              box-shadow ${MOTION.fast} ${MOTION.easeOut};
  z-index: 2;
}
.sn-cta-primary:hover {
  background: #D9B36A;
  border-color: #D9B36A;
  box-shadow: 0 4px 16px rgba(201, 161, 90, 0.25);
}
.sn-cta-primary:active {
  transform: translateY(0);
}
.sn-cta-primary .sn-cta-label {
  position: relative;
  z-index: 2;
}
.sn-cta-primary .sn-cta-arrow {
  position: relative;
  z-index: 2;
  transition: transform 0.2s ${MOTION.easeOut};
}
.sn-cta-primary:hover .sn-cta-arrow {
  transform: translateX(3px);
}
.sn-cta-primary .sn-cta-trajectory {
  position: absolute;
  top: 50%;
  right: 1rem;
  width: 0;
  height: 1px;
  background: #0B0E14;
  opacity: 0;
  transform: translateY(-50%);
  transition: width 0.2s ${MOTION.easeOut},
              opacity 0.2s ${MOTION.easeOut};
  pointer-events: none;
}
.sn-cta-primary:hover .sn-cta-trajectory {
  width: 14px;
  opacity: 0.5;
}
.sn-cta-annotations {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 1;
}
.sn-cta-annotation {
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.25s ${MOTION.easeOut},
              transform 0.25s ${MOTION.easeOut};
}
.sn-cta-wrapper:hover .sn-cta-annotation,
.sn-cta-wrapper:focus-within .sn-cta-annotation {
  opacity: 1;
  transform: translateY(0);
}
.sn-cta-annotation-line {
  stroke: ${COLOR.textFaint};
  stroke-width: ${STROKE_WIDTH};
  fill: none;
}
.sn-cta-annotation-dot {
  fill: ${COLOR.strategy};
}
.sn-cta-annotation-label {
  font-family: ${LABEL_FONT};
  font-size: ${LABEL_SIZE};
  font-weight: ${LABEL_WEIGHT};
  letter-spacing: ${LABEL_SPACING};
  text-transform: uppercase;
  fill: ${LABEL_COLOR};
}
@media (max-width: 768px) {
  .sn-cta-wrapper {
    padding: 36px 40px;
  }
  .sn-cta-annotation--market-structure,
  .sn-cta-annotation--risk {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .sn-cta-primary,
  .sn-cta-primary .sn-cta-arrow,
  .sn-cta-primary .sn-cta-trajectory,
  .sn-cta-annotation {
    transition-duration: 0.01ms !important;
  }
  .sn-cta-primary:hover .sn-cta-arrow {
    transform: none;
  }
  .sn-cta-primary:hover .sn-cta-trajectory {
    display: none;
  }
  .sn-cta-annotation {
    transform: none;
  }
}
`;

function Annotations({ buttonRef, wrapperRef }) {
  const [dims, setDims] = useState(null);

  const measure = useCallback(() => {
    if (!buttonRef.current || !wrapperRef.current) return;

    const buttonRect = buttonRef.current.getBoundingClientRect();
    const wrapperRect = wrapperRef.current.getBoundingClientRect();

    const left = buttonRect.left - wrapperRect.left;
    const top = buttonRect.top - wrapperRect.top;
    const width = buttonRect.width;
    const height = buttonRect.height;

    const paddingLeft = 28;
    const borderRadius = 8;

    setDims({
      left,
      top,
      width,
      height,
      paddingLeft,
      borderRadius,
      centerX: left + width / 2,
      centerY: top + height / 2,
      rightEdge: left + width,
      bottomEdge: top + height,
    });
  }, [buttonRef, wrapperRef]);

  useEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  if (!dims) return null;

  const labelGap = 8;
  const labelHeight = 12;

  // Market state: upper-right, diagonal up-right from top edge
  const msTargetX = dims.centerX + 30;
  const msTargetY = dims.top + 4;
  const msLabelX = msTargetX + 30;
  const msLabelY = msTargetY - 16;

  // Market structure: right side, horizontal right from mid-body
  const mstTargetX = dims.rightEdge - 8;
  const mstTargetY = dims.centerY - 4;
  const mstLabelX = mstTargetX + 30;
  const mstLabelY = mstTargetY;

  // Strategy: bottom-right area, clearly on right side
  const stratTargetX = dims.rightEdge - 30;
  const stratTargetY = dims.centerY;
  const stratLabelX = stratTargetX + 30;
  const stratLabelY = dims.centerY + 42;

  // Risk: lower-right, diagonal down-right from right edge
  const riskTargetX = dims.rightEdge - 4;
  const riskTargetY = dims.top + dims.height * 0.7;
  const riskLabelX = riskTargetX + 30;
  const riskLabelY = riskTargetY + 18;

  // Paper execution: far lower-right, diagonal from arrow trajectory
  const peTargetX = dims.rightEdge + 6;
  const peTargetY = dims.bottomEdge + 4;
  const peLabelX = peTargetX + 30;
  const peLabelY = peTargetY + 16;

  return (
    <svg
      className="sn-cta-annotations"
      aria-hidden="true"
      width="100%"
      height="100%"
      style={{ overflow: "visible" }}
    >
      {/* Market state: upper-right */}
      <g className="sn-cta-annotation sn-cta-annotation--market-state" style={{ transitionDelay: "50ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={msTargetX}
          y1={msTargetY}
          x2={msLabelX - labelGap}
          y2={msLabelY}
        />
        <circle className="sn-cta-annotation-dot" cx={msTargetX} cy={msTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={msLabelX - labelGap} cy={msLabelY} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={msLabelX}
          y={msLabelY + 3}
        >
          Market state
        </text>
      </g>

      {/* Market structure: right side */}
      <g className="sn-cta-annotation sn-cta-annotation--market-structure" style={{ transitionDelay: "100ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={mstTargetX}
          y1={mstTargetY}
          x2={mstLabelX - labelGap}
          y2={mstLabelY}
        />
        <circle className="sn-cta-annotation-dot" cx={mstTargetX} cy={mstTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={mstLabelX - labelGap} cy={mstLabelY} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={mstLabelX}
          y={mstLabelY + 3}
        >
          Market structure
        </text>
      </g>

      {/* Strategy: bottom-center */}
      <g className="sn-cta-annotation sn-cta-annotation--strategy" style={{ transitionDelay: "150ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={stratTargetX}
          y1={stratTargetY}
          x2={stratLabelX}
          y2={stratLabelY - labelGap}
        />
        <circle className="sn-cta-annotation-dot" cx={stratTargetX} cy={stratTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={stratLabelX} cy={stratLabelY - labelGap} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={stratLabelX}
          y={stratLabelY + 3}
          textAnchor="middle"
        >
          Strategy
        </text>
      </g>

      {/* Risk: lower-right */}
      <g className="sn-cta-annotation sn-cta-annotation--risk" style={{ transitionDelay: "175ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={riskTargetX}
          y1={riskTargetY}
          x2={riskLabelX - labelGap}
          y2={riskLabelY}
        />
        <circle className="sn-cta-annotation-dot" cx={riskTargetX} cy={riskTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={riskLabelX - labelGap} cy={riskLabelY} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={riskLabelX}
          y={riskLabelY + 3}
        >
          Risk
        </text>
      </g>

      {/* Paper execution: far lower-right */}
      <g className="sn-cta-annotation sn-cta-annotation--paper-execution" style={{ transitionDelay: "200ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={peTargetX}
          y1={peTargetY}
          x2={peLabelX - labelGap}
          y2={peLabelY}
        />
        <circle className="sn-cta-annotation-dot" cx={peTargetX} cy={peTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={peLabelX - labelGap} cy={peLabelY} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={peLabelX}
          y={peLabelY + 3}
        >
          Paper execution
        </text>
      </g>
    </svg>
  );
}

export default function PrimaryCTA({ href = "/features", children }) {
  const buttonRef = useRef(null);
  const wrapperRef = useRef(null);

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CTA_CSS }} />
      <div className="sn-cta-wrapper" ref={wrapperRef}>
        <Annotations buttonRef={buttonRef} wrapperRef={wrapperRef} />
        <a href={href} className="sn-cta-primary ds-focus-ring" ref={buttonRef}>
          <span className="sn-cta-label">{children}</span>
          <svg
            className="sn-cta-arrow"
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M2 7h10M8 3l4 4-4 4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="sn-cta-trajectory" aria-hidden="true" />
        </a>
      </div>
    </>
  );
}
