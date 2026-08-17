// ---------------------------------------------------------------------------
// Phase 6.4 — Capital Allocation & Portfolio Risk Controls (frontend pure
// domain module).
//
// Answers, at the PORTFOLIO level and MONITORING-ONLY:
//   1. how much capital is currently allocated?
//   2. how much remains available?
//   3. how much estimated capital is committed?
//   4. how much broker-reported margin is being used?
//   5. how much defined risk is currently open?
//   6. how concentrated is the portfolio (strategy / underlying / expiry)?
//   7. which strategies consume the most capital / defined risk?
//   8. are internal, configurable risk limits being approached?
//
// NON-NEGOTIABLE RULES:
//   - Every figure stays source-aware: Paper Available Cash, Broker Available
//     Funds, Premium Outlay, Estimated Capital, Broker Margin, Defined Risk /
//     Max Loss, Capital Used, Capital Allocation and Capital Efficiency are
//     NEVER conflated. "capital used" is never a synonym for broker margin.
//   - Broker margin is consumed ONLY as BROKER_REPORTED; never substituted
//     with estimatedCapital / paperCash / maxLoss, and per-strategy broker
//     margins are NEVER summed into an account figure (aggregate preferred).
//   - Unavailable = null, never 0; unlimited risk = null + UNLIMITED_RISK,
//     never an arbitrary large number; NaN/Infinity never leak.
//   - Concentration is DESCRIPTIVE ONLY (never "good"/"bad", never bullish/
//     bearish, never a recommendation).
//   - Limits are MONITORING / CONTROL VISIBILITY only. This module NEVER
//     blocks execution — no market-hours gate, no order/exit changes.
//   - All functions are deterministic, pure, side-effect free,
//     dependency-light, user-data agnostic and free of broker API calls.
//
// The module CONSUMES Phase 6.2 analytical capital results and Phase 6.3
// capital-efficiency metrics — it never recomputes payoff / risk / premium /
// option-price formulas (§30/§38). Defined risk is the caller-passed
// theoretical max loss (or null), and mixed-expiry structures never receive a
// fabricated finite risk number (§28).
// ---------------------------------------------------------------------------

// ---- Status constants (§37) -------------------------------------------------
export const STATUS_AVAILABLE = "AVAILABLE";
export const STATUS_PARTIAL = "PARTIAL";
export const STATUS_UNAVAILABLE = "UNAVAILABLE";

// ---- Structured warnings ----------------------------------------------------
export const W_UNLIMITED_RISK = "UNLIMITED_RISK";
export const W_MIXED_EXPIRY = "MIXED_EXPIRY_APPROXIMATION";
export const W_INVALID_INPUT = "INVALID_INPUT";
export const W_PARTIAL_COVERAGE = "PARTIAL_COVERAGE";
export const W_BROKER_MARGIN_NOT_ADDITIVE = "BROKER_MARGIN_NOT_ADDITIVE";
export const W_ZERO_DENOMINATOR = "ZERO_DENOMINATOR";
export const W_INVALID_DENOMINATOR = "INVALID_DENOMINATOR";
export const W_NO_OPEN_STRATEGIES = "NO_OPEN_STRATEGIES";
export const W_MISSING_BROKER_DATA = "MISSING_BROKER_DATA";

// Capital bases (§6) — normalized from the Phase 6.2 analytical basis.
export const BASIS_PREMIUM = "PREMIUM";
export const BASIS_RISK_MODEL = "RISK_MODEL";
export const BASIS_MAX_LOSS = "MAX_LOSS";
export const BASIS_UNAVAILABLE = "UNAVAILABLE";

// Allocation ratio denominators (§11/§12) — the denominator is ALWAYS explicit.
export const DENOMINATOR_PAPER_STARTING_CAPITAL = "PAPER_STARTING_CAPITAL";
export const DENOMINATOR_PAPER_AVAILABLE_CASH = "PAPER_AVAILABLE_CASH";
export const DENOMINATOR_BROKER_AVAILABLE_FUNDS = "BROKER_AVAILABLE_FUNDS";
export const DENOMINATOR_BROKER_MARGIN_CAPACITY = "BROKER_MARGIN_CAPACITY";

export const DENOMINATOR_LABELS = {
  [DENOMINATOR_PAPER_STARTING_CAPITAL]: "Paper Starting Capital",
  [DENOMINATOR_PAPER_AVAILABLE_CASH]: "Paper Available Cash",
  [DENOMINATOR_BROKER_AVAILABLE_FUNDS]: "Broker Available Funds",
  [DENOMINATOR_BROKER_MARGIN_CAPACITY]: "Broker Margin Capacity",
};

// Configurable limit rules (§21/§23). All default to null = NOT CONFIGURED.
export const LIMIT_RULES = [
  "maxEstimatedCapitalAllocationPct",
  "maxDefinedRiskPct",
  "maxSingleStrategyAllocationPct",
  "maxSingleStrategyRiskPct",
  "maxUnderlyingConcentrationPct",
  "maxOpenStrategies",
  "allowUnlimitedRisk",
];

export const LIMIT_LABELS = {
  maxEstimatedCapitalAllocationPct: "Estimated Capital Allocation",
  maxDefinedRiskPct: "Defined Risk Allocation",
  maxSingleStrategyAllocationPct: "Single Strategy Capital Concentration",
  maxSingleStrategyRiskPct: "Single Strategy Risk Concentration",
  maxUnderlyingConcentrationPct: "Underlying Concentration",
  maxOpenStrategies: "Maximum Open Strategies",
  allowUnlimitedRisk: "Unlimited-Risk Strategy Presence",
};

// Framework constant: a configured threshold is flagged WARNING at >= 90% of
// the threshold, BREACHED at >= 100%. Documented and overrideable via
// calculateAllocationLimits({ warningBand }).
export const DEFAULT_WARNING_BAND = 0.9;

// ---- Numeric safety ---------------------------------------------------------

function isFiniteNumber(v) {
  return v != null && Number.isFinite(Number(v));
}

function num(v) {
  return isFiniteNumber(v) ? Number(v) : null;
}

function round2(v) {
  return v == null ? null : Math.round(v * 100) / 100;
}

// Part / whole as a percentage (2dp), null whenever either side is missing or
// the whole is not strictly positive. Never a fabricated 0.
function pctOf(part, whole) {
  const p = num(part);
  const w = num(whole);
  if (p === null || w === null || w <= 0) return null;
  return round2((p / w) * 100);
}

function normalizeBasis(basis) {
  if (basis === "premium") return BASIS_PREMIUM;
  if (basis === "risk_model") return BASIS_RISK_MODEL;
  if (basis === "max_loss") return BASIS_MAX_LOSS;
  return BASIS_UNAVAILABLE;
}

// Sum additive values with explicit coverage semantics (§37): unavailable
// members are never treated as 0 — a null / NaN member still counts as
// missing, so the aggregate either states PARTIAL coverage or returns
// unavailable when nothing is present.
function aggregateWithCoverage(values) {
  const list = (values ?? []).filter((v) => v !== undefined);
  const present = list.map(num).filter((v) => v !== null);
  const missing = list.length - present.length;
  if (present.length === 0) return { value: null, coverage: STATUS_UNAVAILABLE.toLowerCase() };
  return {
    value: round2(present.reduce((a, b) => a + b, 0)),
    coverage: missing > 0 ? "partial" : "available",
  };
}

// ---- §5/§6/§7/§8/§26/§28/§29 — Strategy-level allocation ---------------------

// One logical allocation unit per OPEN strategy execution (§27). Consumes:
//   - estimatedCapital  — the Phase 6.2 analyzeCapital result (never recomputed)
//   - maxLoss           — the authoritative theoretical payoff/risk result
//                         (calculateStrategy), ignored for mixed-expiry
//   - brokerMargin      — BROKER_REPORTED only, or null
//   - legs / positions  — CURRENT remaining quantities (§26: partial exits and
//                         reversals must reflect what is still open, never the
//                         original entry quantity)
export function calculateStrategyAllocation({
  executionId = null,
  strategyTag = "Custom",
  positions = [],
  legs = [],
  estimatedCapital = null,
  maxLoss = null,
  maxLossUnlimited = false,
  payoffMode = "same-expiry",
  brokerMargin = null,
  brokerMarginSource = null,
  premiumOutlay = null,
} = {}) {
  const posList = Array.isArray(positions) ? positions.filter((p) => p != null) : [];
  const legList = Array.isArray(legs) ? legs.filter((l) => l != null) : [];

  const warnings = [];

  // Premium outlay — an explicit value (e.g. from the capital API) wins;
  // otherwise derived from the CURRENT buy legs' premiums (no new formula,
  // same premium-outlay definition the engine uses).
  let outlay = num(premiumOutlay);
  if (outlay === null && legList.length > 0) {
    outlay = round2(
      legList.reduce((s, l) => {
        const q = num(l.qty);
        const p = num(l.price);
        const ls = num(l.lotSize) ?? 1;
        return s + (l.action === "buy" && q !== null && p !== null ? q * p * ls : 0);
      }, 0)
    );
  }

  // Estimated capital — Phase 6.2 analytical result consumed as-is.
  const cap = estimatedCapital && typeof estimatedCapital === "object" ? estimatedCapital : null;
  const capValue = num(cap?.value);
  const capBasis = normalizeBasis(cap?.basis);
  const capWarnings = Array.isArray(cap?.warnings) ? cap.warnings : [];
  if (capWarnings.includes(W_UNLIMITED_RISK)) warnings.push(W_UNLIMITED_RISK);
  if (capWarnings.includes(W_MIXED_EXPIRY)) warnings.push(W_MIXED_EXPIRY);

  // Defined risk (§8/§28/§29) — abs(maxLoss) from the authoritative engine,
  // ONLY for same-expiry structures with a finite loss. Mixed-expiry never
  // gets a fabricated finite number (the engine's chain-independent range is
  // not defensible across expiries); unlimited risk stays null + warning.
  let definedRisk = null;
  const mixedExpiry = payoffMode !== "same-expiry";
  if (maxLossUnlimited === true) {
    warnings.push(W_UNLIMITED_RISK);
  } else if (mixedExpiry) {
    warnings.push(W_MIXED_EXPIRY);
  } else if (isFiniteNumber(maxLoss)) {
    definedRisk = round2(Math.abs(Number(maxLoss)));
  }

  // Broker margin (§7) — BROKER_REPORTED only. A non-broker-reported value is
  // dropped (never estimated / paper cash / max loss).
  let broker = null;
  const brokerSource = brokerMarginSource ?? "BROKER_REPORTED";
  if (isFiniteNumber(brokerMargin)) {
    broker = brokerSource === "BROKER_REPORTED" ? round2(Number(brokerMargin)) : null;
  }

  const uniqueWarnings = [...new Set(warnings)];
  const hasCapital = capValue !== null;
  const hasRisk = definedRisk !== null;
  const allocationStatus =
    openPositionCount(posList) === 0 && legList.length === 0
      ? STATUS_UNAVAILABLE
      : !hasCapital || !hasRisk
        ? STATUS_PARTIAL
        : STATUS_AVAILABLE;

  return {
    executionId,
    strategyTag,
    openPositions: openPositionCount(posList),
    legs: legList, // current legs, passed through for exposure/concentration
    premiumOutlay: outlay,
    estimatedCapital: capValue,
    estimatedCapitalBasis: capBasis,
    brokerMargin: broker,
    brokerMarginSource: broker === null ? null : brokerSource,
    definedRisk,
    unlimitedRisk: maxLossUnlimited === true || capWarnings.includes(W_UNLIMITED_RISK),
    capitalBasis: capBasis,
    riskBasis: definedRisk === null ? BASIS_UNAVAILABLE : BASIS_MAX_LOSS,
    allocationStatus,
    warnings: uniqueWarnings,
  };
}

function openPositionCount(positions) {
  return positions.reduce((n, p) => n + (p && p.status !== "closed" ? 1 : 0), 0);
}

// ---- §9/§10/§25/§37 — Portfolio allocation ----------------------------------

// Descriptive portfolio aggregates. Only mathematically additive values are
// summed (premium outlay, estimated capital, defined risk); broker margin is
// the broker-reported ACCOUNT aggregate when available — per-strategy broker
// margins are never summed into an account figure (§10).
export function calculatePortfolioAllocation({
  strategies = [],
  paperStartingCapital = null,
  paperAvailableCash = null,
  brokerAvailableFunds = null,
  brokerMarginAggregate = null,
  brokerMarginSource = null,
} = {}) {
  const list = Array.isArray(strategies) ? strategies.filter((s) => s != null) : [];
  const warnings = [];

  const premiumOutlay = aggregateWithCoverage(list.map((s) => s.premiumOutlay));
  const estimatedCapital = aggregateWithCoverage(list.map((s) => s.estimatedCapital));
  const definedRisk = aggregateWithCoverage(list.map((s) => s.definedRisk));

  // Broker margin (§7/§10/§21-23): aggregate preferred; per-strategy rows are
  // informational only and are never summed (additivity is not guaranteed).
  let brokerMargin = null;
  let brokerMarginAgg = null;
  const src = brokerMarginSource ?? "BROKER_REPORTED";
  if (isFiniteNumber(brokerMarginAggregate) && src === "BROKER_REPORTED") {
    brokerMargin = round2(Number(brokerMarginAggregate));
    brokerMarginAgg = src;
  }
  const perStrategyBrokerPresent = list.some((s) => s.brokerMargin !== null);
  if (perStrategyBrokerPresent && brokerMargin === null) {
    warnings.push(W_BROKER_MARGIN_NOT_ADDITIVE);
  }
  if (perStrategyBrokerPresent && brokerMargin !== null) {
    warnings.push("BROKER_MARGIN_AGGREGATE_USED"); // descriptive: per-strategy rows are never summed
  }
  if (estimatedCapital.coverage === "partial") warnings.push(W_PARTIAL_COVERAGE);
  if (definedRisk.coverage === "partial") warnings.push(W_PARTIAL_COVERAGE);
  if (list.length === 0) warnings.push(W_NO_OPEN_STRATEGIES);

  const status =
    list.length === 0
      ? STATUS_UNAVAILABLE
      : estimatedCapital.coverage === "partial" || definedRisk.coverage === "partial"
        ? STATUS_PARTIAL
        : STATUS_AVAILABLE;

  return {
    strategies: list,
    openStrategyCount: list.length,
    openPositionCount: list.reduce((n, s) => n + (s.openPositions ?? 0), 0),
    totalPremiumOutlay: premiumOutlay.value,
    premiumOutlayCoverage: premiumOutlay.coverage,
    totalEstimatedCapital: estimatedCapital.value,
    estimatedCapitalCoverage: estimatedCapital.coverage,
    totalDefinedRisk: definedRisk.value,
    definedRiskCoverage: definedRisk.coverage,
    brokerMargin,
    brokerMarginSource: brokerMarginAgg,
    perStrategyBrokerPresent,
    paperStartingCapital: num(paperStartingCapital),
    paperAvailableCash: num(paperAvailableCash),
    brokerAvailableFunds: num(brokerAvailableFunds),
    status,
    warnings: [...new Set(warnings)],
  };
}

// ---- §11/§12 — Allocation ratio ---------------------------------------------

// Neutral metric: allocated capital / an EXPLICIT capital basis. The
// denominator is never auto-selected; the caller names it (the default Paper
// Trading view uses PAPER_STARTING_CAPITAL — paper values are never relabeled
// as broker funds, and broker values are never relabeled as paper capital).
export function calculateAllocatedCapitalRatio({
  allocatedCapital = null,
  denominator = null,
  denominatorSource = DENOMINATOR_PAPER_STARTING_CAPITAL,
} = {}) {
  const d = num(denominator);
  const warnings = [];
  if (d === null) warnings.push("MISSING_DENOMINATOR");
  else if (d <= 0) warnings.push(W_INVALID_DENOMINATOR);
  const value = pctOf(allocatedCapital, d);
  return {
    value,
    numerator: num(allocatedCapital),
    denominator: d,
    denominatorLabel: DENOMINATOR_LABELS[denominatorSource] ?? denominatorSource,
    denominatorSource,
    status: value == null ? "unavailable" : "available",
    warnings,
  };
}

// ---- §13/§14/§16/§17 — Concentration ----------------------------------------

// Generic descriptive concentration: each group's share of a chosen additive
// basis. groupBy "strategy" (execution identity) is the default; "symbol"
// (underlying) and "expiry" group by the strategy's first current leg (a
// mixed-expiry strategy is attributed to its first leg's expiry with a
// MIXED_EXPIRY warning — never a fake split across expiries).
// Never interpreted as good/bad; unavailable values are excluded (never 0).
export function calculateCapitalConcentration(strategies, { basis = "ESTIMATED_CAPITAL", groupBy = null } = {}) {
  const list = Array.isArray(strategies) ? strategies.filter((s) => s != null) : [];
  const valueOf = (s) => {
    if (basis === "PREMIUM_OUTLAY") return num(s.premiumOutlay);
    if (basis === "DEFINED_RISK") return num(s.definedRisk);
    return num(s.estimatedCapital);
  };
  const groupKeyOf = (s) => {
    if (groupBy === "symbol") return s.legs?.[0]?.symbol ?? "UNKNOWN";
    if (groupBy === "expiry") return s.legs?.[0]?.expiry ?? "UNKNOWN";
    return s.executionId ?? "standalone";
  };

  const groups = new Map();
  let mixedExpiryGrouped = false;
  for (const s of list) {
    // §28: a mixed-expiry structure preserves its MIXED_EXPIRY_APPROXIMATION
    // flag even when it contributes no value to this basis (e.g. its defined
    // risk is intentionally null across expiries).
    if (groupBy === "expiry" && (s.warnings ?? []).includes(W_MIXED_EXPIRY)) mixedExpiryGrouped = true;
    const v = valueOf(s);
    if (v === null) continue; // unavailable members never count as 0
    const key = String(groupKeyOf(s));
    const g = groups.get(key) ?? { key, value: 0, count: 0 };
    g.value += v;
    g.count += 1;
    groups.set(key, g);
  }

  const total = round2([...groups.values()].reduce((a, g) => a + g.value, 0));
  const items = [...groups.values()]
    .map((g) => ({
      key: g.key,
      count: g.count,
      value: round2(g.value),
      concentrationPct: pctOf(g.value, total),
    }))
    .sort((a, b) => (b.concentrationPct ?? -1) - (a.concentrationPct ?? -1));

  const excludedStrategies = list.filter((s) => valueOf(s) === null).length;
  const warnings = [];
  if (excludedStrategies > 0) warnings.push(W_PARTIAL_COVERAGE);
  if (mixedExpiryGrouped) warnings.push(W_MIXED_EXPIRY);

  const label =
    basis === "ESTIMATED_CAPITAL"
      ? "Estimated Capital Concentration"
      : basis === "PREMIUM_OUTLAY"
        ? "Premium Outlay Concentration"
        : "Defined Risk Concentration";

  return {
    basis,
    groupBy: groupBy ?? "strategy",
    label,
    total: items.length === 0 ? null : total,
    items,
    highest: items[0] ?? null,
    excludedStrategies,
    // §14: unlimited-risk strategies are excluded from the finite-risk
    // denominator and surfaced separately — never a fabricated percentage.
    unlimitedRiskStrategyCount: basis === "DEFINED_RISK" ? list.filter((s) => s.unlimitedRisk === true).length : 0,
    unlimitedRiskExposure: basis === "DEFINED_RISK" ? list.some((s) => s.unlimitedRisk === true) : false,
    coverage: list.length === 0 ? "unavailable" : excludedStrategies > 0 ? "partial" : "available",
    status: items.length === 0 ? STATUS_UNAVAILABLE : excludedStrategies > 0 ? STATUS_PARTIAL : STATUS_AVAILABLE,
    warnings,
  };
}

// ---- §18 — Position-side exposure (neutral measurement) ---------------------

// BUY/SELL and CALL/PUT contract exposure from the CURRENT legs. Measured in
// contracts (qty × lotSize). Purely descriptive — never labeled bullish/
// bearish, never a signal.
export function calculateRiskExposure({ strategies = [] } = {}) {
  const list = Array.isArray(strategies) ? strategies.filter((s) => s != null) : [];
  const buckets = { BUY_CALL: 0, BUY_PUT: 0, SELL_CALL: 0, SELL_PUT: 0 };
  let totalContracts = 0;
  for (const s of list) {
    for (const l of s.legs ?? []) {
      const q = num(l.qty);
      const ls = num(l.lotSize) ?? 1;
      if (q === null) continue;
      const contracts = q * ls;
      const side = l.action === "sell" ? "SELL" : "BUY";
      const type = l.type === "put" ? "PUT" : "CALL";
      buckets[`${side}_${type}`] = round2(buckets[`${side}_${type}`] + contracts);
      totalContracts += contracts;
    }
  }
  const buy = round2(buckets.BUY_CALL + buckets.BUY_PUT);
  const sell = round2(buckets.SELL_CALL + buckets.SELL_PUT);
  const call = round2(buckets.BUY_CALL + buckets.SELL_CALL);
  const put = round2(buckets.BUY_PUT + buckets.SELL_PUT);
  const unlimitedRiskStrategyCount = list.filter((s) => s.unlimitedRisk === true).length;
  return {
    units: "contracts",
    buyExposure: buy,
    sellExposure: sell,
    callExposure: call,
    putExposure: put,
    buyCall: buckets.BUY_CALL,
    buyPut: buckets.BUY_PUT,
    sellCall: buckets.SELL_CALL,
    sellPut: buckets.SELL_PUT,
    totalContracts: round2(totalContracts),
    buySharePct: pctOf(buy, totalContracts),
    sellSharePct: pctOf(sell, totalContracts),
    callSharePct: pctOf(call, totalContracts),
    putSharePct: pctOf(put, totalContracts),
    unlimitedRiskStrategyCount,
    unlimitedRiskExposure: unlimitedRiskStrategyCount > 0,
    status: totalContracts > 0 ? STATUS_AVAILABLE : STATUS_UNAVAILABLE,
    warnings: [],
  };
}

// ---- §21/§22/§23/§24 — Configurable limit framework -------------------------

function thresholdResult(rule, threshold, actual, { warningBand }) {
  if (threshold == null || threshold === "" || !isFiniteNumber(threshold)) {
    return {
      rule,
      configured: threshold != null && threshold !== "",
      threshold: num(threshold),
      actual: num(actual),
      status: "NOT_CONFIGURED",
      breached: false,
      warnings: [],
    };
  }
  const t = num(threshold);
  const a = num(actual);
  if (t <= 0) {
    return { rule, configured: true, threshold: t, actual: a, status: "UNAVAILABLE", breached: false, warnings: [W_INVALID_DENOMINATOR] };
  }
  if (a === null) {
    // §22: missing data must never auto-breach.
    return { rule, configured: true, threshold: t, actual: null, status: "UNAVAILABLE", breached: false, warnings: [] };
  }
  if (a >= t) return { rule, configured: true, threshold: t, actual: a, status: "BREACHED", breached: true, warnings: [] };
  if (a >= t * warningBand) return { rule, configured: true, threshold: t, actual: a, status: "WARNING", breached: false, warnings: [] };
  return { rule, configured: true, threshold: t, actual: a, status: "OK", breached: false, warnings: [] };
}

function flagResult(rule, configured, actual) {
  if (configured == null) {
    return { rule, configured: false, threshold: null, actual: num(actual), status: "NOT_CONFIGURED", breached: false, warnings: [] };
  }
  const a = num(actual);
  if (a === null) {
    return { rule, configured: true, threshold: configured, actual: null, status: "UNAVAILABLE", breached: false, warnings: [] };
  }
  const breached = configured === false && a > 0;
  const status = breached ? "BREACHED" : a > 0 ? "WARNING" : "OK";
  return { rule, configured: true, threshold: configured, actual: a, status, breached, warnings: [] };
}

export function calculateAllocationLimits({ limits = {}, actuals = {}, warningBand = DEFAULT_WARNING_BAND } = {}) {
  const rules = {};
  rules.maxEstimatedCapitalAllocationPct = thresholdResult("maxEstimatedCapitalAllocationPct", limits.maxEstimatedCapitalAllocationPct, actuals.estimatedCapitalAllocationPct, { warningBand });
  rules.maxDefinedRiskPct = thresholdResult("maxDefinedRiskPct", limits.maxDefinedRiskPct, actuals.definedRiskPct, { warningBand });
  rules.maxSingleStrategyAllocationPct = thresholdResult("maxSingleStrategyAllocationPct", limits.maxSingleStrategyAllocationPct, actuals.maxSingleStrategyAllocationPct, { warningBand });
  rules.maxSingleStrategyRiskPct = thresholdResult("maxSingleStrategyRiskPct", limits.maxSingleStrategyRiskPct, actuals.maxSingleStrategyRiskPct, { warningBand });
  rules.maxUnderlyingConcentrationPct = thresholdResult("maxUnderlyingConcentrationPct", limits.maxUnderlyingConcentrationPct, actuals.maxUnderlyingConcentrationPct, { warningBand });
  rules.maxOpenStrategies = thresholdResult("maxOpenStrategies", limits.maxOpenStrategies, actuals.openStrategies, { warningBand });
  rules.allowUnlimitedRisk = flagResult("allowUnlimitedRisk", limits.allowUnlimitedRisk, actuals.unlimitedRiskStrategyCount);

  const results = Object.values(rules);
  const breachedCount = results.filter((r) => r.breached === true).length;
  return {
    rules,
    breachedCount,
    status: breachedCount > 0 ? "BREACHED" : results.some((r) => r.status === "WARNING") ? "WARNING" : "OK",
    warnings: [],
  };
}

// ---- §32 — Portfolio risk controls (top-level orchestrator) -----------------

// One call builds the whole CAPITAL ALLOCATION & RISK view from raw strategy
// allocation inputs + paper/broker capital. MONITORING ONLY — execution is
// never touched here.
export function calculatePortfolioRiskControls({
  strategies = [],
  paperStartingCapital = null,
  paperAvailableCash = null,
  brokerAvailableFunds = null,
  brokerMarginAggregate = null,
  brokerMarginSource = null,
  limits = {},
  allocationDenominator = DENOMINATOR_PAPER_STARTING_CAPITAL,
} = {}) {
  const list = Array.isArray(strategies) ? strategies.filter((s) => s != null) : [];

  const allocation = calculatePortfolioAllocation({
    strategies: list,
    paperStartingCapital,
    paperAvailableCash,
    brokerAvailableFunds,
    brokerMarginAggregate,
    brokerMarginSource,
  });
  const byStrategy = calculateCapitalConcentration(list, { basis: "ESTIMATED_CAPITAL" });
  const byRisk = calculateCapitalConcentration(list, { basis: "DEFINED_RISK" });
  const byUnderlying = calculateCapitalConcentration(list, { basis: "ESTIMATED_CAPITAL", groupBy: "symbol" });
  const byExpiry = calculateCapitalConcentration(list, { basis: "ESTIMATED_CAPITAL", groupBy: "expiry" });
  const exposure = calculateRiskExposure({ strategies: list });

  const allocatedCapitalRatio = calculateAllocatedCapitalRatio({
    allocatedCapital: allocation.totalEstimatedCapital,
    denominator: allocationDenominator === DENOMINATOR_PAPER_AVAILABLE_CASH ? allocation.paperAvailableCash : allocation.paperStartingCapital,
    denominatorSource: allocationDenominator,
  });

  const actuals = {
    estimatedCapitalAllocationPct: allocatedCapitalRatio.value,
    definedRiskPct: pctOf(allocation.totalDefinedRisk, allocation.paperStartingCapital),
    maxSingleStrategyAllocationPct: byStrategy.highest?.concentrationPct ?? null,
    maxSingleStrategyRiskPct: byRisk.highest?.concentrationPct ?? null,
    maxUnderlyingConcentrationPct: byUnderlying.highest?.concentrationPct ?? null,
    openStrategies: allocation.openStrategyCount,
    unlimitedRiskStrategyCount: exposure.unlimitedRiskStrategyCount,
  };
  const limitsResult = calculateAllocationLimits({ limits, actuals });

  const warnings = [
    ...allocation.warnings,
    ...byStrategy.warnings,
    ...byRisk.warnings,
    ...byUnderlying.warnings,
    ...byExpiry.warnings,
  ];

  const status =
    list.length === 0
      ? STATUS_UNAVAILABLE
      : allocation.status === STATUS_PARTIAL || byStrategy.status === STATUS_PARTIAL || byRisk.status === STATUS_PARTIAL
        ? STATUS_PARTIAL
        : STATUS_AVAILABLE;

  return {
    status,
    allocation,
    allocatedCapitalRatio,
    concentration: {
      byStrategy,
      byRisk,
      byUnderlying,
      byExpiry,
    },
    exposure,
    limits: limitsResult,
    unlimitedRiskStrategyCount: exposure.unlimitedRiskStrategyCount,
    warnings: [...new Set(warnings)],
  };
}
