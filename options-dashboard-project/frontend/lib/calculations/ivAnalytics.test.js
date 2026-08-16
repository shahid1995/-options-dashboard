import { describe, it, expect } from "vitest";
import {
  IV_UNIT,
  VOL_POINT,
  normalizeIv,
  decimalToIvPercent,
  formatIvPercent,
  volPointsToDecimal,
  decimalToVolPoints,
  isValidIvDecimal,
  nearestStrike,
  atmIvForChain,
  legIvAnalytics,
  ivCurve,
  ivSkew,
  skewAtMoneyness,
  ivTermStructure,
  termStructureSlope,
  calculateIvChange,
  makeIvObservation,
  MIN_IV_HISTORY,
  calculateIvRank,
  calculateIvPercentile,
  calculateIvAnalytics,
} from "./ivAnalytics";
import { calculateScenario } from "./scenario";

const VALUATION = "2026-08-16";

// Chain fixtures follow the REAL broker convention: iv is PERCENT (18.24 =
// 18.24%). The calculation layer normalizes to canonical decimal.
function makeChain(rows) {
  return {
    underlying_spot_price: 25000,
    chain: rows.map(([strike, callIv, putIv]) => ({
      strike,
      call: { ltp: 200, iv: callIv, delta: 0.5, theta: -1, gamma: 0.001, vega: 2 },
      put: { ltp: 150, iv: putIv, delta: -0.5, theta: -1, gamma: 0.001, vega: 2 },
    })),
  };
}

// ---- Section: normalization ------------------------------------------------

describe("IV normalization (canonical = decimal fraction)", () => {
  it("normalizeIv(18.24) → 0.1824 (broker percent → canonical decimal)", () => {
    expect(normalizeIv(18.24)).toBeCloseTo(0.1824, 10);
  });

  it("normalizeIv(20) → 0.20", () => {
    expect(normalizeIv(20)).toBeCloseTo(0.2, 10);
  });

  it("decimalToIvPercent(0.1824) → 18.24 and formatIvPercent → '18.24%'", () => {
    expect(decimalToIvPercent(0.1824)).toBeCloseTo(18.24, 10);
    expect(formatIvPercent(0.1824)).toBe("18.24%");
  });

  it("volPointsToDecimal(2) → 0.02 and decimalToVolPoints(0.02) → 2", () => {
    expect(VOL_POINT).toBe(0.01);
    expect(IV_UNIT).toBe("decimal fraction");
    expect(volPointsToDecimal(2)).toBeCloseTo(0.02, 12);
    expect(decimalToVolPoints(0.02)).toBeCloseTo(2, 12);
  });

  it("invalid IV (NaN, ±Infinity, negative, zero, non-numeric) → null, never 0", () => {
    expect(normalizeIv(NaN)).toBeNull();
    expect(normalizeIv(Infinity)).toBeNull();
    expect(normalizeIv(-Infinity)).toBeNull();
    expect(normalizeIv(-5)).toBeNull();
    expect(normalizeIv(0)).toBeNull();
    expect(normalizeIv("abc")).toBeNull();
    expect(isValidIvDecimal(0)).toBe(false);
    expect(isValidIvDecimal(-0.1)).toBe(false);
    expect(isValidIvDecimal(NaN)).toBe(false);
  });

  it("missing IV (null / undefined) → null", () => {
    expect(normalizeIv(null)).toBeNull();
    expect(normalizeIv(undefined)).toBeNull();
    expect(decimalToIvPercent(null)).toBeNull();
    expect(decimalToVolPoints(undefined)).toBeNull();
  });
});

// ---- Section: ATM IV -------------------------------------------------------

describe("ATM IV", () => {
  const chain = makeChain([
    [24300, 17.5, 17.9],
    [24350, 18.24, 18.81],
    [24400, 18.5, 19.1],
  ]);

  it("selects the nearest strike to spot (24,372 → 24,350)", () => {
    expect(nearestStrike([24300, 24350, 24400], 24372)).toBe(24350);
    expect(atmIvForChain(chain, 24372).atmStrike).toBe(24350);
  });

  it("uses the SAME strike for CE and PE at ATM", () => {
    const atm = atmIvForChain(chain, 24372);
    expect(atm.atmStrike).toBe(24350);
    expect(atm.callIv).toBeCloseTo(0.1824, 10);
    expect(atm.putIv).toBeCloseTo(0.1881, 10);
    expect(atm.atmIv).toBeCloseTo((0.1824 + 0.1881) / 2, 10);
    expect(atm.status).toBe("available");
  });

  it("one side missing → partial, no fabricated average", () => {
    const oneSided = makeChain([[24350, 18.24, null]]);
    const atm = atmIvForChain(oneSided, 24350);
    expect(atm.status).toBe("partial");
    expect(atm.callIv).toBeCloseTo(0.1824, 10);
    expect(atm.putIv).toBeNull();
    expect(atm.atmIv).toBeNull(); // never fabricate the average
  });

  it("both sides missing → unavailable", () => {
    const none = makeChain([[24350, null, null]]);
    const atm = atmIvForChain(none, 24350);
    expect(atm.status).toBe("unavailable");
    expect(atm.callIv).toBeNull();
    expect(atm.putIv).toBeNull();
    expect(atm.atmIv).toBeNull();
  });

  it("no chain → unavailable", () => {
    const atm = atmIvForChain(null, 25000);
    expect(atm.status).toBe("unavailable");
    expect(atm.atmStrike).toBeNull();
  });
});

// ---- Section: IV curve -----------------------------------------------------

describe("IV curve", () => {
  const chain = makeChain([
    [24000, 12.0, 13.8],
    [24500, 14.4, 13.2],
    [25000, 16.2, 16.8],
  ]);

  it("maps every strike with both sides and percent views", () => {
    const curve = ivCurve(chain, 24000);
    expect(curve).toHaveLength(3);
    expect(curve[0].strike).toBe(24000);
    expect(curve[0].callIv).toBeCloseTo(0.12, 10);
    expect(curve[0].callIvPercent).toBeCloseTo(12, 10);
    expect(curve[1].putIvPercent).toBeCloseTo(13.2, 10);
  });

  it("moneynessPct = (strike − spot) / spot × 100 for the same formula on both sides", () => {
    const curve = ivCurve(chain, 24000);
    expect(curve[1].moneynessPct).toBeCloseTo((24500 - 24000) / 24000 * 100, 8); // +2.0833%
    expect(curve[0].moneynessPct).toBeCloseTo(0, 8);
    expect(curve[0].spotDistance).toBe(0);
    expect(curve[2].moneynessPct).toBeCloseTo((25000 - 24000) / 24000 * 100, 8);
  });

  it("call IV and put IV are normalized independently per strike", () => {
    const curve = ivCurve(chain, 24000);
    expect(curve[2].callIv).toBeCloseTo(0.162, 10);
    expect(curve[2].putIv).toBeCloseTo(0.168, 10);
  });

  it("skew at +2% moneyness: OTM IV − ATM IV (the average) in vol points", () => {
    const atm = atmIvForChain(chain, 24000);
    // ATM IV = (call 0.12 + put 0.138) / 2 = 0.129 (the spec's ATM IV figure).
    expect(atm.atmIv).toBeCloseTo(0.129, 10);
    const skew = skewAtMoneyness(ivCurve(chain, 24000), atm, 2);
    expect(skew.strike).toBe(24500); // exactly +2.0833% → nearest to +2%
    expect(skew.callSkewVolPoints).toBeCloseTo((0.144 - 0.129) / 0.01, 8); // +1.5 vol pts
    expect(skew.putSkewVolPoints).toBeCloseTo((0.132 - 0.129) / 0.01, 8); // +0.3 vol pts
    expect(skew.available).toBe(true);
  });

  it("ivSkew exposes call skew at +2% and put skew at −2% vs ATM", () => {
    const atm = atmIvForChain(chain, 24000);
    const skew = ivSkew(ivCurve(chain, 24000), atm);
    expect(skew.call.moneynessPct).toBe(2);
    expect(skew.put.moneynessPct).toBe(-2);
    expect(skew.put.strike).toBe(24000); // −2% moneyness → nearest is the ATM strike here
    expect(skew.atm.iv).toBeCloseTo(0.129, 10); // (0.12 + 0.138) / 2
  });
});

// ---- Section: term structure -----------------------------------------------

describe("IV term structure", () => {
  const cache = {
    "2026-08-20": makeChain([[25000, 13.8, 13.8]]),
    "2026-08-27": makeChain([[25000, 14.6, 14.6]]),
    "2026-09-03": makeChain([[25000, 15.2, 15.2]]),
  };

  it("builds one entry per expiry with its OWN chain's ATM IV", () => {
    const ts = ivTermStructure(cache, 25000, VALUATION);
    expect(ts).toHaveLength(3);
    expect(ts[0].expiry).toBe("2026-08-20");
    expect(ts[0].atmIv).toBeCloseTo(0.138, 10);
    expect(ts[1].atmIv).toBeCloseTo(0.146, 10);
    expect(ts[2].atmIv).toBeCloseTo(0.152, 10);
    expect(ts.every((t) => t.available)).toBe(true);
  });

  it("each expiry uses its own chain (never the selected expiry's)", () => {
    // 2026-08-27 has a different ATM IV than 2026-08-20; both are present.
    const ts = ivTermStructure(cache, 25000, VALUATION);
    expect(ts[1].atmCallIv).toBeCloseTo(0.146, 10);
    expect(ts[1].atmPutIv).toBeCloseTo(0.146, 10);
  });

  it("computes correct days to expiry (4 / 11 / 18 from 2026-08-16)", () => {
    const ts = ivTermStructure(cache, 25000, VALUATION);
    expect(ts.map((t) => t.daysToExpiry)).toEqual([4, 11, 18]);
  });

  it("slope = IV change per day in vol points (14.6% − 13.8% over 7 days → +0.114/day)", () => {
    const slope = termStructureSlope(ivTermStructure(cache, 25000, VALUATION));
    expect(slope).not.toBeNull();
    const segment = slope[0];
    expect(segment.ivChangeVolPoints).toBeCloseTo(0.8, 8);
    expect(segment.days).toBe(7);
    expect(segment.volPointsPerDay).toBeCloseTo(0.8 / 7, 8);
  });

  it("slope is null when fewer than two comparable expiries exist", () => {
    expect(termStructureSlope([])).toBeNull();
    const single = ivTermStructure({ "2026-08-20": cache["2026-08-20"] }, 25000, VALUATION);
    expect(termStructureSlope(single)).toBeNull();
  });
});

// ---- Section: IV change ----------------------------------------------------

describe("IV change", () => {
  it("absolute vol-point change: 18.2% → 19.0% is +0.8 vol points", () => {
    const c = calculateIvChange(0.182, 0.19);
    expect(c.ivChange).toBeCloseTo(0.008, 10);
    expect(c.ivChangeVolPoints).toBeCloseTo(0.8, 10);
    expect(c.available).toBe(true);
  });

  it("relative change is separate: +4.40% (never confused with vol points)", () => {
    const c = calculateIvChange(0.182, 0.19);
    expect(c.ivChangePercent).toBeCloseTo((0.008 / 0.182) * 100, 8);
    expect(c.ivChangePercent).not.toBeCloseTo(c.ivChangeVolPoints, 2);
  });

  it("missing previous observation → all null, never a fabricated change", () => {
    const c = calculateIvChange(null, 0.19);
    expect(c.ivChange).toBeNull();
    expect(c.ivChangeVolPoints).toBeNull();
    expect(c.ivChangePercent).toBeNull();
    expect(c.available).toBe(false);
    expect(calculateIvChange(0.182, null).ivChangeVolPoints).toBeNull();
  });
});

// ---- Section: historical IV foundation -------------------------------------

describe("guarded historical IV functions", () => {
  it("empty history → null (never a fabricated 0%)", () => {
    expect(calculateIvRank([], 0.2)).toBeNull();
    expect(calculateIvPercentile([], 0.2)).toBeNull();
  });

  it("insufficient history → null", () => {
    const small = Array.from({ length: MIN_IV_HISTORY - 1 }, (_, i) => 0.1 + i * 0.001);
    expect(calculateIvRank(small, 0.2)).toBeNull();
    expect(calculateIvPercentile(small, 0.2)).toBeNull();
  });

  it("valid history yields a rank/percentile", () => {
    const history = Array.from({ length: MIN_IV_HISTORY }, (_, i) => 0.1 + i * 0.002); // 0.100..0.158
    const rank = calculateIvRank(history, 0.13);
    expect(rank).not.toBeNull();
    expect(rank).toBeGreaterThan(0);
    expect(rank).toBeLessThanOrEqual(1);
    const pct = calculateIvPercentile(history, 0.13);
    expect(pct).not.toBeNull();
    expect(pct).toBeGreaterThan(0);
    expect(pct).toBeLessThan(100);
  });

  it("current value exactly at min/max is exact, not invented", () => {
    const history = Array.from({ length: MIN_IV_HISTORY }, (_, i) => 0.1 + i * 0.002);
    const min = Math.min(...history);
    const max = Math.max(...history);
    expect(calculateIvRank(history, min)).toBeCloseTo(1 / history.length, 10);
    expect(calculateIvPercentile(history, min)).toBe(0); // nothing strictly below
    expect(calculateIvRank(history, max)).toBe(1);
    expect(calculateIvPercentile(history, max)).toBeCloseTo(((history.length - 1) / history.length) * 100, 10);
  });

  it("duplicate timestamps / values are handled without invention", () => {
    const obsA = makeIvObservation({ timestamp: "2026-08-16T09:00:00Z", symbol: "NIFTY", expiry: "2026-08-20", strike: 25000, optionType: "call", iv: 18.24, spot: 25000, source: "upstox" });
    const obsB = makeIvObservation({ timestamp: "2026-08-16T09:00:00Z", symbol: "NIFTY", expiry: "2026-08-20", strike: 25000, optionType: "call", iv: 18.5, spot: 25010, source: "upstox" });
    expect(obsA).not.toBeNull();
    expect(obsB).not.toBeNull();
    expect(obsA.iv).toBeCloseTo(0.1824, 10); // stored canonical decimal
    expect(obsB.timestamp).toBe(obsA.timestamp); // same timestamp allowed at model level
    const values = [obsA.iv, obsB.iv, ...Array.from({ length: MIN_IV_HISTORY - 2 }, (_, i) => 0.15 + i * 0.001)];
    const pct = calculateIvPercentile(values, 0.185);
    expect(pct).not.toBeNull();
  });

  it("makeIvObservation rejects invalid IV and invalid identity", () => {
    expect(makeIvObservation({ symbol: "NIFTY", expiry: "2026-08-20", strike: 25000, optionType: "call", iv: -1 })).toBeNull();
    expect(makeIvObservation({ symbol: "NIFTY", expiry: "2026-08-20", strike: 25000, optionType: "call", iv: null })).toBeNull();
    expect(makeIvObservation({ symbol: "NIFTY", expiry: "2026-08-20", strike: 25000, optionType: "straddle", iv: 18 })).toBeNull();
    expect(makeIvObservation({ symbol: "NIFTY", expiry: "2026-08-20", strike: null, optionType: "call", iv: 18 })).toBeNull();
  });
});

// ---- Section: scenario integration -----------------------------------------

describe("scenario IV integration (canonical decimal everywhere)", () => {
  const ctx = (chainCache) => ({
    spot: 25000,
    valuationDate: VALUATION,
    interestRate: 0,
    dividendYield: 0,
    lotSize: 1,
    multiplier: 1,
    chainCache,
  });
  const leg = (overrides = {}) => ({
    id: "l1",
    type: "call",
    action: "buy",
    strike: 25000,
    expiry: "2026-08-20",
    qty: 1,
    price: 200,
    ...overrides,
  });

  it("base IV is normalized from the chain: 18.24% → 0.1824", () => {
    const res = calculateScenario([leg()], ctx({ "2026-08-20": makeChain([[25000, 18.24, 18.81]]) }), {});
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.1824, 10);
  });

  it("a vol-point shift moves the canonical decimal: +2 vol points → 0.2024", () => {
    const res = calculateScenario([leg()], ctx({ "2026-08-20": makeChain([[25000, 18.24, 18.81]]) }), { ivShift: 0.02 });
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.2024, 10);
  });

  it("no double conversion: the chain is normalized once, the shift is canonical vol points", () => {
    // Chain iv 18.24% is normalized ONCE to 0.1824. A +2 vol-point shift is
    // exactly volPointsToDecimal(2) = 0.02. Adding it must give 0.2024 — the
    // shift is never re-scaled (×100 → 2.1824) and the base is never treated
    // as an unnormalized percent.
    expect(volPointsToDecimal(2)).toBeCloseTo(0.02, 12);
    const res = calculateScenario([leg()], ctx({ "2026-08-20": makeChain([[25000, 18.24, 18.81]]) }), { ivShift: 0.02 });
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.2024, 10);
    expect(res.legs[0].scenarioIv).not.toBeCloseTo(2.1824, 6);
    expect(res.legs[0].scenarioIv).not.toBeCloseTo(0.1841, 6); // not 0.1824 + 0.02/100
  });

  it("an absolute canonical IV override applies directly (no re-normalization)", () => {
    const res = calculateScenario([leg()], ctx({ "2026-08-20": makeChain([[25000, 18.24, 18.81]]) }), { iv: 0.3 });
    expect(res.legs[0].scenarioIv).toBeCloseTo(0.3, 10);
  });
});

// ---- Section: authoritative entry ------------------------------------------

describe("calculateIvAnalytics", () => {
  it("returns ATM, curve, skew, term structure and per-leg rows in one call", () => {
    const cache = {
      "2026-08-20": makeChain([[24900, 16.0, 16.4], [25000, 18.0, 18.4], [25100, 19.0, 19.2]]),
      "2026-08-27": makeChain([[25000, 18.8, 19.0]]),
    };
    const sampleLeg = {
      id: "l1",
      type: "call",
      action: "buy",
      strike: 25000,
      expiry: "2026-08-20",
      qty: 1,
      price: 200,
    };
    const a = calculateIvAnalytics({ chainCache: cache, spot: 25000, valuationDate: VALUATION, selectedExpiry: "2026-08-20", legs: [sampleLeg] });
    expect(a.atm.atmStrike).toBe(25000);
    expect(a.atm.status).toBe("available");
    expect(a.curve).toHaveLength(3);
    expect(a.skew.call.moneynessPct).toBe(2);
    expect(a.termStructure).toHaveLength(2);
    expect(a.perLeg[0].liveIv).toBeCloseTo(0.18, 10);
    expect(a.perLeg[0].ivAvailable).toBe(true);
    expect(a.warnings).toEqual([]);
  });

  it("warns MISSING_CHAIN_DATA for an unloaded selected expiry", () => {
    const a = calculateIvAnalytics({ chainCache: {}, spot: 25000, valuationDate: VALUATION, selectedExpiry: "2026-08-20" });
    expect(a.warnings.some((w) => w.code === "MISSING_CHAIN_DATA")).toBe(true);
    expect(a.atm.status).toBe("unavailable");
  });
});
