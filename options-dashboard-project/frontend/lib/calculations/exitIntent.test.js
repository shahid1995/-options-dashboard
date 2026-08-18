// ---------------------------------------------------------------------------
// Phase 6.5.0 — Exit Intent / Selector Foundation (pure domain tests).
//
// The module under test RESOLVES exit targets only. It never executes orders,
// never calculates fills, never mutates positions/cash, never calls broker or
// network APIs, and never bypasses the existing paper execution engine.
//
// Authoritative exposure: the existing NETTED position model (signed
// net_quantity, BUY = + / SELL = −). The current schema ALREADY preserves
// BUY/SELL attribution (position net sign + order-level `action`/`option_type`
// under strategy_execution_id) — no new persistence model is introduced.
// ---------------------------------------------------------------------------
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  resolveExitTargets,
  normalizeSelector,
  selectorLabel,
  exposureFromPosition,
  EXIT_SCOPE,
  EXIT_QUANTITY_MODE,
  OPTION_TYPE,
  SIDE,
  EXIT_ERROR,
} from "./exitIntent";

// ---- Fixtures ---------------------------------------------------------------
//
// Backend PositionOut shape (what GET /paper/positions returns): option_type
// lowercase, net_quantity SIGNED (BUY = +, SELL = −), status open|closed.
// The resolver also accepts the frontend shape via exposureFromPosition.

const pos = (overrides) => ({
  id: 1,
  symbol: "NIFTY",
  expiry: "2026-08-18",
  strike: 25000,
  option_type: "call",
  net_quantity: 2, // + = BUY side, − = SELL side
  average_entry_price: 100,
  lot_size: 65,
  realized_pnl: 0,
  status: "open",
  strategy_execution_id: "exec-1",
  strategy_tag: "Bull Call Spread",
  ...overrides,
});

// Bull Call Spread (exec-1): BUY CE 25000 + SELL CE 25100, 2 lots each.
const bcsBuyCe = pos({ id: 1, strike: 25000, option_type: "call", net_quantity: 2 });
const bcsSellCe = pos({ id: 2, strike: 25100, option_type: "call", net_quantity: -2 });

// Bull Put Spread (exec-2): SELL PE 24800 + BUY PE 24700, 1 lot each.
const bpsSellPe = pos({ id: 3, strike: 24800, option_type: "put", net_quantity: -1, strategy_execution_id: "exec-2", strategy_tag: "Bull Put Spread" });
const bpsBuyPe = pos({ id: 4, strike: 24700, option_type: "put", net_quantity: 1, strategy_execution_id: "exec-2", strategy_tag: "Bull Put Spread" });

// Long Put (exec-3): BUY PE 24500, 3 lots.
const longPut = pos({ id: 5, strike: 24500, option_type: "put", net_quantity: 3, strategy_execution_id: "exec-3", strategy_tag: "Long Put" });

const allPositions = [bcsBuyCe, bcsSellCe, bpsSellPe, bpsBuyPe, longPut];

const intent = (overrides) => ({
  scope: EXIT_SCOPE.PORTFOLIO,
  selector: {},
  quantityMode: EXIT_QUANTITY_MODE.ALL,
  ...overrides,
});

const targetIds = (result) => result.targets.map((t) => t.positionId);

// ---------------------------------------------------------------------------
// Selector combinations (Phase 6.5.0 requirement list)
// ---------------------------------------------------------------------------
describe("resolveExitTargets — selector combinations", () => {
  it("ALL matches every open exposure of the scope", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), allPositions);
    expect(r.ok).toBe(true);
    expect(targetIds(r).sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5]);
  });

  it("CALL / CE matches only call options", () => {
    const r = resolveExitTargets(intent({ selector: { optionType: "CALL" } }), allPositions);
    expect(r.ok).toBe(true);
    expect(targetIds(r).sort((a, b) => a - b)).toEqual([1, 2]);
    const put = resolveExitTargets(intent({ selector: { optionType: "CE" } }), allPositions);
    expect(targetIds(put).sort((a, b) => a - b)).toEqual([1, 2]);
  });

  it("PUT / PE matches only put options", () => {
    const r = resolveExitTargets(intent({ selector: { optionType: "PUT" } }), allPositions);
    expect(targetIds(r).sort((a, b) => a - b)).toEqual([3, 4, 5]);
    const pe = resolveExitTargets(intent({ selector: { optionType: "pe" } }), allPositions);
    expect(targetIds(pe).sort((a, b) => a - b)).toEqual([3, 4, 5]);
  });

  it("BUY SIDE matches only long (net positive) exposures", () => {
    const r = resolveExitTargets(intent({ selector: { action: "BUY" } }), allPositions);
    expect(targetIds(r).sort((a, b) => a - b)).toEqual([1, 4, 5]);
  });

  it("SELL SIDE matches only short (net negative) exposures", () => {
    const r = resolveExitTargets(intent({ selector: { action: "SELL" } }), allPositions);
    expect(targetIds(r).sort((a, b) => a - b)).toEqual([2, 3]);
  });

  it("BUY CALL / BUY CE matches exactly the BUY CE exposure", () => {
    const r = resolveExitTargets(intent({ selector: { optionType: "CALL", action: "BUY" } }), allPositions);
    expect(targetIds(r)).toEqual([1]);
    const ce = resolveExitTargets(intent({ selector: { optionType: "CE", action: "buy" } }), allPositions);
    expect(targetIds(ce)).toEqual([1]);
  });

  it("BUY PUT / BUY PE matches exactly the BUY PE exposures", () => {
    const r = resolveExitTargets(intent({ selector: { optionType: "PUT", action: "BUY" } }), allPositions);
    expect(targetIds(r).sort((a, b) => a - b)).toEqual([4, 5]);
  });

  it("SELL CALL / SELL CE matches exactly the SELL CE exposure", () => {
    const r = resolveExitTargets(intent({ selector: { optionType: "CALL", action: "SELL" } }), allPositions);
    expect(targetIds(r)).toEqual([2]);
  });

  it("SELL PUT / SELL PE matches exactly the SELL PE exposure", () => {
    const r = resolveExitTargets(intent({ selector: { optionType: "PUT", action: "SELL" } }), allPositions);
    expect(targetIds(r)).toEqual([3]);
  });

  it("legId targets exactly one individual leg (string/number tolerant)", () => {
    const r = resolveExitTargets(intent({ selector: { legId: "3" } }), allPositions);
    expect(r.ok).toBe(true);
    expect(targetIds(r)).toEqual([3]);
    const numeric = resolveExitTargets(intent({ selector: { legId: 3 } }), allPositions);
    expect(targetIds(numeric)).toEqual([3]);
  });

  it("an unmatched selector combination reports NO_MATCHING_TARGETS", () => {
    const r = resolveExitTargets(intent({ selector: { optionType: "PUT", action: "BUY", legId: "1" } }), allPositions);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.NO_MATCHING_TARGETS);
  });
});

// ---------------------------------------------------------------------------
// Scope resolution
// ---------------------------------------------------------------------------
describe("resolveExitTargets — scope resolution", () => {
  it("POSITION scope resolves exactly the requested position", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.POSITION, positionId: 4 }), allPositions);
    expect(r.ok).toBe(true);
    expect(r.targets).toHaveLength(1);
    expect(r.targets[0].positionId).toBe(4);
    expect(r.targets[0].legId).toBe("4");
  });

  it("POSITION scope with an unknown id reports TARGET_NOT_FOUND", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.POSITION, positionId: 999 }), allPositions);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.TARGET_NOT_FOUND);
  });

  it("POSITION scope without positionId reports INVALID_INTENT", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.POSITION }), allPositions);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.INVALID_INTENT);
  });

  it("STRATEGY scope resolves only that strategy execution's positions", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.STRATEGY, strategyExecutionId: "exec-2" }), allPositions);
    expect(r.ok).toBe(true);
    expect(targetIds(r).sort((a, b) => a - b)).toEqual([3, 4]);
    for (const t of r.targets) expect(t.strategyExecutionId).toBe("exec-2");
  });

  it("STRATEGY scope for a missing execution reports TARGET_NOT_FOUND", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.STRATEGY, strategyExecutionId: "exec-nope" }), allPositions);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.TARGET_NOT_FOUND);
  });

  it("STRATEGY scope without strategyExecutionId reports INVALID_INTENT", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.STRATEGY }), allPositions);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.INVALID_INTENT);
  });

  it("STRATEGY scope never mixes positions from other strategies", () => {
    // exec-1 has no puts, but exec-2/exec-3 do — the selector must NOT leak.
    const r = resolveExitTargets(
      intent({ scope: EXIT_SCOPE.STRATEGY, strategyExecutionId: "exec-1", selector: { optionType: "PUT" } }),
      allPositions,
    );
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.NO_MATCHING_TARGETS);
  });

  it("PORTFOLIO scope reports NO_MATCHING_TARGETS when nothing is open", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), []);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.NO_MATCHING_TARGETS);
  });

  it("an unknown scope reports INVALID_INTENT", () => {
    const r = resolveExitTargets(intent({ scope: "ACCOUNT" }), allPositions);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.INVALID_INTENT);
  });
});

// ---------------------------------------------------------------------------
// Quantity safety
// ---------------------------------------------------------------------------
describe("resolveExitTargets — quantity safety", () => {
  it("ALL resolves each target at its full remaining quantity", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.STRATEGY, strategyExecutionId: "exec-3" }), allPositions);
    expect(r.ok).toBe(true);
    expect(r.targets[0].quantity).toBe(3);
    expect(r.targets[0].remainingQuantity).toBe(3);
  });

  it("QUANTITY works on an unambiguous single target (partial exit allowed)", () => {
    const r = resolveExitTargets(
      intent({ selector: { legId: "1" }, quantityMode: EXIT_QUANTITY_MODE.QUANTITY, quantity: 1 }),
      allPositions,
    );
    expect(r.ok).toBe(true);
    expect(r.targets).toHaveLength(1);
    expect(r.targets[0].quantity).toBe(1);
    expect(r.targets[0].remainingQuantity).toBe(2);
  });

  it("QUANTITY equal to the full remaining quantity is allowed", () => {
    const r = resolveExitTargets(
      intent({ selector: { optionType: "CALL", action: "SELL" }, quantityMode: EXIT_QUANTITY_MODE.QUANTITY, quantity: 2 }),
      allPositions,
    );
    expect(r.ok).toBe(true);
    expect(r.targets[0].quantity).toBe(2);
  });

  it("QUANTITY greater than the remaining quantity reports EXIT_QUANTITY_EXCEEDS_REMAINING", () => {
    const r = resolveExitTargets(
      intent({ selector: { optionType: "CALL", action: "SELL" }, quantityMode: EXIT_QUANTITY_MODE.QUANTITY, quantity: 3 }),
      allPositions,
    );
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.EXIT_QUANTITY_EXCEEDS_REMAINING);
  });

  it("QUANTITY with multiple matching targets reports AMBIGUOUS_EXIT_QUANTITY (never guessed)", () => {
    const r = resolveExitTargets(
      intent({ selector: { action: "BUY" }, quantityMode: EXIT_QUANTITY_MODE.QUANTITY, quantity: 1 }),
      allPositions,
    );
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.AMBIGUOUS_EXIT_QUANTITY);
  });

  it("QUANTITY with a broad scope reports AMBIGUOUS_EXIT_QUANTITY", () => {
    const r = resolveExitTargets(
      intent({ scope: EXIT_SCOPE.PORTFOLIO, quantityMode: EXIT_QUANTITY_MODE.QUANTITY, quantity: 2 }),
      allPositions,
    );
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.AMBIGUOUS_EXIT_QUANTITY);
  });

  it("QUANTITY without a quantity reports MISSING_QUANTITY", () => {
    const r = resolveExitTargets(
      intent({ selector: { legId: "1" }, quantityMode: EXIT_QUANTITY_MODE.QUANTITY }),
      allPositions,
    );
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.MISSING_QUANTITY);
  });

  it("QUANTITY of 0 / negative / fractional / NaN / Infinity reports INVALID_QUANTITY", () => {
    for (const bad of [0, -2, 2.5, NaN, Infinity, -Infinity]) {
      const r = resolveExitTargets(
        intent({ selector: { legId: "1" }, quantityMode: EXIT_QUANTITY_MODE.QUANTITY, quantity: bad }),
        allPositions,
      );
      expect(r.ok).toBe(false);
      expect(r.error.code).toBe(EXIT_ERROR.INVALID_QUANTITY);
    }
  });

  it("an unknown quantity mode reports INVALID_INTENT", () => {
    const r = resolveExitTargets(intent({ quantityMode: "PERCENT" }), allPositions);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.INVALID_INTENT);
  });
});

// ---------------------------------------------------------------------------
// Remaining quantity / closed / zero-quantity
// ---------------------------------------------------------------------------
describe("resolveExitTargets — remaining quantity & open state", () => {
  it("uses the CURRENT remaining quantity (net quantity), never the original order quantity", () => {
    const raw = pos({
      id: 10,
      option_type: "call",
      net_quantity: 1,
      // The original order quantity lives on the order/leg, NOT the position.
      order_quantity: 5,
    });
    const r = resolveExitTargets(intent({ selector: { legId: "10" } }), [raw]);
    expect(r.ok).toBe(true);
    expect(r.targets[0].remainingQuantity).toBe(1);
    expect(r.targets[0].quantity).toBe(1);
  });

  it("a partially-exited position resolves at its remaining quantity", () => {
    const partial = pos({ id: 11, net_quantity: 1, average_entry_price: 90 });
    const r = resolveExitTargets(intent({ selector: { legId: "11" } }), [partial]);
    expect(r.ok).toBe(true);
    expect(r.targets[0].remainingQuantity).toBe(1);
    expect(r.targets[0].quantity).toBe(1);
  });

  it("zero-quantity positions are excluded from every scope", () => {
    const zero = pos({ id: 20, net_quantity: 0 });
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.POSITION, positionId: 20 }), [zero]);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.TARGET_NOT_FOUND);
  });

  it("closed positions are excluded from every scope", () => {
    const closed = pos({ id: 21, status: "closed", net_quantity: 4 });
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.POSITION, positionId: 21 }), [closed]);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.TARGET_NOT_FOUND);
  });

  it("closed/zero-quantity positions never appear in a broader resolution", () => {
    const open = pos({ id: 22, option_type: "put", net_quantity: 2 });
    const closed = pos({ id: 23, option_type: "put", net_quantity: 5, status: "closed" });
    const zero = pos({ id: 24, option_type: "put", net_quantity: 0 });
    const r = resolveExitTargets(intent({ selector: { optionType: "PUT" } }), [open, closed, zero]);
    expect(targetIds(r)).toEqual([22]);
    expect(r.targets[0].quantity).toBe(2);
  });

  it("a strategy whose positions are all closed reports TARGET_NOT_FOUND", () => {
    const closed = pos({ id: 30, status: "closed", net_quantity: 3, strategy_execution_id: "exec-x" });
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.STRATEGY, strategyExecutionId: "exec-x" }), [closed]);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.TARGET_NOT_FOUND);
  });
});

// ---------------------------------------------------------------------------
// Deterministic ordering
// ---------------------------------------------------------------------------
describe("resolveExitTargets — deterministic ordering", () => {
  it("orders targets by optionType, side, then positionId regardless of input order", () => {
    const shuffled = [longPut, bcsSellCe, bpsBuyPe, bcsBuyCe, bpsSellPe];
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), shuffled);
    expect(r.ok).toBe(true);
    // CALL before PUT; BUY before SELL; numeric positionId as the tie-breaker.
    // PUT/BUY = ids 4, 5 (asc) then PUT/SELL = id 3.
    expect(targetIds(r)).toEqual([1, 2, 4, 5, 3]);
  });

  it("returns identical results for identical inputs", () => {
    const a = resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), allPositions);
    const b = resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), [...allPositions].reverse());
    expect(a).toEqual(b);
  });

  it("side attribution is exact: same strike/type on both sides stays two targets", () => {
    const both = [
      pos({ id: 40, strike: 25000, option_type: "call", net_quantity: 2 }),
      pos({ id: 41, strike: 25000, option_type: "call", net_quantity: -2 }),
    ];
    const r = resolveExitTargets(intent({ selector: { optionType: "CALL" } }), both);
    expect(r.ok).toBe(true);
    expect(r.targets).toHaveLength(2);
    expect(r.targets[0].side).toBe(SIDE.BUY);
    expect(r.targets[1].side).toBe(SIDE.SELL);
  });
});

// ---------------------------------------------------------------------------
// User isolation
// ---------------------------------------------------------------------------
describe("resolveExitTargets — user isolation", () => {
  const mine = [
    pos({ id: 50, option_type: "call", net_quantity: 2, userId: "user-a", strategy_execution_id: "exec-a" }),
    pos({ id: 51, option_type: "put", net_quantity: -1, userId: "user-a", strategy_execution_id: "exec-a" }),
  ];
  const theirs = [
    pos({ id: 60, option_type: "call", net_quantity: 9, userId: "user-b", strategy_execution_id: "exec-b" }),
    pos({ id: 61, option_type: "put", net_quantity: -9, userId: "user-b", strategy_execution_id: "exec-b" }),
  ];
  const mixed = [...mine, ...theirs];

  it("PORTFOLIO scope never includes another user's positions", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), mixed, { userId: "user-a" });
    expect(r.ok).toBe(true);
    expect(targetIds(r).sort((a, b) => a - b)).toEqual([50, 51]);
  });

  it("STRATEGY scope targeting another user's execution reports TARGET_NOT_FOUND", () => {
    const r = resolveExitTargets(
      intent({ scope: EXIT_SCOPE.STRATEGY, strategyExecutionId: "exec-b" }),
      mixed,
      { userId: "user-a" },
    );
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.TARGET_NOT_FOUND);
  });

  it("POSITION scope targeting another user's position reports TARGET_NOT_FOUND", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.POSITION, positionId: 61 }), mixed, { userId: "user-a" });
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.TARGET_NOT_FOUND);
  });

  it("foreign positions never appear in targets even without an explicit userId (caller-filtered)", () => {
    // No options.userId → the resolver trusts the caller's pool (same as the
    // backend's user-scoped query); every target still carries its identity.
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), [mine[0], theirs[0]]);
    expect(r.ok).toBe(true);
    expect(r.targets).toHaveLength(2);
    expect(r.targets.map((t) => t.userId ?? null)).toEqual([null, null]); // no userId leak in output
  });
});

// ---------------------------------------------------------------------------
// Selector normalization / labels
// ---------------------------------------------------------------------------
describe("normalizeSelector / selectorLabel", () => {
  it("normalizes CE/PE and buy/sell case-insensitively", () => {
    expect(normalizeSelector({ optionType: "CE", action: "SELL" })).toEqual({
      optionType: OPTION_TYPE.CALL,
      action: SIDE.SELL,
      legId: null,
    });
    expect(normalizeSelector({ optionType: "put", action: "buy" })).toEqual({
      optionType: OPTION_TYPE.PUT,
      action: SIDE.BUY,
      legId: null,
    });
    expect(normalizeSelector({ legId: 7 })).toEqual({ optionType: null, action: null, legId: "7" });
  });

  it("rejects unrecognized option types / actions", () => {
    expect(normalizeSelector({ optionType: "FUT" })).toBeNull();
    expect(normalizeSelector({ action: "HOLD" })).toBeNull();
    expect(normalizeSelector("nope")).toBeNull();
    expect(normalizeSelector(null)).toBeNull();
  });

  it("labels every supported combination", () => {
    expect(selectorLabel({})).toBe("ALL");
    expect(selectorLabel({ optionType: "CALL" })).toBe("CALL");
    expect(selectorLabel({ optionType: "PUT" })).toBe("PUT");
    expect(selectorLabel({ action: "BUY" })).toBe("BUY");
    expect(selectorLabel({ action: "SELL" })).toBe("SELL");
    expect(selectorLabel({ optionType: "CALL", action: "BUY" })).toBe("BUY CALL");
    expect(selectorLabel({ optionType: "PUT", action: "BUY" })).toBe("BUY PUT");
    expect(selectorLabel({ optionType: "CALL", action: "SELL" })).toBe("SELL CALL");
    expect(selectorLabel({ optionType: "PUT", action: "SELL" })).toBe("SELL PUT");
    expect(selectorLabel({ legId: "9" })).toBe("LEG 9");
  });
});

// ---------------------------------------------------------------------------
// exposureFromPosition — authoritative position mapping
// ---------------------------------------------------------------------------
describe("exposureFromPosition", () => {
  it("maps the backend PositionOut shape (signed net_quantity → side + remaining)", () => {
    const e = exposureFromPosition(pos({ id: 1, option_type: "call", net_quantity: 2, strategy_execution_id: "exec-1" }));
    expect(e.positionId).toBe(1);
    expect(e.optionType).toBe(OPTION_TYPE.CALL);
    expect(e.side).toBe(SIDE.BUY);
    expect(e.remainingQuantity).toBe(2);
    expect(e.strategyExecutionId).toBe("exec-1");

    const short = exposureFromPosition(pos({ id: 2, net_quantity: -2 }));
    expect(short.side).toBe(SIDE.SELL);
    expect(short.remainingQuantity).toBe(2);
  });

  it("maps the frontend shape (action + qty)", () => {
    const e = exposureFromPosition({
      positionId: 5,
      type: "put",
      action: "buy",
      qty: 3,
      executionId: "exec-3",
      status: "open",
    });
    expect(e.optionType).toBe(OPTION_TYPE.PUT);
    expect(e.side).toBe(SIDE.BUY);
    expect(e.remainingQuantity).toBe(3);
    expect(e.strategyExecutionId).toBe("exec-3");
  });

  it("prefers an explicit remainingQuantity when provided", () => {
    const e = exposureFromPosition(pos({ id: 1, net_quantity: 4, remainingQuantity: 2 }));
    expect(e.remainingQuantity).toBe(2);
  });

  it("returns null for unusable input", () => {
    expect(exposureFromPosition(null)).toBeNull();
    expect(exposureFromPosition({})).toBeNull();
    expect(exposureFromPosition("x")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Contract safety
// ---------------------------------------------------------------------------
describe("resolveExitTargets — contract safety", () => {
  it("never mutates inputs and never executes anything", () => {
    const snapshot = JSON.stringify(allPositions);
    resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), allPositions);
    resolveExitTargets(
      intent({ selector: { legId: "1" }, quantityMode: EXIT_QUANTITY_MODE.QUANTITY, quantity: 1 }),
      allPositions,
    );
    expect(JSON.stringify(allPositions)).toBe(snapshot);
  });

  it("targets always carry identity + executable quantity <= remaining", () => {
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.PORTFOLIO }), allPositions);
    for (const t of r.targets) {
      expect(t.positionId).toBeDefined();
      expect(t.legId).toBe(String(t.positionId));
      expect(t.optionType).toMatch(/^(CALL|PUT)$/);
      expect(t.side).toMatch(/^(BUY|SELL)$/);
      expect(Number.isInteger(t.quantity)).toBe(true);
      expect(t.quantity).toBeGreaterThan(0);
      expect(t.quantity).toBeLessThanOrEqual(t.remainingQuantity);
    }
  });

  it("NaN/Infinity remaining quantities are treated as unavailable (excluded, never 0)", () => {
    const bad = pos({ id: 70, net_quantity: NaN });
    const r = resolveExitTargets(intent({ scope: EXIT_SCOPE.POSITION, positionId: 70 }), [bad]);
    expect(r.ok).toBe(false);
    expect(r.error.code).toBe(EXIT_ERROR.TARGET_NOT_FOUND);
  });

  it("invalid intents report INVALID_INTENT without crashing", () => {
    for (const bad of [null, undefined, 42, "x", {}]) {
      const r = resolveExitTargets(bad, allPositions);
      expect(r.ok).toBe(false);
      expect(r.error.code).toBe(EXIT_ERROR.INVALID_INTENT);
    }
  });
});

// ---------------------------------------------------------------------------
// No network / broker dependency
// ---------------------------------------------------------------------------
describe("exitIntent — pure domain, no I/O", () => {
  it("the module makes no broker/network calls (static audit)", async () => {
    const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "exitIntent.js"), "utf8");
    expect(source).not.toMatch(/fetch\s*\(/);
    expect(source).not.toMatch(/axios/);
    expect(source).not.toMatch(/XMLHttpRequest/);
    expect(source).not.toMatch(/WebSocket/);
    expect(source).not.toMatch(/node:http/);
    expect(source).not.toMatch(/^import\s/m);
    expect(source).not.toMatch(/require\s*\(/);
  });

  it("the module exports no execution surface", () => {
    // resolveExitTargets returns pure data; there is no execute/place/order API.
    expect(typeof resolveExitTargets).toBe("function");
    expect(Object.keys({ resolveExitTargets, normalizeSelector, selectorLabel, exposureFromPosition }).sort()).toEqual(
      ["exposureFromPosition", "normalizeSelector", "resolveExitTargets", "selectorLabel"],
    );
  });
});
