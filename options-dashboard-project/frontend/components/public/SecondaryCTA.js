// StrikeNova Secondary CTA — Prototype
// Companion to PrimaryCTA: lower visual weight, same interaction language.
// Signal → Direction → Decision (quieter expression)

"use client";
import React from "react";
import { COLOR, RADIUS, MOTION } from "./tokens";

const CTA_CSS = `
.sn-cta-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.875rem 1.75rem;
  background: transparent;
  color: ${COLOR.textPrimary};
  border: 1px solid ${COLOR.border};
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
              color ${MOTION.fast} ${MOTION.easeOut};
}
.sn-cta-secondary:hover {
  background: ${COLOR.strategyDim};
  border-color: ${COLOR.strategy};
  color: ${COLOR.textPrimary};
}
.sn-cta-secondary:active {
  transform: translateY(0);
}
.sn-cta-secondary .sn-cta-label {
  position: relative;
  z-index: 2;
}
.sn-cta-secondary .sn-cta-arrow {
  position: relative;
  z-index: 2;
  transition: transform 0.2s ${MOTION.easeOut};
}
.sn-cta-secondary:hover .sn-cta-arrow {
  transform: translateX(3px);
}
.sn-cta-secondary .sn-cta-trajectory {
  position: absolute;
  top: 50%;
  right: 1rem;
  width: 0;
  height: 1px;
  background: ${COLOR.strategy};
  opacity: 0;
  transform: translateY(-50%);
  transition: width 0.2s ${MOTION.easeOut},
              opacity 0.2s ${MOTION.easeOut};
  pointer-events: none;
}
.sn-cta-secondary:hover .sn-cta-trajectory {
  width: 14px;
  opacity: 0.5;
}
@media (prefers-reduced-motion: reduce) {
  .sn-cta-secondary,
  .sn-cta-secondary .sn-cta-arrow,
  .sn-cta-secondary .sn-cta-trajectory {
    transition-duration: 0.01ms !important;
  }
  .sn-cta-secondary:hover .sn-cta-arrow {
    transform: none;
  }
  .sn-cta-secondary:hover .sn-cta-trajectory {
    display: none;
  }
}
`;

export default function SecondaryCTA({ href = "/how-it-works", children }) {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CTA_CSS }} />
      <a href={href} className="sn-cta-secondary ds-focus-ring">
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
    </>
  );
}
