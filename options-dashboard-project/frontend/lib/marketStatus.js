// Client-side NSE market calendar, used for the paper-trading status badge.
//
// The badge's authoritative value always comes from the backend
// (`GET /paper/market-status`), which resolves Upstox's live feed with this
// same calendar as its fallback. These helpers exist so the badge can still
// show a sensible expectation while a live check is pending or unreachable —
// the execution gate itself never trusts them: it re-validates against the
// backend at the exact moment an order is submitted and blocks on failure.

import { istClockParts } from "./paperUtils";

// NSE (Equity Derivatives / F&O segment) trading holidays, "YYYY-MM-DD".
// Mirrors the backend's `app/services/market_status.py` list (2025 + 2026).
const NSE_TRADING_HOLIDAYS = new Set([
  // ---- 2025 ----
  "2025-02-26", // Maha Shivratri
  "2025-03-14", // Holi
  "2025-03-31", // Id-Ul-Fitr
  "2025-04-10", // Shri Mahavir Jayanti
  "2025-04-14", // Dr. Ambedkar Jayanti
  "2025-04-18", // Good Friday
  "2025-05-01", // Maharashtra Day
  "2025-05-12", // Buddha Purnima
  "2025-08-15", // Independence Day
  "2025-08-27", // Muharram
  "2025-10-02", // Gandhi Jayanti
  "2025-10-21", // Diwali Laxmi Puja
  "2025-10-22", // Diwali Balipratipada
  "2025-11-05", // Guru Nanak Jayanti
  "2025-12-25", // Christmas
  // ---- 2026 ----
  "2026-01-26", // Republic Day
  "2026-03-03", // Holi
  "2026-03-26", // Ram Navami
  "2026-03-31", // Mahavir Jayanti
  "2026-04-03", // Good Friday
  "2026-04-14", // Dr. Baba Saheb Ambedkar Jayanti
  "2026-05-01", // Maharashtra Day
  "2026-05-28", // Bakri Id / Eid ul-Adha
  "2026-06-26", // Muharram
  "2026-09-14", // Ganesh Chaturthi
  "2026-10-02", // Mahatma Gandhi Jayanti
  "2026-10-20", // Dasara
  "2026-11-08", // Diwali Laxmi Pujan (Sunday — Muhurat trading only)
  "2026-11-10", // Diwali Balipratipada
  "2026-11-24", // Guru Nanak Jayanti
  "2026-12-25", // Christmas
]);

// NSE F&O trading hours (IST): 09:15–15:30, Mon–Fri.
export const MARKET_OPEN_MINUTES = 9 * 60 + 15;
export const MARKET_CLOSE_MINUTES = 15 * 60 + 30;

// Calendar date (YYYY-MM-DD) in India Standard Time.
export function istDateIso(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

// Deterministic NSE calendar status: open / closed + human reason.
export function nseCalendarStatus(date = new Date()) {
  const { weekday, hour, minute, second } = istClockParts(date);
  const tradeDate = istDateIso(date);
  const minutes = hour * 60 + minute + (second ?? 0) / 60;

  if (weekday === "Sat" || weekday === "Sun") {
    return { status: "closed", reason: "Weekend — NSE is closed (Saturday/Sunday).", tradeDate };
  }
  if (NSE_TRADING_HOLIDAYS.has(tradeDate)) {
    return { status: "closed", reason: "NSE trading holiday.", tradeDate };
  }
  if (minutes < MARKET_OPEN_MINUTES) {
    return { status: "closed", reason: "Before the 09:15 IST market open.", tradeDate };
  }
  if (minutes > MARKET_CLOSE_MINUTES) {
    return { status: "closed", reason: "After the 15:30 IST market close.", tradeDate };
  }
  return { status: "open", reason: "Within NSE market hours (Mon–Fri 09:15–15:30 IST).", tradeDate };
}

export const MARKET_STATUS_LABELS = {
  open: "🟢 MARKET OPEN — Orders Enabled",
  closed: "🔴 MARKET CLOSED — Orders Disabled",
  unknown: "🟠 UNABLE TO VERIFY — Orders Blocked",
};

export const MARKET_CLOSED_MSG = "Market is closed. Paper order was not executed.";
export const MARKET_UNKNOWN_MSG = "Unable to verify market status. Order was not executed.";

// Price-provenance label for the UI. While the market is open, quotes are
// live; after close (or when status can't be verified) the simulator only
// has the last available traded/closing prices and stale values must not be
// presented as live.
export function priceModeLabel(status) {
  if (status === "open") return "LIVE";
  if (status === "closed") return "LAST/CLOSE";
  return "UNVERIFIED";
}
