"use client";
import { loginUrl } from "@/lib/api";
import { C } from "@/lib/theme";

export default function Home() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100vh", gap: 20 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600 }}>Options Dashboard</h1>
      <p style={{ color: C.muted, maxWidth: 360, textAlign: "center" }}>
        Log in with your Upstox account to see the live NIFTY option chain.
      </p>
      <a
        href={loginUrl()}
        style={{
          background: C.gold,
          color: "#0B0E14",
          padding: "10px 22px",
          borderRadius: 8,
          fontWeight: 600,
          textDecoration: "none",
        }}
      >
        Login with Upstox
      </a>
    </div>
  );
}
