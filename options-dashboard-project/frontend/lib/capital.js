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
    brokerCashAvailable: capitalValue(c.broker_cash_available),
    brokerMarginUsed: capitalValue(c.broker_margin_used),
    brokerPledgeAvailable: capitalValue(c.broker_pledge_available),
    brokerFundsDetail: c.broker_funds_detail ?? null,
    brokerMarginDetail: c.broker_margin_detail ?? null,
    brokerErrors: c.broker_errors ?? {},
    brokerGeneratedAt: c.broker_generated_at ?? null,
    expiresAt: c.expires_at ?? null,
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

// Estimated-capital basis label. Phase 6.0/6.1 support the premium basis;
// Phase 6.2 adds the analytical risk basis (defined loss). Null when no
// estimate exists.
export function estimatedBasisLabel(basis) {
  if (basis === "premium") return "Premium Basis";
  if (basis === "max_loss" || basis === "risk_model") return "Risk Basis · Defined Loss";
  return null;
}

// Neutral descriptive difference between the broker-reported margin and the
// analytical estimate: broker_margin − estimated_capital. Returns null when
// either side is unavailable — it is descriptive ONLY (never labeled
// "Savings" / "Advantage" / "Efficiency" / "Better") and never computed
// from a missing number.
export function brokerVsEstimateDifference(brokerMargin, estimatedCapital) {
  if (brokerMargin == null || estimatedCapital == null) return null;
  const broker = Number(brokerMargin);
  const estimate = Number(estimatedCapital);
  if (!Number.isFinite(broker) || !Number.isFinite(estimate)) return null;
  return Math.round((broker - estimate) * 100) / 100;
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
  push("brokerCashAvailable", "Broker Cash Available", display.brokerCashAvailable);
  push("brokerMarginUsed", "Broker Margin Used", display.brokerMarginUsed);
  push("brokerPledgeAvailable", "Broker Pledge Available", display.brokerPledgeAvailable);
  push("capitalUsed", "Capital Used", display.capitalUsed);
  return rows;
}

// Per-strategy breakdown rows (whole-strategy capital units — multi-leg
// strategies appear as ONE row, never per-leg margin numbers summed). Phase
// 6.1 adds the whole-strategy BROKER margin (with structured error code).
export function capitalStrategyRows(strategies) {
  return (strategies ?? []).map((s) => ({
    executionId: s.execution_id,
    strategy: s.strategy_tag,
    symbol: s.symbol,
    entryNet: s.entry_net,
    premiumOutlay: s.premium_outlay,
    estimatedCapital: s.estimated_capital,
    estimatedCapitalBasis: estimatedBasisLabel(s.estimated_capital_basis),
    brokerMargin: s.broker_margin ?? null,
    brokerMarginStatus: s.broker_margin_status ?? "unavailable",
    brokerMarginError: s.broker_margin_error ?? null,
    brokerMarginTimestamp: s.broker_margin_timestamp ?? null,
  }));
}

// ---- Phase 6.1 broker display helpers --------------------------------------

// Human label for a structured broker error code. Never shows a raw stack
// trace — just the stable code + a short user-facing explanation.
export function brokerErrorLabel(code) {
  const labels = {
    BROKER_AUTH_REQUIRED: "Broker login required",
    BROKER_TOKEN_EXPIRED: "Broker session expired — log in again",
    BROKER_RATE_LIMITED: "Broker rate limited — try again shortly",
    BROKER_FUNDS_UNAVAILABLE: "Broker funds unavailable",
    BROKER_MARGIN_UNAVAILABLE: "Broker margin unavailable",
    MISSING_INSTRUMENT_KEY: "Instrument key unavailable",
    MARGIN_REQUEST_TOO_LARGE: "Strategy exceeds the 20-instrument broker limit",
    BROKER_BAD_RESPONSE: "Broker response unreadable",
    BROKER_MAINTENANCE: "Upstox Funds maintenance window (12:00 AM – 5:30 AM IST)",
  };
  return labels[code] ?? null;
}

// First structured broker error across funds + margin, or null when all good.
export function firstBrokerError(display) {
  const codes = [];
  if (display.brokerErrors?.funds) codes.push(display.brokerErrors.funds);
  if (Array.isArray(display.brokerErrors?.margin)) codes.push(...display.brokerErrors.margin);
  for (const code of codes) {
    if (code) return { code, label: brokerErrorLabel(code) ?? code };
  }
  // Per-strategy errors are also surfaced (e.g. one strategy missing keys).
  for (const s of capitalStrategyRows(display.strategies)) {
    if (s.brokerMarginError) {
      return { code: s.brokerMarginError, label: brokerErrorLabel(s.brokerMarginError) ?? s.brokerMarginError };
    }
  }
  return null;
}

// Compact "as of" caption for broker data: capture time (+ expiry when known).
export function brokerDataCaption(display) {
  const captured = display.brokerGeneratedAt ?? display.brokerMarginDetail?.generated_at ?? display.brokerFundsDetail?.generated_at;
  const expires = display.expiresAt ?? display.brokerMarginDetail?.expires_at ?? display.brokerFundsDetail?.expires_at;
  const fmt = (iso) => {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };
  const capturedFmt = fmt(captured);
  const expiresFmt = fmt(expires);
  if (!capturedFmt) return null;
  return expiresFmt ? `Broker data as of ${capturedFmt} · expires ${expiresFmt}` : `Broker data as of ${capturedFmt}`;
}
