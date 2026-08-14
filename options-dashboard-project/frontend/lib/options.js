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
