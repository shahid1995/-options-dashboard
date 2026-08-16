// Greeks calculation domain.
//
// Reuses the option-chain Greek data delivered by the backend (per leg: delta,
// gamma, theta, vega on the call/put side of the chain row). No new pricing
// model is introduced here — position-level Greeks are each leg's chain Greek
// scaled by direction (BUY = +, SELL = −) × quantity × lot size × multiplier.

import { dirOf } from "../options";

// Position-level Greeks for a single leg, given its chain row (the chain
// response row containing call/put sides). Any missing Greek stays null.
export function legGreeks(leg, row, { lotSize = 1, multiplier = 1 } = {}) {
  const g = row ? (leg.type === "call" ? row.call : row.put) : null;
  const mult = dirOf(leg.action) * leg.qty * lotSize * multiplier;
  return {
    leg,
    delta: g?.delta != null ? g.delta * mult : null,
    gamma: g?.gamma != null ? g.gamma * mult : null,
    theta: g?.theta != null ? g.theta * mult : null,
    vega: g?.vega != null ? g.vega * mult : null,
  };
}

// Aggregated strategy Greeks.
//
// `chainCache` maps expiry date -> chain response ({ chain: [{ strike, call,
// put }] }); each leg's row is resolved against the chain of its own expiry.
// Returns { rows, totals } where `rows` mirrors the per-leg shape above and
// `totals` sums the non-null values (missing Greek counts as 0).
export function aggregateGreeks(legs, chainCache, { lotSize = 1, multiplier = 1 } = {}) {
  const rows = legs.map((l) => {
    const legChain = chainCache?.[l.expiry];
    const row = legChain?.chain.find((r) => r.strike === l.strike);
    return legGreeks(l, row, { lotSize, multiplier });
  });
  const totals = rows.reduce(
    (acc, r) => ({
      delta: acc.delta + (r.delta ?? 0),
      gamma: acc.gamma + (r.gamma ?? 0),
      theta: acc.theta + (r.theta ?? 0),
      vega: acc.vega + (r.vega ?? 0),
    }),
    { delta: 0, gamma: 0, theta: 0, vega: 0 }
  );
  return { rows, totals };
}
