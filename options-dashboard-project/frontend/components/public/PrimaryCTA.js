// StrikeNova Primary CTA — Anatomical interaction
// Hover/focus reveals the button's construction: icon, spacing, surface, radius
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
  .sn-cta-annotation--spacing,
  .sn-cta-annotation--radius {
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

  // ICON: right side, diagonal up-right
  const iconTargetX = dims.rightEdge - 14;
  const iconTargetY = dims.centerY;
  const iconLabelX = iconTargetX + 35;
  const iconLabelY = iconTargetY - 18;

  // SPACING: left side, horizontal left
  const spacingTargetX = dims.left + dims.paddingLeft;
  const spacingTargetY = dims.centerY;
  const spacingLabelX = spacingTargetX - 38;
  const spacingLabelY = spacingTargetY;

  // SURFACE: bottom, vertical down
  const surfaceTargetX = dims.centerX;
  const surfaceTargetY = dims.centerY;
  const surfaceLabelX = dims.centerX;
  const surfaceLabelY = dims.centerY + 42;

  // RADIUS: top-right corner, diagonal up-right
  const radiusTargetX = dims.rightEdge - dims.borderRadius;
  const radiusTargetY = dims.top + dims.borderRadius;
  const radiusLabelX = radiusTargetX + 30;
  const radiusLabelY = radiusTargetY - 12;

  // DIRECTION: bottom-right, diagonal down-right
  const directionTargetX = dims.rightEdge + 6;
  const directionTargetY = dims.centerY + 16;
  const directionLabelX = directionTargetX + 32;
  const directionLabelY = directionTargetY + 8;

  return (
    <svg
      className="sn-cta-annotations"
      aria-hidden="true"
      width="100%"
      height="100%"
      style={{ overflow: "visible" }}
    >
      {/* ICON */}
      <g className="sn-cta-annotation sn-cta-annotation--icon" style={{ transitionDelay: "50ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={iconTargetX}
          y1={iconTargetY}
          x2={iconLabelX - labelGap}
          y2={iconLabelY}
        />
        <circle className="sn-cta-annotation-dot" cx={iconTargetX} cy={iconTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={iconLabelX - labelGap} cy={iconLabelY} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={iconLabelX}
          y={iconLabelY + 3}
        >
          ICON
        </text>
      </g>

      {/* SPACING */}
      <g className="sn-cta-annotation sn-cta-annotation--spacing" style={{ transitionDelay: "100ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={spacingTargetX}
          y1={spacingTargetY}
          x2={spacingLabelX + labelGap}
          y2={spacingLabelY}
        />
        <line
          className="sn-cta-annotation-line"
          x1={dims.left}
          y1={dims.top - 4}
          x2={dims.left}
          y2={dims.bottomEdge + 4}
          strokeDasharray="2 2"
        />
        <circle className="sn-cta-annotation-dot" cx={spacingTargetX} cy={spacingTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={spacingLabelX + labelGap} cy={spacingLabelY} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={spacingLabelX}
          y={spacingLabelY + 3}
          textAnchor="end"
        >
          SPACING
        </text>
      </g>

      {/* SURFACE */}
      <g className="sn-cta-annotation sn-cta-annotation--surface" style={{ transitionDelay: "150ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={surfaceTargetX}
          y1={surfaceTargetY}
          x2={surfaceLabelX}
          y2={surfaceLabelY - labelGap}
        />
        <circle className="sn-cta-annotation-dot" cx={surfaceTargetX} cy={surfaceTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={surfaceLabelX} cy={surfaceLabelY - labelGap} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={surfaceLabelX}
          y={surfaceLabelY + 3}
          textAnchor="middle"
        >
          SURFACE
        </text>
      </g>

      {/* RADIUS */}
      <g className="sn-cta-annotation sn-cta-annotation--radius" style={{ transitionDelay: "200ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={radiusTargetX}
          y1={radiusTargetY}
          x2={radiusLabelX - labelGap}
          y2={radiusLabelY}
        />
        <circle className="sn-cta-annotation-dot" cx={radiusTargetX} cy={radiusTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={radiusLabelX - labelGap} cy={radiusLabelY} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={radiusLabelX}
          y={radiusLabelY + 3}
        >
          RADIUS
        </text>
      </g>

      {/* DIRECTION */}
      <g className="sn-cta-annotation sn-cta-annotation--direction" style={{ transitionDelay: "175ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={directionTargetX}
          y1={directionTargetY}
          x2={directionLabelX - labelGap}
          y2={directionLabelY}
        />
        <circle className="sn-cta-annotation-dot" cx={directionTargetX} cy={directionTargetY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={directionLabelX - labelGap} cy={directionLabelY} r={DOT_R} />
        <text
          className="sn-cta-annotation-label"
          x={directionLabelX}
          y={directionLabelY + 3}
        >
          DIRECTION
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
