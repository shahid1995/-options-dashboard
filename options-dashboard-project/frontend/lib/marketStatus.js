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

// ---- Phase 5.2.1: segment-aware session definitions --------------------------
//
// The market is no longer one hard-coded 09:15–15:30 rule for all
// instruments. Each segment has an explicit, configurable session definition
// (mirroring the backend's `app/services/market_status.py`), and the status
// badge carries an explicit session state. The product currently trades
// NIFTY index options, so INDEX_DERIVATIVES is the default segment.

export const INDEX_DERIVATIVES = "INDEX_DERIVATIVES";
export const EQUITY_CASH = "EQUITY_CASH";
export const EQUITY_DERIVATIVES = "EQUITY_DERIVATIVES";
export const STOCK_DERIVATIVES = "STOCK_DERIVATIVES";
export const CURRENCY = "CURRENCY";
export const COMMODITY = "COMMODITY";

// Segment → explicit session definition. `continuousOpen/continuousClose`
// are the normal continuous-trading window in IST; `tradingAllowed` says
// whether the segment can accept the requested paper action while open.
export const SESSION_DEFINITIONS = {
  [INDEX_DERIVATIVES]: {
    segment: INDEX_DERIVATIVES,
    timezone: "Asia/Kolkata",
    continuousOpen: "09:15",
    continuousClose: "15:30",
    tradingAllowed: true,
    session: "CONTINUOUS",
  },
  [EQUITY_DERIVATIVES]: {
    segment: EQUITY_DERIVATIVES,
    timezone: "Asia/Kolkata",
    continuousOpen: "09:15",
    continuousClose: "15:30",
    tradingAllowed: true,
    session: "CONTINUOUS",
  },
  [STOCK_DERIVATIVES]: {
    segment: STOCK_DERIVATIVES,
    timezone: "Asia/Kolkata",
    continuousOpen: "09:15",
    continuousClose: "15:30",
    tradingAllowed: true,
    session: "CONTINUOUS",
  },
  // The equity CASH segment runs its own SEBI Closing Auction Session; it is
  // a DIFFERENT session from index-options continuous trading and is never
  // used to enable index-option execution (the backend resolves the
  // instrument's own segment). The local calendar below does not invent the
  // auction window — only the broker/exchange feed reports it.
  [EQUITY_CASH]: {
    segment: EQUITY_CASH,
    timezone: "Asia/Kolkata",
    continuousOpen: "09:15",
    continuousClose: "15:30",
    tradingAllowed: true,
    session: "CONTINUOUS",
  },
  [CURRENCY]: {
    segment: CURRENCY,
    timezone: "Asia/Kolkata",
    continuousOpen: "09:00",
    continuousClose: "17:00",
    tradingAllowed: true,
    session: "CONTINUOUS",
  },
  [COMMODITY]: {
    segment: COMMODITY,
    timezone: "Asia/Kolkata",
    continuousOpen: "09:00",
    continuousClose: "23:30",
    tradingAllowed: true,
    session: "CONTINUOUS",
  },
};

// Explicit session states the badge can display. OPEN is the only state that
// authorizes orders; the others are informational (the backend re-validates
// at execution time). States are only ever derived from broker/exchange
// status values — nothing invents a session the feed did not report.
export const SESSION_STATES = ["OPEN", "CLOSING_AUCTION", "TRANSITION", "CLOSED", "UNKNOWN"];

// NSE F&O trading hours (IST): 09:15–15:30, Mon–Fri (INDEX_DERIVATIVES).
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
// Segment-aware (Phase 5.2.1): uses the segment's explicit continuous
// window. The local calendar never invents a closing-auction window — only
// the broker/exchange feed reports those sessions.
export function nseCalendarStatus(date = new Date(), segment = INDEX_DERIVATIVES) {
  const def = SESSION_DEFINITIONS[segment] ?? SESSION_DEFINITIONS[INDEX_DERIVATIVES];
  const [openH, openM] = def.continuousOpen.split(":").map(Number);
  const [closeH, closeM] = def.continuousClose.split(":").map(Number);
  const openMinutes = openH * 60 + openM;
  const closeMinutes = closeH * 60 + closeM;
  const { weekday, hour, minute, second } = istClockParts(date);
  const tradeDate = istDateIso(date);
  const minutes = hour * 60 + minute + (second ?? 0) / 60;

  if (weekday === "Sat" || weekday === "Sun") {
    return { status: "closed", reason: "Weekend — NSE is closed (Saturday/Sunday).", tradeDate, segment, sessionState: "CLOSED" };
  }
  if (NSE_TRADING_HOLIDAYS.has(tradeDate)) {
    return { status: "closed", reason: "NSE trading holiday.", tradeDate, segment, sessionState: "CLOSED" };
  }
  if (minutes < openMinutes) {
    return { status: "closed", reason: `Before the ${def.continuousOpen} IST market open.`, tradeDate, segment, sessionState: "CLOSED" };
  }
  if (minutes > closeMinutes) {
    return { status: "closed", reason: `After the ${def.continuousClose} IST market close.`, tradeDate, segment, sessionState: "CLOSED" };
  }
  return { status: "open", reason: `Within ${def.segment} market hours (Mon–Fri ${def.continuousOpen}–${def.continuousClose} IST).`, tradeDate, segment, sessionState: "OPEN" };
}

export const MARKET_STATUS_LABELS = {
  open: "🟢 MARKET OPEN — Orders Enabled",
  closed: "🔴 MARKET CLOSED — Orders Disabled",
  unknown: "🟠 UNABLE TO VERIFY — Orders Blocked",
  // Phase 5.2.1 explicit session states: informational badges. Only OPEN
  // authorizes orders; the backend re-validates at execution time.
  closing_auction: "🟡 CLOSING AUCTION — Orders Disabled",
  transition: "🟠 TRANSITION SESSION — Orders Disabled",
};

// Session-state → badge label (defaults to the status-level label when the
// session state is not one of the explicit informational states).
export function sessionStateLabel(sessionState) {
  if (!sessionState) return null;
  const key = String(sessionState).toLowerCase();
  return MARKET_STATUS_LABELS[key] ?? null;
}

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
