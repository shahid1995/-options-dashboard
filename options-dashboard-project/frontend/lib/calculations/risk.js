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

// ROI on the net premium outlay. Undefined (null) when there is no outlay.
export function roiPct(maxProfit, netTotal) {
  return netTotal !== 0 ? (maxProfit / Math.abs(netTotal)) * 100 : null;
}

// Max profit expressed as a multiple of the max loss. Undefined when the
// position cannot lose (maxLoss >= 0).
export function rewardRisk(maxProfit, maxLoss) {
  return maxLoss < 0 ? maxProfit / Math.abs(maxLoss) : null;
}
