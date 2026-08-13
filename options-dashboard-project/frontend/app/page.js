"use client";
import { useEffect, useState } from "react";
import { loginUrl } from "@/lib/api";

export default function Home() {
  const [loginError, setLoginError] = useState(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setLoginError(params.get("login_error"));
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100vh", gap: 20 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600 }}>Options Dashboard</h1>
      <p style={{ color: "#8892A6", maxWidth: 360, textAlign: "center" }}>
        Log in with your Upstox account to see the live NIFTY option chain.
      </p>
      {loginError && (
        <p style={{ color: "#E15252", maxWidth: 400, textAlign: "center", fontSize: 13, border: "1px solid #E15252", borderRadius: 8, padding: "8px 14px", background: "rgba(225,82,82,0.08)" }}>
          Login failed: {loginError}. Please try again.
        </p>
      )}
      <a
        href={loginUrl()}
        style={{
          background: "#C9A15A",
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
