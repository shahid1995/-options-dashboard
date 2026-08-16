// Central calculation API for a strategy.
//
// One authoritative entry point: `calculateStrategy(legs, context)` returns
// the full risk/reward profile (net debit/credit, max profit/loss with
// unbounded-risk classification, breakevens, payoff curve, reward/risk and
// ROI). The UI consumes this everywhere instead of re-deriving payoff math.
//
// `context`:
//   strikes    - underlying prices (chain strikes) to sample the payoff at
//   lotSize    - contract multiplier per lot
//   multiplier - additional position multiplier (default 1)

import { payoffRange, payoffCurve, perLegPayoff, breakevensFromCurve } from "./payoff";
import { hasUnlimitedLoss, hasUnlimitedProfit, netDebitCredit, roiPct, rewardRisk, premiumOutlay } from "./risk";

export function calculateStrategy(legs, { strikes = [], lotSize = 1, multiplier = 1 } = {}) {
  const hasLegs = Array.isArray(legs) && legs.length > 0;
  const { maxProfit, maxLoss } = payoffRange(legs, strikes, { lotSize, multiplier });
  const { netPerLot, netTotal } = netDebitCredit(legs, { lotSize, multiplier });
  const curve = payoffCurve(legs, strikes, { lotSize, multiplier });

  return {
    // Net premium: positive = debit paid, negative = credit received.
    netPerLot,
    netTotal,
    netDebit: netTotal > 0 ? netTotal : 0,
    netCredit: netTotal < 0 ? -netTotal : 0,

    // Cash required to establish the position: total premium paid on long
    // legs (margin for short legs is not modeled).
    premiumOutlay: premiumOutlay(legs, { lotSize, multiplier }),

    // Exact rupee extrema across the sampled strikes (not rounded).
    maxProfit,
    maxLoss,

    // Structural unbounded-risk/profit classification. "Unlimited" is only
    // ever true for genuinely naked net-short / net-long sides.
    maxProfitUnlimited: hasUnlimitedProfit(legs),
    maxLossUnlimited: hasUnlimitedLoss(legs),

    // Underlying prices where P&L crosses zero (rounded to the rupee).
    breakevens: hasLegs ? breakevensFromCurve(curve) : [],

    // Exact curves (strike → P&L). `perLegCurve` also carries per-leg P&L.
    payoffCurve: curve,
    perLegCurve: perLegPayoff(legs, strikes, { lotSize, multiplier }),

    // Return metrics (null when undefined for the position).
    rewardRisk: rewardRisk(maxProfit, maxLoss),
    roi: roiPct(maxProfit, netTotal),
  };
}
