"use client";
import { useEffect, useState } from "react";

// Shared theme colors
export const C = {
  surface: "#12161F",
  surface2: "#171C27",
  border: "#242B3A",
  muted: "#8892A6",
  faint: "#5A6376",
  text: "#E7E9EE",
  gold: "#C9A15A",
  green: "#4CAF7D",
  red: "#E15252",
};

export const SYMBOLS = ["NIFTY", "BANKNIFTY"];

// NSE lot sizes per index — fixed defaults used by the paper trading builder
// (lot size is no longer editable in the UI; it is selected by symbol).
export const LOT_SIZES = { NIFTY: 65, BANKNIFTY: 30 };

export function fmtIN(n, decimals = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function fmtChg(n) {
  if (n === null || n === undefined) return "-";
  const sign = n > 0 ? "+" : "";
  return `${sign}${fmtIN(n)}`;
}

export function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint}px)`);
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [breakpoint]);
  return isMobile;
}

export function TopNav({ active }) {
  const links = [
    ["chain", "/dashboard", "Option Chain"],
    ["paper", "/paper", "Paper Trading"],
  ];
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
      {links.map(([key, href, label]) => (
        <a
          key={key}
          href={href}
          style={{
            fontSize: 12.5,
            padding: "6px 14px",
            borderRadius: 6,
            border: `1px solid ${active === key ? C.gold : C.border}`,
            background: active === key ? "rgba(201,161,90,0.1)" : "transparent",
            color: active === key ? C.gold : C.muted,
            textDecoration: "none",
          }}
        >
          {label}
        </a>
      ))}
    </div>
  );
}

export function SymbolTabs({ symbol, onChange }) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {SYMBOLS.map((s) => (
        <button
          key={s}
          onClick={() => onChange(s)}
          style={{
            fontSize: 12,
            padding: "6px 12px",
            borderRadius: 6,
            border: `1px solid ${symbol === s ? C.gold : C.border}`,
            background: symbol === s ? "rgba(201,161,90,0.1)" : "transparent",
            color: symbol === s ? C.gold : C.muted,
            cursor: "pointer",
          }}
        >
          {s}
        </button>
      ))}
    </div>
  );
}

export function SessionExpired() {
  return (
    <Centered>
      <div style={{ textAlign: "center" }}>
        <div style={{ marginBottom: 10 }}>Your Upstox session has expired (tokens expire daily at 3:30 AM).</div>
        <a href="/" style={{ color: C.gold }}>
          Log in again
        </a>
      </div>
    </Centered>
  );
}

export function Centered({ children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh" }}>
      {children}
    </div>
  );
}

export function Stat({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: C.faint }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: color || C.text }}>{value}</div>
    </div>
  );
}

export function StepButton({ onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{ width: 20, height: 20, lineHeight: "18px", background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, cursor: "pointer", fontSize: 12, padding: 0 }}
    >
      {children}
    </button>
  );
}

export function ShapeIcon({ shape }) {
  const paths = {
    riseUp: "M4 26 L16 26 L28 6",
    fallUp: "M4 6 L16 6 L28 26",
    riseCapped: "M4 26 L12 26 L20 10 L28 10",
    fallCapped: "M4 10 L12 10 L20 26 L28 26",
    plateau: "M4 20 L10 20 L14 10 L20 10 L24 20 L28 20",
    peak: "M4 22 L12 22 L16 8 L20 22 L28 22",
    vUp: "M4 6 L14 22 L16 24 L18 22 L28 6",
  };
  return (
    <svg width="100%" height="32" viewBox="0 0 32 32">
      <path d={paths[shape] || paths.riseUp} stroke={C.green} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
