// Central calculation API for a strategy.
//
// One authoritative entry point: `calculateStrategy(legs, context)` returns
// the full risk/reward profile (net debit/credit, max profit/loss with
// unbounded-risk classification, breakevens, payoff curve, reward/risk and
// ROI). The UI consumes this everywhere instead of re-deriving payoff math.
//
// `context`:
//   strikes    - display prices (visible chain) for the display payoff curve
//   lotSize    - contract multiplier per lot
//   multiplier - additional position multiplier (default 1)
//
// Theoretical risk (max profit/loss, breakevens) for same-expiry strategies
// comes from the chain-independent engine in payoff.js: the strategy's own
// strikes + the S >= 0 price domain + analytic tail slopes. The `strikes`
// argument only shapes the display `payoffCurve` — it never defines the
// theoretical risk boundary. Multi-expiry positions fall back to a sampled
// approximation and report an explicit `calculationWarnings` entry.

import {
  payoffMode,
  theoreticalPayoffAnalysis,
  theoreticalBreakevens,
  payoffRange,
  payoffCurve,
  perLegPayoff,
  breakevensFromCurve,
} from "./payoff";
import { hasUnlimitedLoss, hasUnlimitedProfit, netDebitCredit, roiPct, rewardRisk, premiumOutlay } from "./risk";

export function calculateStrategy(legs, { strikes = [], lotSize = 1, multiplier = 1 } = {}) {
  const hasLegs = Array.isArray(legs) && legs.length > 0;
  const mode = payoffMode(legs);
  const analysis = mode === "same-expiry" && hasLegs ? theoreticalPayoffAnalysis(legs, { lotSize, multiplier }) : null;

  const { netPerLot, netTotal } = netDebitCredit(legs, { lotSize, multiplier });
  const curve = payoffCurve(legs, strikes, { lotSize, multiplier });

  let maxProfit;
  let maxLoss;
  let maxProfitUnlimited;
  let maxLossUnlimited;
  let breakevens;
  let calculationWarnings;
  if (analysis) {
    maxProfitUnlimited = analysis.rightSlope > 0;
    maxLossUnlimited = analysis.rightSlope < 0;
    // When a tail is unbounded the matching flag is true and the UI shows
    // "Unlimited"; the finite value is the exact reference over {0} ∪ strikes.
    maxProfit = analysis.maxFinite;
    maxLoss = analysis.minFinite;
    breakevens = theoreticalBreakevens(analysis);
    calculationWarnings = [];
  } else {
    // Multi-expiry (or no legs): intrinsic same-expiry payoff is not exact for
    // mixed expiries — fall back to the sampled display curve and say so.
    const { maxProfit: mp, maxLoss: ml } = payoffRange(legs, strikes, { lotSize, multiplier });
    maxProfit = mp;
    maxLoss = ml;
    maxProfitUnlimited = hasUnlimitedProfit(legs);
    maxLossUnlimited = hasUnlimitedLoss(legs);
    breakevens = hasLegs ? breakevensFromCurve(curve) : [];
    calculationWarnings = hasLegs
      ? ["Exact same-expiry payoff analysis is unavailable for this mixed-expiry strategy. Max profit, max loss and breakevens are sampled approximations from the visible chain."]
      : [];
  }

  return {
    // Net premium: positive = debit paid, negative = credit received.
    netPerLot,
    netTotal,
    netDebit: netTotal > 0 ? netTotal : 0,
    netCredit: netTotal < 0 ? -netTotal : 0,

    // Cash required to establish the position: total premium paid on long
    // legs. Kept separate from a future margin/capital requirement (not
    // modeled in Phase 2) — do not call premium outlay "capital required".
    premiumOutlay: premiumOutlay(legs, { lotSize, multiplier }),

    // Exact rupee extrema. For same-expiry strategies these come from the
    // theoretical engine (strategy strikes + S = 0, tail-aware), NOT from the
    // visible chain. When an unbounded tail exists the matching Unlimited flag
    // is true and the finite value is only a reference.
    maxProfit,
    maxLoss,

    // Structural unbounded classification. For same-expiry strategies it is
    // derived from the payoff tail slopes; for multi-expiry it falls back to
    // the net call side. Never inferred from the existence of a short leg.
    maxProfitUnlimited,
    maxLossUnlimited,

    // Underlying prices where P&L crosses zero (exact and chain-independent
    // for same-expiry; sampled for multi-expiry).
    breakevens,

    // Calculation provenance: which engine produced the risk numbers.
    payoffMode: mode,
    // Payoff kinks (strategy strikes). Empty for multi-expiry — a single
    // piecewise curve does not exist across different expiries.
    theoreticalBreakpoints: analysis ? analysis.breakpoints : [],
    // Price domain of the theoretical analysis. S >= 0; null = unbounded above.
    theoreticalMinPrice: analysis ? analysis.minPrice : null,
    theoreticalMaxPrice: analysis ? analysis.maxPrice : null,
    // Structured notes for consumers when the result is not exact.
    calculationWarnings,

    // Exact display curves (price → P&L), sampled at the supplied display
    // grid. These are for charts/tables and never feed theoretical risk.
    payoffCurve: curve,
    perLegCurve: perLegPayoff(legs, strikes, { lotSize, multiplier }),

    // Return metrics. A finite ratio is reported only when both sides are
    // defined and the metric is meaningful; the structural unlimited
    // classification always takes precedence over finite values, so a Long
    // Call never shows a fake 21.75 reward/risk or 2175% ROI.
    // UI displays: rewardRiskUnlimited → "Unlimited" (profit side) or "N/A"
    // (loss side); roiUnlimited → "Unlimited"; null without a flag → "N/A".
    rewardRisk: rewardRisk(maxProfit, maxLoss, { maxProfitUnlimited, maxLossUnlimited }),
    rewardRiskUnlimited: maxProfitUnlimited || maxLossUnlimited,
    roi: roiPct(maxProfit, netTotal, { maxProfitUnlimited }),
    roiUnlimited: maxProfitUnlimited,
  };
}
