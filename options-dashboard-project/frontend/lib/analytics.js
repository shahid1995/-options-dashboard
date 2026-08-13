// Pure analytics over a chain: rows of { strike, call: { oi, ltp, ... }, put: { ... } }.

export function oiTotals(rows) {
  let callOI = 0;
  let putOI = 0;
  for (const r of rows) {
    callOI += r.call?.oi ?? 0;
    putOI += r.put?.oi ?? 0;
  }
  return { callOI, putOI };
}

// Put-Call Ratio by open interest. Null when there is no call OI.
export function putCallRatio(rows) {
  const { callOI, putOI } = oiTotals(rows);
  if (!callOI) return null;
  return putOI / callOI;
}

// Max pain: the expiry price where option writers lose the least, i.e. the
// strike minimizing the total intrinsic value paid out across all OI.
export function maxPainStrike(rows) {
  if (!rows.length) return null;
  let best = null;
  let bestPain = Infinity;
  for (const s of rows) {
    let pain = 0;
    for (const k of rows) {
      pain += (k.call?.oi ?? 0) * Math.max(0, s.strike - k.strike);
      pain += (k.put?.oi ?? 0) * Math.max(0, k.strike - s.strike);
    }
    if (pain < bestPain) {
      bestPain = pain;
      best = s.strike;
    }
  }
  return best;
}

// Largest single-side OI across the chain, used to scale OI bars.
export function maxOI(rows) {
  let max = 0;
  for (const r of rows) {
    max = Math.max(max, r.call?.oi ?? 0, r.put?.oi ?? 0);
  }
  return max;
}
