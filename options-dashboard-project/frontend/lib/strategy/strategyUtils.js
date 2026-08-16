// Strategy utilities: builds the two context shapes the rest of the strategy
// domain consumes.
//
// 1. `buildStrategyContext` — the context passed to ready-made strategy
//    `build(ctx)` functions (strike-index offsets from ATM, chain maps per
//    expiry, the expiry list for calendar/diagonal spreads).
//
// 2. `buildChainContext` — the chain context used by the pure leg mutations
//    and transformations in ./strategy.js.

// Every expiry referenced by the strategy legs, deduped and sorted ascending.
// This is the strategy's chain requirement: the builder must have fetched a
// chain for each of these expiries before a multi-expiry (calendar/diagonal)
// strategy can be fully priced or validated for execution.
export function requiredExpiries(legs) {
  return [...new Set((legs ?? []).map((l) => l.expiry).filter(Boolean))].sort();
}

// Required expiries whose chain data has not been loaded yet. `chains` is a
// map of expiry -> chain payload (e.g. the paper page's chainCache). Returns
// [] when every referenced expiry already has a chain loaded.
export function missingChainExpiries(legs, chains) {
  const loaded = new Set(Object.keys(chains ?? {}));
  return requiredExpiries(legs).filter((exp) => !loaded.has(exp));
}

// Context for ready-made strategy templates (see lib/strategies.js).
export function buildStrategyContext({ strikes, atmIndex, chainByStrike, expiry, expiries, chainCache }) {
  const chainByStrikeForExpiry = {};
  (expiries ?? []).forEach((exp) => {
    const ch = chainCache?.[exp];
    if (ch) chainByStrikeForExpiry[exp] = new Map(ch.chain.map((r) => [r.strike, r]));
  });
  return { strikes, atmIndex, chainByStrike, expiry, expiries, chainByStrikeForExpiry };
}

// Chain context for the leg mutations / transformations.
//
// `chainCache` maps expiry date -> chain response ({ chain: [{ strike, call,
// put }], underlying_spot_price }). Strikes are cached sorted per expiry so
// the transformations do not re-sort on every step.
export function buildChainContext({ chainCache, strikes = [], chainByStrike, spot, atmIndex = 0, expiry }) {
  const chainsByExpiry = {};
  Object.entries(chainCache ?? {}).forEach(([exp, ch]) => {
    if (!ch?.chain) return;
    chainsByExpiry[exp] = {
      chain: ch.chain.map((r) => r.strike).sort((a, b) => a - b),
      rows: new Map(ch.chain.map((r) => [r.strike, r])),
      spot: ch.underlying_spot_price ?? null,
    };
  });
  return { strikes, chainByStrike, spot, atmIndex, expiry, chainsByExpiry };
}
