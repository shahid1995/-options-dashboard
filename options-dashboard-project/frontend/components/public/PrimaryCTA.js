// StrikeNova Primary CTA — Anatomical interaction
// Hover/focus reveals the construction of the button: icon, spacing, surface, radius, direction.
// Self-contained component for homepage hero CTA.

"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { COLOR, TYPE, RADIUS, MOTION } from "./tokens";

const DOT_R = 2.5;
const STROKE_WIDTH = 1;
const LABEL_FONT = TYPE.data;

const CTA_CSS = `
.sn-cta-wrapper {
  position: relative;
  display: inline-block;
  padding: 44px 56px;
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
  overflow: hidden;
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
.sn-cta-primary .sn-cta-label,
.sn-cta-primary .sn-cta-arrow {
  position: relative;
  z-index: 2;
}
.sn-cta-primary .sn-cta-arrow {
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
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
  z-index: 1;
}
.sn-cta-annotation-rail {
  opacity: 0;
  transition: opacity 0.22s ${MOTION.easeOut};
}
.sn-cta-wrapper:hover .sn-cta-annotation-rail,
.sn-cta-wrapper:focus-within .sn-cta-annotation-rail {
  opacity: 1;
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
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  fill: ${COLOR.textSecondary};
}
.sn-cta-annotation-measure {
  stroke: ${COLOR.textFaint};
  stroke-width: 1;
  fill: none;
  stroke-dasharray: 2 2;
}
@media (max-width: 768px) {
  .sn-cta-wrapper {
    padding: 36px 42px;
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
  .sn-cta-annotation-rail {
    transition-duration: 0.01ms !important;
  }
  .sn-cta-primary:hover .sn-cta-arrow {
    transform: none;
  }
  .sn-cta-primary:hover .sn-cta-trajectory {
    display: none;
  }
}
`;

function Annotations({ buttonRef, wrapperRef }) {
  const [dims, setDims] = useState(null);

  const measure = useCallback(() => {
    if (!buttonRef.current || !wrapperRef.current) return;
    const buttonRect = buttonRef.current.getBoundingClientRect();
    const wrapperRect = wrapperRef.current.getBoundingClientRect();
    setDims({
      left: buttonRect.left - wrapperRect.left,
      top: buttonRect.top - wrapperRect.top,
      width: buttonRect.width,
      height: buttonRect.height,
    });
  }, [buttonRef, wrapperRef]);

  useEffect(() => {
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (observer && buttonRef.current) observer.observe(buttonRef.current);
    if (observer && wrapperRef.current) observer.observe(wrapperRef.current);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measure]);

  if (!dims) return null;

  const { left, top, width, height } = dims;
  const right = left + width;
  const bottom = top + height;
  const centerY = top + height / 2;
  const railX = right + 42;
  const labelX = railX + 10;

  const radiusTargetX = right - 8;
  const radiusTargetY = top + 8;
  const radiusRailY = top - 18;

  const iconTargetX = right - 10;
  const iconTargetY = centerY;
  const iconRailY = centerY - 18;

  const spacingTargetX = left + 24;
  const spacingTargetY = top - 7;
  const spacingRailY = centerY + 2;

  const directionTargetX = right - Math.min(52, width * 0.2);
  const directionTargetY = centerY + 1;
  const directionRailY = centerY + 22;

  const surfaceTargetX = left + width * 0.58;
  const surfaceTargetY = bottom;
  const surfaceLabelY = bottom + 30;

  return (
    <svg className="sn-cta-annotations" aria-hidden="true">
      <g className="sn-cta-annotation-rail" style={{ transitionDelay: "40ms" }}>
        {/* Radius — top of the right-side rail */}
        <g className="sn-cta-annotation sn-cta-annotation--radius">
          <line className="sn-cta-annotation-line" x1={radiusTargetX} y1={radiusTargetY} x2={railX} y2={radiusRailY} />
          <circle className="sn-cta-annotation-dot" cx={radiusTargetX} cy={radiusTargetY} r={DOT_R} />
          <circle className="sn-cta-annotation-dot" cx={railX} cy={radiusRailY} r={DOT_R} />
          <text className="sn-cta-annotation-label" x={labelX} y={radiusRailY + 3} textAnchor="start">RADIUS</text>
        </g>

        {/* Icon — spaced below radius */}
        <g className="sn-cta-annotation sn-cta-annotation--icon" style={{ transitionDelay: "60ms" }}>
          <line className="sn-cta-annotation-line" x1={iconTargetX} y1={iconTargetY} x2={railX} y2={iconRailY} />
          <circle className="sn-cta-annotation-dot" cx={iconTargetX} cy={iconTargetY} r={DOT_R} />
          <circle className="sn-cta-annotation-dot" cx={railX} cy={iconRailY} r={DOT_R} />
          <text className="sn-cta-annotation-label" x={labelX} y={iconRailY + 3} textAnchor="start">ICON</text>
        </g>

        {/* Spacing — measures internal left padding, then joins the rail */}
        <g className="sn-cta-annotation sn-cta-annotation--spacing" style={{ transitionDelay: "80ms" }}>
          <line className="sn-cta-annotation-measure" x1={left} y1={spacingTargetY} x2={spacingTargetX} y2={spacingTargetY} />
          <line className="sn-cta-annotation-measure" x1={left} y1={spacingTargetY - 4} x2={left} y2={spacingTargetY + 4} />
          <line className="sn-cta-annotation-measure" x1={spacingTargetX} y1={spacingTargetY - 4} x2={spacingTargetX} y2={spacingTargetY + 4} />
          <line className="sn-cta-annotation-line" x1={spacingTargetX} y1={spacingTargetY} x2={railX} y2={spacingRailY} />
          <circle className="sn-cta-annotation-dot" cx={spacingTargetX} cy={spacingTargetY} r={DOT_R} />
          <circle className="sn-cta-annotation-dot" cx={railX} cy={spacingRailY} r={DOT_R} />
          <text className="sn-cta-annotation-label" x={labelX} y={spacingRailY + 3} textAnchor="start">SPACING</text>
        </g>

        {/* Direction — lower right rail */}
        <g className="sn-cta-annotation sn-cta-annotation--direction" style={{ transitionDelay: "100ms" }}>
          <line className="sn-cta-annotation-line" x1={directionTargetX} y1={directionTargetY} x2={railX} y2={directionRailY} />
          <circle className="sn-cta-annotation-dot" cx={directionTargetX} cy={directionTargetY} r={DOT_R} />
          <circle className="sn-cta-annotation-dot" cx={railX} cy={directionRailY} r={DOT_R} />
          <text className="sn-cta-annotation-label" x={labelX} y={directionRailY + 3} textAnchor="start">DIRECTION</text>
        </g>

        {/* Surface — centered beneath the button */}
        <g className="sn-cta-annotation sn-cta-annotation--surface" style={{ transitionDelay: "120ms" }}>
          <line className="sn-cta-annotation-line" x1={surfaceTargetX} y1={surfaceTargetY} x2={surfaceTargetX} y2={surfaceLabelY - 10} />
          <circle className="sn-cta-annotation-dot" cx={surfaceTargetX} cy={surfaceTargetY} r={DOT_R} />
          <circle className="sn-cta-annotation-dot" cx={surfaceTargetX} cy={surfaceLabelY - 10} r={DOT_R} />
          <text className="sn-cta-annotation-label" x={surfaceTargetX} y={surfaceLabelY} textAnchor="middle">SURFACE</text>
        </g>
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
          <svg className="sn-cta-arrow" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="sn-cta-trajectory" aria-hidden="true" />
        </a>
      </div>
    </>
  );
}
