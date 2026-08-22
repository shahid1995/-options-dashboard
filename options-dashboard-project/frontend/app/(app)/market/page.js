"use client";
import { C } from "@/lib/ui";

export default function MarketPage() {
  return (
    <div style={{ maxWidth: 1200 }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Market
        </h1>
        <p style={{ fontSize: 12, color: C.muted, margin: 0 }}>
          Live option chains, market analytics, and watchlist
        </p>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <a
          href="/dashboard"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "16px 20px",
            borderRadius: 8,
            border: `1px solid ${C.border}`,
            background: C.surface,
            color: C.text,
            textDecoration: "none",
            transition: "border-color 0.15s, transform 0.15s",
            flex: "1 1 300px",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = C.gold;
            e.currentTarget.style.transform = "translateY(-2px)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = C.border;
            e.currentTarget.style.transform = "none";
          }}
        >
          <span style={{ fontSize: 24 }}>📈</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>
              Option Chain
            </div>
            <div style={{ fontSize: 12, color: C.muted }}>
              Live option chains for 8 indices with market analytics
            </div>
          </div>
        </a>
      </div>
    </div>
  );
}
