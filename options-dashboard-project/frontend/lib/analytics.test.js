import { describe, it, expect } from "vitest";
import { oiTotals, putCallRatio, maxPainStrike, maxOI } from "./analytics";

const rows = [
  { strike: 100, call: { oi: 100 }, put: { oi: 50 } },
  { strike: 110, call: { oi: 200 }, put: { oi: 300 } },
  { strike: 120, call: { oi: 400 }, put: { oi: 150 } },
];

describe("oiTotals", () => {
  it("sums call and put OI", () => {
    expect(oiTotals(rows)).toEqual({ callOI: 700, putOI: 500 });
  });

  it("treats missing sides / OI as zero", () => {
    expect(oiTotals([{ strike: 100 }, { strike: 110, call: {}, put: { oi: 5 } }])).toEqual({ callOI: 0, putOI: 5 });
  });

  it("returns zeros for empty rows", () => {
    expect(oiTotals([])).toEqual({ callOI: 0, putOI: 0 });
  });
});

describe("putCallRatio", () => {
  it("returns putOI / callOI", () => {
    expect(putCallRatio(rows)).toBeCloseTo(500 / 700);
  });

  it("returns null when there is no call OI", () => {
    expect(putCallRatio([{ strike: 100, put: { oi: 10 } }])).toBeNull();
    expect(putCallRatio([])).toBeNull();
  });
});

describe("maxPainStrike", () => {
  it("returns null for empty rows", () => {
    expect(maxPainStrike([])).toBeNull();
  });

  it("finds the strike minimizing total intrinsic payout", () => {
    // At 100: calls pay 0, puts pay 300*10 + 150*20 = 6000
    // At 110: calls pay 100*10 = 1000, puts pay 150*10 = 1500 -> 2500
    // At 120: calls pay 100*20 + 200*10 = 4000, puts pay 0 -> 4000
    expect(maxPainStrike(rows)).toBe(110);
  });

  it("handles a single strike", () => {
    expect(maxPainStrike([{ strike: 100, call: { oi: 1 }, put: { oi: 1 } }])).toBe(100);
  });
});

describe("maxOI", () => {
  it("returns the largest single-side OI", () => {
    expect(maxOI(rows)).toBe(400);
  });

  it("returns 0 for empty or OI-less rows", () => {
    expect(maxOI([])).toBe(0);
    expect(maxOI([{ strike: 100 }])).toBe(0);
  });
});
