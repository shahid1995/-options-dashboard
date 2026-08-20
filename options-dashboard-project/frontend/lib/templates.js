/**
 * Phase 6.7: Strategy Template utilities
 *
 * Converts between backend StrategyTemplate leg format and frontend
 * Strategy Builder leg format. Provides CRUD helpers and market-price
 * refresh logic.
 */

import { ltpOf } from "./options";

/**
 * Convert a backend template leg (from the API) to a frontend builder leg.
 *
 * Backend format:
 *   { id, position, action, option_type, strike, expiry, quantity, lot_size, price }
 *
 * Frontend builder leg format:
 *   { id, type, strike, action, qty, expiry, price }
 *
 * The frontend leg `id` is regenerated (unique per load).
 */
export function templateLegToFrontend(leg) {
  return {
    id: `tpl-${leg.template_id}-${leg.position}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    type: leg.option_type, // call | put
    strike: leg.strike,
    action: leg.action, // buy | sell
    qty: leg.quantity,
    expiry: leg.expiry,
    price: leg.price ?? 0,
    templateLegId: leg.id, // keep backend id for re-saving
    lotSize: leg.lot_size, // preserve lot_size from template
    // Phase 6.8D: dynamic formula fields
    strikeMode: leg.strike_mode || "fixed",
    strikeOffset: leg.strike_offset ?? null,
    targetDelta: leg.target_delta ?? null,
    expiryMode: leg.expiry_mode || "fixed",
    expiryDteMin: leg.expiry_dte_min ?? null,
    expiryDteMax: leg.expiry_dte_max ?? null,
    formulaVersion: leg.formula_version || 1,
  };
}

/**
 * Convert all backend template legs to frontend builder legs.
 */
export function templateToFrontendLegs(template) {
  return (template.legs ?? [])
    .sort((a, b) => a.position - b.position)
    .map(templateLegToFrontend);
}

/**
 * Refresh leg prices using live chain data (same approach as the existing
 * priceForLeg from strategy.js). When a live LTP exists, use it; otherwise
 * keep the saved price.
 */
export function refreshTemplateLegPrices(legs, chainByStrike, expiry) {
  return legs.map((l) => {
    const exp = l.expiry || expiry;
    const row = chainByStrike?.get?.(l.strike);
    if (!row) return l;
    const live = ltpOf(row, l.type);
    return live != null ? { ...l, price: live } : l;
  });
}

/**
 * Convert frontend builder legs back to the backend template creation payload.
 *
 * @param {string} name - Template name
 * @param {string} symbol - Underlying symbol (default: NIFTY)
 * @param {Array} legs - Frontend builder legs
 * @returns {Object} POST body for /paper/templates
 */
export function frontendLegsToTemplatePayload(name, symbol, legs) {
  return {
    name,
    symbol: symbol || "NIFTY",
    legs: legs.map((l, i) => {
      const leg = {
        action: l.action,
        option_type: l.type,
        strike: l.strike,
        expiry: l.expiry,
        quantity: l.qty,
        lot_size: l.lotSize || 50,
        price: l.price ?? 0,
        position: i,
      };
      // Phase 6.8D: include dynamic formula fields when non-default
      const sm = l.strikeMode || "fixed";
      const em = l.expiryMode || "fixed";
      if (sm !== "fixed" || em !== "fixed") {
        leg.strike_mode = sm;
        leg.expiry_mode = em;
        if (l.strikeOffset != null) leg.strike_offset = l.strikeOffset;
        if (l.targetDelta != null) leg.target_delta = l.targetDelta;
        if (l.expiryDteMin != null) leg.expiry_dte_min = l.expiryDteMin;
        if (l.expiryDteMax != null) leg.expiry_dte_max = l.expiryDteMax;
      }
      return leg;
    }),
  };
}

/**
 * Convert frontend builder legs to an update payload.
 * Only sends name, symbol, and legs (the backend does full leg replacement).
 */
export function frontendLegsToUpdatePayload(name, symbol, legs) {
  const payload = {};
  if (name !== undefined) payload.name = name;
  if (symbol !== undefined) payload.symbol = symbol;
  if (legs !== undefined) payload.legs = legs.map((l, i) => {
    const leg = {
      action: l.action,
      option_type: l.type,
      strike: l.strike,
      expiry: l.expiry,
      quantity: l.qty,
      lot_size: l.lotSize || 50,
      price: l.price ?? 0,
      position: i,
    };
    // Phase 6.8D: include dynamic formula fields when non-default
    const sm = l.strikeMode || "fixed";
    const em = l.expiryMode || "fixed";
    if (sm !== "fixed" || em !== "fixed") {
      leg.strike_mode = sm;
      leg.expiry_mode = em;
      if (l.strikeOffset != null) leg.strike_offset = l.strikeOffset;
      if (l.targetDelta != null) leg.target_delta = l.targetDelta;
      if (l.expiryDteMin != null) leg.expiry_dte_min = l.expiryDteMin;
      if (l.expiryDteMax != null) leg.expiry_dte_max = l.expiryDteMax;
    }
    return leg;
  });
  return payload;
}

/**
 * Build a human-readable leg summary string for display.
 * e.g. "BUY 24500 CE × 1 · SELL 25000 CE × 1"
 */
export function legSummary(legs) {
  if (!legs || legs.length === 0) return "Empty";
  return legs
    .map((l) => {
      const sm = l.strikeMode || "fixed";
      const strikeLabel = sm === "fixed" ? l.strike : sm.toUpperCase();
      return `${l.action.toUpperCase()} ${strikeLabel} ${l.type === "call" ? "CE" : "PE"} ×${l.qty}`;
    })
    .join(" · ");
}

/**
 * Format leg count label.
 */
export function legCountLabel(count) {
  return count === 1 ? "1 leg" : `${count} legs`;
}

// ---- Phase 6.8E: dynamic resolution helpers ----

/**
 * Compare two resolution results and detect changes in resolved
 * strike or expiry for each leg.
 *
 * Returns an array of { position, field, oldValue, newValue } entries
 * for every change detected, or [] if identical.
 */
export function detectResolutionChanges(prev, next) {
  if (!prev?.legs || !next?.legs) return [];
  const changes = [];
  for (let i = 0; i < Math.max(prev.legs.length, next.legs.length); i++) {
    const p = prev.legs[i];
    const n = next.legs[i];
    if (!p || !n) continue;
    if (p.resolved_strike !== n.resolved_strike) {
      changes.push({ position: i, field: "strike", oldValue: p.resolved_strike, newValue: n.resolved_strike });
    }
    if (p.resolved_expiry !== n.resolved_expiry) {
      changes.push({ position: i, field: "expiry", oldValue: p.resolved_expiry, newValue: n.resolved_expiry });
    }
  }
  return changes;
}

/**
 * Build a formula summary string from a resolution leg.
 * e.g. "ATM + 2 steps → 25200, current_week → 2026-08-27"
 */
export function resolvedLegSummary(leg) {
  if (!leg) return "";
  const parts = [];
  if (leg.strike_mode_used && leg.strike_mode_used !== "fixed") {
    parts.push(`${leg.strike_mode_used.toUpperCase()} → ${leg.resolved_strike}`);
  } else {
    parts.push(`${leg.resolved_strike}`);
  }
  if (leg.expiry_mode_used && leg.expiry_mode_used !== "fixed") {
    parts.push(`${leg.expiry_mode_used.replace(/_/g, " ")} → ${leg.resolved_expiry}`);
  } else {
    parts.push(leg.resolved_expiry);
  }
  return parts.join(", ");
}
