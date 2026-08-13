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

// Appends an equity snapshot at most once per `minIntervalMs`, keeping the
// series bounded to `maxPoints`.
export function recordEquityPoint(points, equity, time = Date.now(), maxPoints = 500, minIntervalMs = 60000) {
  const last = points[points.length - 1];
  if (last && time - last.time < minIntervalMs) return points;
  const next = [...points, { time, equity }];
  return next.length > maxPoints ? next.slice(next.length - maxPoints) : next;
}
