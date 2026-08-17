import { describe, it, expect } from "vitest";
import {
  formatMoney,
  formatOptionPrice,
  formatSignedMoney,
  NIFTY_OPTION_TICK_SIZE,
  roundOptionPrice,
} from "./pricing";

describe("roundOptionPrice (NIFTY ₹0.05 tick)", () => {
  it("applies the exact spec tick examples", () => {
    expect(roundOptionPrice(125.23)).toBe(125.25);
    expect(roundOptionPrice(125.24)).toBe(125.25);
    expect(roundOptionPrice(125.25)).toBe(125.25);
    expect(roundOptionPrice(125.26)).toBe(125.25);
    expect(roundOptionPrice(125.27)).toBe(125.25);
    expect(roundOptionPrice(125.28)).toBe(125.30);
  });

  it("handles zero, exact ticks and float artifacts", () => {
    expect(roundOptionPrice(0)).toBe(0);
    expect(roundOptionPrice(31.6)).toBe(31.6);
    expect(roundOptionPrice(48.75)).toBe(48.75);
    // 48.749999999 must land on 48.75, never 48.74999999999999.
    expect(roundOptionPrice(48.749999999)).toBe(48.75);
    // And 125.25 must never become 125.25000000000001.
    expect(roundOptionPrice(125.25)).toBe(125.25);
    expect(String(roundOptionPrice(125.23))).not.toMatch(/2500000000+1/);
  });

  it("rounds large prices safely to the tick", () => {
    expect(roundOptionPrice(999999.99)).toBe(1000000);
    expect(roundOptionPrice(123456.23)).toBe(123456.25);
  });

  it("supports a custom tick size", () => {
    expect(roundOptionPrice(100.62, 0.25)).toBe(100.5);
    expect(roundOptionPrice(100.63, 0.25)).toBe(100.75);
  });

  it("never converts invalid/missing prices to zero", () => {
    expect(roundOptionPrice(null)).toBeNull();
    expect(roundOptionPrice(undefined)).toBeNull();
    expect(roundOptionPrice(NaN)).toBeNull();
    // Negative (invalid) prices pass through — never coerced to a tick or 0.
    expect(roundOptionPrice(-78)).toBe(-78);
    expect(roundOptionPrice(-78)).not.toBe(0);
  });

  it("exposes the NIFTY tick constant", () => {
    expect(NIFTY_OPTION_TICK_SIZE).toBe(0.05);
  });
});

describe("two-decimal display helpers", () => {
  it("formatOptionPrice always shows two decimals with Indian grouping", () => {
    expect(formatOptionPrice(31.6)).toBe("31.60");
    expect(formatOptionPrice(48.75)).toBe("48.75");
    expect(formatOptionPrice(125.25)).toBe("125.25");
    expect(formatOptionPrice(125.251)).toBe("125.25");
    expect(formatOptionPrice(null)).toBe("—");
  });

  it("formatMoney renders ₹ with two decimals (spec §30)", () => {
    expect(formatMoney(3169)).toBe("₹3,169.00");
    expect(formatMoney(5827.25)).toBe("₹5,827.25");
    expect(formatMoney(78)).toBe("₹78.00");
    expect(formatMoney(-78)).toBe("−₹78.00");
    expect(formatMoney(0)).toBe("₹0.00");
    expect(formatMoney(null)).toBe("—");
  });

  it("formatSignedMoney renders signed P&L with the typographic minus", () => {
    expect(formatSignedMoney(120)).toBe("+₹120.00");
    expect(formatSignedMoney(-120)).toBe("−₹120.00");
    expect(formatSignedMoney(0)).toBe("+₹0.00");
    expect(formatSignedMoney(null)).toBe("—");
  });
});
