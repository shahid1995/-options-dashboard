// Canonical option-price helpers (Phase 5.2.1).
//
// NSE specifies the option price step for NIFTY index options as ₹0.05. This
// module is the ONE place option trading prices are tick-aligned and the ONE
// place financial amounts get their two-decimal display normalization, so no
// component scatters Math.round formulas around.
//
// Contract:
// - roundOptionPrice rounds only OPTION TRADING PRICES to the tick. It is
//   never applied to index spot, IV, Greeks, P&L, cash, capital or margin —
//   those keep their own precision rules.
// - formatOptionPrice / formatMoney always render two decimals using the
//   existing Indian number formatting (en-IN grouping).
// - Invalid/missing prices are never coerced to zero.

import { fmtIN } from "./ui";

// Current applicable tick size for NIFTY index option trading prices (₹).
export const NIFTY_OPTION_TICK_SIZE = 0.05;

// Round an option trading price to the nearest valid tick. Numerically safe:
// works in tick units and re-normalizes with a final 10-decimal rounding so
// floating-point artifacts like 125.25000000000001 never escape.
//   125.23 → 125.25 | 125.24 → 125.25 | 125.26 → 125.25
//   125.27 → 125.25 | 125.28 → 125.30
// Returns null for missing/NaN prices and passes invalid (negative) prices
// through unchanged — never 0.
export function roundOptionPrice(price, tickSize = NIFTY_OPTION_TICK_SIZE) {
  if (price == null) return null;
  const value = Number(price);
  if (Number.isNaN(value)) return null;
  if (!(tickSize > 0) || value < 0) return value;
  const ticks = Math.round(value / tickSize);
  const rounded = ticks * tickSize;
  return Math.round(rounded * 1e10) / 1e10;
}

// Two-decimal option-price display (Indian grouping): 31.60, 48.75, 125.25.
export function formatOptionPrice(price) {
  if (price == null || Number.isNaN(Number(price))) return "—";
  return fmtIN(Number(price), 2);
}

// Two-decimal rupee display: ₹3,169.00 · ₹5,827.25 · −₹78.00.
// Negative values render with the typographic minus, matching the app's
// P&L conventions. Null/NaN render as "—".
export function formatMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  return `${n < 0 ? "−" : ""}₹${fmtIN(Math.abs(n), 2)}`;
}

// Signed two-decimal P&L display: +₹120.00 / −₹120.00 (null-safe).
export function formatSignedMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  return `${n >= 0 ? "+" : "−"}₹${fmtIN(Math.abs(n), 2)}`;
}
