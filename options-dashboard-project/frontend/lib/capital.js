// ---------------------------------------------------------------------------
// Phase 6.0 — Capital & Margin Foundation display helpers.
//
// The backend (GET /paper/capital) is the authoritative capital engine: every
// figure carries its source (BROKER_REPORTED | ESTIMATED | CALCULATED) and
// its availability status (available | partial | unavailable), and missing
// values are null — never 0. These helpers ONLY shape that payload for the
// UI (labels, null handling, row ordering). No financial formula is computed
// or duplicated here, and no Return-on-Capital metric exists yet.
// ---------------------------------------------------------------------------

export const CAPITAL_SOURCE_LABELS = {
  BROKER_REPORTED: "Broker Reported",
  ESTIMATED: "Estimated",
  CALCULATED: "Calculated",
  UNAVAILABLE: "Unavailable",
};

export const CAPITAL_STATUS_LABELS = {
  available: "Available",
  partial: "Partial",
  unavailable: "Unavailable",
};

// A value is present only when it is a finite number (null/NaN/Infinity are
// missing — never rendered as a fabricated 0).
export function hasCapitalValue(v) {
  return v != null && Number.isFinite(v);
}

// Backend CapitalValueOut {value, source, status} -> display value (null when
// missing) plus its provenance. Tolerates a missing/loading payload.
export function capitalValue(cv) {
  if (!cv || !hasCapitalValue(cv.value)) {
    return { value: null, source: cv?.source ?? "UNAVAILABLE", status: cv?.status ?? "unavailable" };
  }
  return { value: cv.value, source: cv.source ?? "UNAVAILABLE", status: cv.status ?? "available" };
}

export function sourceLabel(source) {
  return CAPITAL_SOURCE_LABELS[source] ?? "Unknown";
}

export function statusLabel(status) {
  return CAPITAL_STATUS_LABELS[status] ?? "Unknown";
}

// Map the backend capital payload to a flat display shape. Every figure keeps
// {value, source, status}; unavailable stays null, never 0.
export function capitalDisplay(capital) {
  const c = capital ?? {};
  return {
    premiumOutlay: capitalValue(c.premium_outlay),
    brokerMargin: capitalValue(c.broker_margin),
    estimatedCapital: capitalValue(c.estimated_capital),
    estimatedCapitalBasis: c.estimated_capital_basis ?? null,
    brokerAvailableFunds: capitalValue(c.broker_available_funds),
    paperStartingCapital: capitalValue(c.paper_starting_capital),
    paperAvailableCash: capitalValue(c.paper_available_cash),
    capitalUsed: capitalValue(c.capital_used),
    remainingCapital: capitalValue(c.remaining_capital),
    rocInputs: c.roc_inputs ?? null,
    strategies: Array.isArray(c.strategies) ? c.strategies : [],
    generatedAt: c.generated_at ?? null,
    status: c.status ?? "unavailable",
  };
}

// Estimated-capital basis label, e.g. "Premium Basis" for the only basis
// Phase 6.0 supports. Null when no estimate exists.
export function estimatedBasisLabel(basis) {
  if (basis === "premium") return "Premium Basis";
  return null;
}

// Whether the future Return-on-Capital inputs are complete. This is an INPUT
// availability flag — the metric itself is not computed in Phase 6.0.
export function rocInputsAvailable(roc) {
  return Boolean(roc && roc.available === true);
}

// Ordered rows for the compact capital summary. Each row carries the value,
// its explicit source label, availability and an optional note (e.g. the
// estimated-capital basis) so the UI never shows a bare "Margin".
export function capitalRows(display) {
  const rows = [];
  const push = (key, label, cv, note) => {
    rows.push({
      key,
      label,
      value: cv.value,
      source: sourceLabel(cv.source),
      status: cv.status,
      available: cv.value != null,
      note: note ?? null,
    });
  };

  push("paperStartingCapital", "Paper Starting Capital", display.paperStartingCapital);
  push("paperAvailableCash", "Paper Available Cash", display.paperAvailableCash);
  push("premiumOutlay", "Premium Outlay", display.premiumOutlay);
  push("brokerMargin", "Broker Margin", display.brokerMargin);
  push("estimatedCapital", "Estimated Capital", display.estimatedCapital, estimatedBasisLabel(display.estimatedCapitalBasis));
  push("brokerAvailableFunds", "Broker Available Funds", display.brokerAvailableFunds);
  push("capitalUsed", "Capital Used", display.capitalUsed);
  return rows;
}

// Per-strategy breakdown rows (whole-strategy capital units — multi-leg
// strategies appear as ONE row, never per-leg margin numbers summed).
export function capitalStrategyRows(strategies) {
  return (strategies ?? []).map((s) => ({
    executionId: s.execution_id,
    strategy: s.strategy_tag,
    symbol: s.symbol,
    entryNet: s.entry_net,
    premiumOutlay: s.premium_outlay,
    estimatedCapital: s.estimated_capital,
    estimatedCapitalBasis: estimatedBasisLabel(s.estimated_capital_basis),
  }));
}
