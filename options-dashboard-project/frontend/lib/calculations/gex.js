/**
 * GEX v1.0 — Gamma Exposure & Gamma Profile Foundation (Phase 7.1)
 *
 * Pure calculation engine for Gamma Exposure (GEX) derived from
 * normalized option-chain data. This is a MARKET STRUCTURE ANALYTICS
 * domain — it does NOT generate trading signals and does NOT claim
 * to reveal actual dealer positions.
 *
 * ============================================================================
 * OI UNIT VERIFICATION (Phase 7.1 correction)
 * ============================================================================
 *
 * Upstox's option-chain API returns `market_data.oi` as open interest in
 * NUMBER OF CONTRACTS — the same unit used by Upstox's order/margin APIs.
 *
 * Evidence:
 *   - mapper.py lots_to_contracts() docstring: "Upstox order/margin APIs
 *     expect contract units: 1 lot of NIFTY (lot_size 65) → 65 contracts."
 *   - transform_chain() passes market_data.oi through WITHOUT any lot-size
 *     conversion — it is already in contract units.
 *   - Indian market standard (NSE/BSE): OI is reported in contracts.
 *
 * Therefore the GEX formula does NOT multiply OI by lot_size.
 * Lot size is NOT part of the GEX calculation. It is documented as
 * contextual metadata only (e.g. for future Gamma Flip or unit-labeling).
 *
 * Mathematical contract (standard 1%-move dollar/rupee exposure):
 *
 *   Raw GEX_i = Gamma_i × OI_i × S² × 0.01
 *
 * where:
 *   Gamma_i = normalized live gamma per unit (change in delta per 1 underlying point)
 *   OI_i    = open interest in NUMBER OF CONTRACTS (from Upstox market_data.oi)
 *   S       = current underlying spot/index value
 *   0.01    = 1% move factor
 *
 * Sign convention (NAIVE_DEALER_CONVENTION):
 *   Call GEX = + Raw GEX
 *   Put GEX  = - Raw GEX
 *
 * This convention is a MODEL ASSUMPTION, not an observed dealer-position fact.
 * Open interest does not reveal the beneficial owner or whether a dealer is
 * long or short the option.
 *
 * Reference: GEX_V1_0_SPEC.md
 * ============================================================================
 */

// ---- Methodology metadata ---------------------------------------------------

export const GEX_METHOD_VERSION = "GEX_STANDARD_V1";

export const GEX_SIGN_CONVENTION = Object.freeze({
  positioning_model: "NAIVE_DEALER_CONVENTION",
  call_sign: +1,
  put_sign: -1,
  description:
    "Model assumption: calls contribute positive GEX, puts contribute negative GEX. " +
    "This does NOT reflect actual dealer inventory or positions.",
});

/**
 * Documented unit contract for GEX inputs.
 *
 * OI is in NUMBER OF CONTRACTS as returned by Upstox's market_data.oi.
 * Lot size is NOT used in the GEX formula — it is contextual metadata only.
 */
export const GEX_INPUT_UNITS = Object.freeze({
  gamma: "per 1 underlying point (per unit) — from Upstox option_greeks.gamma",
  oi: "NUMBER OF CONTRACTS — from Upstox market_data.oi (NOT lots)",
  spot: "underlying spot/index price",
  lot_size: "contracts per lot — contextual metadata only, NOT used in GEX formula",
});

// ---- Data quality statuses --------------------------------------------------

export const GEX_STATUS = Object.freeze({
  AVAILABLE: "available",
  PARTIAL: "partial",
  UNAVAILABLE: "unavailable",
  INVALID: "invalid",
});

// ---- Input validation -------------------------------------------------------

/**
 * Check whether a value is a valid positive finite number suitable for GEX.
 * null/undefined → false (missing, not zero)
 * 0 → false (invalid for GEX: OI=0 means no exposure)
 * negative → false
 * NaN/Infinity → false
 */
function isPositiveFinite(v) {
  if (v == null) return false;
  const n = Number(v);
  return Number.isFinite(n) && n > 0;
}

/**
 * Validate a single option row's inputs for GEX calculation.
 * Returns null if valid, or an error string if invalid.
 */
function validateOptionInput(gamma, oi, spot) {
  if (!isPositiveFinite(gamma)) return "INVALID_GAMMA";
  if (!isPositiveFinite(oi)) return "INVALID_OI";
  if (!isPositiveFinite(spot)) return "INVALID_SPOT";
  return null;
}

// ---- Core GEX calculation ---------------------------------------------------

/**
 * Calculate raw GEX for a single option contract.
 *
 * Formula: Gamma × OI × spot² × 0.01
 *
 * OI is in NUMBER OF CONTRACTS (not lots). Lot size is NOT part of the
 * formula because Upstox OI already represents contracts.
 *
 * @param {number} gamma  — per-unit gamma (change in delta per 1 underlying point)
 * @param {number} oi     — open interest in NUMBER OF CONTRACTS
 * @param {number} spot   — current underlying spot price
 * @returns {number} raw GEX value (always positive — sign applied separately)
 */
export function rawGex(gamma, oi, spot) {
  return gamma * oi * spot * spot * 0.01;
}

/**
 * Calculate the signed GEX contribution for a single option.
 *
 * Under NAIVE_DEALER_CONVENTION:
 *   Call GEX = + rawGex
 *   Put GEX  = - rawGex
 *
 * @param {string} optionType — "call" or "put"
 * @param {number} gamma
 * @param {number} oi — in NUMBER OF CONTRACTS
 * @param {number} spot
 * @returns {number} signed GEX
 */
export function signedGex(optionType, gamma, oi, spot) {
  const raw = rawGex(gamma, oi, spot);
  return optionType === "call" ? +raw : -raw;
}

// ---- Strike-level GEX -------------------------------------------------------

/**
 * Calculate GEX for a single strike across both call and put sides.
 *
 * @param {object} row — canonical chain row: { strike, call: { gamma, oi }, put: { gamma, oi } }
 * @param {number} spot
 * @returns {object} { strike, callGex, putGex, netGex, callOi, putOi, callGamma, putGamma, status }
 */
export function strikeGex(row, spot) {
  const strike = row.strike;
  const call = row.call || {};
  const put = row.put || {};

  const callGamma = call.gamma ?? null;
  const callOi = call.oi ?? null;
  const putGamma = put.gamma ?? null;
  const putOi = put.oi ?? null;

  // Validate each side independently
  const callError = validateOptionInput(callGamma, callOi, spot);
  const putError = validateOptionInput(putGamma, putOi, spot);

  let callGex = null;
  let putGex = null;
  let netGex = null;
  let status;

  if (callError === null && putError === null) {
    // Both sides available
    callGex = signedGex("call", callGamma, callOi, spot);
    putGex = signedGex("put", putGamma, putOi, spot);
    netGex = callGex + putGex;
    status = GEX_STATUS.AVAILABLE;
  } else if (callError === null) {
    // Only call side available
    callGex = signedGex("call", callGamma, callOi, spot);
    putGex = null;
    netGex = null;
    status = GEX_STATUS.PARTIAL;
  } else if (putError === null) {
    // Only put side available
    callGex = null;
    putGex = signedGex("put", putGamma, putOi, spot);
    netGex = null;
    status = GEX_STATUS.PARTIAL;
  } else {
    // Neither side available
    status = callError === "INVALID_GAMMA" || putError === "INVALID_GAMMA"
      ? GEX_STATUS.INVALID
      : GEX_STATUS.UNAVAILABLE;
  }

  return {
    strike,
    callGex,
    putGex,
    netGex,
    callOi,
    putOi,
    callGamma,
    putGamma,
    status,
  };
}

// ---- Expiry-level GEX -------------------------------------------------------

/**
 * Calculate GEX for a single expiry across all strikes.
 *
 * @param {Array} rows — array of canonical chain rows for this expiry
 * @param {number} spot
 * @returns {object} { expiry, callGex, putGex, netGex, availabilityStatus, validStrikeCount, totalStrikeCount }
 */
export function expiryGex(rows, spot) {
  if (!rows || rows.length === 0) {
    return {
      expiry: null,
      callGex: null,
      putGex: null,
      netGex: null,
      availabilityStatus: GEX_STATUS.UNAVAILABLE,
      validStrikeCount: 0,
      totalStrikeCount: 0,
    };
  }

  const strikeResults = rows.map((row) => strikeGex(row, spot));

  let callTotal = 0;
  let putTotal = 0;
  let hasCall = false;
  let hasPut = false;
  let availableCount = 0;
  let partialCount = 0;
  let invalidCount = 0;

  for (const sr of strikeResults) {
    if (sr.callGex != null) {
      callTotal += sr.callGex;
      hasCall = true;
    }
    if (sr.putGex != null) {
      putTotal += sr.putGex;
      hasPut = true;
    }
    if (sr.status === GEX_STATUS.AVAILABLE) availableCount++;
    else if (sr.status === GEX_STATUS.PARTIAL) partialCount++;
    else if (sr.status === GEX_STATUS.INVALID) invalidCount++;
  }

  // Determine expiry-level status
  let availabilityStatus;
  if (availableCount === strikeResults.length && availableCount > 0) {
    availabilityStatus = GEX_STATUS.AVAILABLE;
  } else if (availableCount + partialCount > 0) {
    availabilityStatus = GEX_STATUS.PARTIAL;
  } else if (invalidCount > 0) {
    availabilityStatus = GEX_STATUS.INVALID;
  } else {
    availabilityStatus = GEX_STATUS.UNAVAILABLE;
  }

  // Net GEX only when both sides have contributions
  const netGex = hasCall && hasPut ? callTotal + putTotal : null;

  return {
    expiry: rows[0]?.expiry ?? rows[0]?.expiry_date ?? null,
    callGex: hasCall ? callTotal : null,
    putGex: hasPut ? putTotal : null,
    netGex,
    availabilityStatus,
    validStrikeCount: availableCount + partialCount,
    totalStrikeCount: strikeResults.length,
    strikes: strikeResults,
  };
}

// ---- Chain-level GEX --------------------------------------------------------

/**
 * Calculate GEX for an entire option chain (one or more expiries).
 *
 * @param {Array} chainRows — array of canonical chain rows: [{ strike, expiry, call: {...}, put: {...} }]
 * @param {object} options
 * @param {number} options.spot — underlying spot price
 * @param {string} [options.symbol] — underlying symbol (for metadata only)
 * @param {string[]} [options.scopeExpiries] — specific expiries to include (null = all)
 * @param {number} [options.lotSize] — contextual lot-size metadata (NOT used in calculation)
 * @returns {object} { underlying, spot, scope, methodology, callGex, putGex, netGex, availabilityStatus, validOptionCount, totalOptionCount, byExpiry, byStrike }
 */
export function chainGex(chainRows, options = {}) {
  const { spot, symbol, scopeExpiries, lotSize } = options;

  // Validate chain-level inputs
  if (!spot || !isPositiveFinite(spot)) {
    return unavailableResult("INVALID_SPOT", chainRows, options);
  }
  if (!chainRows || chainRows.length === 0) {
    return unavailableResult("NO_CHAIN_DATA", [], options);
  }

  // Group by expiry
  const expiryMap = new Map();
  for (const row of chainRows) {
    const expiry = row.expiry ?? row.expiry_date;
    if (!expiryMap.has(expiry)) expiryMap.set(expiry, []);
    expiryMap.get(expiry).push(row);
  }

  // Filter by scope if specified
  let expiryEntries = Array.from(expiryMap.entries());
  if (scopeExpiries && scopeExpiries.length > 0) {
    const scopeSet = new Set(scopeExpiries);
    expiryEntries = expiryEntries.filter(([exp]) => scopeSet.has(exp));
  }

  // Calculate per-expiry GEX
  const expiryResults = expiryEntries.map(([exp, rows]) => {
    const result = expiryGex(rows, spot);
    result.expiry = exp;
    return result;
  });

  // Calculate per-strike GEX (across all expiries, netting same strike)
  const strikeMap = new Map();
  for (const er of expiryResults) {
    for (const sr of er.strikes) {
      const key = sr.strike;
      if (!strikeMap.has(key)) {
        strikeMap.set(key, {
          strike: sr.strike,
          callGex: 0,
          putGex: 0,
          netGex: 0,
          callOi: 0,
          putOi: 0,
          hasAnyCall: false,
          hasAnyPut: false,
        });
      }
      const agg = strikeMap.get(key);
      if (sr.callGex != null) {
        agg.callGex += sr.callGex;
        agg.hasAnyCall = true;
      }
      if (sr.putGex != null) {
        agg.putGex += sr.putGex;
        agg.hasAnyPut = true;
      }
      agg.callOi += sr.callOi ?? 0;
      agg.putOi += sr.putOi ?? 0;
    }
  }

  const byStrike = Array.from(strikeMap.values())
    .map((s) => ({
      strike: s.strike,
      callGex: s.hasAnyCall ? s.callGex : null,
      putGex: s.hasAnyPut ? s.putGex : null,
      netGex: s.hasAnyCall && s.hasAnyPut ? s.callGex + s.putGex : null,
      callOi: s.callOi || null,
      putOi: s.putOi || null,
    }))
    .sort((a, b) => a.strike - b.strike);

  // Aggregate chain totals
  let callTotal = 0;
  let putTotal = 0;
  let hasCall = false;
  let hasPut = false;
  let validCount = 0;
  let totalCount = 0;

  for (const er of expiryResults) {
    if (er.callGex != null) {
      callTotal += er.callGex;
      hasCall = true;
    }
    if (er.putGex != null) {
      putTotal += er.putGex;
      hasPut = true;
    }
    validCount += er.validStrikeCount;
    totalCount += er.totalStrikeCount;
  }

  // Chain-level status
  const statuses = expiryResults.map((e) => e.availabilityStatus);
  let availabilityStatus;
  if (statuses.every((s) => s === GEX_STATUS.AVAILABLE)) {
    availabilityStatus = GEX_STATUS.AVAILABLE;
  } else if (statuses.some((s) => s === GEX_STATUS.AVAILABLE || s === GEX_STATUS.PARTIAL)) {
    availabilityStatus = GEX_STATUS.PARTIAL;
  } else if (statuses.some((s) => s === GEX_STATUS.INVALID)) {
    availabilityStatus = GEX_STATUS.INVALID;
  } else {
    availabilityStatus = GEX_STATUS.UNAVAILABLE;
  }

  return {
    underlying: symbol ?? null,
    spot,
    scope: scopeExpiries
      ? `selected(${scopeExpiries.join(", ")})`
      : "all",
    methodology: GEX_METHOD_VERSION,
    signConvention: GEX_SIGN_CONVENTION,
    inputUnits: GEX_INPUT_UNITS,
    callGex: hasCall ? callTotal : null,
    putGex: hasPut ? putTotal : null,
    netGex: hasCall && hasPut ? callTotal + putTotal : null,
    availabilityStatus,
    validOptionCount: validCount,
    totalOptionCount: totalCount,
    lotSize: lotSize ?? null,
    byExpiry: expiryResults.map(({ strikes, ...rest }) => rest),
    byStrike,
  };
}

// ---- Utility helpers --------------------------------------------------------

function unavailableResult(reason, chainRows, options) {
  return {
    underlying: options.symbol ?? null,
    spot: options.spot ?? null,
    scope: options.scopeExpiries
      ? `selected(${options.scopeExpiries.join(", ")})`
      : "all",
    methodology: GEX_METHOD_VERSION,
    signConvention: GEX_SIGN_CONVENTION,
    inputUnits: GEX_INPUT_UNITS,
    callGex: null,
    putGex: null,
    netGex: null,
    availabilityStatus: GEX_STATUS.UNAVAILABLE,
    reason,
    validOptionCount: 0,
    totalOptionCount: chainRows?.length ?? 0,
    lotSize: options.lotSize ?? null,
    byExpiry: [],
    byStrike: [],
  };
}

/**
 * Format a GEX value into a human-readable string with appropriate scale.
 *
 * @param {number|null} value — raw GEX number
 * @returns {string} formatted string like "₹4,850" or "₹4.85 Cr" or "—"
 */
export function formatGex(value) {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  const sign = value >= 0 ? "+" : "−";
  if (abs >= 1e7) {
    return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
  }
  if (abs >= 1e5) {
    return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
  }
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
