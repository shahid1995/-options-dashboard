"use client";
import { C } from "@/lib/ui";

export default function StrategiesPage() {
  return (
    <div style={{ maxWidth: 1200 }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Strategies
        </h1>
        <p style={{ fontSize: 13, color: C.muted, margin: 0 }}>
          Strategy builder, active strategies, and history
        </p>
      </div>

      <div
        style={{
          textAlign: "center",
          padding: 48,
          color: C.muted,
          fontSize: 13,
          border: `1px solid ${C.border}`,
          borderRadius: 10,
          background: C.surface,
        }}
      >
        <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>⚡</div>
        <div style={{ marginBottom: 8 }}>Strategy building is now on the Strategy Builder</div>
        <div style={{ fontSize: 12, color: C.faint }}>
          Strategy creation, analysis, and paper trading have moved to the{" "}
          <a href="/paper" style={{ color: C.gold }}>
            Strategy Builder
          </a>
          .
        </div>
      </div>
    </div>
  );
}
