import { describe, it, expect } from "vitest";
import { validateLeg, validateStrategy } from "./strategyValidation";

const leg = (overrides = {}) => ({ type: "call", action: "buy", strike: 25000, qty: 1, ...overrides });

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

  it("lists every issue found", () => {
    const { valid, issues } = validateLeg({ type: "x", action: "y", strike: 0, qty: 0 });
    expect(valid).toBe(false);
    expect(issues).toHaveLength(4);
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

  it("labels per-leg issues with their index", () => {
    const { issues } = validateStrategy([leg(), leg({ qty: 0 })]);
    expect(issues).toEqual(["leg 2: quantity must be at least 1"]);
  });
});
