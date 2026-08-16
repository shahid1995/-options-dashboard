// Payoff calculation domain.
//
// Everything here is a pure function of legs + underlying prices. It is the
// single source of truth for at-expiry payoff math used by the strategy lab,
// the payoff graph, the P&L table and the risk summary. No rounding happens
// here except where noted: callers round only when formatting for display.
//
// Two layers coexist:
//
//  1. Sampled helpers (`payoffRange`, `payoffCurve`, `perLegPayoff`,
//     `breakevensFromCurve`) — the display layer. They evaluate P&L at a
//     supplied price list (the visible chain / a chart grid) and are used for
//     visualization, OI overlays and the P&L table.
//
//  2. The theoretical same-expiry engine (`payoffMode`,
//     `theoreticalBreakpoints`, `theoreticalPayoffAnalysis`,
//     `theoreticalBreakevens`) — the risk layer. For strategies whose legs
//     share one expiry, the payoff is piecewise-linear with kinks exactly at
//     the strategy's own strikes, so max profit/loss and breakevens are
//     derived from the legs and the underlying's mathematical price domain
//     (S >= 0), never from the visible chain range.
//
// The visible option chain is a market-data source — it must never define the
// theoretical risk boundary.

import { dirOf } from "../options";

// ---- Sampled (display) helpers ------------------------------------------

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

// Exact min/max at-expiry P&L across the given prices (no rounding). This is
// a sampling helper for the display layer — theoretical risk must use the
// same-expiry engine instead (see `theoreticalPayoffAnalysis`).
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

// Payoff curve: one exact P&L point per price, in order (display grid).
export function payoffCurve(legs, strikes, { lotSize = 1, multiplier = 1 } = {}) {
  return strikes.map((strike) => ({ strike, pnl: pnlAt(legs, strike, { lotSize, multiplier }) }));
}

// Per-leg payoff at each price, plus the combined position: used by the
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

// Breakevens from an arbitrary sampled curve, found by linear interpolation
// between neighbouring points and rounded to the nearest rupee. Works on any
// curve (exact or sampled). A crossing that lands exactly on a sampled point
// registers twice (once from each adjacent segment); consecutive duplicates
// are collapsed so each breakeven appears once. This is the display-layer
// helper — the theoretical engine's `theoreticalBreakevens` is exact and
// chain-independent.
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

// ---- Theoretical same-expiry engine (chain-independent) -----------------

// "same-expiry" when every leg shares one expiry; "multi-expiry" otherwise.
// Mixed-expiry positions cannot be valued exactly with intrinsic payoff alone,
// so the theoretical engine is only exact for same-expiry strategies.
export function payoffMode(legs) {
  if (!Array.isArray(legs) || legs.length === 0) return "same-expiry";
  const expiries = new Set();
  legs.forEach((l) => {
    if (l?.expiry) expiries.add(l.expiry);
  });
  return expiries.size > 1 ? "multi-expiry" : "same-expiry";
}

// The unique strikes used by the strategy legs — the kinks of the payoff.
export function theoreticalBreakpoints(legs) {
  const out = new Set();
  (legs || []).forEach((l) => {
    const s = Number(l?.strike);
    if (Number.isFinite(s)) out.add(s);
  });
  return [...out].sort((a, b) => a - b);
}

// Payoff slope on the flat side of every leg:
//   "left"  — 0 <= S < minStrike (calls flat at 0, puts linear)
//   "right" — S > maxStrike    (puts flat at 0, calls linear)
// Scaled by dir × qty × lotSize × multiplier.
function tailSlope(legs, side, { lotSize, multiplier }) {
  let slope = 0;
  (legs || []).forEach((l) => {
    if (!Number.isFinite(Number(l.strike))) return;
    const scale = dirOf(l.action) * (l.qty || 0) * lotSize * multiplier;
    if (l.type === "call" && side === "right") slope += scale;
    else if (l.type === "put" && side === "left") slope -= scale;
  });
  return slope;
}

// Full theoretical analysis for a same-expiry strategy. Evaluates the payoff
// exactly at S = 0 and at every strategy strike, plus the analytic tail
// slopes that decide unbounded profit/loss. Returns:
//
//   breakpoints        — the payoff kinks (strategy strikes, ascending)
//   minPrice           — 0 (the underlying cannot be negative)
//   maxPrice           — null (the domain is unbounded above)
//   atZero             — exact P&L at S = 0
//   atStrikes          — [{ price, pnl }] at each breakpoint
//   leftSlope          — slope on [0, minStrike); always a bounded segment
//   rightSlope         — slope on (maxStrike, +inf); decides unboundedness
//   rightUnboundedUp   — rightSlope > 0 → open-ended profit
//   rightUnboundedDown — rightSlope < 0 → open-ended loss
//   maxFinite/minFinite — extrema over {0} ∪ breakpoints; equal to the true
//                         max profit / max loss whenever the corresponding
//                         tail is not unbounded
export function theoreticalPayoffAnalysis(legs, { lotSize = 1, multiplier = 1 } = {}) {
  const breakpoints = theoreticalBreakpoints(legs);
  const atZero = pnlAt(legs, 0, { lotSize, multiplier });
  const atStrikes = breakpoints.map((price) => ({ price, pnl: pnlAt(legs, price, { lotSize, multiplier }) }));
  const leftSlope = tailSlope(legs, "left", { lotSize, multiplier });
  const rightSlope = tailSlope(legs, "right", { lotSize, multiplier });
  const pnls = [atZero, ...atStrikes.map((p) => p.pnl)];
  return {
    breakpoints,
    minPrice: 0,
    maxPrice: null,
    atZero,
    atStrikes,
    leftSlope,
    rightSlope,
    rightUnboundedUp: rightSlope > 0,
    rightUnboundedDown: rightSlope < 0,
    maxFinite: Math.max(...pnls),
    minFinite: Math.min(...pnls),
  };
}

// Exact breakevens from the piecewise-linear payoff: every segment between
// adjacent kinks (including the [0, minStrike] segment), solved linearly where
// it crosses zero, plus the upper tail (maxStrike, +inf) when it crosses.
// Flat zero segments are skipped (every point there is a breakeven, so
// reporting the endpoints would be noise). Values are exact (not rounded);
// formatting is a display concern.
export function theoreticalBreakevens(analysis) {
  const out = [];
  const pts = [{ price: analysis.minPrice, pnl: analysis.atZero }, ...analysis.atStrikes];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (a.pnl === 0 && b.pnl === 0) continue; // flat zero segment
    if ((a.pnl >= 0 && b.pnl <= 0) || (a.pnl <= 0 && b.pnl >= 0)) {
      const denom = a.pnl - b.pnl;
      const t = denom === 0 ? 0 : a.pnl / denom;
      const be = a.price + t * (b.price - a.price);
      if (out.length === 0 || Math.abs(out[out.length - 1] - be) > 1e-9) out.push(be);
    }
  }
  if (analysis.rightSlope !== 0 && analysis.atStrikes.length > 0) {
    const k = analysis.atStrikes[analysis.atStrikes.length - 1];
    const be = k.price - k.pnl / analysis.rightSlope;
    if (be > k.price + 1e-9) out.push(be);
  }
  return out;
}

// Display-only price grid for charts. Includes the strategy's strikes, the
// visible chain strikes, spot, and padded tails — never below 0. This is a
// visualization helper; it must never feed theoretical risk calculations.
export function payoffGrid({ strikes = [], breakpoints = [], spot = null, padding = 0.2 } = {}) {
  const anchors = new Set();
  [...strikes, ...breakpoints].forEach((s) => {
    const n = Number(s);
    if (Number.isFinite(n)) anchors.add(n);
  });
  if (spot != null) {
    const n = Number(spot);
    if (Number.isFinite(n)) anchors.add(n);
  }
  const sorted = [...anchors].sort((a, b) => a - b);
  if (sorted.length === 0) return [];
  let step = null;
  for (let i = 1; i < sorted.length; i++) {
    const gap = sorted[i] - sorted[i - 1];
    if (gap > 0 && (step === null || gap < step)) step = gap;
  }
  if (step === null) step = Math.max(1, Math.round(sorted[0] * 0.01));
  const span = sorted[sorted.length - 1] - sorted[0];
  const pad = Math.max(span * padding, step);
  const from = Math.max(0, Math.floor((sorted[0] - pad) / step) * step);
  const to = Math.ceil((sorted[sorted.length - 1] + pad) / step) * step;
  const grid = [];
  for (let s = from; s <= to + step / 2; s += step) grid.push(Math.round(s * 1e6) / 1e6);
  sorted.forEach((a) => {
    if (!grid.some((g) => Math.abs(g - a) < 1e-9)) grid.push(a);
  });
  return grid.sort((a, b) => a - b);
}
