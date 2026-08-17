// Phase 6.3 — Capital Efficiency & Return Metrics tests (§31 matrix).

import { describe, it, expect } from "vitest";
import {
  calculatePremiumRoi,
  calculateReturnOnCapital,
  calculateReturnOnMargin,
  calculateReturnOnRiskCapital,
  calculateCapitalEfficiency,
  calculateCapitalEfficiencySet,
  W_INVALID_DENOMINATOR,
  W_MISSING_DENOMINATOR,
  W_MISSING_PNL,
  W_UNLIMITED_RISK,
  W_MISMATCHED_PERIOD,
  W_DENOMINATOR_NOT_SPECIFIED,
  W_SOURCE_NOT_BROKER_REPORTED,
} from "./capitalEfficiency";

const roi = (pnl, outlay) => calculatePremiumRoi({ pnl, premiumOutlay: outlay });
const roc = (pnl, est, opts = {}) => calculateReturnOnCapital({ pnl, estimatedCapital: est, ...opts });
const rom = (pnl, broker, opts = {}) => calculateReturnOnMargin({ pnl, brokerMargin: broker, ...opts });
const rorc = (pnl, maxLoss, opts = {}) => calculateReturnOnRiskCapital({ pnl, maxLoss, ...opts });

describe("Premium ROI (§7)", () => {
  it("1. valid positive P&L", () => {
    const r = roi(1000, 5000);
    expect(r.value).toBe(20);
    expect(r.status).toBe("available");
    expect(r.numerator).toBe(1000);
    expect(r.denominator).toBe(5000);
  });

  it("2. negative P&L preserves sign", () => {
    expect(roi(-1000, 5000).value).toBe(-20);
  });

  it("3. zero P&L is a valid 0.0% (never collapsed with unavailable)", () => {
    const r = roi(0, 5000);
    expect(r.value).toBe(0);
    expect(r.status).toBe("available");
  });

  it("4. zero premium → unavailable, never divide by zero", () => {
    const r = roi(1000, 0);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_INVALID_DENOMINATOR);
  });

  it("5. missing premium → unavailable", () => {
    const r = roi(1000, undefined);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_MISSING_DENOMINATOR);
  });

  it("6. invalid premium (NaN) → unavailable", () => {
    expect(roi(1000, NaN).value).toBeNull();
    expect(roi(1000, "abc").value).toBeNull();
  });
});

describe("Return on Capital (§8)", () => {
  it("7. valid estimated capital", () => {
    const r = roc(1000, 5827.25);
    expect(r.value).toBe(17.16); // 1000 / 5827.25 × 100
    expect(r.status).toBe("available");
    expect(r.denominatorLabel).toBe("Estimated Capital");
    expect(r.denominatorSource).toBe("ESTIMATED");
  });

  it("8. negative P&L", () => {
    expect(roc(-1000, 5827.25).value).toBe(-17.16);
  });

  it("9. zero P&L → 0.0%", () => {
    expect(roc(0, 5827.25)).toMatchObject({ value: 0, status: "available" });
  });

  it("10. zero capital → unavailable", () => {
    const r = roc(1000, 0);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_INVALID_DENOMINATOR);
  });

  it("11. missing estimated capital → unavailable", () => {
    const r = roc(1000, null);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_MISSING_DENOMINATOR);
  });

  it("12. unlimited strategy → unavailable + UNLIMITED_RISK", () => {
    const r = roc(1000, 5827.25, { unlimited: true });
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_UNLIMITED_RISK);
  });
});

describe("Return on Margin (§9)", () => {
  it("13. valid broker margin", () => {
    const r = rom(1000, 37503);
    expect(r.value).toBe(2.67); // 1000 / 37503 × 100
    expect(r.status).toBe("available");
    expect(r.denominatorLabel).toBe("Broker Margin");
    expect(r.denominatorSource).toBe("BROKER_REPORTED");
  });

  it("14. unavailable broker margin → unavailable (never estimated/paper cash)", () => {
    const r = rom(1000, null);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_MISSING_DENOMINATOR);
  });

  it("15. zero broker margin → unavailable", () => {
    const r = rom(1000, 0);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_INVALID_DENOMINATOR);
  });

  it("16. negative P&L", () => {
    expect(rom(-1000, 37503).value).toBe(-2.67);
  });

  it("17. source separation: non-BROKER_REPORTED value is rejected", () => {
    const r = rom(1000, { value: 37503, source: "ESTIMATED" });
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_SOURCE_NOT_BROKER_REPORTED);
  });
});

describe("Return on Risk Capital (§10)", () => {
  it("18. finite max loss", () => {
    const r = rorc(1000, -5827.25);
    expect(r.value).toBe(17.16); // 1000 / abs(-5827.25) × 100
    expect(r.basis).toBe("MAX_LOSS");
    expect(r.denominator).toBe(5827.25);
  });

  it("19. unlimited loss → unavailable + UNLIMITED_RISK", () => {
    const r = rorc(1000, -5827.25, { unlimited: true });
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_UNLIMITED_RISK);
  });

  it("20. zero max loss → unavailable", () => {
    const r = rorc(1000, 0);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_INVALID_DENOMINATOR);
  });

  it("21. missing max loss → unavailable", () => {
    const r = rorc(1000, null);
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_MISSING_DENOMINATOR);
  });
});

describe("Separation (§22-25)", () => {
  it("22. broker vs estimated are independent values", () => {
    const onCapital = roc(1000, 5827.25);
    const onMargin = rom(1000, 37503);
    expect(onCapital.value).toBe(17.16);
    expect(onMargin.value).toBe(2.67);
    expect(onCapital.value).not.toBe(onMargin.value);
  });

  it("23. no fallback between denominators", () => {
    // Only estimated capital exists → Return on Margin is STILL unavailable.
    expect(rom(1000, null).value).toBeNull();
    // Only broker margin exists → Return on Capital is STILL unavailable.
    expect(roc(1000, null).value).toBeNull();
    // Only premium outlay exists → risk capital stays unavailable.
    expect(rorc(1000, null).value).toBeNull();
  });

  it("24. correct denominator labels and sources", () => {
    expect(roi(100, 500).denominatorLabel).toBe("Premium Outlay");
    expect(roi(100, 500).denominatorSource).toBe("CALCULATED");
    expect(roc(100, 500).denominatorLabel).toBe("Estimated Capital");
    expect(roc(100, 500).denominatorSource).toBe("ESTIMATED");
    expect(rom(100, 500).denominatorLabel).toBe("Broker Margin");
    expect(rom(100, 500).denominatorSource).toBe("BROKER_REPORTED");
    expect(rorc(100, -500).denominatorLabel).toBe("Defined Max Loss");
    expect(rorc(100, -500).denominatorSource).toBe("CALCULATED");
  });

  it("25. no hidden denominator selection", () => {
    const r = calculateCapitalEfficiency({ pnl: 1000, denominator: 5827.25, denominatorType: undefined });
    expect(r.value).toBeNull();
    expect(r.warnings).toContain(W_DENOMINATOR_NOT_SPECIFIED);
    expect(calculateCapitalEfficiency({ pnl: 1000, denominator: 5827.25, denominatorType: "MADE_UP" }).value).toBeNull();
  });
});

describe("Period (§16/§26/§27)", () => {
  it("26. matching time period → metrics computed", () => {
    const set = calculateCapitalEfficiencySet({
      pnl: 1000,
      pnlType: "REALIZED",
      period: "inception",
      capitalPeriod: "inception",
      premiumOutlay: 5000,
      estimatedCapital: 5827.25,
      brokerMargin: { value: 37503, source: "BROKER_REPORTED" },
      maxLoss: -5827.25,
      maxLossUnlimited: false,
    });
    expect(set.premiumRoi.value).toBe(20);
    expect(set.returnOnCapital.value).toBe(17.16);
    expect(set.returnOnMargin.value).toBe(2.67);
    expect(set.returnOnRiskCapital.value).toBe(17.16);
    expect(set.status).toBe("available");
  });

  it("27. mismatched period → unavailable + MISMATCHED_PERIOD", () => {
    const set = calculateCapitalEfficiencySet({
      pnl: 1000,
      period: "week",
      capitalPeriod: "inception",
      premiumOutlay: 5000,
      estimatedCapital: 5827.25,
      brokerMargin: 37503,
      maxLoss: -5827.25,
    });
    expect(set.premiumRoi.value).toBeNull();
    expect(set.returnOnCapital.value).toBeNull();
    expect(set.returnOnMargin.value).toBeNull();
    expect(set.returnOnRiskCapital.value).toBeNull();
    expect(set.warnings).toContain(W_MISMATCHED_PERIOD);
    expect(set.premiumRoi.warnings).toContain(W_MISMATCHED_PERIOD);
  });
});

describe("Portfolio (§15/§28-30)", () => {
  it("28. strategy-level aggregation via the set", () => {
    const set = calculateCapitalEfficiencySet({
      pnl: 1000,
      pnlType: "REALIZED",
      period: "inception",
      premiumOutlay: 5000,
      estimatedCapital: 5827.25,
      brokerMargin: 37503,
      maxLoss: -5827.25,
    });
    expect(set.capitalEfficiency.denominatorType).toBe("ESTIMATED_CAPITAL");
    expect(set.capitalEfficiency.value).toBe(17.16);
  });

  it("29. portfolio aggregation reports partial when some denominators are missing", () => {
    const set = calculateCapitalEfficiencySet({
      pnl: 1000,
      premiumOutlay: 5000,
      estimatedCapital: null,
      brokerMargin: null,
      maxLoss: null,
    });
    expect(set.premiumRoi.value).toBe(20);
    expect(set.returnOnCapital.value).toBeNull();
    expect(set.returnOnMargin.value).toBeNull();
    expect(set.returnOnRiskCapital.value).toBeNull();
    expect(set.status).toBe("partial");
  });

  it("30. non-additive denominator safety: never fabricate an aggregate", () => {
    // Broker margin unavailable → Return on Margin stays null even though
    // estimated capital exists; no silent substitution, no invented sum.
    const set = calculateCapitalEfficiencySet({
      pnl: 1000,
      premiumOutlay: 5000,
      estimatedCapital: 5827.25,
      brokerMargin: null,
      maxLoss: -5827.25,
    });
    expect(set.returnOnMargin.value).toBeNull();
    expect(set.returnOnCapital.value).toBe(17.16);
    // The explicit capital-efficiency denominator is always reported.
    expect(set.capitalEfficiency.denominatorType).toBe("ESTIMATED_CAPITAL");
    expect(set.capitalEfficiency.denominatorSource).toBe("ESTIMATED");
  });
});

describe("Numeric safety (§6/§31-35)", () => {
  it("31. NaN P&L → unavailable", () => {
    expect(roi(NaN, 5000).value).toBeNull();
    expect(roi(NaN, 5000).warnings).toContain(W_MISSING_PNL);
  });

  it("32. Infinity denominator → unavailable", () => {
    expect(roi(1000, Infinity).value).toBeNull();
    expect(rom(1000, Infinity).value).toBeNull();
  });

  it("33. null inputs → unavailable", () => {
    expect(roi(null, 5000).value).toBeNull();
    expect(roi(1000, null).value).toBeNull();
  });

  it("34. negative denominator → unavailable + INVALID_DENOMINATOR", () => {
    expect(roi(1000, -5000).warnings).toContain(W_INVALID_DENOMINATOR);
    expect(roc(1000, -5827.25).value).toBeNull();
    expect(rom(1000, -37503).value).toBeNull();
  });

  it("35. zero P&L is available 0.0% across all metrics", () => {
    expect(roi(0, 5000)).toMatchObject({ value: 0, status: "available" });
    expect(roc(0, 5827.25)).toMatchObject({ value: 0, status: "available" });
    expect(rom(0, 37503)).toMatchObject({ value: 0, status: "available" });
    expect(rorc(0, -5827.25)).toMatchObject({ value: 0, status: "available" });
  });

  it("no NaN/Infinity ever leaks into results", () => {
    const cases = [roi(1000, 5000), roc(-1000, 5827.25), rom(0, 37503), rorc(1000, -5827.25)];
    for (const r of cases) {
      expect(Number.isFinite(r.value)).toBe(true);
      expect(JSON.stringify(r)).not.toMatch(/NaN|Infinity/);
    }
  });
});
