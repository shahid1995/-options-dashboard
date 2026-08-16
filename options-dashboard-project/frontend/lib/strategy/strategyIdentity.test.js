import { describe, it, expect } from "vitest";
import {
  createStrategy,
  deriveStrategy,
  markModified,
  strategySourceLabel,
  serializeStrategy,
  newStrategyId,
} from "./strategyIdentity";

const leg = (overrides = {}) => ({ id: "l1", type: "call", action: "buy", strike: 25000, expiry: "2026-08-28", qty: 1, price: 200, ...overrides });

describe("createStrategy", () => {
  it("builds the canonical strategy shape with defaults", () => {
    const s = createStrategy({ underlying: "NIFTY", primaryExpiry: "2026-08-28", legs: [leg()] });
    expect(s).toMatchObject({
      name: "Custom Strategy",
      underlying: "NIFTY",
      primaryExpiry: "2026-08-28",
      legs: [leg()],
      source: "custom",
      status: "draft",
    });
    expect(typeof s.id).toBe("string");
    expect(s.createdAt).toBeTruthy();
    expect(s.updatedAt).toBeTruthy();
  });

  it("keeps an explicitly supplied id and timestamps", () => {
    const s = createStrategy({ id: "fixed-id", name: "My Hedge", createdAt: "2026-01-01T00:00:00.000Z", source: "template" });
    expect(s.id).toBe("fixed-id");
    expect(s.name).toBe("My Hedge");
    expect(s.source).toBe("template");
    expect(s.createdAt).toBe("2026-01-01T00:00:00.000Z");
  });

  it("clamps invalid source/status values to safe defaults", () => {
    const s = createStrategy({ source: "banana", status: "done" });
    expect(s.source).toBe("custom");
    expect(s.status).toBe("draft");
  });
});

describe("strategy identity lifecycle", () => {
  it("a template strategy starts as a template", () => {
    const s = createStrategy({ name: "Bull Call Spread", source: "template" });
    expect(strategySourceLabel(s.source)).toBe("TEMPLATE");
  });

  it("editing a template marks it modified but keeps its name", () => {
    const template = createStrategy({ name: "Bull Call Spread", source: "template" });
    const modified = markModified(template);
    expect(modified.source).toBe("modified");
    expect(modified.name).toBe("Bull Call Spread"); // never silently renamed
    expect(strategySourceLabel(modified.source)).toBe("MODIFIED");
  });

  it("a custom strategy stays custom when edited", () => {
    const custom = createStrategy({ name: "My NIFTY Hedge", source: "custom" });
    expect(markModified(custom).source).toBe("custom");
  });

  it("a saved template is treated like a template when edited", () => {
    const saved = createStrategy({ name: "Iron Condor", source: "saved" });
    expect(markModified(saved).source).toBe("modified");
  });
});

describe("deriveStrategy", () => {
  it("keeps identity fields stable across derivation", () => {
    const s1 = deriveStrategy({ id: "abc", name: "Bull Call Spread", underlying: "NIFTY", primaryExpiry: "2026-08-28", legs: [leg()], source: "template", createdAt: "2026-01-01T00:00:00.000Z" });
    const s2 = deriveStrategy({ id: "abc", name: "Bull Call Spread", underlying: "NIFTY", primaryExpiry: "2026-08-28", legs: [leg({ id: "l2" })], source: "modified", createdAt: "2026-01-01T00:00:00.000Z" });
    expect(s2.id).toBe("abc");
    expect(s2.createdAt).toBe("2026-01-01T00:00:00.000Z");
    expect(s2.legs).toEqual([leg({ id: "l2" })]);
    expect(s2.source).toBe("modified");
    expect(s2.updatedAt >= s1.updatedAt).toBe(true);
  });
});

describe("serializeStrategy", () => {
  it("snapshots the strategy and deep-copies legs", () => {
    const s = createStrategy({ name: "Iron Condor", underlying: "BANKNIFTY", primaryExpiry: "2026-08-28", legs: [leg()], source: "saved" });
    const snap = serializeStrategy(s);
    expect(snap).toMatchObject({ id: s.id, name: "Iron Condor", underlying: "BANKNIFTY", primaryExpiry: "2026-08-28", source: "saved" });
    snap.legs[0].price = 999;
    expect(s.legs[0].price).toBe(200); // stored snapshot is independent
  });
});

describe("newStrategyId", () => {
  it("produces unique ids", () => {
    const a = newStrategyId();
    const b = newStrategyId();
    expect(a).not.toBe(b);
    expect(a).toMatch(/^strategy-/);
  });
});
