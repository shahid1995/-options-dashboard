// Payoff calculation domain.
//
// Everything here is a pure function of legs + underlying prices. It is the
// single source of truth for at-expiry payoff math used by the strategy lab,
// the payoff graph, the P&L table and the risk summary. No rounding happens
// here except where noted: callers round only when formatting for display.

import { dirOf } from "../options";

// At-expiry P&L (rupees) for a set of legs at a given underlying price.
// Quantity, lot size and multiplier all scale the rupee figure.
export function pnlAt(legs, price, { lotSize = 1, multiplier = 1 } = {}) {
  let pnl = 0;
  legs.forEach((l) => {
    const intrinsic = l.type === "call" ? Math.max(0, price - l.strike) : Math.max(0, l.strike - price);
    pnl += dirOf(l.action) * (intrinsic - l.price) * l.qty * lotSize * multiplier;
  });
  return pnl;
}

// Exact min/max at-expiry P&L across the given strikes (no rounding). Payoff
// is piecewise-linear with kinks at the strikes, so sampling at the strikes
// yields the true extrema for same-expiry positions (existing behavior).
export function payoffRange(legs, strikes, { lotSize = 1, multiplier = 1 } = {}) {
  if (!strikes || strikes.length === 0) return { maxProfit: 0, maxLoss: 0 };
  let maxProfit = -Infinity;
  let maxLoss = Infinity;
  strikes.forEach((s) => {
    const pnl = pnlAt(legs, s, { lotSize, multiplier });
    if (pnl > maxProfit) maxProfit = pnl;
    if (pnl < maxLoss) maxLoss = pnl;
  });
  return { maxProfit, maxLoss };
}

// Payoff curve: one exact P&L point per strike, in strike order.
export function payoffCurve(legs, strikes, { lotSize = 1, multiplier = 1 } = {}) {
  return strikes.map((strike) => ({ strike, pnl: pnlAt(legs, strike, { lotSize, multiplier }) }));
}

// Per-leg payoff at each strike, plus the combined position: used by the
// leg-by-leg "Strategy Chart". Each point is { strike, legPnl: [..], combined }.
export function perLegPayoff(legs, strikes, { lotSize = 1, multiplier = 1 } = {}) {
  return strikes.map((strike) => {
    const legPnl = legs.map((l) => {
      const intrinsic = l.type === "call" ? Math.max(0, strike - l.strike) : Math.max(0, l.strike - strike);
      return dirOf(l.action) * (intrinsic - l.price) * l.qty * lotSize * multiplier;
    });
    return { strike, legPnl, combined: legPnl.reduce((a, b) => a + b, 0) };
  });
}

// Underlying price(s) where the payoff crosses zero, found by linear
// interpolation between neighbouring curve points and rounded to the nearest
// rupee. Works on any curve (exact or sampled).
//
// A crossing that lands exactly on a sampled strike registers twice (once
// from each adjacent segment); consecutive duplicates are collapsed so each
// breakeven appears once.
export function breakevensFromCurve(curve) {
  const out = [];
  for (let i = 0; i < curve.length - 1; i++) {
    const a = curve[i];
    const b = curve[i + 1];
    if ((a.pnl >= 0 && b.pnl <= 0) || (a.pnl <= 0 && b.pnl >= 0)) {
      const denom = a.pnl - b.pnl;
      const t = denom === 0 ? 0 : a.pnl / denom;
      const breakeven = Math.round(a.strike + t * (b.strike - a.strike));
      if (out.length === 0 || out[out.length - 1] !== breakeven) out.push(breakeven);
    }
  }
  return out;
}
