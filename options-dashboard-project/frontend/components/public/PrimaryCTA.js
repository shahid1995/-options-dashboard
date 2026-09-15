// StrikeNova Primary CTA — Anatomical interaction
// Hover/focus reveals the button's construction: icon, spacing, surface, radius
// Self-contained component for homepage hero CTA.
// Anchor-driven geometry: connectors attach to measured button positions.

"use client";
import React, { useState, useRef, useEffect, useCallback } from "react";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "./tokens";

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
  stroke-width: 1;
  fill: none;
}
.sn-cta-annotation-dot {
  fill: ${COLOR.strategy};
}
.sn-cta-annotation-label {
  font-family: ${TYPE.data};
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  fill: ${COLOR.textSecondary};
}
.sn-cta-annotation-bg {
  fill: ${COLOR.surface};
  opacity: 0.9;
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

function Annotations({ buttonRef, wrapperRef, visible }) {
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
    const paddingTop = 14;
    const borderRadius = 8;

    setDims({
      left,
      top,
      width,
      height,
      paddingLeft,
      paddingTop,
      borderRadius,
      iconX: left + width - 12,
      iconY: top + height / 2,
      spacingX: left + paddingLeft,
      spacingY: top + height / 2,
      surfaceX: left + width / 2,
      surfaceY: top + height / 2,
      radiusX: left + width - borderRadius,
      radiusY: top + borderRadius,
      directionX: left + width + 8,
      directionY: top + height / 2 + 18,
    });
  }, [buttonRef, wrapperRef]);

  useEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  if (!dims) return null;

  const labelW = 60;
  const labelH = 16;
  const labelPad = 4;

  return (
    <svg
      className="sn-cta-annotations"
      aria-hidden="true"
      width="100%"
      height="100%"
      style={{ overflow: "visible" }}
    >
      {/* ICON: connector from arrow icon to label */}
      <g className="sn-cta-annotation sn-cta-annotation--icon" style={{ transitionDelay: "50ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={dims.iconX}
          y1={dims.iconY}
          x2={dims.iconX + 30}
          y2={dims.iconY - 22}
        />
        <circle className="sn-cta-annotation-dot" cx={dims.iconX} cy={dims.iconY} r="2.5" />
        <rect
          className="sn-cta-annotation-bg"
          x={dims.iconX + 32}
          y={dims.iconY - 34}
          width={labelW}
          height={labelH}
          rx="2"
        />
        <text
          className="sn-cta-annotation-label"
          x={dims.iconX + 32 + labelPad}
          y={dims.iconY - 22}
        >
          ICON
        </text>
      </g>

      {/* SPACING: connector from internal left padding to label */}
      <g className="sn-cta-annotation sn-cta-annotation--spacing" style={{ transitionDelay: "100ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={dims.spacingX}
          y1={dims.spacingY}
          x2={dims.spacingX - 35}
          y2={dims.spacingY}
        />
        <line
          className="sn-cta-annotation-line"
          x1={dims.left}
          y1={dims.top - 6}
          x2={dims.left}
          y2={dims.top + dims.height + 6}
        />
        <circle className="sn-cta-annotation-dot" cx={dims.spacingX} cy={dims.spacingY} r="2.5" />
        <rect
          className="sn-cta-annotation-bg"
          x={dims.spacingX - 35 - labelW - labelPad}
          y={dims.spacingY - labelH / 2}
          width={labelW}
          height={labelH}
          rx="2"
        />
        <text
          className="sn-cta-annotation-label"
          x={dims.spacingX - 35 - labelW - labelPad + labelPad}
          y={dims.spacingY + 3}
        >
          SPACING
        </text>
      </g>

      {/* SURFACE: connector from button body center to label below */}
      <g className="sn-cta-annotation sn-cta-annotation--surface" style={{ transitionDelay: "150ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={dims.surfaceX}
          y1={dims.surfaceY}
          x2={dims.surfaceX}
          y2={dims.surfaceY + 35}
        />
        <circle className="sn-cta-annotation-dot" cx={dims.surfaceX} cy={dims.surfaceY} r="2.5" />
        <rect
          className="sn-cta-annotation-bg"
          x={dims.surfaceX - labelW / 2}
          y={dims.surfaceY + 37}
          width={labelW}
          height={labelH}
          rx="2"
        />
        <text
          className="sn-cta-annotation-label"
          x={dims.surfaceX - labelW / 2 + labelPad}
          y={dims.surfaceY + 49}
        >
          SURFACE
        </text>
      </g>

      {/* RADIUS: connector from top-right corner to label */}
      <g className="sn-cta-annotation sn-cta-annotation--radius" style={{ transitionDelay: "200ms" }}>
        <path
          className="sn-cta-annotation-line"
          d={`M ${dims.radiusX} ${dims.radiusY} L ${dims.radiusX + 25} ${dims.radiusY - 15}`}
        />
        <circle className="sn-cta-annotation-dot" cx={dims.radiusX} cy={dims.radiusY} r="2.5" />
        <rect
          className="sn-cta-annotation-bg"
          x={dims.radiusX + 27}
          y={dims.radiusY - 27}
          width={labelW}
          height={labelH}
          rx="2"
        />
        <text
          className="sn-cta-annotation-label"
          x={dims.radiusX + 27 + labelPad}
          y={dims.radiusY - 15}
        >
          RADIUS
        </text>
      </g>

      {/* DIRECTION: connector from arrow trajectory to label */}
      <g className="sn-cta-annotation sn-cta-annotation--direction" style={{ transitionDelay: "175ms" }}>
        <line
          className="sn-cta-annotation-line"
          x1={dims.directionX}
          y1={dims.directionY - 10}
          x2={dims.directionX + 30}
          y2={dims.directionY + 5}
        />
        <circle className="sn-cta-annotation-dot" cx={dims.directionX} cy={dims.directionY - 10} r="2.5" />
        <rect
          className="sn-cta-annotation-bg"
          x={dims.directionX + 32}
          y={dims.directionY - 7}
          width={labelW + 8}
          height={labelH}
          rx="2"
        />
        <text
          className="sn-cta-annotation-label"
          x={dims.directionX + 32 + labelPad}
          y={dims.directionY + 5}
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
