// ---------------------------------------------------------------------------
// Phase 6.2 — Analytical Capital Model (frontend pure domain module).
//
// Answers: "what capital requirement can the platform ANALYTICALLY estimate
// when broker margin is unavailable or when the strategy is hypothetical?"
//
// This is an INDEPENDENT analytical model. It NEVER replaces, overrides or
// reinterprets broker-reported margin (Phase 6.1 stays authoritative for
// BROKER_REPORTED values), never calls the broker API, never touches the
// paper portfolio, and never fabricates a number for unlimited risk.
//
// The model consumes the existing authoritative calculation engines
// (calculateStrategy → payoff.js / risk.js) and the canonical option-price
// helper (pricing.js roundOptionPrice). No payoff, risk, premium or
// option-price formula is duplicated here.
//
// Result contract (§5):
//   {
//     value,                    // finite number in ₹ (whole strategy) or null
//     source,                   // "ESTIMATED" (analytical) — never BROKER_REPORTED
//     basis,                    // "premium" | "max_loss" | "risk_model" | "unavailable"
//     status,                   // "available" | "partial" | "unavailable"
//     warnings,                 // structured codes: INVALID_LEG, MISSING_PREMIUM,
//                               //   UNLIMITED_RISK, MIXED_EXPIRY_APPROXIMATION,
//                               //   UNSUPPORTED_STRUCTURE, INSUFFICIENT_RISK_MODEL
//     notes                     // preserved engine warnings (human strings)
//   }
//
// Rules: unavailable value = null (never 0); 0 is a VALID estimate; no NaN /
// Infinity ever; no fabricated values; ₹0.05 tick rounding is NEVER applied
// to capital totals (only to tradable option prices via roundOptionPrice,
// and only inside scenarioCapital where scenario prices cross the boundary).
// ---------------------------------------------------------------------------

import { calculateStrategy } from "./strategyCalculator";
import { roundOptionPrice } from "../pricing";

export const BASIS_PREMIUM = "premium";
export const BASIS_MAX_LOSS = "max_loss";
export const BASIS_RISK_MODEL = "risk_model";
export const BASIS_UNAVAILABLE = "unavailable";

export const WARNING_INVALID_LEG = "INVALID_LEG";
export const WARNING_MISSING_PREMIUM = "MISSING_PREMIUM";
export const WARNING_UNLIMITED_RISK = "UNLIMITED_RISK";
export const WARNING_MIXED_EXPIRY = "MIXED_EXPIRY_APPROXIMATION";
export const WARNING_UNSUPPORTED = "UNSUPPORTED_STRUCTURE";
export const WARNING_INSUFFICIENT_MODEL = "INSUFFICIENT_RISK_MODEL";

const SOURCE_ESTIMATED = "ESTIMATED";

function round2(value) {
  return Math.round(value * 100) / 100;
}

function isFiniteNumber(value) {
  return value != null && Number.isFinite(Number(value));
}

// ---- Input validation (§11) -------------------------------------------------
// Analytically invalid inputs are rejected safely with a structured warning —
// no exceptions leak to the UI for normal invalid user input.

function validateLegs(legs) {
  if (!Array.isArray(legs) || legs.length === 0) {
    return { ok: false, warnings: [WARNING_UNSUPPORTED] };
  }
  for (const l of legs) {
    if (!l || typeof l !== "object") return { ok: false, warnings: [WARNING_INVALID_LEG] };
    if (l.type !== "call" && l.type !== "put") return { ok: false, warnings: [WARNING_INVALID_LEG] };
    if (l.action !== "buy" && l.action !== "sell") return { ok: false, warnings: [WARNING_INVALID_LEG] };
    const qty = Number(l.qty);
    if (!Number.isFinite(qty) || qty <= 0 || !Number.isInteger(qty)) {
      // zero / negative / fractional quantity are analytically invalid
      return { ok: false, warnings: [WARNING_INVALID_LEG] };
    }
    const strike = Number(l.strike);
    if (!Number.isFinite(strike) || strike <= 0) return { ok: false, warnings: [WARNING_INVALID_LEG] };
    if (l.price == null || Number.isNaN(Number(l.price))) return { ok: false, warnings: [WARNING_MISSING_PREMIUM] };
    const price = Number(l.price);
    if (!Number.isFinite(price) || price < 0) return { ok: false, warnings: [WARNING_INVALID_LEG] };
    // Expiry is optional for the analytical model (manual legs may omit it);
    // when present it must be a non-empty string (a malformed expiry is an
    // invalid leg). Mixed-expiry detection itself stays with payoffMode.
    if (l.expiry !== undefined && l.expiry !== null) {
      if (typeof l.expiry !== "string" || l.expiry.trim() === "") {
        return { ok: false, warnings: [WARNING_INVALID_LEG] };
      }
    }
  }
  return { ok: true, warnings: [] };
}

function unavailable(warnings, notes) {
  return {
    value: null,
    source: SOURCE_ESTIMATED,
    basis: BASIS_UNAVAILABLE,
    status: "unavailable",
    warnings: [...(warnings ?? [])],
    notes: [...(notes ?? [])],
  };
}

function available(value, basis, warnings, notes) {
  return {
    value: round2(value),
    source: SOURCE_ESTIMATED,
    basis,
    status: "available",
    warnings: [...(warnings ?? [])],
    notes: [...(notes ?? [])],
  };
}

// ---- Primary analytical entry point (§4/§5) ---------------------------------

export function analyzeCapital(legs, { lotSize = 1, multiplier = 1 } = {}) {
  const validated = validateLegs(legs);
  if (!validated.ok) return unavailable(validated.warnings);

  const ls = Number(lotSize);
  const mult = Number(multiplier);
  if (!isFiniteNumber(ls) || ls <= 0 || !isFiniteNumber(mult) || mult <= 0) {
    // missing/zero/invalid lot size or multiplier → unavailable, never fabricated
    return unavailable([WARNING_INVALID_LEG]);
  }

  let calc;
  try {
    // Reuse the authoritative strategy engine — never re-derive payoff/risk
    // formulas here (§3/§19/§20).
    calc = calculateStrategy(legs, { lotSize: ls, multiplier: mult });
  } catch {
    return unavailable([WARNING_UNSUPPORTED]);
  }

  const notes = Array.isArray(calc.calculationWarnings) ? [...calc.calculationWarnings] : [];
  const mixedExpiry = calc.payoffMode !== "same-expiry";

  // Sanity: the engine must give us a finite net premium to reason about.
  if (!isFiniteNumber(calc.netTotal)) {
    return unavailable([WARNING_INSUFFICIENT_MODEL], notes);
  }

  // §9 — Unlimited-loss safety: never invent a finite analytical number when
  // the existing engine says risk is open-ended.
  if (calc.maxLossUnlimited === true) {
    const warnings = [WARNING_UNLIMITED_RISK];
    if (mixedExpiry) warnings.push(WARNING_MIXED_EXPIRY);
    return unavailable(warnings, notes);
  }

  // §10 — Mixed-expiry (calendar / diagonal / any mixed structure):
  //   · premium basis MAY remain available when the strategy is a defined
  //     net debit (premium flow is deterministic across expiries);
  //   · a risk basis is NEVER presented as an exact same-expiry result;
  //   · the engine's own mixed-expiry warnings are preserved.
  if (mixedExpiry) {
    if (calc.netTotal > 0) {
      return available(calc.netTotal, BASIS_PREMIUM, [], notes);
    }
    return unavailable([WARNING_MIXED_EXPIRY], notes);
  }

  // Same-expiry. The engine must confirm a finite max loss.
  if (!Number.isFinite(calc.maxLoss)) {
    return unavailable([WARNING_INSUFFICIENT_MODEL], notes);
  }

  // §8 — Structure classification from the legs (no recommendations):
  //   · single all-long leg (Long Call / Long Put) → PREMIUM basis (net debit)
  //   · everything else with a finite risk result → RISK_MODEL basis
  //     (abs(maxLoss) from the authoritative theoretical engine) — spreads,
  //     condors, butterflies, straddles/strangles, defined ratios, naked
  //     short put (which follows the existing Phase 2 S ≥ 0 domain result).
  const hasSellLeg = legs.some((l) => l.action === "sell");
  if (legs.length === 1 && !hasSellLeg) {
    return available(calc.netTotal, BASIS_PREMIUM, [], notes);
  }
  return available(Math.abs(calc.maxLoss), BASIS_RISK_MODEL, [], notes);
}

// ---- Scenario capital (§15) -------------------------------------------------
// Operates on scenario-modified strategy inputs and produces the same result
// contract. ANALYTICAL ONLY: never calls Upstox / the broker provider / the
// paper capital endpoint, never modifies portfolio state. Scenario leg prices
// are normalized to the canonical tradable tick (roundOptionPrice) so an
// off-tick scenario premium (125.23) is evaluated at the tradable price
// (125.25); capital TOTALS are never tick-rounded.

export function scenarioCapital(legs, { lotSize = 1, multiplier = 1 } = {}) {
  if (!Array.isArray(legs) || legs.length === 0) {
    return analyzeCapital(legs, { lotSize, multiplier });
  }
  const aligned = legs.map((l) => ({
    ...l,
    price: roundOptionPrice(l.price),
  }));
  return analyzeCapital(aligned, { lotSize, multiplier });
}

// ---- Future capital-efficiency inputs (§21) ---------------------------------
// PREPARES clean inputs for Phase 6.3. No Return on Capital / Return on
// Margin / Capital Efficiency metric is computed in this phase.
//   available = pnl and capital_used are both present (a future metric can
//   never divide by an unknown denominator); broker_margin and
//   estimated_capital are included as optional inputs (null when missing).

export function capitalEfficiencyInputs({ pnl, capitalUsed, brokerMargin, estimatedCapital } = {}) {
  const num = (v) => (isFiniteNumber(v) ? Number(v) : null);
  const p = num(pnl);
  const cu = num(capitalUsed);
  return {
    pnl: p,
    capital_used: cu,
    broker_margin: num(brokerMargin),
    estimated_capital: num(estimatedCapital),
    available: p !== null && cu !== null,
  };
}
