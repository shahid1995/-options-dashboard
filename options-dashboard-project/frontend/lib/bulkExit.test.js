import { describe, it, expect } from "vitest";
import {
  buildBulkExitRequest,
  bulkExitDisplay,
  openStrategyGroups,
} from "./portfolio";

const LOT = 65;

const pos = (overrides) => ({
  positionId: 1,
  id: "pos-1",
  symbol: "NIFTY",
  type: "call",
  strike: 24350,
  expiry: "2026-08-27",
  action: "buy",
  qty: 1,
  lotSize: LOT,
  entryPremium: 125.25,
  executionId: "exec-1",
  strategyName: "Bull Call Spread",
  currentLtp: 135.0,
  unrealizedPnl: (135.0 - 125.25) * LOT,
  ...overrides,
});

describe("buildBulkExitRequest", () => {
  it("carries one idempotency key for the whole operation", () => {
    const req = buildBulkExitRequest("exit-strat");
    expect(req.client_order_id.startsWith("exit-strat-")).toBe(true);
    expect(req.client_order_id.length).toBeGreaterThanOrEqual(8);
  });

  it("defaults to the exit-all prefix", () => {
    expect(buildBulkExitRequest().client_order_id.startsWith("exit-all-")).toBe(true);
  });

  it("is unique across calls (double-submit protection)", () => {
    expect(buildBulkExitRequest("exit-all").client_order_id).not.toBe(
      buildBulkExitRequest("exit-all").client_order_id
    );
  });
});

describe("openStrategyGroups", () => {
  it("groups open positions by strategy execution", () => {
    const groups = openStrategyGroups([
      pos({ positionId: 1, executionId: "exec-1", strategyName: "Bull Call Spread", qty: 1, currentLtp: 100, unrealizedPnl: 10 }),
      pos({ positionId: 2, executionId: "exec-1", strategyName: "Bull Call Spread", qty: 2, currentLtp: 200, unrealizedPnl: 20 }),
      pos({ positionId: 3, executionId: "exec-2", strategyName: "Long Call", qty: 1, currentLtp: 300, unrealizedPnl: 30 }),
    ]);
    expect(groups).toHaveLength(2);
    const spread = groups.find((g) => g.executionId === "exec-1");
    expect(spread.strategyName).toBe("Bull Call Spread");
    expect(spread.positions).toHaveLength(2);
    expect(spread.value).toBe(100 * 1 * LOT + 200 * 2 * LOT);
    expect(spread.unrealized).toBe(30);
    expect(spread.isStrategy).toBe(true);
    const long = groups.find((g) => g.executionId === "exec-2");
    expect(long.positions).toHaveLength(1);
  });

  it("puts positions without an execution into a standalone group", () => {
    const groups = openStrategyGroups([
      pos({ positionId: 1, executionId: null, strategyName: "Custom" }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].executionId).toBeNull();
    expect(groups[0].strategyName).toBe("Standalone");
    expect(groups[0].isStrategy).toBe(false);
  });

  it("returns null value/unrealized when no market mark exists (never 0)", () => {
    const groups = openStrategyGroups([
      pos({ positionId: 1, executionId: "exec-1", currentLtp: null, unrealizedPnl: null }),
    ]);
    expect(groups[0].value).toBeNull();
    expect(groups[0].unrealized).toBeNull();
  });

  it("handles empty input", () => {
    expect(openStrategyGroups([])).toEqual([]);
    expect(openStrategyGroups(null)).toEqual([]);
  });
});

describe("bulkExitDisplay", () => {
  it("shapes a SUCCESS result", () => {
    const d = bulkExitDisplay({
      scope: "ACCOUNT",
      status: "SUCCESS",
      requested_count: 3,
      exited_count: 3,
      failed_count: 0,
      total_realized_pnl: 1234.5,
      cash_change: 6789.0,
      positions: [],
      groups: [{ strategy_tag: "Long Call", exited: 1 }],
      errors: [],
      duplicated: false,
    });
    expect(d.status).toBe("SUCCESS");
    expect(d.exitedCount).toBe(3);
    expect(d.totalRealizedPnl).toBe(1234.5);
    expect(d.duplicated).toBe(false);
  });

  it("derives failedCount from the position list when the field is missing", () => {
    const d = bulkExitDisplay({
      status: "PARTIAL",
      requested_count: 2,
      exited_count: 1,
      positions: [
        { status: "EXITED" },
        { status: "FAILED", error: "boom" },
      ],
    });
    expect(d.failedCount).toBe(1);
    expect(d.positions[1].error).toBe("boom");
  });

  it("tolerates an empty/missing result (render safety)", () => {
    const d = bulkExitDisplay(null);
    expect(d.status).toBe("FAILED");
    expect(d.requestedCount).toBe(0);
    expect(d.positions).toEqual([]);
    expect(d.errors).toEqual([]);
  });
});
