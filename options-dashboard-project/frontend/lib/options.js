// Helpers for working with option chain rows and legs.

// The call or put side of a chain row.
export const legOf = (row, type) => (type === "call" ? row.call : row.put);

export const ltpOf = (row, type) => legOf(row, type).ltp;

// +1 for buy, -1 for sell.
export const dirOf = (action) => (action === "buy" ? 1 : -1);

export const sortedStrikes = (chainResponse) =>
  chainResponse.chain.map((r) => r.strike).sort((a, b) => a - b);

export function nearestStrikeIndex(strikes, spot) {
  if (spot == null || strikes.length === 0) return 0;
  let best = 0;
  let bestDiff = Infinity;
  strikes.forEach((s, i) => {
    const diff = Math.abs(s - spot);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = i;
    }
  });
  return best;
}

export function nearestStrike(strikes, spot) {
  return strikes[nearestStrikeIndex(strikes, spot)];
}

// ---- Payoff & risk helpers (shared with the strategy lab) ----

// Direction-adjusted quantity for one option side: + for net long, - for net
// short. Zero means every short is offset by a long (defined risk).
export function sideNetQty(legs, type) {
  return legs.filter((l) => l.type === type).reduce((sum, l) => sum + dirOf(l.action) * l.qty, 0);
}

// A position has theoretically unlimited loss ONLY when it is net short on a
// side — i.e. it contains a naked (uncovered) short call or short put.
// Long-only positions and fully-hedged spreads are never marked unlimited.
export function hasUnlimitedLoss(legs) {
  return sideNetQty(legs, "call") < 0 || sideNetQty(legs, "put") < 0;
}

// Mirror image on the profit side: a net long position has open-ended profit.
export function hasUnlimitedProfit(legs) {
  return sideNetQty(legs, "call") > 0 || sideNetQty(legs, "put") > 0;
}

// At-expiry P&L (rupees) for a set of legs at a given underlying price.
export function pnlAt(legs, price, { lotSize = 1, multiplier = 1 } = {}) {
  let pnl = 0;
  legs.forEach((l) => {
    const intrinsic = l.type === "call" ? Math.max(0, price - l.strike) : Math.max(0, l.strike - price);
    pnl += dirOf(l.action) * (intrinsic - l.price) * l.qty * lotSize * multiplier;
  });
  return pnl;
}

// Exact min/max at-expiry P&L across the given strikes (no rounding).
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
