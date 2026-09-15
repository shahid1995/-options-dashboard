// StrikeNova Primary CTA — Anatomical interaction
// Hover/focus reveals the button's construction: icon, spacing, surface, radius
// Self-contained component for homepage hero CTA.

"use client";
import React from "react";
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
  position: absolute;
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

function Annotations() {
  return (
    <svg className="sn-cta-annotations" aria-hidden="true" width="100%" height="100%" viewBox="0 0 320 140" preserveAspectRatio="none">
      {/* ICON annotation - right side pointing to arrow */}
      <g className="sn-cta-annotation sn-cta-annotation--icon" style={{ transitionDelay: "50ms" }}>
        <line className="sn-cta-annotation-line" x1="240" y1="70" x2="270" y2="40" />
        <circle className="sn-cta-annotation-dot" cx="240" cy="70" r="2.5" />
        <rect className="sn-cta-annotation-bg" x="272" y="28" width="40" height="16" rx="2" />
        <text className="sn-cta-annotation-label" x="276" y="40">ICON</text>
      </g>

      {/* SPACING annotation - left side pointing to padding */}
      <g className="sn-cta-annotation sn-cta-annotation--spacing" style={{ transitionDelay: "100ms" }}>
        <line className="sn-cta-annotation-line" x1="80" y1="70" x2="20" y2="70" />
        <line className="sn-cta-annotation-line" x1="20" y1="55" x2="20" y2="85" />
        <circle className="sn-cta-annotation-dot" cx="80" cy="70" r="2.5" />
        <rect className="sn-cta-annotation-bg" x="0" y="58" width="58" height="16" rx="2" />
        <text className="sn-cta-annotation-label" x="4" y="70">SPACING</text>
      </g>

      {/* SURFACE annotation - bottom pointing to button body */}
      <g className="sn-cta-annotation sn-cta-annotation--surface" style={{ transitionDelay: "150ms" }}>
        <line className="sn-cta-annotation-line" x1="160" y1="120" x2="160" y2="138" />
        <circle className="sn-cta-annotation-dot" cx="160" cy="120" r="2.5" />
        <rect className="sn-cta-annotation-bg" x="126" y="126" width="68" height="16" rx="2" />
        <text className="sn-cta-annotation-label" x="130" y="138">SURFACE</text>
      </g>

      {/* RADIUS annotation - top-right pointing to corner */}
      <g className="sn-cta-annotation sn-cta-annotation--radius" style={{ transitionDelay: "200ms" }}>
        <path className="sn-cta-annotation-line" d="M 220 20 L 260 20 Q 268 20 268 28 L 268 38" />
        <circle className="sn-cta-annotation-dot" cx="220" cy="20" r="2.5" />
        <rect className="sn-cta-annotation-bg" x="272" y="26" width="46" height="16" rx="2" />
        <text className="sn-cta-annotation-label" x="276" y="38">RADIUS</text>
      </g>

      {/* DIRECTION annotation - bottom-right pointing to arrow direction */}
      <g className="sn-cta-annotation sn-cta-annotation--direction" style={{ transitionDelay: "175ms" }}>
        <line className="sn-cta-annotation-line" x1="225" y1="95" x2="255" y2="120" />
        <circle className="sn-cta-annotation-dot" cx="225" cy="95" r="2.5" />
        <rect className="sn-cta-annotation-bg" x="257" y="108" width="62" height="16" rx="2" />
        <text className="sn-cta-annotation-label" x="261" y="120">DIRECTION</text>
      </g>
    </svg>
  );
}

export default function PrimaryCTA({ href = "/features", children }) {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CTA_CSS }} />
      <div className="sn-cta-wrapper">
        <Annotations />
        <a href={href} className="sn-cta-primary ds-focus-ring">
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
