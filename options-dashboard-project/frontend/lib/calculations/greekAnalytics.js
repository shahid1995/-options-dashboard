// Greek Analytics domain (Phase 4.0).
//
// A single, reusable analytics layer that keeps the platform's TWO Greek
// sources separate and compares them only after normalizing to ONE canonical
// unit contract:
//
//   LIVE GREEKS  — broker/option-chain values (Upstox option_greeks passed
//                  through by the backend transform_chain).
//   MODEL GREEKS — the Phase 3 Black-Scholes model (bsGreeks in pricing.js),
//                  resolved per leg with its own expiry, IV and time.
//
// Neither source ever substitutes for the other. A missing live Greek stays
// null; a missing model Greek stays null; the difference is null whenever
// either side is null. The UI consumes ONLY the canonical values below, so it
// can never accidentally compare theta/year against theta/day or vega/1.00
// against vega/1%.
//
// ============================================================================
// CANONICAL UNIT CONTRACT (the only units the UI may display)
// ============================================================================
//   delta          exposure change per 1 underlying point (unitless)
//   gamma          exposure change in delta per 1 underlying point
//   thetaPerDay    ₹ exposure change per calendar day
//   vegaPerVolPoint  ₹ exposure change per 1 volatility point
//                  (1 vol point = 0.01 volatility = 1% IV)
//
// Every value is "exposure" = the strategy-level figure, i.e. the per-unit
// contract value scaled by  dir × qty × lotSize × multiplier  (BUY = +,
// SELL = −). Raw contract-level values are also exposed per leg as `unit`.
// ============================================================================

import { dirOf } from "../options";
import { calculateScenario } from "./scenario";

// ---- Documented source conventions ------------------------------------------

// LIVE (broker chain) convention — discovered from the existing code: the
// backend passes Upstox's `option_greeks` straight through (see
// backend/app/routers/chains.py transform_chain). Upstox's docs describe the
// fields only qualitatively ("rate of change of premium based on change in
// volatility", "impact on premium based on time left for expiry"); the Indian
// market standard these feeds carry is: delta & gamma per 1 underlying point,
// theta per calendar day, vega per 1 volatility point (= 1% IV change),
// iv in percent (18.24 = 18.24%). The factors below encode exactly that; if a
// feed is ever verified to differ, change the factor — never the UI.
export const LIVE_GREEK_CONVENTION = {
  delta: "per 1 underlying point (per unit)",
  gamma: "per 1 underlying point (per unit)",
  theta: "₹ per calendar day (per unit) — Indian-market standard",
  vega: "₹ per 1 volatility point = 1% IV (per unit) — Indian-market standard",
  // IV is NOT consumed by this module. Note for Phase 4.1 (IV analytics): the
  // broker feed represents iv in percent (e.g. 18.24 = 18.24%) while the
  // Phase 3 scenario/model engine consumes chain iv as a decimal fraction
  // (0.18 = 18%). Reconciling feed vs model IV units is deferred to that
  // phase — Phase 4.0 changes no IV handling.
};
export const LIVE_THETA_PER_DAY_FACTOR = 1; // chain theta is already per calendar day
export const LIVE_VEGA_PER_VOL_POINT_FACTOR = 1; // chain vega is already per 1 vol point

// MODEL (Phase 3 Black-Scholes) convention — bsGreeks in pricing.js:
// delta & gamma per 1 underlying point, theta per YEAR (annualized),
// vega per 1.00 volatility FRACTION. Converted below.
export const MODEL_GREEK_CONVENTION = {
  delta: "per 1 underlying point (per unit)",
  gamma: "per 1 underlying point (per unit)",
  theta: "₹ per YEAR (annualized, per unit)",
  vega: "₹ per 1.00 volatility fraction (per unit)",
};
export const MODEL_THETA_PER_DAY_FACTOR = 1 / 365; // annualized → per calendar day
export const MODEL_VEGA_PER_VOL_POINT_FACTOR = 0.01; // per 1.00 vol fraction → per 1 vol point

export const GREEK_KEYS = ["delta", "gamma", "thetaPerDay", "vegaPerVolPoint"];

export const CANONICAL_UNIT_CONTRACT = {
  delta: "exposure change per 1 underlying point (scaled by dir × qty × lot size × multiplier)",
  gamma: "exposure change in delta per 1 underlying point (scaled by dir × qty × lot size × multiplier)",
  thetaPerDay: "₹ exposure change per calendar day (scaled by dir × qty × lot size × multiplier)",
  vegaPerVolPoint: "₹ exposure change per 1 volatility point (1 vol point = 0.01 volatility; scaled by dir × qty × lot size × multiplier)",
};

// ---- Normalization helpers ---------------------------------------------------

// Convert RAW live chain Greeks (per unit) into canonical EXPOSURE values.
// `scale` = dir × qty × lotSize × multiplier. Missing values stay null —
// never zero, never replaced by the model.
export function canonicalizeLive(raw, scale) {
  if (!raw) return { delta: null, gamma: null, thetaPerDay: null, vegaPerVolPoint: null };
  const mult = Number.isFinite(Number(scale)) ? Number(scale) : 1;
  return {
    delta: raw.delta != null ? raw.delta * mult : null,
    gamma: raw.gamma != null ? raw.gamma * mult : null,
    thetaPerDay: raw.theta != null ? raw.theta * LIVE_THETA_PER_DAY_FACTOR * mult : null,
    vegaPerVolPoint: raw.vega != null ? raw.vega * LIVE_VEGA_PER_VOL_POINT_FACTOR * mult : null,
  };
}

// Convert exposure-scaled MODEL Greeks (from a scenario result leg: delta,
// gamma, theta, vega already scaled by dir × qty × lot × mult, in raw model
// units) into canonical EXPOSURE values. Missing values stay null.
export function canonicalizeModelScaled(scaled) {
  if (!scaled) return { delta: null, gamma: null, thetaPerDay: null, vegaPerVolPoint: null };
  return {
    delta: scaled.delta != null ? scaled.delta : null,
    gamma: scaled.gamma != null ? scaled.gamma : null,
    thetaPerDay: scaled.theta != null ? scaled.theta * MODEL_THETA_PER_DAY_FACTOR : null,
    vegaPerVolPoint: scaled.vega != null ? scaled.vega * MODEL_VEGA_PER_VOL_POINT_FACTOR : null,
  };
}

// ---- Aggregation with explicit ZERO vs UNAVAILABLE ---------------------------

// Sum a set of per-leg values, distinguishing a valid zero from "no data".
//   status: "available"   — every value present
//           "partial"     — some values present, some missing
//           "unavailable" — no value present
export function sumWithStatus(values) {
  const present = values.filter((v) => v != null && Number.isFinite(Number(v)));
  if (present.length === 0) return { total: null, status: "unavailable" };
  const total = present.reduce((a, b) => a + b, 0);
  return { total, status: present.length === values.length ? "available" : "partial" };
}

// ---- Per-leg analytics ------------------------------------------------------

// Build one canonical analytics row for a leg.
//
//   live  — RAW chain greeks { delta, gamma, theta, vega } (per unit), or null
//   model — exposure-scaled model greeks { delta, gamma, theta, vega } in raw
//           model units (theta per year, vega per 1.00), or null
//   scale — dir × qty × lotSize × multiplier (exposure multiplier)
//
// Returns:
//   {
//     legId, expiry, strike, type, action, qty,
//     unit:    { delta, gamma, thetaPerDay, vegaPerVolPoint },  // per-unit canonical
//     live:    { delta, gamma, thetaPerDay, vegaPerVolPoint },  // exposure canonical
//     model:   { ... },                                          // exposure canonical
//     difference: { ... },                                       // model − live (exposure)
//     liveAvailable, modelAvailable,                            // booleans
//   }
export function perLegGreekAnalytics(leg, live, model, scale) {
  const s = Number.isFinite(Number(scale)) ? Number(scale) : 1;
  const liveExposure = canonicalizeLive(live, s);
  const modelExposure = canonicalizeModelScaled(model);
  const unit = canonicalizeLive(live, 1);

  const difference = {};
  GREEK_KEYS.forEach((k) => {
    difference[k] =
      modelExposure[k] != null && liveExposure[k] != null ? modelExposure[k] - liveExposure[k] : null;
  });

  return {
    legId: leg.id,
    expiry: leg.expiry,
    strike: leg.strike,
    type: leg.type,
    action: leg.action,
    qty: leg.qty,
    unit,
    live: liveExposure,
    model: modelExposure,
    difference,
    liveAvailable: GREEK_KEYS.some((k) => liveExposure[k] != null),
    modelAvailable: GREEK_KEYS.some((k) => modelExposure[k] != null),
  };
}

// ---- Strategy totals ---------------------------------------------------------

// Sum canonical per-leg rows into { live, model, difference } strategy totals
// plus an availability status per Greek per source. A total is null when NO
// leg contributes a value (unavailable); when only some legs contribute it is
// the sum of the available legs and flagged "partial".
export function totalGreekSet(rows) {
  const pick = (source) => (k) => rows.map((r) => r[source][k]);
  const live = {};
  const model = {};
  const difference = {};
  const status = { live: {}, model: {}, difference: {} };

  GREEK_KEYS.forEach((k) => {
    const l = sumWithStatus(pick("live")(k));
    const m = sumWithStatus(pick("model")(k));
    live[k] = l.total;
    model[k] = m.total;
    status.live[k] = l.status;
    status.model[k] = m.status;
    // Difference only over legs that have BOTH sides (never a fabricated gap).
    const both = rows
      .map((r) => (r.live[k] != null && r.model[k] != null ? r.model[k] - r.live[k] : null))
      .filter((v) => v != null);
    if (both.length === 0) {
      difference[k] = null;
      status.difference[k] = "unavailable";
    } else {
      difference[k] = both.reduce((a, b) => a + b, 0);
      status.difference[k] = both.length === rows.length ? "available" : "partial";
    }
  });

  return { live, model, difference, status };
}

// ---- Contributions -----------------------------------------------------------

// Per-leg contribution to one canonical Greek, from a chosen source
// (default "live" — the market's current exposure). `pct` = value / signed
// total × 100, so the percentages of the contributing legs sum to 100
// (e.g. +35% / −20% / +85% — see the Phase 4.0 spec). Null values are skipped;
// a null total yields null pct for every leg.
export function greekContribution(rows, greek, source = "live") {
  const entries = rows.map((r) => {
    const value = r[source][greek];
    return { legId: r.legId, label: `${r.action.toUpperCase()} ${r.strike} ${r.type === "call" ? "CE" : "PE"}`, value, pct: null };
  });
  const present = entries.filter((e) => e.value != null);
  const total = present.reduce((a, b) => a + b.value, 0);
  if (present.length && total !== 0) {
    present.forEach((e) => {
      e.pct = (e.value / total) * 100;
    });
  }
  return { entries, total: present.length ? total : null, available: present.length > 0 };
}

// ---- Reuse with an existing scenario result ----------------------------------

// Derive the { live, model, difference, status } totals from an already-
// computed scenario result (see calculateScenario in scenario.js). This is how
// the Scenario Panel shows "Current Live Greeks vs Scenario Model Greeks"
// without ever re-running or duplicating the scenario calculation.
export function scenarioGreekComparison(scenarioResult) {
  const rows = (scenarioResult?.legs ?? []).map((entry) =>
    perLegGreekAnalytics(entry.leg, entry.liveGreeks, entry, entry.scale)
  );
  return totalGreekSet(rows);
}

// ---- Authoritative entry point -----------------------------------------------

// Greek analytics for a whole strategy: per-leg rows, strategy totals, status
// and contributions.
//
//   legs           — canonical strategy legs ({ id, type, action, strike,
//                    expiry, qty, price })
//   marketContext  — { spot, valuationDate, chainCache, lotSize, multiplier,
//                    interestRate, dividendYield } (same shape as the scenario
//                    engine)
//   options.scenario — hypothetical state for the MODEL greeks (default {} =
//                    the current market state: current spot, current per-leg
//                    IV, today's time to expiry). Live greeks always come from
//                    the chain regardless of the scenario — live data is never
//                    scenario-adjusted.
//
// Model greeks come from calculateScenario() (Phase 3) — the model is never
// duplicated here, and every model leg uses its own expiry / IV / time.
// Live greeks come from the same per-leg chain resolution inside the scenario
// engine (raw, never substituted).
export function calculateStrategyGreeks(legs, marketContext = {}, { scenario = {} } = {}) {
  const result = calculateScenario(legs, marketContext, scenario);

  const rows = result.legs.map((entry) =>
    perLegGreekAnalytics(entry.leg, entry.liveGreeks, entry, entry.scale)
  );

  const totals = totalGreekSet(rows);

  const contributions = {};
  GREEK_KEYS.forEach((k) => {
    contributions[k] = greekContribution(rows, k, "live");
  });

  return { rows, totals, contributions, warnings: result.warnings };
}
