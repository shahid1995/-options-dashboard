// StrikeNova Primary CTA — Prototype
// Signal → Direction → Decision
// Self-contained component for homepage hero CTA testing.

"use client";
import React from "react";
import { COLOR, RADIUS, MOTION } from "./tokens";

const CTA_CSS = `
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
@media (prefers-reduced-motion: reduce) {
  .sn-cta-primary,
  .sn-cta-primary .sn-cta-arrow,
  .sn-cta-primary .sn-cta-trajectory {
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

export default function PrimaryCTA({ href = "/features", children }) {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CTA_CSS }} />
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
    </>
  );
}
