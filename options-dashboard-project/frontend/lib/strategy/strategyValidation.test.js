import { describe, it, expect } from "vitest";
import { validateLeg, validateStrategy, validateExecution } from "./strategyValidation";

const leg = (overrides = {}) => ({ type: "call", action: "buy", strike: 25000, qty: 1, expiry: "2026-08-28", price: 200, ...overrides });

describe("validateLeg", () => {
  it("accepts a well-formed leg", () => {
    expect(validateLeg(leg())).toEqual({ valid: true, issues: [] });
  });

  it("rejects a missing leg", () => {
    expect(validateLeg(null).valid).toBe(false);
  });

  it("rejects invalid type and action", () => {
    expect(validateLeg(leg({ type: "future" })).valid).toBe(false);
    expect(validateLeg(leg({ action: "short" })).valid).toBe(false);
  });

  it("rejects non-positive or non-numeric strikes", () => {
    expect(validateLeg(leg({ strike: 0 })).valid).toBe(false);
    expect(validateLeg(leg({ strike: "" })).valid).toBe(false);
    expect(validateLeg(leg({ strike: "abc" })).valid).toBe(false);
  });

  it("rejects quantities below 1", () => {
    expect(validateLeg(leg({ qty: 0 })).valid).toBe(false);
    expect(validateLeg(leg({ qty: -2 })).valid).toBe(false);
  });

  it("rejects a missing expiry", () => {
    const { valid, issues } = validateLeg(leg({ expiry: null }));
    expect(valid).toBe(false);
    expect(issues).toContain("Expiry is missing.");
  });

  it("rejects missing, negative or non-numeric premiums", () => {
    expect(validateLeg(leg({ price: undefined })).valid).toBe(false);
    expect(validateLeg(leg({ price: -5 })).valid).toBe(false);
    expect(validateLeg(leg({ price: "abc" })).valid).toBe(false);
    expect(validateLeg(leg({ price: 0 })).valid).toBe(true); // zero premium is valid
  });

  it("lists every issue found", () => {
    const { valid, issues } = validateLeg({ type: "x", action: "y", strike: 0, qty: 0, expiry: null, price: -1 });
    expect(valid).toBe(false);
    expect(issues).toHaveLength(6);
  });
});

describe("validateStrategy", () => {
  it("accepts a non-empty list of valid legs", () => {
    expect(validateStrategy([leg(), leg({ type: "put", strike: 24900 })]).valid).toBe(true);
  });

  it("rejects an empty or non-array strategy", () => {
    expect(validateStrategy([]).valid).toBe(false);
    expect(validateStrategy(null).valid).toBe(false);
  });

  it("labels per-leg issues with their index and an actionable message", () => {
    const { issues } = validateStrategy([leg(), leg({ qty: 0 })]);
    expect(issues).toEqual(["Leg 2: Quantity must be at least 1."]);
  });
});

describe("validateExecution — pre-execution gate", () => {
  const validLegs = [leg(), leg({ type: "put", strike: 24900 })];
  const chains = { "2026-08-28": [24900, 25000] };
  const expiries = ["2026-08-28"];

  it("a valid strategy with a verified open market can proceed", () => {
    const r = validateExecution(validLegs, { marketStatus: { status: "open" }, chains, expiries });
    expect(r.valid).toBe(true);
    expect(r.issues).toEqual([]);
  });

  it("a closed market blocks execution", () => {
    const r = validateExecution(validLegs, { marketStatus: { status: "closed" }, chains, expiries });
    expect(r.valid).toBe(false);
    expect(r.issues).toContain("Market is closed. Paper order was not executed.");
  });

  it("an unknown market status blocks execution (never treated as open)", () => {
    const r = validateExecution(validLegs, { marketStatus: { status: "unknown" }, chains, expiries });
    expect(r.valid).toBe(false);
    expect(r.issues).toContain("Unable to verify market status. Order was not executed.");
  });

  it("a missing market status blocks execution (no status is never open)", () => {
    const r = validateExecution(validLegs, { chains, expiries });
    expect(r.valid).toBe(false);
    expect(r.issues).toContain("Unable to verify market status. Order was not executed.");
  });

  it("an invalid strategy cannot execute even when the market is open", () => {
    const r = validateExecution([leg({ qty: 0 })], { marketStatus: { status: "open" }, chains, expiries });
    expect(r.valid).toBe(false);
    expect(r.issues).toContain("Leg 1: Quantity must be at least 1.");
  });

  it("flags strikes that are missing from the loaded chain", () => {
    const r = validateExecution([leg({ strike: 25100 })], { marketStatus: { status: "open" }, chains, expiries });
    expect(r.issues).toContain("Leg 1: Strike 25100 is not available in the 2026-08-28 chain.");
  });

  it("flags expiries whose chain data is not loaded", () => {
    const r = validateExecution([leg({ expiry: "2026-09-04" })], { marketStatus: { status: "open" }, chains, expiries });
    expect(r.issues).toContain("Leg 1: Chain data for expiry 2026-09-04 is not loaded.");
  });

  it("flags expiries that are not available at all", () => {
    const r = validateExecution([leg({ expiry: "2027-01-01" })], { marketStatus: { status: "open" }, chains, expiries });
    expect(r.issues).toContain("Leg 1: Expiry 2027-01-01 is not available.");
  });

  it("skips chain checks when no chain map is provided (analysis mode)", () => {
    const r = validateExecution(validLegs, { marketStatus: { status: "open" } });
    expect(r.valid).toBe(true);
  });
});
