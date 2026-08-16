import { describe, it, expect } from "vitest";
import {
  OBSERVATION_METRICS,
  GREEK_METRICS,
  makeObservation,
  observationFromChainRow,
  observationKey,
  sameObservation,
  observationDataQuality,
  dataQuality,
  absoluteChange,
  percentChange,
  volPointChange,
  difference,
  ratio,
  change,
  directionOfChange,
  normalizedMagnitude,
  pairwiseComparison,
  cePeComparison,
  cePeComparisons,
  priceIvRelationship,
  greekPriceRelationship,
  crossMetricSnapshot,
  pearsonCorrelation,
  vixAnalytics,
  condition,
  strengthAndConfidence,
  calculateMarketAnalytics,
} from "./marketAnalytics";
import { MIN_STAT_SAMPLE } from "./statistics";
import { normalizeIv } from "./ivAnalytics";

// Chain-side fixture uses the REAL broker convention: iv is PERCENT.
const SIDE = { ltp: 100, iv: 18.24, delta: 0.5, gamma: 0.002, theta: -1.5, vega: 2, oi: 1000, volume: 500 };

function obs(overrides = {}) {
  return makeObservation({
    timestamp: "2026-08-16T10:00:00Z",
    symbol: "NIFTY",
    expiry: "2026-08-27",
    strike: 24350,
    spot: 24372,
    call: SIDE,
    put: { ...SIDE, delta: -0.5 },
    ...overrides,
  });
}

// ---- Basic changes -------------------------------------------------------------

describe("change helpers", () => {
  it("absolute change", () => {
    expect(absoluteChange(10, 4)).toBe(6);
  });

  it("percentage change", () => {
    expect(percentChange(12, 10)).toBeCloseTo(20, 10);
  });

  it("vol-point change on canonical decimals (0.19 vs 0.1824 → +0.76 vol pts)", () => {
    expect(volPointChange(0.19, 0.1824)).toBeCloseTo(0.76, 10);
  });

  it("direction: up / down / flat / unavailable", () => {
    expect(directionOfChange(11, 10)).toBe("up");
    expect(directionOfChange(9, 10)).toBe("down");
    expect(directionOfChange(10, 10)).toBe("flat");
    expect(directionOfChange(null, 10)).toBe("unavailable");
    expect(directionOfChange(10, undefined)).toBe("unavailable");
  });

  it("flat uses a tiny epsilon, not strict equality", () => {
    expect(directionOfChange(10 + 1e-12, 10)).toBe("flat");
  });

  it("invalid inputs → null everywhere (no NaN/Infinity)", () => {
    expect(absoluteChange(null, 5)).toBeNull();
    expect(absoluteChange(5, NaN)).toBeNull();
    expect(percentChange(null, 5)).toBeNull();
    expect(volPointChange(undefined, 0.1)).toBeNull();
    expect(difference(Infinity, 5)).toBeNull();
    expect(ratio(5, Infinity)).toBeNull();
    expect(change(NaN, 5).available).toBe(false);
  });

  it("zero denominator → null (not Infinity)", () => {
    expect(percentChange(5, 0)).toBeNull();
    expect(ratio(5, 0)).toBeNull();
  });

  it("normalizedMagnitude is deterministic, 0 for flat, null on missing", () => {
    expect(normalizedMagnitude(10, 10)).toBe(0);
    // |change| / (|previous| + |change|) = 10 / (10 + 10) = 0.5
    expect(normalizedMagnitude(20, 10)).toBeCloseTo(0.5, 10);
    expect(normalizedMagnitude(null, 10)).toBeNull();
    expect(normalizedMagnitude(0, 0)).toBe(0);
  });
});

// ---- Observation model -----------------------------------------------------------

describe("observation model", () => {
  it("normalizes broker side fields to canonical units", () => {
    const o = obs();
    expect(o.call.price).toBe(100);
    expect(o.call.iv).toBeCloseTo(0.1824, 10); // 18.24% → canonical decimal
    expect(o.call.delta).toBe(0.5);
    expect(o.call.thetaPerDay).toBe(-1.5);
    expect(o.call.vegaPerVolPoint).toBe(2);
    expect(o.call.oi).toBe(1000);
    expect(o.call.volume).toBe(500);
  });

  it("0 is a valid zero, null is unavailable — never conflated", () => {
    const o = makeObservation({
      symbol: "NIFTY",
      expiry: "2026-08-27",
      strike: 24350,
      call: { ...SIDE, ltp: 0, oi: 0, volume: 0 },
      put: { ltp: null },
    });
    expect(o.call.price).toBe(0);
    expect(o.call.oi).toBe(0);
    expect(o.put.price).toBeNull();
  });

  it("observationFromChainRow maps a backend chain row", () => {
    const row = { strike: 24350, call: SIDE, put: { ...SIDE, delta: -0.5 } };
    const o = observationFromChainRow({ symbol: "NIFTY", expiry: "2026-08-27", row, spot: 24372 });
    expect(o.strike).toBe(24350);
    expect(o.call.iv).toBeCloseTo(0.1824, 10);
    expect(o.spot).toBe(24372);
  });

  it("identity = symbol + expiry + strike", () => {
    const a = obs();
    const b = obs({ strike: 24400 });
    expect(observationKey(a)).toBe("NIFTY|2026-08-27|24350");
    expect(sameObservation(a, obs())).toBe(true);
    expect(sameObservation(a, b)).toBe(false);
    expect(sameObservation(a, null)).toBe(false);
  });
});

// ---- CE/PE comparison ---------------------------------------------------------------

describe("CE vs PE comparison", () => {
  it("difference and absolute difference", () => {
    const o = obs(); // call iv 18.24%, put iv 18.24% → 0 difference; use iv override
    const cmp = cePeComparison(makeObservation({ ...o, call: { ...SIDE, iv: 18.24 }, put: { ...SIDE, iv: 20.1 } }), "iv");
    expect(cmp.ce).toBeCloseTo(0.1824, 10);
    expect(cmp.pe).toBeCloseTo(0.201, 10);
    expect(cmp.difference).toBeCloseTo(-0.0186, 10);
    expect(cmp.absoluteDifference).toBeCloseTo(0.0186, 10);
  });

  it("ratio and relative difference", () => {
    const o = makeObservation({
      symbol: "NIFTY", expiry: "2026-08-27", strike: 24350,
      call: { ...SIDE, oi: 2000 }, put: { ...SIDE, oi: 1000 },
    });
    const cmp = cePeComparison(o, "oi");
    expect(cmp.ratio).toBe(2);
    expect(cmp.relativeDifference).toBe(100);
  });

  it("normalized asymmetry: abs(A−B) / max(abs(A), abs(B))", () => {
    const o = makeObservation({
      symbol: "NIFTY", expiry: "2026-08-27", strike: 24350,
      call: { ...SIDE, volume: 300 }, put: { ...SIDE, volume: 100 },
    });
    const cmp = cePeComparison(o, "volume");
    expect(cmp.normalizedDifference).toBeCloseTo(2 / 3, 10);
  });

  it("zero denominator → ratio null (no Infinity)", () => {
    const o = makeObservation({
      symbol: "NIFTY", expiry: "2026-08-27", strike: 24350,
      call: { ...SIDE, oi: 0 }, put: { ...SIDE, oi: 0 },
    });
    const cmp = cePeComparison(o, "oi");
    expect(cmp.ratio).toBeNull();
    expect(cmp.dominantSide).toBe("equal");
  });

  it("dominant side is purely numeric (no bullish/bearish)", () => {
    const o = makeObservation({
      symbol: "NIFTY", expiry: "2026-08-27", strike: 24350,
      call: { ...SIDE, delta: 0.6 }, put: { ...SIDE, delta: -0.4 },
    });
    const cmp = cePeComparison(o, "delta");
    expect(cmp.dominantSide).toBe("first"); // 0.6 > -0.4 — numeric only
    const ivCmp = cePeComparison(o, "iv");
    expect(ivCmp.dominantSide).toBe("equal");
  });

  it("covers every canonical metric", () => {
    const o = obs();
    const all = cePeComparisons(o);
    expect(all.map((c) => c.metric)).toEqual(OBSERVATION_METRICS);
  });
});

// ---- Relationships -------------------------------------------------------------------

function pairObs(prevOverrides, currOverrides) {
  return { current: obs(currOverrides), previous: obs(prevOverrides) };
}

describe("price/IV relationship", () => {
  it("same direction when price and IV both move up", () => {
    const { current, previous } = pairObs(
      { call: { ...SIDE, ltp: 100, iv: 18 }, put: { ...SIDE, ltp: 100, iv: 18 } },
      { call: { ...SIDE, ltp: 110, iv: 19 }, put: { ...SIDE, ltp: 110, iv: 19 } }
    );
    const rel = priceIvRelationship(current, previous);
    expect(rel.priceDirection).toBe("up");
    expect(rel.ivDirection).toBe("up");
    expect(rel.sameDirection).toBe(true);
    expect(rel.oppositeDirection).toBe(false);
    expect(rel.priceChange).toBe(10);
    expect(rel.ivChangeVolPoints).toBeCloseTo(1, 10);
  });

  it("opposite direction when price rises and IV falls", () => {
    const { current, previous } = pairObs(
      { call: { ...SIDE, ltp: 100, iv: 19 }, put: { ...SIDE, ltp: 100, iv: 19 } },
      { call: { ...SIDE, ltp: 105, iv: 18 }, put: { ...SIDE, ltp: 105, iv: 18 } }
    );
    const rel = priceIvRelationship(current, previous);
    expect(rel.priceDirection).toBe("up");
    expect(rel.ivDirection).toBe("down");
    expect(rel.sameDirection).toBe(false);
    expect(rel.oppositeDirection).toBe(true);
  });

  it("unavailable when either observation is missing or identity differs", () => {
    const { current, previous } = pairObs({}, {});
    const rel = priceIvRelationship(current, null);
    expect(rel.aligned).toBe(false);
    const mismatched = priceIvRelationship(obs({ strike: 24400 }), previous);
    expect(mismatched.aligned).toBe(false);
    expect(mismatched.priceDirection).toBe("unavailable");
  });
});

describe("price/Greek relationships", () => {
  it("price vs delta", () => {
    const { current, previous } = pairObs(
      { call: { ...SIDE, ltp: 100, delta: 0.5 }, put: { ...SIDE, ltp: 100, delta: -0.5 } },
      { call: { ...SIDE, ltp: 108, delta: 0.55 }, put: { ...SIDE, ltp: 108, delta: -0.45 } }
    );
    const rel = greekPriceRelationship(current, previous, "delta");
    expect(rel.priceDirection).toBe("up");
    expect(rel.metricDirection).toBe("up");
    expect(rel.sameDirection).toBe(true);
    expect(rel.metricChange).toBeCloseTo(0.05, 10);
  });

  it("price vs gamma", () => {
    const { current, previous } = pairObs(
      { call: { ...SIDE, ltp: 100, gamma: 0.002 }, put: { ...SIDE, ltp: 100, gamma: 0.002 } },
      { call: { ...SIDE, ltp: 95, gamma: 0.003 }, put: { ...SIDE, ltp: 95, gamma: 0.003 } }
    );
    const rel = greekPriceRelationship(current, previous, "gamma");
    expect(rel.priceDirection).toBe("down");
    expect(rel.metricDirection).toBe("up");
    expect(rel.oppositeDirection).toBe(true);
  });

  it("price vs vega", () => {
    const { current, previous } = pairObs(
      { call: { ...SIDE, ltp: 100, vega: 2 }, put: { ...SIDE, ltp: 100, vega: 2 } },
      { call: { ...SIDE, ltp: 100, vega: 2.2 }, put: { ...SIDE, ltp: 100, vega: 2.2 } }
    );
    const rel = greekPriceRelationship(current, previous, "vegaPerVolPoint");
    expect(rel.priceDirection).toBe("flat");
    expect(rel.metricDirection).toBe("up");
    expect(rel.metricChange).toBeCloseTo(0.2, 10);
  });

  it("crossMetricSnapshot is a neutral data snapshot", () => {
    const { current, previous } = pairObs({}, {});
    const snap = crossMetricSnapshot(current, previous);
    expect(snap.aligned).toBe(true);
    expect(typeof snap.ivChangeVolPoints).toBe("number");
    expect(Object.keys(snap)).toEqual(
      expect.arrayContaining(["priceChange", "ivChangeVolPoints", "deltaChange", "gammaChange", "thetaChange", "vegaChange"])
    );
  });
});

// ---- Correlation -----------------------------------------------------------------------

describe("Pearson correlation", () => {
  it("positive correlation ≈ 1 for aligned series", () => {
    const x = [1, 2, 3, 4, 5];
    const y = [2, 4, 6, 8, 10];
    expect(pearsonCorrelation(x, y)).toBeCloseTo(1, 10);
  });

  it("negative correlation ≈ −1 for inversely aligned series", () => {
    const x = [1, 2, 3, 4, 5];
    const y = [10, 8, 6, 4, 2];
    expect(pearsonCorrelation(x, y)).toBeCloseTo(-1, 10);
  });

  it("zero-variance series → null (never NaN/Infinity)", () => {
    expect(pearsonCorrelation([5, 5, 5, 5, 5], [1, 2, 3, 4, 5])).toBeNull();
    expect(pearsonCorrelation([1, 2, 3, 4, 5], [5, 5, 5, 5, 5])).toBeNull();
  });

  it("insufficient observations → null", () => {
    expect(pearsonCorrelation([1, 2], [2, 4])).toBeNull();
    expect(pearsonCorrelation([], [])).toBeNull();
  });

  it("unequal lengths → null (timestamps not aligned)", () => {
    expect(pearsonCorrelation([1, 2, 3], [1, 2])).toBeNull();
  });
});

// ---- Data quality ------------------------------------------------------------------------

describe("data quality", () => {
  it("complete", () => {
    expect(dataQuality(4, 4).status).toBe("available");
  });

  it("partial", () => {
    const q = dataQuality(7, 10);
    expect(q.status).toBe("partial");
    expect(q.availableCount).toBe(7);
    expect(q.expectedCount).toBe(10);
  });

  it("unavailable", () => {
    expect(dataQuality(0, 10).status).toBe("unavailable");
    expect(observationDataQuality(null).status).toBe("unavailable");
  });

  it("observationDataQuality reflects partial fields", () => {
    const o = makeObservation({
      symbol: "NIFTY", expiry: "2026-08-27", strike: 24350,
      call: { ltp: 100, iv: 18 },
      put: {},
    });
    const q = observationDataQuality(o);
    expect(q.status).toBe("partial");
    expect(q.availableCount).toBe(2);
  });
});

// ---- Multi-expiry isolation ---------------------------------------------------------------

describe("multi-expiry safety", () => {
  it("same expiry + strike observations compare normally", () => {
    const { current, previous } = pairObs({}, {});
    const rel = priceIvRelationship(current, previous);
    expect(rel.aligned).toBe(true);
  });

  it("different expiry remains separate (comparisons unavailable)", () => {
    const { current, previous } = pairObs({}, {});
    const other = obs({ expiry: "2026-09-24" });
    expect(sameObservation(current, other)).toBe(false);
    expect(priceIvRelationship(current, other).aligned).toBe(false);
    expect(greekPriceRelationship(current, other, "delta").aligned).toBe(false);
  });

  it("no accidental primary-expiry substitution in calculateMarketAnalytics", () => {
    const result = calculateMarketAnalytics({
      current: obs({ expiry: "2026-08-27" }),
      previous: obs({ expiry: "2026-09-24" }),
    });
    expect(result.relationships.priceIv.aligned).toBe(false);
    expect(result.price.current).not.toBeNull();
    expect(result.price.previous).not.toBeNull();
    expect(result.warnings.some((w) => w.code === "OBSERVATION_MISMATCH")).toBe(true);
  });
});

// ---- VIX ------------------------------------------------------------------------------------

describe("VIX handling", () => {
  it("VIX available → measurements computed", () => {
    const v = vixAnalytics(13.5, [12, 12.5, 13, 12.8, 13.2, 13.4, 13.1, 13.3]);
    expect(v.status).toBe("available");
    expect(v.current).toBe(13.5);
    expect(v.change).toBeCloseTo(0.2, 10);
  });

  it("VIX unavailable → status unavailable", () => {
    const v = vixAnalytics(null);
    expect(v.status).toBe("unavailable");
    expect(v.current).toBeNull();
    expect(v.zScore).toBeNull();
  });

  it("no IV→VIX substitution: ATM IV never fills a missing VIX", () => {
    // A fully populated chain observation (with ATM IV) still yields an
    // unavailable VIX result — IV is never substituted for VIX.
    const o = obs();
    const v = vixAnalytics(o.call.iv);
    expect(v.status).toBe("available"); // explicit VIX value supplied
    // but when NO VIX value is supplied, the rich observation does not help:
    const v2 = vixAnalytics(null);
    expect(v2.status).toBe("unavailable");
    expect(v2.current).toBeNull();
  });

  it("z-score/percentile require MIN_STAT_SAMPLE history", () => {
    const v = vixAnalytics(13.5, [12, 13]); // tiny history
    expect(v.status).toBe("partial");
    expect(v.zScore).toBeNull();
    expect(v.percentileRank).toBeNull();
  });
});

// ---- Condition framework ---------------------------------------------------------------------

describe("neutral condition framework", () => {
  it("condition is a neutral fact, not advice", () => {
    const c = condition({
      id: "iv_change",
      detected: true,
      magnitude: 73,
      evidence: { current: 0.21, previous: 0.19, changeVolPoints: 2 },
    });
    expect(c.id).toBe("iv_change");
    expect(c.detected).toBe(true);
    expect(c.magnitude).toBe(73);
    expect(c.evidence.changeVolPoints).toBe(2);
    // No direction, no bullish/bearish, no buy/sell anywhere in the shape.
    expect(Object.keys(c).sort()).toEqual(["detected", "evidence", "id", "magnitude", "status"]);
  });

  it("strength and confidence stay strictly separate", () => {
    const sc = strengthAndConfidence({ magnitude: 82, availableCount: 8, expectedCount: 10 });
    expect(sc.strength).toBe(82); // size of the measured effect
    expect(sc.confidence).toBe(80); // data completeness
    // Both are documented as NOT probabilities; the shape carries no such claim.
  });
});

// ---- Authoritative result --------------------------------------------------------------------

describe("calculateMarketAnalytics", () => {
  it("produces the generic result structure with warnings", () => {
    const result = calculateMarketAnalytics({ current: obs(), previous: obs({}), history: [] });
    expect(result.identity).toEqual({ symbol: "NIFTY", expiry: "2026-08-27", strike: 24350 });
    expect(result.cePe.length).toBe(OBSERVATION_METRICS.length);
    GREEK_METRICS.forEach((m) => {
      expect(result.greeks[m]).toBeDefined();
      expect(result.relationships.greek[m]).toBeDefined();
    });
    expect(result.vix.status).toBe("unavailable");
    expect(Array.isArray(result.warnings)).toBe(true);
  });

  it("IV z-score/percentile are null without sufficient history (never fabricated)", () => {
    const result = calculateMarketAnalytics({ current: obs(), previous: obs({}), history: [] });
    expect(result.iv.zScore).toBeNull();
    expect(result.iv.percentileRank).toBeNull();
    expect(result.statistics.ivAnomaly.status).toBe("unavailable");
  });

  it("IV analytics populate with a real history", () => {
    const hist = Array.from({ length: MIN_STAT_SAMPLE }, (_, i) =>
      makeObservation({
        symbol: "NIFTY", expiry: "2026-08-27", strike: 24350,
        call: { ...SIDE, iv: 17 + i * 0.5 }, put: { ...SIDE, iv: 17 + i * 0.5 },
      })
    );
    const result = calculateMarketAnalytics({ current: obs(), previous: obs({}), history: hist });
    expect(result.iv.rollingMean).not.toBeNull();
    expect(result.iv.zScore).not.toBeNull();
    expect(result.iv.percentileRank).not.toBeNull();
    expect(result.iv.anomaly.magnitude).not.toBeNull();
  });

  it("canonical IV flows are not double-converted", () => {
    // makeObservation normalizes broker percent (18.24 → 0.1824) exactly once.
    const o = obs();
    expect(o.call.iv).toBeCloseTo(normalizeIv(18.24), 12);
    // And the canonical decimal is what the analytics layer compares.
    const result = calculateMarketAnalytics({ current: o, previous: obs({}) });
    expect(result.iv.current).toBeCloseTo(0.1824, 10);
  });
});
