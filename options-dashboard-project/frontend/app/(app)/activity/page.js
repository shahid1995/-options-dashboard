"use client";
import { C } from "@/lib/ui";

export default function ActivityPage() {
  return (
    <div style={{ maxWidth: 1200 }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Activity
        </h1>
        <p style={{ fontSize: 13, color: C.muted, margin: 0 }}>
          Orders, executions, exits, and system events
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
        <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>🕐</div>
        <div style={{ marginBottom: 8 }}>Activity is now on the Orders page</div>
        <div style={{ fontSize: 12, color: C.faint }}>
          Order history, trade journal, and execution details have moved to{" "}
          <a href="/orders" style={{ color: C.gold }}>
            Orders
          </a>
          .
        </div>
      </div>
    </div>
  );
}
