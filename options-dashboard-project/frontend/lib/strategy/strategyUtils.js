// Strategy utilities: builds the two context shapes the rest of the strategy
// domain consumes.
//
// 1. `buildStrategyContext` — the context passed to ready-made strategy
//    `build(ctx)` functions (strike-index offsets from ATM, chain maps per
//    expiry, the expiry list for calendar/diagonal spreads).
//
// 2. `buildChainContext` — the chain context used by the pure leg mutations
//    and transformations in ./strategy.js.

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
