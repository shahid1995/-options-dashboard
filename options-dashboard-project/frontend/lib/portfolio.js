// Pure helpers for the Phase 5.0 server-authoritative paper portfolio.
//
// The backend decides fills, positions, cash and realized P&L; these helpers
// only shape that state for the UI and build idempotent request payloads.
// Nothing here ever decides that an order filled or that cash changed.

// Unique idempotency key for executions/exits. Two calls never collide, so a
// double click / browser retry submits the SAME key and the backend replays
// the original result instead of executing twice.
export function makeClientOrderId(prefix = "exec") {
  const rand =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
  return `${prefix}-${rand}`.slice(0, 64);
}

// Backend PositionOut -> the position shape the paper UI renders.
// action is derived from the signed net quantity (BUY = +, SELL = −).
export function toFrontendPosition(p) {
  return {
    positionId: p.id,
    id: `pos-${p.id}`,
    symbol: p.symbol,
    type: p.option_type,
    strike: p.strike,
    expiry: p.expiry,
    action: p.net_quantity >= 0 ? "buy" : "sell",
    qty: Math.abs(p.net_quantity),
    lotSize: p.lot_size,
    entryPremium: p.average_entry_price,
    avgEntryPrice: p.average_entry_price,
    realizedPnl: p.realized_pnl,
    strategyName: p.strategy_tag ?? "Custom",
    executionId: p.strategy_execution_id,
    status: p.status,
    openedAt: p.opened_at,
  };
}

// Mark-to-market P&L for a position at a market price, in the same convention
// as the backend: long = (price − avg) × qty × lot, short = (avg − price) ×
// qty × lot. Returns null when no market mark is available (never 0 — 0 is a
// valid P&L, not a missing one).
export function unrealizedPnl(position, ltp) {
  if (ltp == null) return null;
  const dir = position.action === "buy" ? 1 : -1;
  return dir * (ltp - position.entryPremium) * position.lotSize * position.qty;
}

// Exit-quantity validation for the UI (the backend is the final authority).
export function validateExitQuantity(position, qty) {
  if (!Number.isInteger(qty) || qty <= 0) {
    return { ok: false, error: "Exit quantity must be a positive whole number of lots." };
  }
  if (qty > position.qty) {
    return { ok: false, error: `Only ${position.qty} lot(s) available to exit.` };
  }
  return { ok: true };
}

// Human-readable fallback per structured backend error code (§32). The
// backend sends "CODE: message" details; we surface the human part and never
// expose internal stack traces.
const ERROR_DEFAULTS = {
  MARKET_CLOSED: "Market is closed. Paper order was not executed.",
  MARKET_UNKNOWN: "Unable to verify market status. Order was not executed.",
  CHAIN_DATA_MISSING: "Required market data is not available. Paper order was not executed.",
  BULK_EXIT_CHAIN_DATA_MISSING: "Required market data is not available. No position was closed.",
  INVALID_QUANTITY: "Invalid quantity.",
  POSITION_NOT_FOUND: "Position not found.",
  INSUFFICIENT_POSITION: "Not enough quantity available to exit.",
  INVALID_STATE_TRANSITION: "This action is not allowed in the current state.",
  DUPLICATE_REQUEST: "This request was already processed.",
  EXECUTION_FAILED: "The paper order could not be executed.",
};

export function paperErrorMessage(error) {
  const detail = error?.response?.data?.detail ?? error?.message;
  if (typeof detail === "string" && detail) {
    const match = detail.match(/^([A-Z_]+):\s*([\s\S]*)$/);
    if (match && ERROR_DEFAULTS[match[1]]) return match[2] || ERROR_DEFAULTS[match[1]];
    return detail;
  }
  return ERROR_DEFAULTS.EXECUTION_FAILED;
}

// Portfolio summary -> display values, tolerating a missing/unavailable
// backend payload (loading/empty states).
export function portfolioDisplay(portfolio) {
  const summary = portfolio?.summary ?? {};
  const round2 = (v) => (v == null ? null : Math.round(v * 100) / 100);
  return {
    startingCash: round2(summary.starting_cash ?? 500000),
    availableCash: round2(summary.available_cash ?? null),
    investedValue: round2(summary.invested_value ?? 0),
    realizedPnl: round2(summary.realized_pnl ?? 0),
    unrealizedPnl: summary.unrealized_pnl == null ? null : round2(summary.unrealized_pnl),
    totalPnl: round2(summary.total_pnl ?? summary.realized_pnl ?? 0),
    openPositionCount: summary.open_position_count ?? 0,
    openStrategyCount: summary.open_strategy_count ?? 0,
  };
}

// Whether trading buttons are enabled, based on the market-status badge.
// Informational only — the backend re-validates at execution time.
export function canTrade(marketStatus) {
  return marketStatus?.status === "open";
}

// Build the idempotent strategy-execution request from the builder state.
export function buildExecutionRequest({ symbol, strategy, legs, lotSize, multiplier, startingCapital }) {
  return {
    client_order_id: makeClientOrderId("exec"),
    symbol,
    strategy_tag: strategy?.name ?? "Custom",
    strategy_id: strategy?.id ?? null,
    starting_capital: startingCapital,
    legs: legs.map((l) => ({
      symbol,
      expiration_date: l.expiry,
      strike_price: l.strike,
      option_type: l.type,
      action: l.action,
      quantity: l.qty * multiplier,
      lot_size: lotSize,
    })),
  };
}

// Build the idempotent position-exit request (quantity in lots).
export function buildExitRequest(qty) {
  return { client_order_id: makeClientOrderId("exit"), quantity: qty };
}

// Build the idempotent BULK exit request (EXIT STRATEGY / EXIT ALL). One key
// covers the WHOLE operation: a retry/double-submit replays the original
// result instead of closing anything twice.
export function buildBulkExitRequest(prefix = "exit-all") {
  return { client_order_id: makeClientOrderId(prefix) };
}

// Group the open positions (frontend shape from toFrontendPosition) by
// strategy execution so the UI can offer one EXIT STRATEGY per group.
// Standalone positions (no execution id) form their own group without a
// strategy button. Approximate current value = |qty| × lot × LTP (mark-based,
// informational only — the backend decides the final fill prices).
export function openStrategyGroups(positionsWithLtp) {
  const map = new Map();
  for (const p of positionsWithLtp ?? []) {
    const key = p.executionId ?? "standalone";
    let g = map.get(key);
    if (!g) {
      g = {
        executionId: key === "standalone" ? null : p.executionId,
        strategyName: key === "standalone" ? "Standalone" : p.strategyName ?? "Custom",
        positions: [],
        value: 0,
        hasMarks: true,
        unrealized: 0,
      };
      map.set(key, g);
    }
    g.positions.push(p);
    if (p.currentLtp == null) {
      g.hasMarks = false;
    } else {
      g.value += Math.abs(p.currentLtp) * (p.lotSize ?? 0) * p.qty;
      g.unrealized += p.unrealizedPnl ?? 0;
    }
  }
  return Array.from(map.values()).map((g) => ({
    ...g,
    value: g.hasMarks ? Math.round(g.value * 100) / 100 : null,
    unrealized: g.hasMarks ? Math.round(g.unrealized * 100) / 100 : null,
    isStrategy: g.executionId != null,
  }));
}

// ---- Phase 5.2.1: strategy filter over ACTIVE positions ---------------------
//
// The filter is built dynamically from the currently-open strategy
// executions (never hard-coded). Its unique identity is the strategy
// EXECUTION id — selecting a strategy filters by strategy_execution_id, not
// by name string, symbol, strike or option type.

// Dropdown options: [{ executionId, strategyName, count }] — one per open
// strategy execution (count = number of open legs/positions it owns).
export function strategyFilterOptions(positionsWithLtp) {
  const groups = openStrategyGroups(positionsWithLtp).filter((g) => g.isStrategy);
  return groups.map((g) => ({
    executionId: g.executionId,
    strategyName: g.strategyName,
    count: g.positions.length,
  }));
}

// Filter the active positions to ONE strategy execution (or all when
// executionId is null/undefined — "All Open Positions"). The comparison is
// always against the position's strategy_execution_id.
export function filterPositionsByStrategy(positionsWithLtp, executionId) {
  if (executionId == null) return positionsWithLtp ?? [];
  return (positionsWithLtp ?? []).filter((p) => p.executionId === executionId);
}

// Shape a backend BulkExitOut into the display object the result banner uses.
export function bulkExitDisplay(result) {
  const r = result ?? {};
  const failed = (r.positions ?? []).filter((p) => p.status !== "EXITED");
  return {
    scope: r.scope ?? "ACCOUNT",
    status: r.status ?? "FAILED",
    requestedCount: r.requested_count ?? 0,
    exitedCount: r.exited_count ?? 0,
    failedCount: r.failed_count ?? failed.length,
    totalRealizedPnl: r.total_realized_pnl ?? 0,
    cashChange: r.cash_change ?? 0,
    positions: r.positions ?? [],
    groups: r.groups ?? [],
    errors: r.errors ?? [],
    duplicated: r.duplicated ?? false,
  };
}
