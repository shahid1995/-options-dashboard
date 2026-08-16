// Scenario & Time Analysis domain (Phase 3).
//
// Answers "what happens if spot / IV / time / rate / dividend change?" for a
// whole strategy, using the Black-Scholes-style model in ./pricing.js.
//
// Key separation — these concepts are NEVER merged:
//   - Phase 2 expiry payoff  = intrinsic value at expiration (risk engine,
//     authoritative for max profit / max loss / breakevens).
//   - Live LTP               = broker/chain mark (the current P&L basis).
//   - Model value            = pricing-model value under scenario inputs.
//   - Scenario P&L           = model value relative to entry or current mark.
//
// marketContext — the current market state (separate from user strategy state):
//   {
//     spot,           // underlying spot (> 0)
//     valuationDate,  // ISO date (YYYY-MM-DD) of "now"
//     interestRate,   // decimal (0.06 = 6%), configurable default 0
//     dividendYield,  // decimal, configurable default 0
//     chainCache,     // { [expiry]: chain response } — per-expiry market data
//     lotSize,        // contract multiplier per lot
//     multiplier,     // additional position multiplier (default 1)
//   }
//
// scenario — the hypothetical state (relative inputs are the default UI):
//   {
//     spot,           // absolute scenario spot (> 0), overrides relative forms
//     spotPct,        // relative move as a decimal (0.02 = +2%)
//     spotPoints,     // relative move in index points
//     iv,             // absolute IV level for EVERY leg (decimal, 0.2 = 20%)
//     ivShift,        // volatility-POINT shift (decimal: 0.02 = +2 vol points)
//     timeShiftDays,  // whole days forward from valuationDate (0 = today)
//     interestRate,   // rate override (decimal)
//     dividendYield,  // dividend override (decimal)
//   }
//
// Every leg is priced with ITS OWN expiry (own time to expiry) and ITS OWN
// current IV (from its own expiry's chain row). The primary expiry is never
// used as a substitute for a far-expiry leg. Nothing is invented: a leg with
// no IV and no absolute `iv` override is marked unavailable with a structured
// MISSING_IV warning, and totals over available legs are flagged `partial`.

import { dirOf } from "../options";
import { bsValue, bsGreeks, timeToExpiry, addDays, MIN_VOLATILITY } from "./pricing";

export const SCENARIO_DEFAULT_RATE = 0;
export const SCENARIO_DEFAULT_DIVIDEND = 0;

// ---- Warnings ---------------------------------------------------------------

// Build a structured warning object. Codes:
//   MISSING_IV               — no IV for a leg and no absolute `iv` override
//   MISSING_CHAIN_DATA       — the leg's expiry chain / strike row is absent
//   INVALID_SPOT             — resolved scenario spot is not a positive number
//   INVALID_VOLATILITY       — negative scenario IV was clamped to the floor
//   INVALID_TIME             — valuation date could not be resolved
//   MODEL_NOT_AVAILABLE      — a leg (or the whole strategy) could not be priced
//   MULTI_EXPIRY_APPROXIMATION — mixed-expiry position: modelled leg-by-leg,
//                                expiry payoff behaviour is not exact
export function scenarioWarning(code, message, legId = null) {
  const w = { code, message };
  if (legId != null) w.legId = legId;
  return w;
}

// ---- Context / leg resolution ----------------------------------------------

// Resolve the current market data for every leg against ITS OWN expiry chain.
// Returns { legData, warnings } where each entry is:
//   { leg, currentLtp, currentIv, liveGreeks, baseT }
// `baseT` is the year-fraction time to expiry from the current valuation date.
// `liveGreeks` is the RAW broker/chain Greek set { delta, gamma, theta, vega }
// at per-unit contract level (see lib/calculations/greekAnalytics.js for the
// documented unit conventions) — kept raw here so the analytics layer owns all
// unit normalization; it is never substituted for the model Greeks below.
export function resolveScenarioLegs(legs, marketContext = {}) {
  const chainCache = marketContext.chainCache ?? {};
  const valuationDate = marketContext.valuationDate ?? new Date().toISOString().slice(0, 10);
  const warnings = [];
  const legData = (legs ?? []).map((leg) => {
    const chain = chainCache?.[leg.expiry];
    const row = chain?.chain?.find((r) => r.strike === leg.strike);
    const side = row ? (leg.type === "call" ? row.call : row.put) : null;
    const currentIv = side?.iv != null ? Number(side.iv) : null;
    const currentLtp = side?.ltp != null ? Number(side.ltp) : null;
    const baseT = timeToExpiry(valuationDate, leg.expiry);
    const liveGreeks = side
      ? {
          delta: side.delta != null ? Number(side.delta) : null,
          gamma: side.gamma != null ? Number(side.gamma) : null,
          theta: side.theta != null ? Number(side.theta) : null,
          vega: side.vega != null ? Number(side.vega) : null,
        }
      : null;

    if (!row) {
      warnings.push(
        scenarioWarning("MISSING_CHAIN_DATA", `Chain data for ${leg.type.toUpperCase()} ${leg.strike} ${leg.expiry} is not loaded.`, leg.id)
      );
    }
    if (currentIv == null) {
      warnings.push(
        scenarioWarning(
          "MISSING_IV",
          `IV is unavailable for ${leg.action.toUpperCase()} ${leg.type.toUpperCase()} ${leg.strike} ${leg.expiry}.`,
          leg.id
        )
      );
    }
    return { leg, currentIv, currentLtp, liveGreeks, baseT };
  });
  return { legData, warnings };
}

// ---- Scenario parameter resolution ------------------------------------------

// The scenario spot: absolute `spot` wins, then relative `spotPct`, then
// `spotPoints`, then the current market spot. Returns null (with warning) when
// the result is not a positive finite number — negative underlyings are never
// priced.
export function resolveScenarioSpot(baseSpot, scenario = {}) {
  let spot;
  if (scenario.spot != null) spot = Number(scenario.spot);
  else if (scenario.spotPct != null) spot = Number(baseSpot) * (1 + Number(scenario.spotPct));
  else if (scenario.spotPoints != null) spot = Number(baseSpot) + Number(scenario.spotPoints);
  else spot = Number(baseSpot);
  return Number.isFinite(spot) && spot > 0 ? spot : null;
}

// Scenario IV for one leg: absolute `iv` override wins; otherwise the leg's own
// current IV plus the volatility-POINT shift. Clamped to a positive floor;
// a clamp emits an INVALID_VOLATILITY warning (no silent substitution).
export function resolveScenarioIv(legDataEntry, scenario = {}, warnings = []) {
  if (scenario.iv != null) {
    const iv = Number(scenario.iv);
    if (!Number.isFinite(iv) || iv < 0) {
      warnings.push(scenarioWarning("INVALID_VOLATILITY", `Scenario IV ${scenario.iv} is invalid; clamped to the safe minimum.`, legDataEntry.leg.id));
      return MIN_VOLATILITY;
    }
    return Math.max(iv, MIN_VOLATILITY);
  }
  if (legDataEntry.currentIv == null) return null; // MISSING_IV already reported
  const shifted = legDataEntry.currentIv + Number(scenario.ivShift ?? 0);
  if (shifted < MIN_VOLATILITY) {
    warnings.push(scenarioWarning("INVALID_VOLATILITY", `Scenario IV ${shifted.toFixed(4)} for leg would be negative; clamped to the safe minimum.`, legDataEntry.leg.id));
    return MIN_VOLATILITY;
  }
  return shifted;
}

// ---- Single-scenario evaluation ---------------------------------------------

// Evaluate one scenario against pre-resolved leg data. This is the lightweight
// per-cell workhorse used by both `calculateScenario` and
// `calculateScenarioMatrix` (the matrix resolves leg data once and reuses it).
export function evaluateScenario(legData, marketContext, scenario = {}, baseWarnings = []) {
  const warnings = [...baseWarnings];
  const baseSpot = Number(marketContext.spot);
  const spot = resolveScenarioSpot(baseSpot, scenario);
  if (spot == null) {
    warnings.push(scenarioWarning("INVALID_SPOT", `Scenario spot could not be resolved to a positive number (base ${baseSpot}).`));
  }

  const rate = Number(scenario.interestRate ?? marketContext.interestRate ?? SCENARIO_DEFAULT_RATE);
  const dividendYield = Number(scenario.dividendYield ?? marketContext.dividendYield ?? SCENARIO_DEFAULT_DIVIDEND);
  const shiftDays = Number(scenario.timeShiftDays ?? 0);
  const valuationDate = addDays(marketContext.valuationDate ?? new Date().toISOString().slice(0, 10), shiftDays);
  const lotSize = Number(marketContext.lotSize ?? 1);
  const multiplier = Number(marketContext.multiplier ?? 1);

  const legs = legData.map((entry) => {
    const leg = entry.leg;
    const scenarioIv = spot == null ? null : resolveScenarioIv(entry, scenario, warnings);
    const scenarioT = entry.baseT == null ? null : timeToExpiry(valuationDate, leg.expiry);
    const scale = dirOf(leg.action) * leg.qty * lotSize * multiplier;
    const unitValue =
      spot != null && scenarioIv != null && scenarioT != null
        ? bsValue(leg.type, spot, leg.strike, scenarioT, scenarioIv, rate, dividendYield)
        : null;
    const greeks =
      spot != null && scenarioIv != null && scenarioT != null
        ? bsGreeks(leg.type, spot, leg.strike, scenarioT, scenarioIv, rate, dividendYield)
        : { delta: null, gamma: null, theta: null, vega: null };

    return {
      leg,
      // LIVE market data (from the leg's own expiry chain) — never overwritten
      // by the model value below. `liveGreeks` stays RAW (per-unit contract
      // level); `scale` is the exposure multiplier dir × qty × lot × mult so
      // the Greek analytics layer can normalize both sources to the canonical
      // exposure units from exactly the same inputs.
      currentLtp: entry.currentLtp,
      currentIv: entry.currentIv,
      liveGreeks: entry.liveGreeks,
      scale,
      // MODELLED scenario state.
      scenarioIv,
      scenarioT,
      scenarioValue: unitValue,
      modelVsMarket: unitValue != null && entry.currentLtp != null ? unitValue - entry.currentLtp : null,
      // Scaled rupee figures (direction-aware).
      pnlVsEntry:
        unitValue != null ? dirOf(leg.action) * (unitValue - leg.price) * leg.qty * lotSize * multiplier : null,
      pnlChangeVsCurrent:
        unitValue != null && entry.currentLtp != null
          ? dirOf(leg.action) * (unitValue - entry.currentLtp) * leg.qty * lotSize * multiplier
          : null,
      // Model Greeks, exposure-scaled (dir × qty × lot × mult) — raw model
      // units (theta per year, vega per 1.00 vol fraction); the analytics
      // layer converts these to the canonical theta/day and vega/vol-point.
      delta: greeks.delta != null ? greeks.delta * scale : null,
      gamma: greeks.gamma != null ? greeks.gamma * scale : null,
      theta: greeks.theta != null ? greeks.theta * scale : null,
      vega: greeks.vega != null ? greeks.vega * scale : null,
      available: unitValue != null,
    };
  });

  const priced = legs.filter((l) => l.available);
  const partial = priced.length !== legs.length;
  // Current mark and change-vs-current are only reported when every leg has a
  // live LTP — a partial rupee figure would look authoritative but isn't.
  const fullyMarked = legs.every((l) => l.currentLtp != null);

  // Strategy totals are null (unpriced) when the scenario spot itself is
  // invalid — a partial sum of zero would silently look like "no P&L" instead
  // of "cannot be priced". When the spot is valid but only some legs price
  // (missing IV etc.), the totals cover the priced legs and `partial` flags it.
  const strategyValue =
    spot != null
      ? priced.reduce((sum, l) => sum + dirOf(l.leg.action) * l.scenarioValue * l.leg.qty * lotSize * multiplier, 0)
      : null;
  const currentValue = fullyMarked
    ? legs.reduce((sum, l) => sum + dirOf(l.leg.action) * l.currentLtp * l.leg.qty * lotSize * multiplier, 0)
    : null;
  const scenarioPnl = spot != null ? priced.reduce((sum, l) => sum + l.pnlVsEntry, 0) : null;
  const scenarioChange = fullyMarked ? legs.reduce((sum, l) => sum + l.pnlChangeVsCurrent, 0) : null;
  const totals = legs.reduce(
    (acc, l) => ({
      delta: acc.delta + (l.delta ?? 0),
      gamma: acc.gamma + (l.gamma ?? 0),
      theta: acc.theta + (l.theta ?? 0),
      vega: acc.vega + (l.vega ?? 0),
    }),
    { delta: 0, gamma: 0, theta: 0, vega: 0 }
  );

  if (partial) {
    warnings.push(
      scenarioWarning(
        "MODEL_NOT_AVAILABLE",
        `${legs.length - priced.length} leg(s) could not be priced; strategy totals cover the remaining ${priced.length} leg(s) only.`
      )
    );
  }
  if (new Set(legs.map((l) => l.leg.expiry)).size > 1) {
    warnings.push(
      scenarioWarning(
        "MULTI_EXPIRY_APPROXIMATION",
        "Mixed-expiry strategy: each leg is modelled with its own expiry, IV and time to expiry, but expiry payoff behaviour is not exact for this position."
      )
    );
  }

  return {
    scenario,
    spot,
    valuationDate,
    rate,
    dividendYield,
    strategyValue,
    currentValue,
    scenarioPnl,
    scenarioChange,
    partial,
    legs,
    totals,
    warnings,
  };
}

// ---- Authoritative entry point ---------------------------------------------

// One scenario for the whole strategy. `legs` are canonical strategy legs
// ({ id, type, action, strike, expiry, qty, price }); `marketContext` holds
// the current market state; `scenario` holds the hypothetical inputs.
export function calculateScenario(legs, marketContext = {}, scenario = {}) {
  const { legData, warnings } = resolveScenarioLegs(legs, marketContext);
  return evaluateScenario(legData, marketContext, scenario, warnings);
}

// ---- Scenario grids ---------------------------------------------------------

// Default axes for each matrix mode (all relative to the current state).
const GRID_DEFAULTS = {
  spotIv: {
    rows: [-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03], // spot pct
    columns: [-0.04, -0.02, 0, 0.02, 0.04], // iv vol points
  },
  spotTime: {
    rows: [-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03], // spot pct
    columns: [0, 1, 3, 5, 7], // time days forward
  },
  ivTime: {
    rows: [-0.05, -0.02, 0, 0.02, 0.05], // iv vol points
    columns: [0, 1, 3, 5, 7], // time days forward
  },
};

// Build the scenario parameters for one matrix cell from the axis labels.
function scenarioForCell(axis, rowValue, columnValue) {
  if (axis === "spotIv") return { spotPct: rowValue, ivShift: columnValue };
  if (axis === "spotTime") return { spotPct: rowValue, timeShiftDays: columnValue };
  return { ivShift: rowValue, timeShiftDays: columnValue };
}

// A pure scenario matrix: rows × columns of strategy P&L under combined
// scenario inputs. `axis` is one of "spotIv" | "spotTime" | "ivTime".
// Every cell is { scenarioPnl, strategyValue, scenarioChange } (nulls when the
// cell's strategy could not be fully priced). Returns the labels plus the
// cell grid, computed in ONE pass over the resolved leg data so the matrix
// never triggers per-cell React state churn.
export function calculateScenarioMatrix(legs, marketContext = {}, { axis = "spotIv", rows, columns } = {}) {
  const { legData, warnings } = resolveScenarioLegs(legs, marketContext);
  const rowLabels = rows ?? GRID_DEFAULTS[axis]?.rows ?? GRID_DEFAULTS.spotIv.rows;
  const colLabels = columns ?? GRID_DEFAULTS[axis]?.columns ?? GRID_DEFAULTS.spotIv.columns;

  const cells = rowLabels.map((r) =>
    colLabels.map((c) => {
      const res = evaluateScenario(legData, marketContext, scenarioForCell(axis, r, c), []);
      return {
        scenarioPnl: res.partial ? null : res.scenarioPnl,
        strategyValue: res.partial ? null : res.strategyValue,
        scenarioChange: res.partial ? null : res.scenarioChange,
      };
    })
  );

  return { axis, rows: rowLabels, columns: colLabels, cells, warnings };
}
