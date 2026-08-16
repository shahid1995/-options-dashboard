import { describe, expect, it } from "vitest";
import {
  CAPITAL_SOURCE_LABELS,
  capitalDisplay,
  capitalRows,
  capitalStrategyRows,
  capitalValue,
  estimatedBasisLabel,
  hasCapitalValue,
  rocInputsAvailable,
  sourceLabel,
  statusLabel,
} from "./capital";

describe("capital display helpers (Phase 6.0)", () => {
  it("hasCapitalValue only accepts finite numbers — null/NaN/Infinity are missing", () => {
    expect(hasCapitalValue(0)).toBe(true);
    expect(hasCapitalValue(492000)).toBe(true);
    expect(hasCapitalValue(null)).toBe(false);
    expect(hasCapitalValue(undefined)).toBe(false);
    expect(hasCapitalValue(NaN)).toBe(false);
    expect(hasCapitalValue(Infinity)).toBe(false);
  });

  it("missing values stay null — never converted to 0", () => {
    const missing = capitalValue({ value: null, source: "BROKER_REPORTED", status: "unavailable" });
    expect(missing.value).toBeNull();
    expect(missing.source).toBe("BROKER_REPORTED");
    expect(missing.status).toBe("unavailable");

    const zero = capitalValue({ value: 0, source: "CALCULATED", status: "available" });
    expect(zero.value).toBe(0); // a real zero is a valid figure
  });

  it("tolerates a missing/loading payload", () => {
    const d = capitalDisplay(null);
    expect(d.premiumOutlay.value).toBeNull();
    expect(d.brokerMargin.value).toBeNull();
    expect(d.estimatedCapital.value).toBeNull();
    expect(d.strategies).toEqual([]);
    expect(d.status).toBe("unavailable");
  });

  it("maps the backend contract and preserves source labels", () => {
    const d = capitalDisplay({
      premium_outlay: { value: 5827.25, source: "CALCULATED", status: "available" },
      broker_margin: { value: null, source: "BROKER_REPORTED", status: "unavailable" },
      estimated_capital: { value: 5827.25, source: "ESTIMATED", status: "available" },
      estimated_capital_basis: "premium",
      broker_available_funds: { value: null, source: "BROKER_REPORTED", status: "unavailable" },
      paper_starting_capital: { value: 500000, source: "CALCULATED", status: "available" },
      paper_available_cash: { value: 494172.75, source: "CALCULATED", status: "available" },
      capital_used: { value: 5827.25, source: "ESTIMATED", status: "available" },
      remaining_capital: { value: 494172.75, source: "CALCULATED", status: "available" },
      roc_inputs: { pnl: 1200, capital_used: 5827.25, available: true },
      strategies: [],
      generated_at: "2026-08-16T10:00:00+00:00",
      status: "partial",
    });

    expect(d.premiumOutlay.value).toBe(5827.25);
    expect(d.premiumOutlay.source).toBe("CALCULATED");
    expect(d.brokerMargin.value).toBeNull();
    expect(d.brokerMargin.source).toBe("BROKER_REPORTED");
    expect(d.estimatedCapitalBasis).toBe("premium");
    expect(rocInputsAvailable(d.rocInputs)).toBe(true);
    expect(d.status).toBe("partial");
  });

  it("source and status labels are explicit", () => {
    expect(sourceLabel("BROKER_REPORTED")).toBe("Broker Reported");
    expect(sourceLabel("ESTIMATED")).toBe("Estimated");
    expect(sourceLabel("CALCULATED")).toBe("Calculated");
    expect(sourceLabel("UNAVAILABLE")).toBe("Unavailable");
    expect(statusLabel("available")).toBe("Available");
    expect(statusLabel("unavailable")).toBe("Unavailable");
    // Unknown provenance never slips through as a bare label.
    expect(sourceLabel("SOMETHING_ELSE")).toBe("Unknown");
    expect(Object.keys(CAPITAL_SOURCE_LABELS).sort()).toEqual(
      ["BROKER_REPORTED", "CALCULATED", "ESTIMATED", "UNAVAILABLE"].sort()
    );
  });

  it("estimated-capital basis labels only the premium basis", () => {
    expect(estimatedBasisLabel("premium")).toBe("Premium Basis");
    expect(estimatedBasisLabel(null)).toBeNull();
    expect(estimatedBasisLabel(undefined)).toBeNull();
  });

  it("rocInputsAvailable reflects input readiness, not a computed metric", () => {
    expect(rocInputsAvailable({ pnl: 1200, capital_used: 5827.25, available: true })).toBe(true);
    expect(rocInputsAvailable({ pnl: null, capital_used: null, available: false })).toBe(false);
    expect(rocInputsAvailable(null)).toBe(false);
    expect(rocInputsAvailable(undefined)).toBe(false);
  });

  it("capitalRows renders every figure with its source and availability", () => {
    const d = capitalDisplay({
      premium_outlay: { value: 0, source: "CALCULATED", status: "available" },
      broker_margin: { value: null, source: "BROKER_REPORTED", status: "unavailable" },
      estimated_capital: { value: 5827.25, source: "ESTIMATED", status: "available" },
      estimated_capital_basis: "premium",
      broker_available_funds: { value: null, source: "BROKER_REPORTED", status: "unavailable" },
      paper_starting_capital: { value: 500000, source: "CALCULATED", status: "available" },
      paper_available_cash: { value: 494172.75, source: "CALCULATED", status: "available" },
      capital_used: { value: 5827.25, source: "ESTIMATED", status: "available" },
      remaining_capital: { value: 494172.75, source: "CALCULATED", status: "available" },
    });
    const rows = capitalRows(d);
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));

    expect(byKey.paperStartingCapital.label).toBe("Paper Starting Capital");
    expect(byKey.paperStartingCapital.value).toBe(500000);
    expect(byKey.premiumOutlay.value).toBe(0); // valid zero outlay
    expect(byKey.brokerMargin.value).toBeNull();
    expect(byKey.brokerMargin.source).toBe("Broker Reported");
    expect(byKey.brokerMargin.status).toBe("unavailable");
    expect(byKey.estimatedCapital.note).toBe("Premium Basis");
    expect(byKey.estimatedCapital.source).toBe("Estimated");
    expect(byKey.capitalUsed.value).toBe(5827.25);
  });

  it("capitalStrategyRows keeps multi-leg strategies as ONE capital unit", () => {
    const rows = capitalStrategyRows([
      {
        execution_id: "exec-1",
        strategy_tag: "Bull Call Spread",
        symbol: "NIFTY",
        entry_net: 5827.25,
        premium_outlay: 8141.25,
        estimated_capital: 5827.25,
        estimated_capital_basis: "premium",
      },
      {
        execution_id: "exec-2",
        strategy_tag: "Short Put",
        symbol: "NIFTY",
        entry_net: -5850,
        premium_outlay: 0,
        estimated_capital: null,
        estimated_capital_basis: null,
      },
    ]);

    expect(rows).toHaveLength(2);
    expect(rows[0].strategy).toBe("Bull Call Spread");
    expect(rows[0].entryNet).toBe(5827.25);
    expect(rows[0].premiumOutlay).toBe(8141.25);
    expect(rows[0].estimatedCapital).toBe(5827.25);
    expect(rows[0].estimatedCapitalBasis).toBe("Premium Basis");
    // Credit strategy: premium received is NOT capital required.
    expect(rows[1].estimatedCapital).toBeNull();
    expect(rows[1].estimatedCapitalBasis).toBeNull();
  });

  it("never presents broker margin as available or paper cash as broker funds", () => {
    const d = capitalDisplay({
      broker_margin: { value: null, source: "BROKER_REPORTED", status: "unavailable" },
      broker_available_funds: { value: null, source: "BROKER_REPORTED", status: "unavailable" },
      paper_available_cash: { value: 494172.75, source: "CALCULATED", status: "available" },
    });
    expect(d.brokerMargin.value).toBeNull();
    expect(d.brokerAvailableFunds.value).toBeNull();
    expect(d.paperAvailableCash.value).toBe(494172.75);
    expect(d.paperAvailableCash.source).toBe("CALCULATED");
  });
});
