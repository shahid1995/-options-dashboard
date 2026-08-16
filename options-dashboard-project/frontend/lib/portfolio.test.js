import { describe, it, expect } from "vitest";
import {
  buildExecutionRequest,
  buildExitRequest,
  canTrade,
  makeClientOrderId,
  paperErrorMessage,
  portfolioDisplay,
  toFrontendPosition,
  unrealizedPnl,
  validateExitQuantity,
} from "./portfolio";

const LOT = 65;

describe("makeClientOrderId", () => {
  it("is unique across calls (protects double clicks / retries)", () => {
    expect(makeClientOrderId()).not.toBe(makeClientOrderId());
    expect(makeClientOrderId("exec")).not.toBe(makeClientOrderId("exec"));
  });

  it("is prefixed and bounded to 64 chars", () => {
    const id = makeClientOrderId("exit");
    expect(id.startsWith("exit-")).toBe(true);
    expect(id.length).toBeLessThanOrEqual(64);
  });
});

describe("toFrontendPosition", () => {
  it("maps a long backend position to the UI shape", () => {
    const p = toFrontendPosition({
      id: 7,
      symbol: "NIFTY",
      expiry: "2026-08-27",
      strike: 24350,
      option_type: "call",
      net_quantity: 2,
      average_entry_price: 125.25,
      lot_size: LOT,
      realized_pnl: 0,
      status: "open",
      strategy_execution_id: "abc123",
      strategy_tag: "Long Call",
      opened_at: "2026-08-16T04:00:00Z",
    });
    expect(p).toMatchObject({
      positionId: 7,
      id: "pos-7",
      type: "call",
      action: "buy",
      qty: 2,
      lotSize: LOT,
      entryPremium: 125.25,
      strategyName: "Long Call",
      executionId: "abc123",
      status: "open",
    });
  });

  it("derives action sell from a negative net quantity", () => {
    const p = toFrontendPosition({ id: 8, symbol: "NIFTY", expiry: "2026-08-27", strike: 24550, option_type: "call", net_quantity: -1, average_entry_price: 35.6, lot_size: LOT, realized_pnl: 0, status: "open", strategy_execution_id: null });
    expect(p.action).toBe("sell");
    expect(p.qty).toBe(1);
    expect(p.strategyName).toBe("Custom");
  });
});

describe("unrealizedPnl", () => {
  it("long: (price − avg) × qty × lot", () => {
    const pos = { action: "buy", entryPremium: 100, lotSize: LOT, qty: 2 };
    expect(unrealizedPnl(pos, 120)).toBe(20 * 2 * LOT);
  });

  it("short: (avg − price) × qty × lot", () => {
    const pos = { action: "sell", entryPremium: 100, lotSize: LOT, qty: 2 };
    expect(unrealizedPnl(pos, 90)).toBe(10 * 2 * LOT);
  });

  it("returns null (not 0) when no market mark is available", () => {
    expect(unrealizedPnl({ action: "buy", entryPremium: 100, lotSize: LOT, qty: 1 }, null)).toBeNull();
  });
});

describe("validateExitQuantity", () => {
  const pos = { qty: 5 };

  it("rejects zero / negative / non-integer quantities", () => {
    expect(validateExitQuantity(pos, 0).ok).toBe(false);
    expect(validateExitQuantity(pos, -1).ok).toBe(false);
    expect(validateExitQuantity(pos, 1.5).ok).toBe(false);
  });

  it("rejects quantities above the available position (insufficient)", () => {
    const r = validateExitQuantity(pos, 6);
    expect(r.ok).toBe(false);
    expect(r.error).toContain("Only 5 lot(s)");
  });

  it("allows partial exits", () => {
    expect(validateExitQuantity(pos, 2)).toEqual({ ok: true });
  });

  it("allows full exits", () => {
    expect(validateExitQuantity(pos, 5)).toEqual({ ok: true });
  });
});

describe("paperErrorMessage", () => {
  it("surfaces the human part of a structured backend error", () => {
    const err = { response: { data: { detail: "CHAIN_DATA_MISSING: Market data unavailable for NIFTY 24550 CALL (2026-08-27). Paper order was not executed." } } };
    expect(paperErrorMessage(err)).toContain("Market data unavailable");
  });

  it("uses the per-code default when the backend sends only the code", () => {
    const err = { response: { data: { detail: "INSUFFICIENT_POSITION: Only 1 lot(s) available to exit." } } };
    expect(paperErrorMessage(err)).toContain("Only 1 lot(s)");
    const codeOnly = { response: { data: { detail: "EXECUTION_FAILED: " } } };
    expect(paperErrorMessage(codeOnly)).toBe("The paper order could not be executed.");
  });

  it("passes through plain messages and falls back when nothing is usable", () => {
    expect(paperErrorMessage({ message: "Market is closed." })).toBe("Market is closed.");
    expect(paperErrorMessage(new Error("Network Error"))).toBe("Network Error");
    expect(paperErrorMessage({})).toBe("The paper order could not be executed.");
  });
});

describe("portfolioDisplay", () => {
  it("shapes a full backend summary with separate realized/unrealized", () => {
    const d = portfolioDisplay({
      summary: {
        starting_cash: 500000,
        available_cash: 491858.75,
        invested_value: 8141.25,
        realized_pnl: 1300,
        unrealized_pnl: null,
        total_pnl: 1300,
        open_position_count: 1,
        open_strategy_count: 1,
      },
    });
    expect(d.availableCash).toBe(491858.75);
    expect(d.realizedPnl).toBe(1300);
    expect(d.unrealizedPnl).toBeNull(); // marks come from the chain cache, never fabricated
    expect(d.totalPnl).toBe(1300);
    expect(d.openPositionCount).toBe(1);
  });

  it("handles an empty/missing portfolio (empty state)", () => {
    const d = portfolioDisplay(null);
    expect(d.startingCash).toBe(500000);
    expect(d.availableCash).toBeNull();
    expect(d.openPositionCount).toBe(0);
    expect(d.realizedPnl).toBe(0);
  });
});

describe("canTrade", () => {
  it("enables trading only when the market is verified open", () => {
    expect(canTrade({ status: "open" })).toBe(true);
    expect(canTrade({ status: "closed" })).toBe(false);
    expect(canTrade({ status: "unknown" })).toBe(false);
    expect(canTrade(null)).toBe(false);
    expect(canTrade(undefined)).toBe(false);
  });
});

describe("buildExecutionRequest", () => {
  it("is idempotent-shaped and maps builder legs to backend legs", () => {
    const req = buildExecutionRequest({
      symbol: "NIFTY",
      strategy: { name: "Bull Call Spread", id: "strat-9" },
      legs: [
        { type: "call", strike: 24350, expiry: "2026-08-27", action: "buy", qty: 1 },
        { type: "call", strike: 24550, expiry: "2026-08-27", action: "sell", qty: 1 },
      ],
      lotSize: LOT,
      multiplier: 1,
      startingCapital: 500000,
    });
    expect(req.client_order_id.length).toBeGreaterThanOrEqual(8);
    expect(req.strategy_tag).toBe("Bull Call Spread");
    expect(req.strategy_id).toBe("strat-9");
    expect(req.legs).toHaveLength(2);
    expect(req.legs[0]).toEqual({
      symbol: "NIFTY",
      expiration_date: "2026-08-27",
      strike_price: 24350,
      option_type: "call",
      action: "buy",
      quantity: 1,
      lot_size: LOT,
    });
  });

  it("scales quantity by the multiplier (contracts)", () => {
    const req = buildExecutionRequest({
      symbol: "NIFTY",
      strategy: null,
      legs: [{ type: "put", strike: 24000, expiry: "2026-08-27", action: "buy", qty: 2 }],
      lotSize: LOT,
      multiplier: 3,
      startingCapital: 500000,
    });
    expect(req.legs[0].quantity).toBe(6);
  });
});

describe("buildExitRequest", () => {
  it("carries an idempotency key and the requested quantity", () => {
    const req = buildExitRequest(2);
    expect(req.client_order_id.startsWith("exit-")).toBe(true);
    expect(req.quantity).toBe(2);
  });
});
