// Strategy domain: the leg model plus every leg mutation and strategy
// transformation used by the Strategy Builder.
//
// All functions are pure — they take legs (or a leg + chain context) and
// return new legs, never mutating input. The chain context (`ctx`) describes
// the option chains available to resolve strike lists, live prices and the
// ATM reference:
//
//   ctx = {
//     strikes,             // primary (selected) expiry, sorted ascending
//     chainByStrike,       // primary expiry: strike -> { call, put } row
//     chainsByExpiry,      // { [expiry]: { chain: [strikes], rows: Map, spot } }
//     spot,                // primary expiry underlying spot (may be null)
//     atmIndex,            // index of the ATM strike in ctx.strikes
//     expiry,              // primary expiry date string
//   }
//
// Build it with `buildChainContext` from ./strategyUtils.

// The canonical leg shape used across the app:
//   { id, type: "call"|"put", action: "buy"|"sell", strike, expiry, qty, price }
// Additional metadata (e.g. `hedge: true`) is preserved as-is.
export function makeLeg({ type, strike, action = "buy", qty = 1, expiry = null, price = 0, hedge = false, id } = {}) {
  const numericPrice = Number.isFinite(Number(price)) ? Number(price) : 0;
  return {
    id: id ?? `${type}-${strike}-${expiry ?? "x"}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type,
    strike,
    action,
    qty,
    expiry,
    price: numericPrice,
    hedge,
  };
}

// ---- Leg mutations (return new leg arrays) ----

export function addLeg(legs, leg) {
  return [...legs, leg];
}

export function updateLeg(legs, id, patch) {
  return legs.map((l) => (l.id === id ? { ...l, ...patch } : l));
}

export function removeLeg(legs, id) {
  return legs.filter((l) => l.id !== id);
}

// Move one leg one or more strikes along its expiry's chain, re-pricing it
// from the chain when a live price is available (falling back to its current
// price). Returns the (possibly unchanged) leg.
export function moveLegByStrikes(l, steps, ctx) {
  if (!steps || !l) return l;
  const strikes = strikesForLeg(l, ctx);
  if (strikes.length === 0) return l;
  const idx = strikes.indexOf(l.strike);
  if (idx === -1) return l;
  const newIdx = Math.min(Math.max(idx + steps, 0), strikes.length - 1);
  const newStrike = strikes[newIdx];
  const price = priceForLeg(ctx, l.type, newStrike, l.expiry);
  return { ...l, strike: newStrike, price: price ?? l.price };
}

// List-level strike change (e.g. the +/- steppers in the legs table).
export function changeLegStrike(legs, id, direction, ctx) {
  const l = legs.find((x) => x.id === id);
  if (!l) return legs;
  const moved = moveLegByStrikes(l, direction, ctx);
  return legs.map((x) => (x.id === id ? moved : x));
}

// Refresh every leg's price from its expiry's chain; legs whose chain has no
// row keep their current price.
export function resetLegPrices(legs, ctx) {
  return legs.map((l) => {
    const price = priceForLeg(ctx, l.type, l.strike, l.expiry);
    return price == null ? l : { ...l, price };
  });
}

// ---- Chain lookups used by the transformations ----

// Sorted strikes available for a leg: the leg's own expiry chain when it has
// been fetched, otherwise the primary chain (existing fallback behavior).
export function strikesForLeg(l, ctx) {
  const exp = l.expiry ? ctx.chainsByExpiry?.[l.expiry] : null;
  if (exp?.chain?.length) return exp.chain;
  return ctx.strikes ?? [];
}

// Chain row (primary or per-expiry) for a type/strike/expiry lookup.
export function rowForLeg(ctx, type, strike, expiryDate) {
  const exp = expiryDate ? ctx.chainsByExpiry?.[expiryDate] : null;
  return exp?.rows.get(strike) ?? ctx.chainByStrike?.get(strike);
}

// Live premium for a leg, or null when the row/ltp is unavailable.
export function priceForLeg(ctx, type, strike, expiryDate) {
  const row = rowForLeg(ctx, type, strike, expiryDate);
  if (!row) return null;
  const ltp = type === "call" ? row.call.ltp : row.put.ltp;
  return ltp ?? null;
}

// ---- Strategy transformations (Shift / Width / Hedge) ----

// Shift every leg the same number of strikes up (+) or down (−).
export function applyShift(legs, delta, ctx) {
  if (!delta) return legs;
  return legs.map((l) => moveLegByStrikes(l, delta, ctx));
}

// Widen (+) or narrow (−) the position: legs above the ATM ride up, legs
// below ride down, ATM legs drift with their own side. Each leg is measured
// against its own expiry's ATM strike.
export function applyWidth(legs, delta, ctx) {
  if (!delta) return legs;
  return legs.map((l) => {
    const exp = l.expiry ? ctx.chainsByExpiry?.[l.expiry] : null;
    const strikes = exp?.chain?.length ? exp.chain : ctx.strikes;
    const spotRef = exp?.spot ?? ctx.spot;
    if (strikes.length === 0 || spotRef == null) return l;
    let atmIdx = 0;
    let bestDiff = Infinity;
    strikes.forEach((s, i) => {
      const d = Math.abs(s - spotRef);
      if (d < bestDiff) {
        bestDiff = d;
        atmIdx = i;
      }
    });
    const idx = strikes.indexOf(l.strike);
    if (idx === -1) return l;
    const off = idx - atmIdx;
    // Legs above ATM ride up, legs below ride down, ATM legs drift with
    // their side — widening pushes wings out, narrowing pulls them in.
    const dir = off === 0 ? (l.type === "call" ? 1 : -1) : Math.sign(off);
    return moveLegByStrikes(l, dir * delta, ctx);
  });
}

// A protective long OTM leg: level 1 = long call +4, 2 = long put −4,
// 3 = long call +5, 4 = long put −5, … (primary expiry chain).
export function buildHedgeLeg(level, ctx) {
  const side = level % 2 === 1 ? "call" : "put";
  const offset = 4 + Math.floor((level - 1) / 2);
  const sign = side === "call" ? 1 : -1;
  const strikeIdx = Math.min(Math.max(ctx.atmIndex + sign * offset, 0), (ctx.strikes?.length ?? 1) - 1);
  const strike = ctx.strikes?.[strikeIdx];
  if (strike == null) return null;
  const price = priceForLeg(ctx, side, strike, ctx.expiry);
  return makeLeg({ type: side, strike, action: "buy", qty: 1, expiry: ctx.expiry, price: price ?? 0, hedge: true });
}

// Add hedge level `level` as a new protective leg (no-op when the strike
// cannot be resolved).
export function addHedgeLeg(legs, level, ctx) {
  const leg = buildHedgeLeg(level, ctx);
  if (!leg) return legs;
  return addLeg(legs, leg);
}

// Remove the most recently added hedge leg (no-op when none exist).
export function removeLastHedgeLeg(legs) {
  const hedgeLegs = legs.filter((l) => l.hedge);
  if (hedgeLegs.length === 0) return legs;
  const last = hedgeLegs[hedgeLegs.length - 1];
  return legs.filter((l) => l.id !== last.id);
}
