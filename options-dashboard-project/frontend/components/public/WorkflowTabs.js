// =============================================================================
// WorkflowTabs — Accessible tab interface for Strategy Lab & Paper Trading
// =============================================================================
"use client";
import React, { useState } from "react";
import { COLOR, TYPE, SPACE, RADIUS, MOTION } from "@/components/public/tokens";
import { useIsMobile } from "@/lib/ui";

/**
 * WorkflowTabs — accessible tab interface.
 *
 * Props:
 *   tabs: [{ id, label, content: ReactNode }]
 *   defaultTab: string (tab id)
 *   ariaLabel: string
 */
export default function WorkflowTabs({ tabs, defaultTab, ariaLabel }) {
  const isMobile = useIsMobile();
  const [activeTab, setActiveTab] = useState(defaultTab || tabs[0]?.id);

  const activeContent = tabs.find((t) => t.id === activeTab)?.content;

  return (
    <div>
      {/* Tab list */}
      <div
        role="tablist"
        aria-label={ariaLabel}
        style={{
          display: "flex",
          gap: SPACE.xs,
          marginBottom: SPACE.cardLg,
          flexWrap: "wrap",
        }}
      >
        {tabs.map((tab) => {
          const isActive = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`tabpanel-${tab.id}`}
              id={`tab-${tab.id}`}
              onClick={() => setActiveTab(tab.id)}
              className="ds-focus-ring"
              style={{
                padding: isMobile ? "0.5rem 0.75rem" : "0.625rem 1.25rem",
                fontSize: TYPE.caption.size,
                fontWeight: 700,
                letterSpacing: "0.06em",
                fontFamily: TYPE.data,
                textTransform: "uppercase",
                background: isActive ? COLOR.strategy : "transparent",
                color: isActive ? "#0B0E14" : COLOR.textMuted,
                border: `1px solid ${isActive ? COLOR.strategy : COLOR.border}`,
                borderRadius: RADIUS.md,
                cursor: "pointer",
                transition: "background 0.15s, color 0.15s, border-color 0.15s",
                minHeight: 44,
                whiteSpace: "nowrap",
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab panel */}
      <div
        role="tabpanel"
        id={`tabpanel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        style={{
          background: COLOR.surface,
          border: `1px solid ${COLOR.border}`,
          borderRadius: RADIUS.lg,
          padding: isMobile ? SPACE.card : SPACE.cardLg,
        }}
      >
        {activeContent}
      </div>
    </div>
  );
}
