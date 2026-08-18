"use client";
import { C } from "@/lib/ui";

export default function BrokersPage() {
  return (
    <div style={{ maxWidth: 1200 }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Brokers
        </h1>
        <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
          Broker accounts, connection, capabilities, and funds
        </p>
      </div>

      <div
        style={{
          textAlign: "center",
          padding: 48,
          color: C.muted,
          fontSize: 13,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          background: C.surface,
        }}
      >
        <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>🔗</div>
        <div style={{ marginBottom: 8 }}>Broker management coming soon.</div>
        <div style={{ fontSize: 12, color: C.faint }}>
          Currently connected via Upstox OAuth. Broker connection diagnostics
          are available in the{" "}
          <a href="/paper" style={{ color: C.gold }}>
            Strategy Builder
          </a>{" "}
          Broker tab.
        </div>
      </div>
    </div>
  );
}
