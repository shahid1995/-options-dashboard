// StrikeNova Primary CTA — with destination preview on hover/focus
// Signal → Direction → Decision → Destination revealed
// Self-contained component for homepage hero CTA.

"use client";
import React from "react";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "./tokens";

const PREVIEW_ITEMS = [
  {
    index: "01",
    label: "Market Intelligence",
    href: "/market-intelligence",
    color: COLOR.intelligence,
    tagline: "See what the market is doing — in real time.",
  },
  {
    index: "02",
    label: "Strategy Lab",
    href: "/strategy-lab",
    color: COLOR.strategy,
    tagline: "Build. Analyze. Test.",
  },
  {
    index: "03",
    label: "Risk & Scenarios",
    href: "/strategy-lab",
    color: COLOR.negative,
    tagline: "Know your downside before you commit.",
  },
  {
    index: "04",
    label: "Paper Trading",
    href: "/paper-trading",
    color: COLOR.positive,
    tagline: "Rehearse without risk.",
  },
];

const CTA_CSS = `
.sn-cta-wrapper {
  position: relative;
  display: inline-block;
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
.sn-cta-preview {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  z-index: 10;
  width: 280px;
  background: ${COLOR.surface};
  border: 1px solid ${COLOR.border};
  border-radius: ${RADIUS.md};
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  opacity: 0;
  transform: translateY(-4px);
  pointer-events: none;
  transition: opacity 0.2s ${MOTION.easeOut},
              transform 0.2s ${MOTION.easeOut};
}
.sn-cta-wrapper:hover .sn-cta-preview,
.sn-cta-wrapper:focus-within .sn-cta-preview {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}
.sn-cta-preview-header {
  padding: 0.25rem 0.25rem 0.5rem;
  border-bottom: 1px solid ${COLOR.borderSubtle};
  margin-bottom: 0.125rem;
}
.sn-cta-preview-title {
  font-size: 0.8125rem;
  font-weight: 700;
  color: ${COLOR.textPrimary};
  font-family: inherit;
  letter-spacing: 0.02em;
}
.sn-cta-preview-sub {
  font-size: 0.6875rem;
  color: ${COLOR.textMuted};
  font-family: inherit;
}
.sn-cta-preview-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.25rem;
  border-radius: ${RADIUS.sm};
  transition: background ${MOTION.fast} ${MOTION.easeOut};
}
.sn-cta-preview-item:hover {
  background: ${COLOR.surfaceElevated};
}
.sn-cta-preview-index {
  font-size: 0.625rem;
  font-weight: 700;
  font-family: ${TYPE.data};
  width: 1.25rem;
  flex-shrink: 0;
}
.sn-cta-preview-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: ${COLOR.textPrimary};
  font-family: inherit;
}
.sn-cta-preview-tagline {
  display: none;
}
@media (prefers-reduced-motion: reduce) {
  .sn-cta-primary,
  .sn-cta-primary .sn-cta-arrow,
  .sn-cta-primary .sn-cta-trajectory,
  .sn-cta-preview {
    transition-duration: 0.01ms !important;
  }
  .sn-cta-primary:hover .sn-cta-arrow {
    transform: none;
  }
  .sn-cta-primary:hover .sn-cta-trajectory {
    display: none;
  }
  .sn-cta-preview {
    transform: none;
  }
}
`;

export default function PrimaryCTA({ href = "/features", children }) {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CTA_CSS }} />
      <div className="sn-cta-wrapper">
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
        <div className="sn-cta-preview" aria-hidden="true">
          <div className="sn-cta-preview-header">
            <div className="sn-cta-preview-title">Explore StrikeNova</div>
            <div className="sn-cta-preview-sub">Follow the decision workflow</div>
          </div>
          {PREVIEW_ITEMS.map((item) => (
            <a key={item.index} href={item.href} className="sn-cta-preview-item" tabIndex={-1}>
              <span className="sn-cta-preview-index" style={{ color: item.color }}>{item.index}</span>
              <span className="sn-cta-preview-label">{item.label}</span>
            </a>
          ))}
        </div>
      </div>
    </>
  );
}
