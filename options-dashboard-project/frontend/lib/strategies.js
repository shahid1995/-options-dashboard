// Readymade option strategies. Each strategy's `build` function takes a
// context describing the currently loaded chain and returns a list of legs.
//
// We use STRIKE-INDEX offsets from the ATM strike (not rupee offsets) so
// these work correctly no matter what strike spacing NSE uses for a given
// expiry (50-point, 100-point, etc).

import { ltpOf } from "./options";

function strikeAt(ctx, offset) {
  const idx = Math.min(Math.max(ctx.atmIndex + offset, 0), ctx.strikes.length - 1);
  return ctx.strikes[idx];
}

// Resolve the chain rows for a given expiry: falls back to the primary chain
// when a far expiry's data hasn't been fetched yet.
function chainMapFor(ctx, expiryDate) {
  if (expiryDate && expiryDate !== ctx.expiry) {
    const map = ctx.chainByStrikeForExpiry?.[expiryDate];
    if (map) return map;
  }
  return ctx.chainByStrike;
}

// The expiry used by multi-expiry strategies (calendar / diagonal): the next
// listed expiry after the primary one, or the primary itself if there is none.
function nextExpiry(ctx) {
  if (!Array.isArray(ctx.expiries) || ctx.expiries.length === 0) return ctx.expiry;
  const later = [...ctx.expiries].sort().filter((e) => e > ctx.expiry);
  return later[0] ?? ctx.expiry;
}

function legAt(ctx, type, offset, action, qty = 1, expiryDate = ctx.expiry) {
  const strike = strikeAt(ctx, offset);
  const row = chainMapFor(ctx, expiryDate).get(strike);
  const price = row ? ltpOf(row, type) ?? 0 : 0;
  return {
    id: `${type}-${strike}-${action}-${expiryDate}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    type,
    strike,
    action,
    qty,
    expiry: expiryDate,
    price,
  };
}

function leg(ctx, type, offset, action, qty = 1) {
  return legAt(ctx, type, offset, action, qty, ctx.expiry);
}

export const STRATEGY_CATEGORIES = ["Bullish", "Bearish", "Neutral", "Others"];

export const STRATEGIES = [
  // ---- Bullish ----
  { id: "buy_call", name: "Buy Call", category: "Bullish", shape: "riseUp", build: (ctx) => [leg(ctx, "call", 0, "buy")] },
  { id: "sell_put", name: "Sell Put", category: "Bullish", shape: "riseUp", build: (ctx) => [leg(ctx, "put", 0, "sell")] },
  { id: "bull_call_spread", name: "Bull Call Spread", category: "Bullish", shape: "riseCapped", build: (ctx) => [leg(ctx, "call", 0, "buy"), leg(ctx, "call", 2, "sell")] },
  { id: "bull_put_spread", name: "Bull Put Spread", category: "Bullish", shape: "riseCapped", build: (ctx) => [leg(ctx, "put", 0, "sell"), leg(ctx, "put", -2, "buy")] },
  { id: "call_ratio_back", name: "Call Ratio Back Spread", category: "Bullish", shape: "riseUp", build: (ctx) => [leg(ctx, "call", 0, "sell", 1), leg(ctx, "call", 2, "buy", 2)] },
  { id: "bull_condor", name: "Bull Condor", category: "Bullish", shape: "plateau", build: (ctx) => [leg(ctx, "call", -2, "buy"), leg(ctx, "call", 0, "sell"), leg(ctx, "call", 2, "sell"), leg(ctx, "call", 4, "buy")] },
  { id: "bull_butterfly", name: "Bull Butterfly", category: "Bullish", shape: "peak", build: (ctx) => [leg(ctx, "call", -2, "buy"), leg(ctx, "call", 0, "sell", 2), leg(ctx, "call", 2, "buy")] },
  { id: "range_forward", name: "Range Forward", category: "Bullish", shape: "riseUp", build: (ctx) => [leg(ctx, "put", -1, "sell"), leg(ctx, "call", 1, "buy")] },
  { id: "long_synthetic_future", name: "Long Synthetic Future", category: "Bullish", shape: "riseUp", build: (ctx) => [leg(ctx, "call", 0, "buy"), leg(ctx, "put", 0, "sell")] },
  { id: "jade_lizard", name: "Jade Lizard", category: "Bullish", shape: "fallCapped", build: (ctx) => [leg(ctx, "put", -1, "sell"), leg(ctx, "call", 1, "sell"), leg(ctx, "call", 3, "buy")] },
  { id: "long_seagull", name: "Long Seagull", category: "Bullish", shape: "riseCapped", build: (ctx) => [leg(ctx, "call", 0, "buy"), leg(ctx, "put", -1, "sell"), leg(ctx, "call", 2, "sell")] },
  { id: "ratio_put_spread", name: "Ratio Put Spread (1:2)", category: "Bullish", shape: "fallLeft", build: (ctx) => [leg(ctx, "put", 0, "buy"), leg(ctx, "put", -2, "sell", 2)] },
  { id: "diagonal_call", name: "Call Diagonal", category: "Bullish", shape: "riseUp", build: (ctx) => [legAt(ctx, "call", 0, "buy", 1, nextExpiry(ctx)), leg(ctx, "call", 1, "sell")] },

  // ---- Bearish ----
  { id: "buy_put", name: "Buy Put", category: "Bearish", shape: "fallUp", build: (ctx) => [leg(ctx, "put", 0, "buy")] },
  { id: "sell_call", name: "Sell Call", category: "Bearish", shape: "fallUp", build: (ctx) => [leg(ctx, "call", 0, "sell")] },
  { id: "bear_put_spread", name: "Bear Put Spread", category: "Bearish", shape: "fallCapped", build: (ctx) => [leg(ctx, "put", 0, "buy"), leg(ctx, "put", -2, "sell")] },
  { id: "bear_call_spread", name: "Bear Call Spread", category: "Bearish", shape: "fallCapped", build: (ctx) => [leg(ctx, "call", 0, "sell"), leg(ctx, "call", 2, "buy")] },
  { id: "put_ratio_back", name: "Put Ratio Back Spread", category: "Bearish", shape: "fallUp", build: (ctx) => [leg(ctx, "put", 0, "sell", 1), leg(ctx, "put", -2, "buy", 2)] },
  { id: "bear_condor", name: "Bear Condor", category: "Bearish", shape: "plateau", build: (ctx) => [leg(ctx, "put", 2, "buy"), leg(ctx, "put", 0, "sell"), leg(ctx, "put", -2, "sell"), leg(ctx, "put", -4, "buy")] },
  { id: "bear_butterfly", name: "Bear Butterfly", category: "Bearish", shape: "peak", build: (ctx) => [leg(ctx, "put", 2, "buy"), leg(ctx, "put", 0, "sell", 2), leg(ctx, "put", -2, "buy")] },
  { id: "short_synthetic_future", name: "Short Synthetic Future", category: "Bearish", shape: "fallUp", build: (ctx) => [leg(ctx, "put", 0, "buy"), leg(ctx, "call", 0, "sell")] },
  { id: "short_seagull", name: "Short Seagull", category: "Bearish", shape: "fallCapped", build: (ctx) => [leg(ctx, "put", 0, "buy"), leg(ctx, "call", 1, "sell"), leg(ctx, "put", -2, "sell")] },
  { id: "ratio_call_spread", name: "Ratio Call Spread (1:2)", category: "Bearish", shape: "fallRight", build: (ctx) => [leg(ctx, "call", 0, "buy"), leg(ctx, "call", 2, "sell", 2)] },
  { id: "diagonal_put", name: "Put Diagonal", category: "Bearish", shape: "fallUp", build: (ctx) => [legAt(ctx, "put", 0, "buy", 1, nextExpiry(ctx)), leg(ctx, "put", -1, "sell")] },

  // ---- Neutral ----
  { id: "long_straddle", name: "Long Straddle", category: "Neutral", shape: "vUp", build: (ctx) => [leg(ctx, "call", 0, "buy"), leg(ctx, "put", 0, "buy")] },
  { id: "short_straddle", name: "Short Straddle", category: "Neutral", shape: "peak", build: (ctx) => [leg(ctx, "call", 0, "sell"), leg(ctx, "put", 0, "sell")] },
  { id: "long_strangle", name: "Long Strangle", category: "Neutral", shape: "vUp", build: (ctx) => [leg(ctx, "call", 2, "buy"), leg(ctx, "put", -2, "buy")] },
  { id: "short_strangle", name: "Short Strangle", category: "Neutral", shape: "plateau", build: (ctx) => [leg(ctx, "call", 2, "sell"), leg(ctx, "put", -2, "sell")] },
  { id: "iron_condor", name: "Iron Condor", category: "Neutral", shape: "plateau", build: (ctx) => [leg(ctx, "put", -4, "buy"), leg(ctx, "put", -2, "sell"), leg(ctx, "call", 2, "sell"), leg(ctx, "call", 4, "buy")] },
  { id: "iron_butterfly", name: "Iron Butterfly", category: "Neutral", shape: "peak", build: (ctx) => [leg(ctx, "put", -2, "buy"), leg(ctx, "put", 0, "sell"), leg(ctx, "call", 0, "sell"), leg(ctx, "call", 2, "buy")] },
  { id: "long_iron_condor", name: "Long Iron Condor", category: "Neutral", shape: "valley", build: (ctx) => [leg(ctx, "put", -4, "sell"), leg(ctx, "put", -2, "buy"), leg(ctx, "call", 2, "buy"), leg(ctx, "call", 4, "sell")] },
  { id: "long_iron_butterfly", name: "Long Iron Butterfly", category: "Neutral", shape: "valley", build: (ctx) => [leg(ctx, "put", -2, "sell"), leg(ctx, "put", 0, "buy"), leg(ctx, "call", 0, "buy"), leg(ctx, "call", 2, "sell")] },
  { id: "broken_wing_call", name: "Broken Wing Butterfly (Call)", category: "Neutral", shape: "broken", build: (ctx) => [leg(ctx, "call", -2, "buy"), leg(ctx, "call", 0, "sell", 2), leg(ctx, "call", 3, "buy")] },
  { id: "broken_wing_put", name: "Broken Wing Butterfly (Put)", category: "Neutral", shape: "broken", build: (ctx) => [leg(ctx, "put", 2, "buy"), leg(ctx, "put", 0, "sell", 2), leg(ctx, "put", -3, "buy")] },
  { id: "long_guts", name: "Long Guts", category: "Neutral", shape: "vUp", build: (ctx) => [leg(ctx, "call", 1, "buy"), leg(ctx, "put", -1, "buy")] },
  { id: "short_guts", name: "Short Guts", category: "Neutral", shape: "peak", build: (ctx) => [leg(ctx, "call", 1, "sell"), leg(ctx, "put", -1, "sell")] },
  { id: "calendar", name: "Calendar Spread", category: "Neutral", shape: "flat", build: (ctx) => [leg(ctx, "call", 0, "sell"), legAt(ctx, "call", 0, "buy", 1, nextExpiry(ctx))] },

  // ---- Others ----
  { id: "strap", name: "Strap (2 Call + 1 Put)", category: "Others", shape: "vUp", build: (ctx) => [leg(ctx, "call", 0, "buy", 2), leg(ctx, "put", 0, "buy", 1)] },
  { id: "strip", name: "Strip (1 Call + 2 Put)", category: "Others", shape: "vUp", build: (ctx) => [leg(ctx, "call", 0, "buy", 1), leg(ctx, "put", 0, "buy", 2)] },
  { id: "long_call_ladder", name: "Long Call Ladder", category: "Others", shape: "fallUp", build: (ctx) => [leg(ctx, "call", 0, "buy"), leg(ctx, "call", 2, "sell"), leg(ctx, "call", 4, "sell")] },
  { id: "long_put_ladder", name: "Long Put Ladder", category: "Others", shape: "riseUp", build: (ctx) => [leg(ctx, "put", 0, "buy"), leg(ctx, "put", -2, "sell"), leg(ctx, "put", -4, "sell")] },
  { id: "box_spread", name: "Box Spread", category: "Others", shape: "flat", build: (ctx) => [leg(ctx, "call", -2, "buy"), leg(ctx, "call", 2, "sell"), leg(ctx, "put", 2, "buy"), leg(ctx, "put", -2, "sell")] },
];

export function strategiesFor(category) {
  return STRATEGIES.filter((s) => s.category === category);
}
