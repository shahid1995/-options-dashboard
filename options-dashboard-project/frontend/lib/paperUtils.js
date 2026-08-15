// Pure helpers for the paper trading portfolio.

const CSV_COLUMNS = [
  ["symbol", (h) => h.symbol],
  ["type", (h) => h.type],
  ["strike", (h) => h.strike],
  ["expiry", (h) => h.expiry],
  ["action", (h) => h.action],
  ["qty", (h) => h.qty],
  ["lot_size", (h) => h.lotSize],
  ["strategy", (h) => h.strategyName ?? "Custom"],
  ["entry_premium", (h) => h.entryPremium],
  ["exit_price", (h) => h.exitPrice],
  ["realized_pnl", (h) => h.realizedPnl],
  ["entry_time", (h) => h.entryTime],
  ["exit_time", (h) => h.exitTime],
];

function csvEscape(v) {
  if (v === null || v === undefined) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function historyToCsv(history) {
  const header = CSV_COLUMNS.map(([name]) => name).join(",");
  const lines = history.map((h) => CSV_COLUMNS.map(([, get]) => csvEscape(get(h))).join(","));
  return [header, ...lines].join("\n");
}

// Groups closed trades by the strategy they were executed from.
export function strategyStats(history) {
  const groups = new Map();
  for (const h of history) {
    const name = h.strategyName ?? "Custom";
    const g = groups.get(name) ?? { strategyName: name, trades: 0, wins: 0, totalPnl: 0 };
    g.trades += 1;
    if (h.realizedPnl > 0) g.wins += 1;
    g.totalPnl += h.realizedPnl;
    groups.set(name, g);
  }
  return [...groups.values()]
    .map((g) => ({ ...g, winRate: g.trades ? g.wins / g.trades : 0 }))
    .sort((a, b) => b.totalPnl - a.totalPnl);
}

// NSE index derivatives trade Monday–Friday, 09:15–15:30 IST.
const MARKET_OPEN_MINUTES = 9 * 60 + 15;
const MARKET_CLOSE_MINUTES = 15 * 60 + 30;

export function istClockParts(date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type) => parts.find((p) => p.type === type)?.value;
  return { weekday: get("weekday"), hour: Number(get("hour")), minute: Number(get("minute")), second: Number(get("second")) };
}

// True when `date` falls inside NSE market hours (Mon–Fri 09:15–15:30 IST).
// Market holidays are not modeled (there is no holiday calendar client-side;
// the "skip flat" rule is what keeps holiday sessions from plotting flat).
export function isWithinMarketHours(date = new Date()) {
  const { weekday, hour, minute } = istClockParts(date);
  if (weekday === "Sat" || weekday === "Sun") return false;
  const minutes = hour * 60 + minute;
  return minutes >= MARKET_OPEN_MINUTES && minutes <= MARKET_CLOSE_MINUTES;
}

// Appends an equity snapshot at most once per `minIntervalMs`, keeping the
// series bounded to `maxPoints`. With `opts.skipFlat`, a point equal to the
// previous one is dropped (off-market and holiday sessions are perfectly flat,
// so keeping them only draws meaningless straight lines).
export function recordEquityPoint(points, equity, time = Date.now(), maxPoints = 500, minIntervalMs = 60000, opts = {}) {
  const { skipFlat = false } = opts;
  const last = points[points.length - 1];
  if (last && time - last.time < minIntervalMs) return points;
  if (skipFlat && last && last.equity === equity) return points;
  const next = [...points, { time, equity }];
  return next.length > maxPoints ? next.slice(next.length - maxPoints) : next;
}

// Cleans a stored series (e.g. history saved before market-hours filtering
// existed): drops off-market points and consecutive flat values.
export function sanitizeEquityHistory(points) {
  const out = [];
  for (const p of points) {
    if (!isWithinMarketHours(new Date(p.time))) continue;
    const last = out[out.length - 1];
    if (last && last.equity === p.equity) continue;
    out.push(p);
  }
  return out;
}
