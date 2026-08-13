// Price alerts on option strikes, persisted by the caller (localStorage).
// Alert: { id, symbol, expiry, strike, type: "call"|"put",
//          condition: "above"|"below", level, triggeredAt: string|null }

export function makeAlert({ symbol, expiry, strike, type, condition, level }) {
  return {
    id: `alert-${symbol}-${strike}-${type}-${condition}-${Date.now()}`,
    symbol,
    expiry,
    strike,
    type,
    condition,
    level,
    triggeredAt: null,
  };
}

export function ltpFor(rows, strike, type) {
  const row = rows.find((r) => r.strike === strike);
  if (!row) return null;
  return type === "call" ? row.call?.ltp ?? null : row.put?.ltp ?? null;
}

// Evaluates untriggered alerts for (symbol, expiry) against the live chain.
// Returns { alerts, fired } where `alerts` has triggeredAt stamped on newly
// fired ones and `fired` lists just those.
export function evaluateAlerts(alerts, rows, symbol, expiry, now = () => new Date().toISOString()) {
  const fired = [];
  const next = alerts.map((a) => {
    if (a.triggeredAt || a.symbol !== symbol || a.expiry !== expiry) return a;
    const ltp = ltpFor(rows, a.strike, a.type);
    if (ltp == null) return a;
    const hit = a.condition === "above" ? ltp >= a.level : ltp <= a.level;
    if (!hit) return a;
    const updated = { ...a, triggeredAt: now() };
    fired.push({ ...updated, ltp });
    return updated;
  });
  return { alerts: next, fired };
}

export function describeAlert(a) {
  const side = a.type === "call" ? "CE" : "PE";
  const dir = a.condition === "above" ? "≥" : "≤";
  return `${a.symbol} ${a.strike} ${side} ${dir} ${a.level}`;
}
