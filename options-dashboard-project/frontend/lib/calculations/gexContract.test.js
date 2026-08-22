/**
 * GEX Phase 7.5 — Snapshot Validation, Schema Version & SB Contract Tests
 *
 * Level A — Snapshot schema version
 * Level B — Snapshot validation: valid snapshots
 * Level C — Snapshot validation: invalid snapshots
 * Level D — Snapshot validation: edge cases
 * Level E — Strategy Builder contract versioning
 * Level F — Snapshot field completeness
 */

import { describe, it, expect } from "vitest";
import {
  captureGexSnapshot,
  validateGexSnapshot,
  GEX_SNAPSHOT_SCHEMA_VERSION,
  GEX_HISTORY_VERSION,
} from "./gexHistory";
import { computeGexAnalytics, STRATEGY_BUILDER_VERSION } from "./gexAnalytics";

// =============================================================================
// Test fixtures
// =============================================================================

const VALUATION_DATE = "2026-08-22";

/** Canonical chain response */
function makeChain(rows, spot = 25000, expiry = "2026-08-28", symbol = "NIFTY") {
  return {
    symbol,
    expiry_date: expiry,
    underlying_spot_price: spot,
    chain: rows,
  };
}

const DEFAULT_ROWS = [
  { strike: 24900, call: { gamma: 0.001, oi: 500, iv: 0.22 }, put: { gamma: 0.003, oi: 1200, iv: 0.19 } },
  { strike: 25000, call: { gamma: 0.002, oi: 1000, iv: 0.18 }, put: { gamma: 0.003, oi: 800, iv: 0.20 } },
];

function validSnapshot(overrides = {}) {
  const chain = makeChain(overrides.rows ?? DEFAULT_ROWS, overrides.spot ?? 25000, overrides.expiry ?? "2026-08-28");
  return captureGexSnapshot(chain, overrides.spot ?? 25000, overrides.timestamp ?? "2026-08-22T09:00:00Z", {
    valuationDate: overrides.valuationDate ?? VALUATION_DATE,
  });
}

function series(count, startMs = Date.parse("2026-08-22T09:00:00Z"), intervalMs = 300_000) {
  return Array.from({ length: count }, (_, i) => {
    const spot = 25000 + i * 10;
    const chain = makeChain(DEFAULT_ROWS, spot);
    return captureGexSnapshot(chain, spot, new Date(startMs + i * intervalMs).toISOString(), { valuationDate: VALUATION_DATE });
  });
}

// =============================================================================
// Level A — Snapshot schema version
// =============================================================================

describe("Level A — Snapshot schema version", () => {
  it("GEX_SNAPSHOT_SCHEMA_VERSION is defined", () => {
    expect(GEX_SNAPSHOT_SCHEMA_VERSION).toBe("GEXSnapshot_v1");
  });

  it("GEX_HISTORY_VERSION is defined", () => {
    expect(GEX_HISTORY_VERSION).toBe("GEX_HISTORY_V1");
  });

  it("captureGexSnapshot returns schemaVersion", () => {
    const snap = validSnapshot();
    expect(snap.schemaVersion).toBe("GEXSnapshot_v1");
  });

  it("captureGexSnapshot returns snapshotId as null", () => {
    const snap = validSnapshot();
    expect(snap.snapshotId).toBeNull();
  });

  it("captureGexSnapshot returns valuationDate", () => {
    const snap = validSnapshot({ valuationDate: "2026-08-20" });
    expect(snap.valuationDate).toBe("2026-08-20");
  });

  it("captureGexSnapshot computes dte from valuationDate + expiry", () => {
    const snap = validSnapshot({ valuationDate: "2026-08-22", expiry: "2026-08-28" });
    expect(snap.dte).not.toBeNull();
    expect(snap.dte).toBeGreaterThan(5);
    expect(snap.dte).toBeLessThan(7);
  });

  it("captureGexSnapshot without valuationDate has null dte", () => {
    const chain = makeChain(DEFAULT_ROWS, 25000);
    const snap = captureGexSnapshot(chain, 25000, "2026-08-22T09:00:00Z");
    expect(snap.valuationDate).toBeNull();
    expect(snap.dte).toBeNull();
  });

  it("captureGexSnapshot returns underlying field", () => {
    const snap = validSnapshot();
    expect(snap.underlying).toBe("NIFTY");
  });
});

// =============================================================================
// Level B — Snapshot validation: valid snapshots
// =============================================================================

describe("Level B — Valid snapshot validation", () => {
  it("valid snapshot passes validation", () => {
    const snap = validSnapshot();
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(true);
    expect(result.issues).toHaveLength(0);
    expect(result.snapshotVersion).toBe("GEXSnapshot_v1");
  });

  it("valid snapshot with null optional fields passes", () => {
    const snap = validSnapshot();
    snap.dte = null;
    snap.valuationDate = null;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(true);
  });

  it("valid snapshot with null GEX values passes", () => {
    const snap = validSnapshot();
    snap.callGex = null;
    snap.putGex = null;
    snap.netGex = null;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(true);
  });

  it("valid snapshot with zero GEX values passes", () => {
    const snap = validSnapshot();
    snap.callGex = 0;
    snap.putGex = 0;
    snap.netGex = 0;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(true);
  });
});

// =============================================================================
// Level C — Snapshot validation: invalid snapshots
// =============================================================================

describe("Level C — Invalid snapshot validation", () => {
  it("null snapshot → NOT_OBJECT", () => {
    const result = validateGexSnapshot(null);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("NOT_OBJECT");
  });

  it("undefined snapshot → NOT_OBJECT", () => {
    const result = validateGexSnapshot(undefined);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("NOT_OBJECT");
  });

  it("primitive value → NOT_OBJECT", () => {
    const result = validateGexSnapshot("not an object");
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("NOT_OBJECT");
  });

  it("missing capturedAt → MISSING_CAPTURED_AT", () => {
    const snap = validSnapshot();
    snap.capturedAt = null;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("MISSING_CAPTURED_AT");
  });

  it("invalid capturedAt → INVALID_CAPTURED_AT", () => {
    const snap = validSnapshot();
    snap.capturedAt = "not-a-date";
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("INVALID_CAPTURED_AT");
  });

  it("null spot → MISSING_OR_INVALID_SPOT", () => {
    const snap = validSnapshot();
    snap.spot = null;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("MISSING_OR_INVALID_SPOT");
  });

  it("zero spot → NON_POSITIVE_SPOT", () => {
    const snap = validSnapshot();
    snap.spot = 0;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("NON_POSITIVE_SPOT");
  });

  it("negative spot → NON_POSITIVE_SPOT", () => {
    const snap = validSnapshot();
    snap.spot = -100;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("NON_POSITIVE_SPOT");
  });

  it("NaN netGex → INVALID_NET_GEX", () => {
    const snap = validSnapshot();
    snap.netGex = NaN;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("INVALID_NET_GEX");
  });

  it("Infinity netGex → INVALID_NET_GEX", () => {
    const snap = validSnapshot();
    snap.netGex = Infinity;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("INVALID_NET_GEX");
  });

  it("NaN callGex → INVALID_CALL_GEX", () => {
    const snap = validSnapshot();
    snap.callGex = NaN;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("INVALID_CALL_GEX");
  });

  it("missing symbol → MISSING_SYMBOL", () => {
    const snap = validSnapshot();
    snap.symbol = null;
    snap.underlying = null;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("MISSING_SYMBOL");
  });

  it("non-array strikeData → STRIKE_DATA_NOT_ARRAY", () => {
    const snap = validSnapshot();
    snap.strikeData = "not an array";
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("STRIKE_DATA_NOT_ARRAY");
  });

  it("invalid strike entry → INVALID_STRIKE_ENTRY", () => {
    const snap = validSnapshot();
    snap.strikeData = [null, { strike: 25000 }];
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues.some((i) => i.startsWith("INVALID_STRIKE_ENTRY:"))).toBe(true);
  });

  it("non-array expiryData → EXPIRY_DATA_NOT_ARRAY", () => {
    const snap = validSnapshot();
    snap.expiryData = "not an array";
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues).toContain("EXPIRY_DATA_NOT_ARRAY");
  });

  it("unknown schema version → UNKNOWN_SCHEMA_VERSION", () => {
    const snap = validSnapshot();
    snap.schemaVersion = "GEXSnapshot_v99";
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues.some((i) => i.startsWith("UNKNOWN_SCHEMA_VERSION:"))).toBe(true);
  });
});

// =============================================================================
// Level D — Snapshot validation: edge cases
// =============================================================================

describe("Level D — Validation edge cases", () => {
  it("missing schemaVersion → warning, not error", () => {
    const snap = validSnapshot();
    delete snap.schemaVersion;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(true);
    expect(result.warnings).toContain("MISSING_SCHEMA_VERSION");
  });

  it("missing methodology → warning, not error", () => {
    const snap = validSnapshot();
    snap.methodology = null;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(true);
    expect(result.warnings).toContain("MISSING_METHODOLOGY");
  });

  it("NaN in strike gamma → warning", () => {
    const snap = validSnapshot();
    snap.strikeData = [{ strike: 25000, callGamma: NaN, putGamma: 0.003 }];
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(true);
    expect(result.warnings.some((w) => w.includes("NON_FINITE"))).toBe(true);
  });

  it("invalid DTE → warning", () => {
    const snap = validSnapshot();
    snap.dte = -5;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(true);
    expect(result.warnings).toContain("INVALID_DTE");
  });

  it("multiple issues reported simultaneously", () => {
    const snap = validSnapshot();
    snap.spot = null;
    snap.capturedAt = null;
    snap.netGex = NaN;
    const result = validateGexSnapshot(snap);
    expect(result.valid).toBe(false);
    expect(result.issues.length).toBeGreaterThanOrEqual(3);
  });

  it("empty object → multiple issues", () => {
    const result = validateGexSnapshot({});
    expect(result.valid).toBe(false);
    expect(result.issues.length).toBeGreaterThan(0);
  });

  it("snapshot with only spot and capturedAt → still has warnings", () => {
    const snap = { spot: 25000, capturedAt: "2026-08-22T09:00:00Z" };
    const result = validateGexSnapshot(snap);
    expect(result.warnings.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// Level E — Strategy Builder contract versioning
// =============================================================================

describe("Level E — Strategy Builder contract versioning", () => {
  it("STRATEGY_BUILDER_VERSION is defined", () => {
    expect(STRATEGY_BUILDER_VERSION).toBe("strategyBuilderInputs_v1");
  });

  it("computeGexAnalytics returns strategyBuilderVersion", () => {
    const data = series(5);
    const result = computeGexAnalytics(data, { valuationDate: VALUATION_DATE });
    expect(result.strategyBuilderVersion).toBe("strategyBuilderInputs_v1");
  });

  it("unavailable analytics also returns strategyBuilderVersion", () => {
    const result = computeGexAnalytics([]);
    expect(result.strategyBuilderVersion).toBe("strategyBuilderInputs_v1");
  });

  it("SB interface has all required v1 fields", () => {
    const data = series(5);
    const result = computeGexAnalytics(data, { valuationDate: VALUATION_DATE });
    const sb = result.strategyBuilderInputs;

    const requiredFields = [
      "netGex", "normalizedNetGex", "callGexShare",
      "netGexSma", "deltaGexSma",
      "velocity", "acceleration", "volatility",
      "gexPercentile", "descriptiveZ",
      "concentrationTop3", "profileLabels", "flipDistancePct",
    ];

    for (const field of requiredFields) {
      expect(sb).toHaveProperty(field);
    }
  });

  it("SB fields are number|null or string[]", () => {
    const data = series(5);
    const result = computeGexAnalytics(data, { valuationDate: VALUATION_DATE });
    const sb = result.strategyBuilderInputs;

    for (const [key, val] of Object.entries(sb)) {
      if (key === "profileLabels") {
        expect(Array.isArray(val)).toBe(true);
      } else {
        expect(val === null || typeof val === "number").toBe(true);
      }
    }
  });
});

// =============================================================================
// Level F — Snapshot field completeness
// =============================================================================

describe("Level F — Snapshot field completeness", () => {
  it("snapshot has all v1 fields", () => {
    const snap = validSnapshot();

    // Identity
    expect(snap).toHaveProperty("schemaVersion");
    expect(snap).toHaveProperty("snapshotId");

    // Temporal
    expect(snap).toHaveProperty("capturedAt");
    expect(snap).toHaveProperty("valuationDate");

    // Market identity
    expect(snap).toHaveProperty("underlying");
    expect(snap).toHaveProperty("symbol");
    expect(snap).toHaveProperty("spot");

    // Expiry
    expect(snap).toHaveProperty("expiry");
    expect(snap).toHaveProperty("dte");

    // Methodology
    expect(snap).toHaveProperty("methodology");
    expect(snap).toHaveProperty("methodologyMetadata");

    // GEX
    expect(snap).toHaveProperty("callGex");
    expect(snap).toHaveProperty("putGex");
    expect(snap).toHaveProperty("netGex");

    // Quality
    expect(snap).toHaveProperty("availabilityStatus");
    expect(snap).toHaveProperty("validStrikeCount");
    expect(snap).toHaveProperty("totalStrikeCount");
    expect(snap).toHaveProperty("chainAgeMs");

    // Data
    expect(snap).toHaveProperty("strikeData");
    expect(snap).toHaveProperty("expiryData");
  });

  it("snapshot field types are correct", () => {
    const snap = validSnapshot();
    expect(typeof snap.schemaVersion).toBe("string");
    expect(snap.snapshotId).toBeNull();
    expect(typeof snap.capturedAt).toBe("string");
    expect(typeof snap.spot).toBe("number");
    expect(typeof snap.callGex).toBe("number");
    expect(typeof snap.putGex).toBe("number");
    expect(typeof snap.netGex).toBe("number");
    expect(Array.isArray(snap.strikeData)).toBe(true);
    expect(Array.isArray(snap.expiryData)).toBe(true);
    expect(typeof snap.methodologyMetadata).toBe("object");
  });

  it("strike data has all v1 fields", () => {
    const snap = validSnapshot();
    const strike = snap.strikeData[0];
    expect(strike).toHaveProperty("strike");
    expect(strike).toHaveProperty("callGamma");
    expect(strike).toHaveProperty("callOi");
    expect(strike).toHaveProperty("callIv");
    expect(strike).toHaveProperty("callGex");
    expect(strike).toHaveProperty("putGamma");
    expect(strike).toHaveProperty("putOi");
    expect(strike).toHaveProperty("putIv");
    expect(strike).toHaveProperty("putGex");
    expect(strike).toHaveProperty("netGex");
  });

  it("methodologyMetadata has all v1 fields", () => {
    const snap = validSnapshot();
    const mm = snap.methodologyMetadata;
    expect(mm).toHaveProperty("gexVersion");
    expect(mm).toHaveProperty("formula");
    expect(mm).toHaveProperty("oiUnit");
    expect(mm).toHaveProperty("signConvention");
    expect(mm).toHaveProperty("callSign");
    expect(mm).toHaveProperty("putSign");
    expect(mm).toHaveProperty("lotSizeFactorApplied");
    expect(mm.lotSizeFactorApplied).toBe(false);
    expect(mm.oiUnit).toBe("contracts");
  });

  it("snapshot roundtrip: validate → capture → validate", () => {
    const chain = makeChain(DEFAULT_ROWS, 25000);
    const snap = captureGexSnapshot(chain, 25000, "2026-08-22T09:00:00Z", { valuationDate: VALUATION_DATE });
    const validation = validateGexSnapshot(snap);
    expect(validation.valid).toBe(true);
    expect(validation.snapshotVersion).toBe("GEXSnapshot_v1");
  });
});
