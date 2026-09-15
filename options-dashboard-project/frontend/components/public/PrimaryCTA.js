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
.sn-cta-annotation {
  opacity: 0;
  transition: opacity 0.22s ${MOTION.easeOut};
}
.sn-cta-wrapper:hover .sn-cta-annotation,
.sn-cta-wrapper:focus-within .sn-cta-annotation {
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
  .sn-cta-annotation {
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
    const observer = new ResizeObserver(measure);
    if (buttonRef.current) observer.observe(buttonRef.current);
    if (wrapperRef.current) observer.observe(wrapperRef.current);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measure]);

  if (!dims) return null;

  const { left, top, width, height } = dims;
  const right = left + width;
  const bottom = top + height;
  const centerX = left + width / 2;
  const centerY = top + height / 2;

  const iconX = right - 10;
  const iconY = centerY;
  const iconLabelX = Math.min(iconX + 32, left + width + 42);
  const iconLabelY = centerY - 22;

  const spacingX1 = left;
  const spacingX2 = left + 24;
  const spacingY = centerY;
  const spacingLabelX = Math.max(2, left - 44);
  const spacingLabelY = centerY - 4;

  const surfaceX = centerX;
  const surfaceY = bottom;
  const surfaceLabelX = centerX;
  const surfaceLabelY = bottom + 30;

  const radiusX = right - 8;
  const radiusY = top + 8;
  const radiusLabelX = Math.min(right + 38, left + width + 50);
  const radiusLabelY = top - 10;

  const directionX = right - width * 0.22;
  const directionY = centerY + 1;
  const directionLabelX = Math.min(right + 56, left + width + 68);
  const directionLabelY = bottom + 26;

  return (
    <svg className="sn-cta-annotations" aria-hidden="true">
      <g className="sn-cta-annotation sn-cta-annotation--icon" style={{ transitionDelay: "40ms" }}>
        <line className="sn-cta-annotation-line" x1={iconX} y1={iconY} x2={iconLabelX - 8} y2={iconLabelY} />
        <circle className="sn-cta-annotation-dot" cx={iconX} cy={iconY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={iconLabelX - 8} cy={iconLabelY} r={DOT_R} />
        <text className="sn-cta-annotation-label" x={iconLabelX} y={iconLabelY + 3}>ICON</text>
      </g>

      <g className="sn-cta-annotation sn-cta-annotation--spacing" style={{ transitionDelay: "80ms" }}>
        <line className="sn-cta-annotation-measure" x1={spacingX1} y1={top - 7} x2={spacingX2} y2={top - 7} />
        <line className="sn-cta-annotation-measure" x1={spacingX1} y1={top - 11} x2={spacingX1} y2={top - 3} />
        <line className="sn-cta-annotation-measure" x1={spacingX2} y1={top - 11} x2={spacingX2} y2={top - 3} />
        <line className="sn-cta-annotation-line" x1={spacingX2} y1={top - 7} x2={spacingLabelX + 40} y2={spacingLabelY} />
        <circle className="sn-cta-annotation-dot" cx={spacingX2} cy={top - 7} r={DOT_R} />
        <text className="sn-cta-annotation-label" x={spacingLabelX} y={spacingLabelY + 3}>SPACING</text>
      </g>

      <g className="sn-cta-annotation sn-cta-annotation--surface" style={{ transitionDelay: "120ms" }}>
        <line className="sn-cta-annotation-line" x1={surfaceX} y1={surfaceY} x2={surfaceX} y2={surfaceLabelY - 10} />
        <circle className="sn-cta-annotation-dot" cx={surfaceX} cy={surfaceY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={surfaceX} cy={surfaceLabelY - 10} r={DOT_R} />
        <text className="sn-cta-annotation-label" x={surfaceLabelX} y={surfaceLabelY} textAnchor="middle">SURFACE</text>
      </g>

      <g className="sn-cta-annotation sn-cta-annotation--radius" style={{ transitionDelay: "160ms" }}>
        <path className="sn-cta-annotation-line" d={`M ${radiusX} ${radiusY} Q ${radiusX + 14} ${radiusY} ${radiusX + 14} ${radiusY - 8} L ${radiusLabelX - 8} ${radiusY - 8}`} />
        <circle className="sn-cta-annotation-dot" cx={radiusX} cy={radiusY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={radiusLabelX - 8} cy={radiusY - 8} r={DOT_R} />
        <text className="sn-cta-annotation-label" x={radiusLabelX} y={radiusY - 5}>RADIUS</text>
      </g>

      <g className="sn-cta-annotation sn-cta-annotation--direction" style={{ transitionDelay: "200ms" }}>
        <line className="sn-cta-annotation-line" x1={directionX} y1={directionY} x2={directionLabelX - 8} y2={directionLabelY - 10} />
        <circle className="sn-cta-annotation-dot" cx={directionX} cy={directionY} r={DOT_R} />
        <circle className="sn-cta-annotation-dot" cx={directionLabelX - 8} cy={directionLabelY - 10} r={DOT_R} />
        <text className="sn-cta-annotation-label" x={directionLabelX} y={directionLabelY - 7}>DIRECTION</text>
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
