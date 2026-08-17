// ---------------------------------------------------------------------------
// Phase 6.3 — Capital Efficiency & Return Metrics (frontend pure domain module).
//
// Canonical, source-aware return metrics. The platform NEVER displays a bare
// "ROI": every metric carries its own explicitly-defined denominator, label,
// source and basis, and the five concepts stay strictly separate:
//
//   PREMIUM ROI           = P&L / Premium Outlay          (basis PREMIUM)
//   RETURN ON CAPITAL     = P&L / Estimated Capital       (basis ESTIMATED)
//   RETURN ON MARGIN      = P&L / Broker Margin           (BROKER_REPORTED only)
//   RETURN ON RISK CAPITAL= P&L / abs(Max Loss)           (basis MAX_LOSS)
//   CAPITAL EFFICIENCY    = P&L / explicitly chosen capital denominator
//
// Rules (non-negotiable):
//   - Never fabricate denominators: null / 0 / negative / NaN / Infinity →
//     value null, never a divide-by-zero, never a fallback (no paper cash
//     for broker margin, no broker margin for estimated capital, no max loss
//     for premium outlay, ...).
//   - Numerator sign preserved (positive P&L → +%, negative → −%, zero → 0.0%).
//   - P&L state is explicit: REALIZED | UNREALIZED | TOTAL (PROJECTED allowed
//     for builder contexts, always labeled).
//   - The P&L period must match the capital period; a mismatch returns
//     unavailable + MISMATCHED_PERIOD (no period normalization/annualization).
//   - No auto-selected denominators: capital-efficiency requires an explicit
//     denominatorType, and the primary strategy preference (Estimated Capital)
//     is documented, never silently swapped.
//
// All functions are deterministic, pure, side-effect free, dependency-light
// and broker-independent (they CONSUME broker-reported values, never fetch).
// ---------------------------------------------------------------------------

export const W_INVALID_DENOMINATOR = "INVALID_DENOMINATOR";
export const W_MISSING_DENOMINATOR = "MISSING_DENOMINATOR";
export const W_MISSING_PNL = "MISSING_PNL";
export const W_UNLIMITED_RISK = "UNLIMITED_RISK";
export const W_MISMATCHED_PERIOD = "MISMATCHED_PERIOD";
export const W_DENOMINATOR_NOT_SPECIFIED = "DENOMINATOR_NOT_SPECIFIED";
export const W_SOURCE_NOT_BROKER_REPORTED = "SOURCE_NOT_BROKER_REPORTED";

export const DENOMINATOR_TYPES = ["PREMIUM_OUTLAY", "ESTIMATED_CAPITAL", "BROKER_MARGIN", "MAX_LOSS"];

export const DENOMINATOR_LABELS = {
  PREMIUM_OUTLAY: "Premium Outlay",
  ESTIMATED_CAPITAL: "Estimated Capital",
  BROKER_MARGIN: "Broker Margin",
  MAX_LOSS: "Defined Max Loss",
};

// ---- Numeric safety ---------------------------------------------------------

function safeNum(v) {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

// Accept a plain number or a {value, source, basis, status} capital object
// (the backend CapitalValueOut shape) — never trust the shape blindly.
function denomValue(x) {
  return x == null ? null : safeNum(typeof x === "object" ? x.value : x);
}

function denomSource(x, fallback) {
  return x && typeof x === "object" ? x.source ?? fallback : fallback;
}

function denomBasis(x, fallback) {
  return x && typeof x === "object" ? x.basis ?? fallback : fallback;
}

// P&L / denominator × 100, rounded to two decimals. null whenever either side
// is missing or the denominator is not a strictly positive finite number.
function pct(pnl, denominator) {
  const p = safeNum(pnl);
  const d = safeNum(denominator);
  if (p === null || d === null || d <= 0) return null;
  return Math.round((p / d) * 10000) / 100;
}

function base({ value, numerator, denominator, denominatorLabel, denominatorSource, basis, pnlType, period, warnings }) {
  return {
    value, // finite percentage or null
    status: value == null ? "unavailable" : "available",
    numerator: safeNum(numerator),
    denominator: safeNum(denominator),
    denominatorLabel,
    denominatorSource,
    basis,
    pnlType: pnlType ?? "TOTAL", // REALIZED | UNREALIZED | TOTAL | PROJECTED
    period: period ?? null,
    warnings: [...(warnings ?? [])],
  };
}

// ---- Premium ROI (§7) -------------------------------------------------------

export function calculatePremiumRoi({ pnl, premiumOutlay, pnlType, period } = {}) {
  const den = denomValue(premiumOutlay);
  const label = DENOMINATOR_LABELS.PREMIUM_OUTLAY;
  const source = denomSource(premiumOutlay, "CALCULATED");
  if (safeNum(pnl) === null) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "PREMIUM", pnlType, period, warnings: [W_MISSING_PNL] });
  }
  if (den === null) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "PREMIUM", pnlType, period, warnings: [W_MISSING_DENOMINATOR] });
  }
  if (den <= 0) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "PREMIUM", pnlType, period, warnings: [W_INVALID_DENOMINATOR] });
  }
  return base({ value: pct(pnl, den), numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "PREMIUM", pnlType, period, warnings: [] });
}

// ---- Return on Estimated Capital (§8) ---------------------------------------

export function calculateReturnOnCapital({ pnl, estimatedCapital, basis, unlimited = false, pnlType, period } = {}) {
  const den = denomValue(estimatedCapital);
  const label = DENOMINATOR_LABELS.ESTIMATED_CAPITAL;
  const source = denomSource(estimatedCapital, "ESTIMATED");
  const basisValue = basis ?? denomBasis(estimatedCapital, "ESTIMATED");
  if (unlimited === true) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: basisValue, pnlType, period, warnings: [W_UNLIMITED_RISK] });
  }
  if (safeNum(pnl) === null) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: basisValue, pnlType, period, warnings: [W_MISSING_PNL] });
  }
  if (den === null) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: basisValue, pnlType, period, warnings: [W_MISSING_DENOMINATOR] });
  }
  if (den <= 0) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: basisValue, pnlType, period, warnings: [W_INVALID_DENOMINATOR] });
  }
  return base({ value: pct(pnl, den), numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: basisValue, pnlType, period, warnings: [] });
}

// ---- Return on Broker Margin (§9) -------------------------------------------

export function calculateReturnOnMargin({ pnl, brokerMargin, pnlType, period } = {}) {
  const den = denomValue(brokerMargin);
  const label = DENOMINATOR_LABELS.BROKER_MARGIN;
  const source = denomSource(brokerMargin, "BROKER_REPORTED");
  // §9/§25: only BROKER_REPORTED values may be a margin denominator — never
  // estimated capital, never paper cash, never a fabricated source.
  if (brokerMargin && typeof brokerMargin === "object" && brokerMargin.source && brokerMargin.source !== "BROKER_REPORTED") {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "BROKER_REPORTED", pnlType, period, warnings: [W_SOURCE_NOT_BROKER_REPORTED] });
  }
  if (safeNum(pnl) === null) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "BROKER_REPORTED", pnlType, period, warnings: [W_MISSING_PNL] });
  }
  if (den === null) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "BROKER_REPORTED", pnlType, period, warnings: [W_MISSING_DENOMINATOR] });
  }
  if (den <= 0) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "BROKER_REPORTED", pnlType, period, warnings: [W_INVALID_DENOMINATOR] });
  }
  return base({ value: pct(pnl, den), numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "BROKER_REPORTED", pnlType, period, warnings: [] });
}

// ---- Return on Risk Capital (§10) -------------------------------------------

export function calculateReturnOnRiskCapital({ pnl, maxLoss, unlimited = false, pnlType, period } = {}) {
  const raw = safeNum(maxLoss);
  // maxLoss is a loss (≤ 0); the risk-capital denominator is its magnitude.
  const den = raw === null ? null : Math.abs(raw);
  const label = DENOMINATOR_LABELS.MAX_LOSS;
  const source = "CALCULATED";
  if (unlimited === true) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "MAX_LOSS", pnlType, period, warnings: [W_UNLIMITED_RISK] });
  }
  if (safeNum(pnl) === null) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "MAX_LOSS", pnlType, period, warnings: [W_MISSING_PNL] });
  }
  if (den === null) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "MAX_LOSS", pnlType, period, warnings: [W_MISSING_DENOMINATOR] });
  }
  if (den === 0) {
    return base({ value: null, numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "MAX_LOSS", pnlType, period, warnings: [W_INVALID_DENOMINATOR] });
  }
  return base({ value: pct(pnl, den), numerator: pnl, denominator: den, denominatorLabel: label, denominatorSource: source, basis: "MAX_LOSS", pnlType, period, warnings: [] });
}

// ---- Capital Efficiency (§11/§12) -------------------------------------------
// An EXPLICIT, source-aware efficiency ratio: P&L / a caller-chosen capital
// basis. The denominatorType is never auto-selected — if the caller does not
// name it, the result is unavailable (DENOMINATOR_NOT_SPECIFIED).

export function calculateCapitalEfficiency({ pnl, denominator, denominatorType, denominatorSource, basis, pnlType, period } = {}) {
  if (!DENOMINATOR_TYPES.includes(denominatorType)) {
    return {
      value: null,
      status: "unavailable",
      denominatorType: denominatorType ?? null,
      denominatorValue: denomValue(denominator),
      denominatorSource: denominatorSource ?? denomSource(denominator, "CALCULATED"),
      basis: basis ?? "UNSPECIFIED",
      numerator: safeNum(pnl),
      pnlType: pnlType ?? "TOTAL",
      period: period ?? null,
      warnings: [W_DENOMINATOR_NOT_SPECIFIED],
    };
  }
  const den = denomValue(denominator);
  const label = DENOMINATOR_LABELS[denominatorType];
  const source = denominatorSource ?? denomSource(denominator, "CALCULATED");
  const warnings = [];
  let value = null;
  if (safeNum(pnl) === null) warnings.push(W_MISSING_PNL);
  else if (den === null) warnings.push(W_MISSING_DENOMINATOR);
  else if (den <= 0) warnings.push(W_INVALID_DENOMINATOR);
  else value = pct(pnl, den);
  return {
    value,
    status: value == null ? "unavailable" : "available",
    denominatorType,
    denominatorValue: den,
    denominatorSource: source,
    basis,
    numerator: safeNum(pnl),
    pnlType: pnlType ?? "TOTAL",
    period: period ?? null,
    warnings,
  };
}

// ---- Full metric set (§4/§12/§16) -------------------------------------------
// One call computes the whole, non-overlapping set. The P&L period must match
// the capital period; otherwise every metric is unavailable with
// MISMATCHED_PERIOD (no period-normalized/annualized returns in Phase 6.3).
// The preferred capital-efficiency denominator (Estimated Capital, §12 primary)
// is explicit; the caller can compute other variants with
// calculateCapitalEfficiency directly.

export function calculateCapitalEfficiencySet({
  pnl,
  pnlType = "TOTAL",
  period = "inception",
  capitalPeriod = period,
  premiumOutlay,
  estimatedCapital,
  brokerMargin,
  maxLoss,
  maxLossUnlimited = false,
  estimatedCapitalBasis,
} = {}) {
  const periodWarn = period !== capitalPeriod ? [W_MISMATCHED_PERIOD] : [];
  const withPeriod = (metric) =>
    periodWarn.length > 0
      ? { ...metric, value: null, status: "unavailable", warnings: [...metric.warnings, W_MISMATCHED_PERIOD] }
      : metric;

  const premiumRoi = withPeriod(calculatePremiumRoi({ pnl, premiumOutlay, pnlType, period }));
  const returnOnCapital = withPeriod(
    calculateReturnOnCapital({
      pnl,
      estimatedCapital,
      basis: estimatedCapitalBasis ?? (estimatedCapital && typeof estimatedCapital === "object" ? estimatedCapital.basis : undefined),
      unlimited: maxLossUnlimited,
      pnlType,
      period,
    })
  );
  const returnOnMargin = withPeriod(calculateReturnOnMargin({ pnl, brokerMargin, pnlType, period }));
  const returnOnRiskCapital = withPeriod(calculateReturnOnRiskCapital({ pnl, maxLoss, unlimited: maxLossUnlimited, pnlType, period }));
  const capitalEfficiency = withPeriod(
    calculateCapitalEfficiency({
      pnl,
      denominator: estimatedCapital,
      denominatorType: "ESTIMATED_CAPITAL",
      denominatorSource: "ESTIMATED",
      basis: estimatedCapitalBasis ?? (estimatedCapital && typeof estimatedCapital === "object" ? estimatedCapital.basis : undefined),
      pnlType,
      period,
    })
  );

  const metrics = [premiumRoi, returnOnCapital, returnOnMargin, returnOnRiskCapital, capitalEfficiency];
  const availableCount = metrics.filter((m) => m.status === "available").length;
  const status = availableCount === 0 ? "unavailable" : availableCount === metrics.length ? "available" : "partial";

  return {
    premiumRoi,
    returnOnCapital,
    returnOnMargin,
    returnOnRiskCapital,
    capitalEfficiency,
    status,
    period,
    pnlType,
    warnings: periodWarn,
  };
}
