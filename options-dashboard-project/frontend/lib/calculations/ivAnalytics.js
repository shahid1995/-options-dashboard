// IV Analytics domain (Phase 4.1) — canonical implied-volatility layer.
//
// ONE canonical internal representation exists for IV in the calculation
// layer: a DECIMAL FRACTION. 0.1824 = 18.24%. The UI may display a percentage
// ("18.24%") but every calculation consumes the decimal.
//
// ============================================================================
// CANONICAL IV UNIT CONTRACT (the only units the calculation layer uses)
// ============================================================================
//   canonical IV        decimal fraction       0.1824 = 18.24%
//   volatility point    0.01 volatility        2 vol points = 0.02
//
//   normalizeIv(18.24)        → 0.1824   (broker feed → canonical)
//   decimalToIvPercent(0.1824) → 18.24   (canonical → display number)
//   formatIvPercent(0.1824)    → "18.24%"
//   volPointsToDecimal(2)      → 0.02
//   decimalToVolPoints(0.02)   → 2
//
// Broker convention (verified against the backend chain transform and its
// tests): Upstox option_greeks `iv` is delivered as a PERCENT number — the
// backend fixture uses iv: 14.2 meaning 14.2%. NEVER feed that number to the
// pricing model directly; normalize it first. Nothing in this module ever
// mixes iv-percent, iv-decimal and vol-points in the same arithmetic.
//
// Invalid IV (null, undefined, NaN, ±Infinity, <= 0) NEVER becomes a valid
// market IV: normalizeIv returns null, structured states distinguish
// MISSING / INVALID / PARTIAL, and missing values are never silently turned
// into 0% or into a model substitute.

// ---- Unit contract ---------------------------------------------------------

export const IV_UNIT = "decimal fraction"; // 0.1824 = 18.24%
export const VOL_POINT = 0.01; // 1 volatility point = 0.01 volatility
export const IV_WARNING_CODES = [
  "MISSING_IV",
  "MISSING_CHAIN_DATA",
  "INSUFFICIENT_HISTORY",
  "INVALID_IV",
  "PARTIAL_DATA",
];

// ---- Normalization helpers (pure; never duplicated in React) --------------

// A valid canonical IV is a finite number > 0 (an ATM/OTM IV of exactly 0% is
// not a real market value; the pricing model clamps its own floor separately).
export function isValidIvDecimal(v) {
  return v != null && Number.isFinite(Number(v)) && Number(v) > 0;
}

// Broker feed IV is PERCENT (18.24 = 18.24%). Normalize to canonical decimal.
export function normalizeIv(raw) {
  if (raw === null || raw === undefined) return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return null; // NaN, ±Infinity, 0, negative → null
  return n / 100;
}

// Canonical decimal → percent NUMBER (0.1824 → 18.24). Null for invalid input.
export function decimalToIvPercent(dec) {
  const v = Number(dec);
  if (!isValidIvDecimal(v)) return null;
  return Number((v * 100).toFixed(4));
}

// Canonical decimal → percent STRING for display ("18.24%").
export function formatIvPercent(dec, digits = 2) {
  const v = Number(dec);
  if (!isValidIvDecimal(v)) return null;
  return `${(v * 100).toFixed(digits)}%`;
}

// Volatility points → canonical decimal (2 → 0.02).
export function volPointsToDecimal(points) {
  const v = Number(points);
  if (!Number.isFinite(v)) return null;
  return v * VOL_POINT;
}

// Canonical decimal → volatility points (0.02 → 2).
export function decimalToVolPoints(dec) {
  const v = Number(dec);
  if (!Number.isFinite(v)) return null;
  return v / VOL_POINT;
}

// ---- Structured warnings ---------------------------------------------------

export function ivWarning(code, message, meta = null) {
  const w = { code, message };
  if (meta != null) w.meta = meta;
  return w;
}

// ---- Shared date helper ----------------------------------------------------

// Whole calendar days between an ISO valuation date and an ISO expiry date
// (0 when expired; null when either date is unparseable).
export function daysToExpiry(valuationDate, expiryDate) {
  const v = new Date(`${valuationDate}T00:00:00Z`);
  const e = new Date(`${expiryDate}T00:00:00Z`);
  if (Number.isNaN(v.getTime()) || Number.isNaN(e.getTime())) return null;
  return Math.max(0, Math.round((e - v) / 86400000));
}

// ---- ATM IV ----------------------------------------------------------------

// Nearest available strike to the current spot (ties go to the lower strike).
// Re-derived from the chain every call — never a cached index.
export function nearestStrike(strikes, spot) {
  const s = Number(spot);
  if (!strikes || strikes.length === 0 || !Number.isFinite(s)) return null;
  let best = null;
  let bestDiff = Infinity;
  strikes.forEach((k) => {
    const diff = Math.abs(Number(k) - s);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = k;
    }
  });
  return best;
}

// ATM IV for ONE chain. CE and PE always come from the SAME nearest strike
// (spec §9). The average is only computed when both sides are present; a
// one-sided chain yields status "partial" with no fabricated average.
export function atmIvForChain(chain, spot) {
  const empty = { atmStrike: null, callIv: null, putIv: null, atmIv: null, status: "unavailable" };
  if (!chain?.chain || chain.chain.length === 0) return empty;
  const atmStrike = nearestStrike(chain.chain.map((r) => r.strike), spot);
  if (atmStrike == null) return empty;
  const row = chain.chain.find((r) => r.strike === atmStrike);
  const callIv = row?.call?.iv != null ? normalizeIv(row.call.iv) : null;
  const putIv = row?.put?.iv != null ? normalizeIv(row.put.iv) : null;

  let atmIv = null;
  let status = "unavailable";
  if (callIv != null && putIv != null) {
    atmIv = (callIv + putIv) / 2; // ATM Average IV = (Call IV + Put IV) / 2
    status = "available";
  } else if (callIv != null || putIv != null) {
    status = "partial"; // one side missing → never fabricate the average
  }
  return { atmStrike, callIv, putIv, atmIv, status };
}

// ---- Per-leg IV ------------------------------------------------------------

// Authoritative per-leg IV analytics. Every leg resolves against ITS OWN
// expiry chain and its own call/put side — never the primary expiry's IV.
export function legIvAnalytics(legs, chainCache) {
  return (legs ?? []).map((leg) => {
    const chain = chainCache?.[leg.expiry];
    const row = chain?.chain?.find((r) => r.strike === leg.strike);
    const side = row ? (leg.type === "call" ? row.call : row.put) : null;
    const liveIv = side?.iv != null ? normalizeIv(side.iv) : null;
    return {
      legId: leg.id,
      type: leg.type,
      action: leg.action,
      strike: leg.strike,
      expiry: leg.expiry,
      liveIv,
      liveIvPercent: liveIv != null ? decimalToIvPercent(liveIv) : null,
      ivAvailable: liveIv != null,
    };
  });
}

// ---- IV curve by strike ----------------------------------------------------

// Reusable IV curve: one row per chain strike with both sides, spot distance
// and moneyness. moneynessPct = (strike − spot) / spot × 100 (the SAME formula
// for calls and puts — call/put ITM/OTM labels, if ever added, are derived
// separately and never change the formula).
export function ivCurve(chain, spot) {
  if (!chain?.chain) return [];
  const s = Number(spot);
  return chain.chain.map((row) => {
    const strike = Number(row.strike);
    const callIv = row.call?.iv != null ? normalizeIv(row.call.iv) : null;
    const putIv = row.put?.iv != null ? normalizeIv(row.put.iv) : null;
    return {
      strike,
      callIv,
      putIv,
      callIvPercent: callIv != null ? decimalToIvPercent(callIv) : null,
      putIvPercent: putIv != null ? decimalToIvPercent(putIv) : null,
      spotDistance: Number.isFinite(s) ? strike - s : null,
      moneynessPct: Number.isFinite(s) && s > 0 ? ((strike - s) / s) * 100 : null,
    };
  });
}

// ---- IV skew ---------------------------------------------------------------

// Descriptive skew (NOT a signal): IV of OTM options vs ATM IV, in volatility
// points. `offsetPct` is the target moneyness (positive = OTM calls,
// negative = OTM puts); the nearest strike at that moneyness is used for BOTH
// sides (consistent with the ATM rule).
export function skewAtMoneyness(curve, atm, offsetPct) {
  const target = Number(offsetPct);
  const none = { moneynessPct: target, strike: null, callIv: null, putIv: null, callSkewVolPoints: null, putSkewVolPoints: null, available: false };
  if (!Array.isArray(curve) || curve.length === 0 || atm?.atmIv == null) return none;
  let best = null;
  let bestDiff = Infinity;
  curve.forEach((p) => {
    if (p.moneynessPct == null) return;
    const diff = Math.abs(p.moneynessPct - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = p;
    }
  });
  if (!best) return none;
  return {
    moneynessPct: target,
    strike: best.strike,
    callIv: best.callIv,
    putIv: best.putIv,
    callSkewVolPoints: best.callIv != null ? decimalToVolPoints(best.callIv - atm.atmIv) : null,
    putSkewVolPoints: best.putIv != null ? decimalToVolPoints(best.putIv - atm.atmIv) : null,
    available: (best.callIv != null || best.putIv != null) && atm.atmIv != null,
  };
}

// Call skew at +2% moneyness, put skew at −2% moneyness, both vs ATM IV.
export function ivSkew(curve, atm) {
  return {
    atm: { strike: atm?.atmStrike ?? null, iv: atm?.atmIv ?? null },
    call: skewAtMoneyness(curve, atm, 2),
    put: skewAtMoneyness(curve, atm, -2),
  };
}

// ---- IV term structure -----------------------------------------------------

// ATM IV per loaded expiry, each from ITS OWN chain (never the selected
// expiry's chain), sorted by days to expiry.
export function ivTermStructure(chainCache, spot, valuationDate) {
  const entries = Object.entries(chainCache ?? {}).map(([exp, chain]) => {
    const atm = atmIvForChain(chain, spot);
    return {
      expiry: exp,
      daysToExpiry: daysToExpiry(valuationDate, exp),
      atmCallIv: atm.callIv,
      atmPutIv: atm.putIv,
      atmIv: atm.atmIv,
      available: atm.status === "available",
      status: atm.status,
    };
  });
  return entries.sort((a, b) => (a.daysToExpiry ?? Infinity) - (b.daysToExpiry ?? Infinity));
}

// Descriptive term-structure slope between consecutive expiries:
// IV change per day (vol points/day) = (IV2 − IV1) / (DTE2 − DTE1).
// Descriptive only — never labelled bullish/bearish. Returns null when fewer
// than two comparable expiries exist.
export function termStructureSlope(termStructure) {
  const pts = (termStructure ?? [])
    .filter((t) => t.available && t.daysToExpiry != null)
    .sort((a, b) => a.daysToExpiry - b.daysToExpiry);
  if (pts.length < 2) return null;
  const segments = [];
  for (let i = 1; i < pts.length; i++) {
    const prev = pts[i - 1];
    const cur = pts[i];
    const days = cur.daysToExpiry - prev.daysToExpiry;
    if (days <= 0) continue;
    const ivChangeVolPoints = decimalToVolPoints(cur.atmIv - prev.atmIv);
    segments.push({
      from: prev.expiry,
      to: cur.expiry,
      fromDte: prev.daysToExpiry,
      toDte: cur.daysToExpiry,
      ivChangeVolPoints,
      days,
      volPointsPerDay: ivChangeVolPoints / days,
    });
  }
  return segments.length ? segments : null;
}

// ---- IV change -------------------------------------------------------------

// Current IV vs a previous observation. Three distinct metrics:
//   ivChange           canonical decimal difference (0.008)
//   ivChangeVolPoints  same difference in vol points (+0.8)
//   ivChangePercent    RELATIVE change vs previous (+4.40%) — never confused
//                      with the vol-point figure
// Missing/invalid inputs → all null (a missing previous observation never
// fabricates a change).
export function calculateIvChange(previousIv, currentIv) {
  const prev = Number(previousIv);
  const curr = Number(currentIv);
  if (!isValidIvDecimal(prev) || !isValidIvDecimal(curr)) {
    return { ivChange: null, ivChangeVolPoints: null, ivChangePercent: null, available: false };
  }
  const ivChange = curr - prev;
  const ivChangePercent = prev > 0 ? (ivChange / prev) * 100 : null;
  return { ivChange, ivChangeVolPoints: decimalToVolPoints(ivChange), ivChangePercent, available: true };
}

// ---- Historical IV foundation (Phase 4.1 — model + interfaces only) --------

// Minimum reliable sample size before rank/percentile helpers may return a
// value. Below this they return null — the UI must never show a fabricated
// IV Rank / Percentile.
export const MIN_IV_HISTORY = 30;

// Configurable collection policy for a FUTURE collector. Deliberately OFF in
// this phase: nothing in the app records IV history yet, so there is no
// uncontrolled database growth. When a future phase enables collection it must
// honour these bounds (sampling interval, retention, per-key cap) and the
// backend IV_HISTORY_* settings.
export const IV_HISTORY_CONFIG = {
  enabled: false, // NO automatic recording in Phase 4.1
  sampleIntervalSeconds: 300, // recommended: one snapshot per 5 minutes
  retentionDays: 90,
  maxObservationsPerKey: 2000,
  sources: ["upstox"],
};

// IVObservation — the canonical historical observation shape (spec §18):
//   { timestamp, symbol, expiry, strike, optionType, iv, spot, source }
// `iv` is always stored in CANONICAL DECIMAL (0.1824 = 18.24%). Returns null
// for invalid input (invalid iv, missing identity) — never a partial row.
export function makeIvObservation({ timestamp, symbol, expiry, strike, optionType, iv, spot, source }) {
  const dec = normalizeIv(iv); // broker input is percent → canonical decimal
  if (dec == null) return null;
  if (!symbol || !expiry || !["call", "put"].includes(optionType)) return null;
  const s = Number(strike);
  if (strike == null || !Number.isFinite(s)) return null;
  return {
    timestamp: timestamp ?? new Date().toISOString(),
    symbol: String(symbol).toUpperCase(),
    expiry,
    strike: s,
    optionType,
    iv: dec, // canonical decimal
    spot: spot != null && Number.isFinite(Number(spot)) ? Number(spot) : null,
    source: source ?? "upstox",
  };
}

// GUARDED IV Rank: fraction of history at or below `currentIv` (0..1).
// Returns null for invalid current IV or insufficient history — an empty or
// tiny sample NEVER yields a fabricated "0%" or "100%".
export function calculateIvRank(history, currentIv) {
  const iv = Number(currentIv);
  if (!isValidIvDecimal(iv)) return null;
  const sample = (history ?? []).map(Number).filter((v) => isValidIvDecimal(v));
  if (sample.length < MIN_IV_HISTORY) return null;
  const atOrBelow = sample.filter((v) => v <= iv).length;
  return atOrBelow / sample.length;
}

// GUARDED IV Percentile (0..100): percentage of history strictly below
// `currentIv`. Same guards as calculateIvRank. A current value exactly at the
// minimum yields 0, exactly at the maximum yields (n−1)/n × 100 — exact, not
// invented.
export function calculateIvPercentile(history, currentIv) {
  const iv = Number(currentIv);
  if (!isValidIvDecimal(iv)) return null;
  const sample = (history ?? []).map(Number).filter((v) => isValidIvDecimal(v));
  if (sample.length < MIN_IV_HISTORY) return null;
  const below = sample.filter((v) => v < iv).length;
  return (below / sample.length) * 100;
}

// ---- Authoritative entry point ---------------------------------------------

// One IV analytics result for a symbol + selected expiry:
//   {
//     atm:            { atmStrike, callIv, putIv, atmIv, status },   (selected expiry)
//     curve:          [{ strike, callIv, putIv, callIvPercent, putIvPercent,
//                        spotDistance, moneynessPct }],
//     skew:           { atm, call: skewAt +2%, put: skewAt −2% },
//     termStructure:  [{ expiry, daysToExpiry, atmCallIv, atmPutIv, atmIv,
//                        available, status }],                          (every loaded expiry)
//     termSlope:      [{ from, to, ivChangeVolPoints, days, volPointsPerDay }] | null,
//     perLeg:         leg-level IV (legs optional — IV tab works without legs),
//     warnings:       structured MISSING_IV / MISSING_CHAIN_DATA / PARTIAL_DATA
//   }
// Derived analytics here are always distinguishable from raw broker IV:
// `atm`, `curve[*].callIv/putIv` are normalized broker values; everything
// else (averages, skew, slope, change) is derived and labelled as such in the
// UI.
export function calculateIvAnalytics({ chainCache = {}, spot, valuationDate, legs = [], selectedExpiry = null } = {}) {
  const warnings = [];
  const chain = selectedExpiry ? chainCache?.[selectedExpiry] : null;

  const atm = chain ? atmIvForChain(chain, spot) : { atmStrike: null, callIv: null, putIv: null, atmIv: null, status: "unavailable" };
  if (!chain && selectedExpiry) {
    warnings.push(ivWarning("MISSING_CHAIN_DATA", `Chain data for expiry ${selectedExpiry} is not loaded.`));
  } else if (chain && atm.status === "unavailable") {
    warnings.push(ivWarning("MISSING_IV", `ATM IV is unavailable for ${selectedExpiry}: no valid call/put IV at the nearest strike.`));
  } else if (chain && atm.status === "partial") {
    warnings.push(ivWarning("PARTIAL_DATA", `ATM IV for ${selectedExpiry} is partial: only one side has a valid IV at the ATM strike.`));
  }

  const curve = chain ? ivCurve(chain, spot) : [];
  const skew = curve.length && atm.atmIv != null ? ivSkew(curve, atm) : { atm: { strike: atm.atmStrike, iv: atm.atmIv }, call: skewAtMoneyness([], atm, 2), put: skewAtMoneyness([], atm, -2) };

  const termStructure = ivTermStructure(chainCache, spot, valuationDate);
  const termSlope = termStructureSlope(termStructure);
  if (termStructure.some((t) => t.status === "partial")) {
    warnings.push(ivWarning("PARTIAL_DATA", "Term structure includes an expiry with only one-sided ATM IV."));
  }

  const perLeg = legIvAnalytics(legs, chainCache);

  return { atm, curve, skew, termStructure, termSlope, perLeg, warnings };
}
