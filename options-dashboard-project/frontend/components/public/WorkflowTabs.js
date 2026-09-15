// =============================================================================
// WorkflowTabs — Decision Workflow: analytical progression interface
// 01 MARKET VIEW → 02 STRATEGY → 03 PAYOFF → 04 RISK
// =============================================================================
"use client";
import React, { useState } from "react";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "@/components/public/tokens";
import { useIsMobile } from "@/lib/ui";
import { DemoLabel } from "@/components/public/truth";

/** @typedef {{ id: string, number: string, label: string, sublabel: string, content: React.ReactNode }} WorkflowStep */

/**
 * WorkflowTabs — accessible analytical workflow interface.
 *
 * @param {{ steps: WorkflowStep[], defaultStep: string, ariaLabel: string }} props
 */
export default function WorkflowTabs({ steps, defaultStep, ariaLabel }) {
  const isMobile = useIsMobile();
  const [activeStep, setActiveStep] = useState(defaultStep || steps[0]?.id);

  const activeContent = steps.find((s) => s.id === activeStep)?.content;

  return (
    <div>
      {/* Step progression bar */}
      <div
        role="tablist"
        aria-label={ariaLabel}
        style={{
          display: "flex",
          gap: 0,
          marginBottom: SPACE.cardLg,
          flexDirection: isMobile ? "column" : "row",
        }}
      >
        {steps.map((step, index) => {
          const isActive = step.id === activeStep;
          const isLast = index === steps.length - 1;

          return (
            <React.Fragment key={step.id}>
              {/* Individual step trigger */}
              <button
                role="tab"
                aria-selected={isActive}
                aria-controls={`tabpanel-${step.id}`}
                id={`tab-${step.id}`}
                onClick={() => setActiveStep(step.id)}
                className="ds-focus-ring"
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: isMobile ? "flex-start" : "center",
                  textAlign: "left",
                  padding: `${SPACE.comp} ${SPACE.compLg}`,
                  background: "transparent",
                  border: "none",
                  borderBottom: isMobile ? "none" : `2px solid ${isActive ? COLOR.strategy : "transparent"}`,
                  borderLeft: isMobile ? `2px solid ${isActive ? COLOR.strategy : COLOR.border}` : "none",
                  cursor: "pointer",
                  transition: `border-color ${MOTION.fast}, background ${MOTION.fast}`,
                  borderRadius: 0,
                  minHeight: "auto",
                  gap: SPACE.xs,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: SPACE.small,
                    width: "100%",
                  }}
                >
                  <span
                    style={{
                      fontSize: "0.625rem",
                      fontWeight: 700,
                      fontFamily: TYPE.data,
                      color: isActive ? COLOR.strategy : COLOR.textFaint,
                      letterSpacing: "0.04em",
                      transition: `color ${MOTION.fast}`,
                    }}
                  >
                    {step.number}
                  </span>
                  <span
                    style={{
                      fontSize: TYPE.caption.size,
                      fontWeight: 700,
                      letterSpacing: "0.06em",
                      fontFamily: TYPE.data,
                      textTransform: "uppercase",
                      color: isActive ? COLOR.textPrimary : COLOR.textMuted,
                      transition: `color ${MOTION.fast}`,
                    }}
                  >
                    {step.label}
                  </span>
                </div>
                <span
                  style={{
                    fontSize: "0.6875rem",
                    color: isActive ? COLOR.textSecondary : COLOR.textFaint,
                    lineHeight: 1.4,
                    transition: `color ${MOTION.fast}`,
                  }}
                >
                  {step.sublabel}
                </span>
              </button>

              {/* Connector (horizontal on desktop, hidden on mobile) */}
              {!isLast && !isMobile && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    paddingBottom: "2rem",
                    flexShrink: 0,
                  }}
                  aria-hidden="true"
                >
                  <div
                    style={{
                      width: "2rem",
                      height: 1,
                      background: COLOR.borderSubtle,
                    }}
                  />
                  <svg
                    width="6"
                    height="8"
                    viewBox="0 0 6 8"
                    fill="none"
                    style={{ marginLeft: -1 }}
                  >
                    <path
                      d="M0 0 L6 4 L0 8 Z"
                      fill={COLOR.borderSubtle}
                    />
                  </svg>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Active content panel */}
      <div
        role="tabpanel"
        id={`tabpanel-${activeStep}`}
        aria-labelledby={`tab-${activeStep}`}
      >
        {activeContent}
      </div>

      {/* Demo disclaimer */}
      <div style={{ textAlign: "center", marginTop: SPACE.cardLg }}>
        <DemoLabel style={{ fontSize: "0.625rem" }} />
      </div>
    </div>
  );
}
