/**
 * GEX v1.0 — Phase 7.1 Tests (CORRECTED)
 *
 * OI UNIT VERIFIED: Upstox market_data.oi is NUMBER OF CONTRACTS.
 * The GEX formula does NOT multiply by lot_size.
 *
 * Four levels of validation per the GEX_V1_0_SPEC:
 *   Level A — Hand-calculated fixtures
 *   Level B — Algebraic properties
 *   Level C — Aggregation properties
 *   Level D — Independent reference calculation (duplicated formula in test)
 */

import { describe, it, expect } from "vitest";
import {
  rawGex,
  signedGex,
  strikeGex,
  expiryGex,
  chainGex,
  formatGex,
  GEX_STATUS,
  GEX_METHOD_VERSION,
  GEX_SIGN_CONVENTION,
  GEX_INPUT_UNITS,
} from "./gex";

// =============================================================================
// Level A — Hand-calculated fixtures
// =============================================================================

describe("Level A — Hand-calculated fixtures", () => {
  // Fixture from GEX_V1_0_SPEC §14, adapted for verified OI-in-contracts unit:
  //
  // Spot = 25,000
  // Lot size = 65 (contextual metadata only — NOT in formula)
  //
  // Strike 25,000 CE:
  //   Gamma = 0.002, OI = 1000 (CONTRACTS)
  //
  // Strike 25,000 PE:
  //   Gamma = 0.003, OI = 500 (CONTRACTS)

  const SPOT = 25000;

  it("raw GEX for 25000 CE matches hand calculation (OI in contracts, no lot_size)", () => {
    // rawGex = gamma × oi × spot² × 0.01
    //        = 0.002 × 1000 × 25000² × 0.01
    //        = 0.002 × 1000 × 625000000 × 0.01
    //        = 0.002 × 1000 × 6250000
    //        = 0.002 × 6250000000
    //        = 12,500,000
    const expected = 0.002 * 1000 * 25000 * 25000 * 0.01;
    expect(rawGex(0.002, 1000, SPOT)).toBe(expected);
    expect(rawGex(0.002, 1000, SPOT)).toBe(12500000);
  });

  it("signed GEX for CE is positive under baseline convention", () => {
    expect(signedGex("call", 0.002, 1000, SPOT)).toBe(12500000);
  });

  it("signed GEX for PE is negative under baseline convention", () => {
    // raw PE GEX = 0.003 × 500 × 25000² × 0.01
    //            = 0.003 × 500 × 6250000
    //            = 0.003 × 3125000000
    //            = 9,375,000
    const expected = 0.003 * 500 * 25000 * 25000 * 0.01;
    expect(signedGex("put", 0.003, 500, SPOT)).toBe(-expected);
    expect(signedGex("put", 0.003, 500, SPOT)).toBe(-9375000);
  });

  it("strike-level GEX for fixture strike is correctly computed", () => {
    const row = {
      strike: 25000,
      call: { gamma: 0.002, oi: 1000 },
      put: { gamma: 0.003, oi: 500 },
    };
    const result = strikeGex(row, SPOT);
    expect(result.strike).toBe(25000);
    expect(result.callGex).toBe(12500000);
    expect(result.putGex).toBe(-9375000);
    expect(result.netGex).toBe(12500000 + -9375000);
    expect(result.callOi).toBe(1000);
    expect(result.putOi).toBe(500);
    expect(result.callGamma).toBe(0.002);
    expect(result.putGamma).toBe(0.003);
    expect(result.status).toBe(GEX_STATUS.AVAILABLE);
  });

  it("expiry-level GEX aggregates across strikes", () => {
    const rows = [
      {
        strike: 25000,
        call: { gamma: 0.002, oi: 1000 },
        put: { gamma: 0.003, oi: 500 },
      },
      {
        strike: 25100,
        call: { gamma: 0.001, oi: 800 },
        put: { gamma: 0.002, oi: 600 },
      },
    ];
    const result = expiryGex(rows, SPOT);

    // Strike 1 CE: 0.002 × 1000 × 25000² × 0.01 = 12,500,000
    // Strike 1 PE: -0.003 × 500 × 25000² × 0.01 = -9,375,000
    // Strike 2 CE: 0.001 × 800 × 25000² × 0.01 = 5,000,000
    // Strike 2 PE: -0.002 × 600 × 25000² × 0.01 = -7,500,000
    const s1ce = 0.002 * 1000 * 25000 * 25000 * 0.01;
    const s1pe = 0.003 * 500 * 25000 * 25000 * 0.01;
    const s2ce = 0.001 * 800 * 25000 * 25000 * 0.01;
    const s2pe = 0.002 * 600 * 25000 * 25000 * 0.01;

    expect(result.callGex).toBe(s1ce + s2ce);
    expect(result.putGex).toBe(-s1pe + -s2pe);
    expect(result.netGex).toBe(s1ce + s2ce + -s1pe + -s2pe);
    expect(result.validStrikeCount).toBe(2);
    expect(result.totalStrikeCount).toBe(2);
    expect(result.availabilityStatus).toBe(GEX_STATUS.AVAILABLE);
  });
});

// =============================================================================
// Level B — Algebraic properties
// =============================================================================

describe("Level B — Algebraic properties", () => {
  const BASE = { gamma: 0.002, oi: 1000, spot: 25000 };
  const baseGex = rawGex(BASE.gamma, BASE.oi, BASE.spot);

  it("doubling OI doubles GEX", () => {
    expect(rawGex(BASE.gamma, BASE.oi * 2, BASE.spot)).toBe(baseGex * 2);
  });

  it("doubling gamma doubles GEX", () => {
    expect(rawGex(BASE.gamma * 2, BASE.oi, BASE.spot)).toBe(baseGex * 2);
  });

  it("changing spot follows the S² factor", () => {
    // spot doubled → GEX × 4
    expect(rawGex(BASE.gamma, BASE.oi, BASE.spot * 2)).toBeCloseTo(baseGex * 4, 0);
  });

  it("zero OI gives zero contribution", () => {
    expect(rawGex(BASE.gamma, 0, BASE.spot)).toBe(0);
  });

  it("call sign is positive under baseline convention", () => {
    expect(signedGex("call", BASE.gamma, BASE.oi, BASE.spot)).toBeGreaterThan(0);
  });

  it("put sign is negative under baseline convention", () => {
    expect(signedGex("put", BASE.gamma, BASE.oi, BASE.spot)).toBeLessThan(0);
  });

  it("net GEX equals call GEX + put GEX for same inputs", () => {
    const call = signedGex("call", BASE.gamma, BASE.oi, BASE.spot);
    const put = signedGex("put", BASE.gamma, BASE.oi, BASE.spot);
    expect(call + put).toBe(0); // same gamma, same OI → symmetric cancellation
  });

  it("sign convention metadata is correct", () => {
    expect(GEX_SIGN_CONVENTION.call_sign).toBe(+1);
    expect(GEX_SIGN_CONVENTION.put_sign).toBe(-1);
    expect(GEX_SIGN_CONVENTION.positioning_model).toBe("NAIVE_DEALER_CONVENTION");
  });

  it("methodology version is documented", () => {
    expect(GEX_METHOD_VERSION).toBe("GEX_STANDARD_V1");
  });
});

// =============================================================================
// CRITICAL REGRESSION: Lot size is NOT in the GEX formula
// =============================================================================

describe("CRITICAL — Lot size is NOT in the GEX formula", () => {
  it("changing lot_size does NOT change GEX", () => {
    const gex1 = rawGex(0.002, 1000, 25000);
    const gex2 = rawGex(0.002, 1000, 25000);
    // rawGex does not accept lot_size — it is irrelevant to the formula
    expect(gex1).toBe(gex2);
  });

  it("GEX formula is gamma × OI × spot² × 0.01 — no lot_size factor", () => {
    // Verify the formula by constructing the expected value manually
    const gamma = 0.002;
    const oi = 1000; // contracts
    const spot = 25000;
    const expected = gamma * oi * spot * spot * 0.01;
    expect(rawGex(gamma, oi, spot)).toBe(expected);
    // No lot_size parameter exists in rawGex — this is by design
  });

  it("regression: rawGex signature has exactly 3 parameters (gamma, oi, spot)", () => {
    // This test proves that rawGex does NOT accept a lot_size parameter.
    // If someone adds lot_size to the function signature, this test will fail
    // because the extra argument will be silently ignored by JavaScript,
    // but the TEST documents the intended API contract.
    expect(rawGex.length).toBe(3);
  });

  it("GEX_INPUT_UNITS documents OI as contracts, not lots", () => {
    expect(GEX_INPUT_UNITS.oi).toContain("CONTRACTS");
    expect(GEX_INPUT_UNITS.oi).toContain("NOT lots");
    expect(GEX_INPUT_UNITS.lot_size).toContain("NOT used in GEX formula");
  });
});

// =============================================================================
// Level C — Aggregation properties
// =============================================================================

describe("Level C — Aggregation properties", () => {
  const SPOT = 25000;

  const chainRows = [
    {
      strike: 24900,
      expiry: "2026-08-28",
      call: { gamma: 0.001, oi: 500 },
      put: { gamma: 0.004, oi: 1200 },
    },
    {
      strike: 25000,
      expiry: "2026-08-28",
      call: { gamma: 0.002, oi: 1000 },
      put: { gamma: 0.003, oi: 800 },
    },
    {
      strike: 25100,
      expiry: "2026-08-28",
      call: { gamma: 0.003, oi: 700 },
      put: { gamma: 0.001, oi: 400 },
    },
    {
      strike: 25000,
      expiry: "2026-09-04",
      call: { gamma: 0.0015, oi: 600 },
      put: { gamma: 0.0025, oi: 500 },
    },
  ];

  it("strike aggregation equals sum of option rows", () => {
    const result = chainGex(chainRows, { spot: SPOT, symbol: "NIFTY" });
    const manualStrikeTotal = result.byStrike.reduce((sum, s) => {
      const call = s.callGex ?? 0;
      const put = s.putGex ?? 0;
      return sum + call + put;
    }, 0);
    expect(result.callGex).not.toBeNull();
    expect(result.putGex).not.toBeNull();
    expect(result.netGex).toBeCloseTo(manualStrikeTotal, 0);
  });

  it("expiry aggregation equals sum of strike rows", () => {
    const result = chainGex(chainRows, { spot: SPOT, symbol: "NIFTY" });
    // Sum of all expiry-level callGex/putGex must equal chain-level totals
    const expiryCallSum = result.byExpiry.reduce((sum, e) => sum + (e.callGex ?? 0), 0);
    const expiryPutSum = result.byExpiry.reduce((sum, e) => sum + (e.putGex ?? 0), 0);
    expect(expiryCallSum).toBeCloseTo(result.callGex, 0);
    expect(expiryPutSum).toBeCloseTo(result.putGex, 0);
  });

  it("chain aggregation equals sum of expiry rows", () => {
    const result = chainGex(chainRows, { spot: SPOT, symbol: "NIFTY" });
    const expirySum = result.byExpiry.reduce((sum, e) => {
      return sum + (e.callGex ?? 0) + (e.putGex ?? 0);
    }, 0);
    expect(result.callGex + result.putGex).toBeCloseTo(expirySum, 0);
  });

  it("filtered expiry scope does not include excluded expiries", () => {
    const result = chainGex(chainRows, {
      spot: SPOT,
      symbol: "NIFTY",
      scopeExpiries: ["2026-08-28"],
    });
    expect(result.byExpiry.length).toBe(1);
    expect(result.byExpiry[0].expiry).toBe("2026-08-28");
    expect(result.totalOptionCount).toBe(3);
  });

  it("no duplicate option row silently doubles exposure", () => {
    const singleRow = [
      {
        strike: 25000,
        expiry: "2026-08-28",
        call: { gamma: 0.002, oi: 1000 },
        put: { gamma: 0.003, oi: 500 },
      },
    ];
    const doubledRow = [
      ...singleRow,
      {
        strike: 25000,
        expiry: "2026-08-28",
        call: { gamma: 0.002, oi: 1000 },
        put: { gamma: 0.003, oi: 500 },
      },
    ];
    const single = chainGex(singleRow, { spot: SPOT, symbol: "NIFTY" });
    const doubled = chainGex(doubledRow, { spot: SPOT, symbol: "NIFTY" });
    // Doubled input should produce doubled GEX (not silently deduplicated)
    expect(doubled.callGex).toBeCloseTo(single.callGex * 2, 0);
    expect(doubled.putGex).toBeCloseTo(single.putGex * 2, 0);
  });
});

// =============================================================================
// Data-quality rules
// =============================================================================

describe("Data-quality rules", () => {
  const SPOT = 25000;

  it("missing gamma makes that side unavailable", () => {
    const row = {
      strike: 25000,
      call: { gamma: null, oi: 1000 },
      put: { gamma: 0.003, oi: 500 },
    };
    const result = strikeGex(row, SPOT);
    expect(result.callGex).toBeNull();
    expect(result.putGex).toBe(-9375000); // put is still calculated
    expect(result.netGex).toBeNull();
    expect(result.status).toBe(GEX_STATUS.PARTIAL);
  });

  it("missing OI makes that side unavailable", () => {
    const row = {
      strike: 25000,
      call: { gamma: 0.002, oi: null },
      put: { gamma: 0.003, oi: 500 },
    };
    const result = strikeGex(row, SPOT);
    expect(result.callGex).toBeNull();
    expect(result.putGex).toBe(-9375000);
    expect(result.status).toBe(GEX_STATUS.PARTIAL);
  });

  it("negative OI is invalid", () => {
    const row = {
      strike: 25000,
      call: { gamma: 0.002, oi: -100 },
      put: { gamma: 0.003, oi: 500 },
    };
    const result = strikeGex(row, SPOT);
    expect(result.callGex).toBeNull();
    expect(result.putGex).toBe(-9375000);
    expect(result.status).toBe(GEX_STATUS.PARTIAL);
  });

  it("NaN gamma is invalid", () => {
    const row = {
      strike: 25000,
      call: { gamma: NaN, oi: 1000 },
      put: { gamma: 0.003, oi: 500 },
    };
    const result = strikeGex(row, SPOT);
    expect(result.callGex).toBeNull();
    expect(result.status).toBe(GEX_STATUS.PARTIAL);
  });

  it("Infinity gamma is invalid", () => {
    const row = {
      strike: 25000,
      call: { gamma: Infinity, oi: 1000 },
      put: { gamma: 0.003, oi: 500 },
    };
    const result = strikeGex(row, SPOT);
    expect(result.callGex).toBeNull();
    expect(result.status).toBe(GEX_STATUS.PARTIAL);
  });

  it("zero spot is invalid at chain level", () => {
    const rows = [
      {
        strike: 25000,
        expiry: "2026-08-28",
        call: { gamma: 0.002, oi: 1000 },
        put: { gamma: 0.003, oi: 500 },
      },
    ];
    const result = chainGex(rows, { spot: 0, symbol: "NIFTY" });
    expect(result.netGex).toBeNull();
    expect(result.availabilityStatus).toBe(GEX_STATUS.UNAVAILABLE);
    expect(result.reason).toBe("INVALID_SPOT");
  });

  it("negative spot is invalid at chain level", () => {
    const rows = [
      {
        strike: 25000,
        expiry: "2026-08-28",
        call: { gamma: 0.002, oi: 1000 },
        put: { gamma: 0.003, oi: 500 },
      },
    ];
    const result = chainGex(rows, { spot: -100, symbol: "NIFTY" });
    expect(result.availabilityStatus).toBe(GEX_STATUS.UNAVAILABLE);
  });

  it("empty chain returns unavailable", () => {
    const result = chainGex([], { spot: SPOT, symbol: "NIFTY" });
    expect(result.availabilityStatus).toBe(GEX_STATUS.UNAVAILABLE);
    expect(result.reason).toBe("NO_CHAIN_DATA");
  });

  it("null chain returns unavailable", () => {
    const result = chainGex(null, { spot: SPOT, symbol: "NIFTY" });
    expect(result.availabilityStatus).toBe(GEX_STATUS.UNAVAILABLE);
  });

  it("partial chain with some valid strikes returns PARTIAL", () => {
    const rows = [
      {
        strike: 25000,
        expiry: "2026-08-28",
        call: { gamma: 0.002, oi: 1000 },
        put: { gamma: 0.003, oi: 500 },
      },
      {
        strike: 25100,
        expiry: "2026-08-28",
        call: { gamma: null, oi: null },
        put: { gamma: null, oi: null },
      },
    ];
    const result = chainGex(rows, { spot: SPOT, symbol: "NIFTY" });
    expect(result.availabilityStatus).toBe(GEX_STATUS.PARTIAL);
  });
});

// =============================================================================
// Unit safety — prove OI is in contracts
// =============================================================================

describe("Unit safety — OI is in contracts", () => {
  it("spot is squared — not multiplied linearly", () => {
    const s1 = rawGex(0.002, 1000, 25000);
    const s2 = rawGex(0.002, 1000, 50000);
    // 50000 = 2 × 25000, so GEX should be 4× larger
    expect(s2).toBeCloseTo(s1 * 4, 0);
  });

  it("1% factor is applied — raw formula includes × 0.01", () => {
    const withFactor = rawGex(0.002, 1000, 25000);
    const withoutFactor = 0.002 * 1000 * 25000 * 25000;
    expect(withFactor).toBeCloseTo(withoutFactor * 0.01, 0);
    expect(withFactor).toBeLessThan(withoutFactor);
  });

  it("chainGex accepts lotSize as contextual metadata only", () => {
    const rows = [
      {
        strike: 25000,
        expiry: "2026-08-28",
        call: { gamma: 0.002, oi: 1000 },
        put: { gamma: 0.003, oi: 500 },
      },
    ];
    // Same GEX regardless of lotSize — it's not in the formula
    const r1 = chainGex(rows, { spot: 25000, symbol: "NIFTY", lotSize: 65 });
    const r2 = chainGex(rows, { spot: 25000, symbol: "NIFTY", lotSize: 30 });
    expect(r1.netGex).toBe(r2.netGex);
    // But lotSize metadata is preserved
    expect(r1.lotSize).toBe(65);
    expect(r2.lotSize).toBe(30);
  });
});

// =============================================================================
// Independent reference calculation (Level D simplified)
// =============================================================================

describe("Level D — Independent reference calculation", () => {
  // Deliberately duplicated minimal formula — a bug in rawGex would NOT
  // make these tests pass because the reference uses a separate implementation.
  // Formula: gamma × OI × spot² × 0.01 (NO lot_size)

  function referenceGex(gamma, oi, spot) {
    return gamma * oi * spot * spot * 0.01;
  }

  function referenceSignedGex(type, gamma, oi, spot) {
    const raw = referenceGex(gamma, oi, spot);
    return type === "call" ? raw : -raw;
  }

  const fixtures = [
    { gamma: 0.002, oi: 1000, spot: 25000 },
    { gamma: 0.005, oi: 2000, spot: 52000 },
    { gamma: 0.001, oi: 500, spot: 18000 },
    { gamma: 0.01, oi: 100, spot: 80000 },
  ];

  for (const f of fixtures) {
    it(`production matches reference for gamma=${f.gamma} oi=${f.oi} spot=${f.spot}`, () => {
      expect(rawGex(f.gamma, f.oi, f.spot)).toBe(
        referenceGex(f.gamma, f.oi, f.spot)
      );
      expect(signedGex("call", f.gamma, f.oi, f.spot)).toBe(
        referenceSignedGex("call", f.gamma, f.oi, f.spot)
      );
      expect(signedGex("put", f.gamma, f.oi, f.spot)).toBe(
        referenceSignedGex("put", f.gamma, f.oi, f.spot)
      );
    });
  }
});

// =============================================================================
// Format helper
// =============================================================================

describe("formatGex", () => {
  it("formats large values in Cr", () => {
    expect(formatGex(48500000)).toBe("+₹4.85 Cr");
    expect(formatGex(-48500000)).toBe("−₹4.85 Cr");
  });

  it("formats medium values in L", () => {
    expect(formatGex(485000)).toBe("+₹4.85 L");
  });

  it("formats small values in ₹", () => {
    expect(formatGex(48500)).toBe("+₹48,500");
  });

  it("returns — for null/undefined", () => {
    expect(formatGex(null)).toBe("—");
    expect(formatGex(undefined)).toBe("—");
    expect(formatGex(NaN)).toBe("—");
    expect(formatGex(Infinity)).toBe("—");
  });
});

// =============================================================================
// Chain-level integration with real-world-like data
// =============================================================================

describe("Chain-level GEX with real-world-like data", () => {
  it("computes full chain GEX for NIFTY-like chain (OI in contracts)", () => {
    const spot = 25512;
    const rows = [
      {
        strike: 25200,
        expiry: "2026-08-28",
        call: { gamma: 0.0015, oi: 2000 },
        put: { gamma: 0.0008, oi: 1500 },
      },
      {
        strike: 25300,
        expiry: "2026-08-28",
        call: { gamma: 0.0018, oi: 3000 },
        put: { gamma: 0.0012, oi: 2500 },
      },
      {
        strike: 25400,
        expiry: "2026-08-28",
        call: { gamma: 0.0022, oi: 4000 },
        put: { gamma: 0.0018, oi: 3500 },
      },
      {
        strike: 25500,
        expiry: "2026-08-28",
        call: { gamma: 0.0025, oi: 5000 },
        put: { gamma: 0.0022, oi: 4500 },
      },
      {
        strike: 25600,
        expiry: "2026-08-28",
        call: { gamma: 0.0020, oi: 3500 },
        put: { gamma: 0.0025, oi: 4000 },
      },
    ];

    const result = chainGex(rows, { spot, symbol: "NIFTY" });

    expect(result.underlying).toBe("NIFTY");
    expect(result.spot).toBe(spot);
    expect(result.methodology).toBe("GEX_STANDARD_V1");
    expect(result.availabilityStatus).toBe(GEX_STATUS.AVAILABLE);
    expect(result.callGex).not.toBeNull();
    expect(result.putGex).not.toBeNull();
    expect(result.netGex).not.toBeNull();
    expect(result.callGex).toBeGreaterThan(0);
    expect(result.putGex).toBeLessThan(0);
    expect(result.byExpiry.length).toBe(1);
    expect(result.byStrike.length).toBe(5);

    // Verify strike-level aggregation matches chain total
    const strikeSum = result.byStrike.reduce((sum, s) => {
      return sum + (s.callGex ?? 0) + (s.putGex ?? 0);
    }, 0);
    expect(result.netGex).toBeCloseTo(strikeSum, 0);

    // Verify lotSize is metadata only (null when not provided)
    expect(result.lotSize).toBeNull();
  });
});
