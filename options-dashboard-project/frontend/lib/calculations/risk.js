// Risk calculation domain: net debit/credit, unlimited-profit/loss
// classification, reward/risk and ROI. All pure functions of legs.

import { dirOf } from "../options";

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

// Net premium paid (positive) or received (negative), per lot and in total
// (per lot × lot size × multiplier). Sign convention: debit > 0, credit < 0.
export function netDebitCredit(legs, { lotSize = 1, multiplier = 1 } = {}) {
  const perLot = legs.reduce((sum, l) => sum + dirOf(l.action) * l.price * l.qty, 0);
  return {
    perLot,
    total: perLot * lotSize * multiplier,
    netPerLot: perLot,
    netTotal: perLot * lotSize * multiplier,
  };
}

// Total premium paid on long (buy) legs: the cash required to establish the
// position (margin for short legs is not modeled in the simulator, so this is
// the honest "capital / premium requirement" figure for debit strategies and
// the visible outlay for credit strategies).
export function premiumOutlay(legs, { lotSize = 1, multiplier = 1 } = {}) {
  return legs.reduce((sum, l) => (l.action === "buy" ? sum + l.price * l.qty * lotSize * multiplier : sum), 0);
}

// Premium ROI: max profit as a percentage of the premium OUTLAY (net debit).
// Undefined (null) when the profit side is structurally unlimited (a finite %
// over a finite sampled max profit would be misleading), or when there is no
// premium outlay at all (credit / zero-flow strategies — dividing by zero
// would fabricate a ratio). Callers surface the classification via
// `roiUnlimited` rather than embedding "Unlimited" in the math.
export function roiPct(maxProfit, netTotal, { maxProfitUnlimited = false } = {}) {
  if (maxProfitUnlimited) return null;
  if (netTotal <= 0) return null;
  return (maxProfit / netTotal) * 100;
}

// Max profit expressed as a multiple of the max loss. Undefined (null) when
// the position cannot lose (maxLoss >= 0) or when either side is structurally
// unlimited — a finite number there would misrepresent an open-ended position
// (∞ profit or 0/∞ loss). The caller decides the label via the unlimited flags.
export function rewardRisk(maxProfit, maxLoss, { maxProfitUnlimited = false, maxLossUnlimited = false } = {}) {
  if (maxProfitUnlimited || maxLossUnlimited) return null;
  return maxLoss < 0 ? maxProfit / Math.abs(maxLoss) : null;
}
