// Pure analytics over a chain: rows of { strike, call: { oi, ltp, ... }, put: { ... } }.

export function oiTotals(rows) {
  let callOI = 0;
  let putOI = 0;
  for (const r of rows) {
    callOI += r.call?.oi ?? 0;
    putOI += r.put?.oi ?? 0;
  }
  return { callOI, putOI };
}

// Put-Call Ratio by open interest. Null when there is no call OI.
export function putCallRatio(rows) {
  const { callOI, putOI } = oiTotals(rows);
  if (!callOI) return null;
  return putOI / callOI;
}

// Max pain: the expiry price where option writers lose the least, i.e. the
// strike minimizing the total intrinsic value paid out across all OI.
export function maxPainStrike(rows) {
  if (!rows.length) return null;
  let best = null;
  let bestPain = Infinity;
  for (const s of rows) {
    let pain = 0;
    for (const k of rows) {
      pain += (k.call?.oi ?? 0) * Math.max(0, s.strike - k.strike);
      pain += (k.put?.oi ?? 0) * Math.max(0, k.strike - s.strike);
    }
    if (pain < bestPain) {
      bestPain = pain;
      best = s.strike;
    }
  }
  return best;
}

// Largest single-side OI across the chain, used to scale OI bars.
export function maxOI(rows) {
  let max = 0;
  for (const r of rows) {
    max = Math.max(max, r.call?.oi ?? 0, r.put?.oi ?? 0);
  }
  return max;
}

// ---------------------------------------------------------------------------
// Phase 5.1 — Portfolio & Journal Analytics display helpers.
//
// The backend (GET /paper/analytics) is the authoritative analytics engine:
// every metric is computed there from server-authoritative paper records.
// These helpers ONLY format server values for display and compute the two
// mark-based measurements the backend cannot (market value / concentration,
// which need live LTPs from the frontend chain cache). No financial formula
// is duplicated here.
// ---------------------------------------------------------------------------

// User-friendly duration label, mirroring the backend's convention.
// "2h 14m", "45m", "30s", "3d 4h"; null when unknown.
export function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return null;
  const s = Math.trunc(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

// Display metadata for a completed trade's result (WIN/LOSS/BREAKEVEN).
export function resultBadge(result) {
  if (result === "WIN") return { label: "WIN", color: "#4CAF7D" };
  if (result === "LOSS") return { label: "LOSS", color: "#E15252" };
  if (result === "BREAKEVEN") return { label: "BREAKEVEN", color: "#8892A6" };
  return { label: "—", color: "#5A6376" };
}

// Flatten the server analytics response into display-safe blocks. Every
// missing/None metric stays null (never 0/NaN/Infinity) so the UI can show
// "—"/"No completed trades" instead of fabricated numbers.
export function analyticsDisplay(analytics) {
  const a = analytics ?? {};
  const summary = a.summary ?? {};
  const perf = a.performance ?? {};
  const dd = a.drawdown ?? {};
  const round2 = (v) => (v == null || Number.isNaN(v) ? null : Math.round(v * 100) / 100);
  return {
    summary: {
      startingCapital: round2(summary.starting_capital),
      availableCash: round2(summary.available_cash),
      investedValue: round2(summary.invested_value),
      realizedPnl: round2(summary.realized_pnl ?? 0),
      unrealizedPnl: summary.unrealized_pnl == null ? null : round2(summary.unrealized_pnl),
      totalPnl: round2(summary.total_pnl ?? 0),
      returnPct: summary.return_pct == null ? null : round2(summary.return_pct),
      openPositionCount: summary.open_position_count ?? 0,
      openStrategyCount: summary.open_strategy_count ?? 0,
    },
    performance: {
      totalCompletedTrades: perf.total_completed_trades ?? 0,
      winningTrades: perf.winning_trades ?? 0,
      losingTrades: perf.losing_trades ?? 0,
      breakevenTrades: perf.breakeven_trades ?? 0,
      winRate: perf.win_rate == null ? null : round2(perf.win_rate),
      averageWinner: round2(perf.average_winner),
      averageLoser: round2(perf.average_loser),
      profitFactor: perf.profit_factor == null ? null : Math.round(perf.profit_factor * 100) / 100,
      expectancy: round2(perf.expectancy),
      largestWinner: round2(perf.largest_winner),
      largestLoser: round2(perf.largest_loser),
      currentWinStreak: perf.current_win_streak ?? 0,
      currentLossStreak: perf.current_loss_streak ?? 0,
      maxWinStreak: perf.max_win_streak ?? 0,
      maxLossStreak: perf.max_loss_streak ?? 0,
      averageHoldingDuration: perf.average_holding_duration == null ? null : formatDuration(perf.average_holding_duration),
      medianHoldingDuration: perf.median_holding_duration == null ? null : formatDuration(perf.median_holding_duration),
    },
    drawdown: {
      currentDrawdown: round2(dd.current_drawdown),
      currentDrawdownPct: dd.current_drawdown_pct == null ? null : round2(dd.current_drawdown_pct),
      maxDrawdown: round2(dd.max_drawdown),
      maxDrawdownPct: dd.max_drawdown_pct == null ? null : round2(dd.max_drawdown_pct),
    },
    positions: a.positions ?? { long_exposure: 0, short_exposure: 0, total_exposure: 0, items: [] },
    strategies: a.strategies ?? [],
    journal: a.journal ?? [],
    dailyPnl: a.daily_pnl ?? [],
    dataQuality: a.data_quality ?? {},
    filters: a.filters ?? {},
  };
}

// Server equity-curve points -> recharts series. The curve is REALIZED-only
// (equity = starting capital + cumulative realized P&L); the UI labels it.
export function equityChartData(curve) {
  return (curve ?? []).map((p) => ({
    date: p.date,
    equity: p.equity,
    cumulativePnl: p.cumulative_pnl,
    pnl: p.pnl,
  }));
}

// Map the server's completed-trade journal to display rows: human date,
// duration fallback, result badge metadata, leg summary text.
export function journalDisplayRows(analytics) {
  const a = analyticsDisplay(analytics);
  return a.journal.map((row) => {
    const badge = resultBadge(row.result);
    const legs = (row.legs ?? []).map((l) => ({
      label: `${l.action === "buy" ? "BUY" : "SELL"} ${l.symbol} ${l.strike} ${l.option_type === "call" ? "CE" : "PE"}${l.quantity && l.lot_size ? ` ×${l.quantity} lot` : ""}`,
      strike: l.strike,
      action: l.action,
    }));
    return {
      executionId: row.execution_id,
      strategy: row.strategy ?? "Custom",
      symbol: row.symbol,
      entryAt: row.entry_at,
      exitAt: row.exit_at,
      entryLabel: fmtShortDate(row.entry_at),
      exitLabel: fmtShortDate(row.exit_at),
      durationLabel: row.duration_label ?? formatDuration(row.duration_seconds),
      realizedPnl: row.realized_pnl ?? 0,
      result: row.result,
      resultColor: badge.color,
      legs,
    };
  });
}

// Sort completed-trade journal rows by date | pnl | duration (stable, safe
// for empty/partial data). Used by the journal table's sort control.
export function sortJournalRows(rows, key) {
  const sorted = [...rows];
  if (key === "pnl") return sorted.sort((a, b) => b.realizedPnl - a.realizedPnl);
  if (key === "duration") {
    const dur = (r) =>
      typeof r.duration_seconds === "number" ? r.duration_seconds : -1;
    return sorted.sort((a, b) => dur(b) - dur(a));
  }
  // date (default): newest first, missing dates last.
  return sorted.sort((a, b) => {
    const t = (v) => (v ? new Date(v).getTime() : -Infinity);
    return t(b.exitAt ?? b.entryAt) - t(a.exitAt ?? a.entryAt);
  });
}

// Accepts either the backend PositionAnalyticsItemOut shape or the frontend
// toFrontendPosition shape and returns the canonical mark-based position
// shape used by marketValue / concentration / markedExposure.
export function normalizeMarkedPosition(p) {
  const qty =
    p.net_quantity != null
      ? p.net_quantity
      : (p.action === "sell" ? -1 : 1) * (p.qty ?? 0);
  return {
    symbol: p.symbol,
    strike: p.strike,
    option_type: p.option_type ?? p.type,
    net_quantity: qty,
    lot_size: p.lot_size ?? p.lotSize,
    currentLtp: p.currentLtp ?? null,
  };
}

// Mark-based market value of one open position: |qty| × lot × LTP.
// Returns null when there is no live mark (never 0 for "missing").
export function marketValue(position) {
  const p = normalizeMarkedPosition(position);
  if (p.currentLtp == null) return null;
  return Math.abs(p.net_quantity ?? 0) * (p.lot_size ?? 0) * p.currentLtp;
}

// Concentration across open positions (mark-based, absolute exposure).
// Returns { total, items: [{ key, marketValue, concentrationPct }] } sorted
// by market value desc. concentrationPct is null when total exposure is 0
// (a measurement only — never labeled good/bad).
export function concentration(positions) {
  const withValue = (positions ?? [])
    .map((p) => {
      const mv = marketValue(p);
      if (mv == null) return null;
      const n = normalizeMarkedPosition(p);
      const side = n.net_quantity > 0 ? "long" : "short";
      return {
        key: `${n.symbol ?? "?"} ${n.strike ?? "?"} ${(n.option_type ?? "").toUpperCase()} · ${side}`,
        marketValue: mv,
      };
    })
    .filter(Boolean);
  const total = withValue.reduce((sum, i) => sum + i.marketValue, 0);
  return {
    total,
    items: withValue
      .map((i) => ({
        key: i.key,
        marketValue: Math.round(i.marketValue * 100) / 100,
        concentrationPct: total > 0 ? Math.round((i.marketValue / total) * 10000) / 100 : null,
      }))
      .sort((a, b) => b.marketValue - a.marketValue),
  };
}

// Mark-based long/short exposure of open positions (market value). Falls back
// to null per side when no marks exist (never fabricates a value).
export function markedExposure(positions) {
  let long = null;
  let short = null;
  for (const p of positions ?? []) {
    const n = normalizeMarkedPosition(p);
    const mv = marketValue(n);
    if (mv == null) continue;
    if (n.net_quantity > 0) long = (long ?? 0) + mv;
    else short = (short ?? 0) + mv;
  }
  return {
    longExposure: long == null ? null : Math.round(long * 100) / 100,
    shortExposure: short == null ? null : Math.round(short * 100) / 100,
    totalExposure: long == null && short == null ? null : Math.round((long ?? 0) + (short ?? 0)),
  };
}

function fmtShortDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

// Empty-state helper: "No completed trades" instead of "Win rate 0%".
export function hasCompletedTrades(analytics) {
  return (analyticsDisplay(analytics).performance.totalCompletedTrades ?? 0) > 0;
}
