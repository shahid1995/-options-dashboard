import { describe, it, expect } from "vitest";
import {
  detectResolutionChanges,
  resolvedLegSummary,
} from "./templates";

describe("Phase 6.8E: detectResolutionChanges", () => {
  it("returns empty array when both are null", () => {
    expect(detectResolutionChanges(null, null)).toEqual([]);
  });

  it("returns empty array when resolutions are identical", () => {
    const prev = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-27" },
        { resolved_strike: 25200, resolved_expiry: "2026-08-27" },
      ],
    };
    const next = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-27" },
        { resolved_strike: 25200, resolved_expiry: "2026-08-27" },
      ],
    };
    expect(detectResolutionChanges(prev, next)).toEqual([]);
  });

  it("detects strike change", () => {
    const prev = {
      legs: [{ resolved_strike: 25000, resolved_expiry: "2026-08-27" }],
    };
    const next = {
      legs: [{ resolved_strike: 25100, resolved_expiry: "2026-08-27" }],
    };
    const changes = detectResolutionChanges(prev, next);
    expect(changes).toHaveLength(1);
    expect(changes[0]).toEqual({
      position: 0,
      field: "strike",
      oldValue: 25000,
      newValue: 25100,
    });
  });

  it("detects expiry change", () => {
    const prev = {
      legs: [{ resolved_strike: 25000, resolved_expiry: "2026-08-27" }],
    };
    const next = {
      legs: [{ resolved_strike: 25000, resolved_expiry: "2026-09-03" }],
    };
    const changes = detectResolutionChanges(prev, next);
    expect(changes).toHaveLength(1);
    expect(changes[0]).toEqual({
      position: 0,
      field: "expiry",
      oldValue: "2026-08-27",
      newValue: "2026-09-03",
    });
  });

  it("detects both strike and expiry change on same leg", () => {
    const prev = {
      legs: [{ resolved_strike: 25000, resolved_expiry: "2026-08-27" }],
    };
    const next = {
      legs: [{ resolved_strike: 25100, resolved_expiry: "2026-09-03" }],
    };
    const changes = detectResolutionChanges(prev, next);
    expect(changes).toHaveLength(2);
    expect(changes.map((c) => c.field)).toEqual(["strike", "expiry"]);
  });

  it("detects changes across multiple legs", () => {
    const prev = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-27" },
        { resolved_strike: 25200, resolved_expiry: "2026-08-27" },
      ],
    };
    const next = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-27" }, // same
        { resolved_strike: 25300, resolved_expiry: "2026-09-03" }, // both changed
      ],
    };
    const changes = detectResolutionChanges(prev, next);
    expect(changes).toHaveLength(2);
    expect(changes[0].position).toBe(1);
    expect(changes[1].position).toBe(1);
  });

  it("handles prev with no legs", () => {
    const next = {
      legs: [{ resolved_strike: 25000, resolved_expiry: "2026-08-27" }],
    };
    expect(detectResolutionChanges(null, next)).toEqual([]);
  });

  it("handles different leg counts gracefully", () => {
    const prev = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-27" },
        { resolved_strike: 25200, resolved_expiry: "2026-08-27" },
      ],
    };
    const next = {
      legs: [{ resolved_strike: 25000, resolved_expiry: "2026-08-27" }],
    };
    expect(detectResolutionChanges(prev, next)).toEqual([]);
  });
});

describe("Phase 6.8E: resolvedLegSummary", () => {
  it("returns strike and expiry for fixed mode", () => {
    const leg = {
      resolved_strike: 25000,
      resolved_expiry: "2026-08-27",
      strike_mode_used: "fixed",
      expiry_mode_used: "fixed",
    };
    expect(resolvedLegSummary(leg)).toBe("25000, 2026-08-27");
  });

  it("shows ATM formula with resolved values", () => {
    const leg = {
      resolved_strike: 25100,
      resolved_expiry: "2026-08-27",
      strike_mode_used: "atm_offset_steps",
      expiry_mode_used: "fixed",
    };
    expect(resolvedLegSummary(leg)).toBe("ATM_OFFSET_STEPS → 25100, 2026-08-27");
  });

  it("shows both formula modes", () => {
    const leg = {
      resolved_strike: 25200,
      resolved_expiry: "2026-09-03",
      strike_mode_used: "atm",
      expiry_mode_used: "next_week",
    };
    expect(resolvedLegSummary(leg)).toBe("ATM → 25200, next week → 2026-09-03");
  });

  it("returns empty string for null leg", () => {
    expect(resolvedLegSummary(null)).toBe("");
  });
});

// ---- Phase 6.9: detectResolutionChanges for execution preview ----

describe("Phase 6.9: detectResolutionChanges for execution preview", () => {
  it("detects strike change between preview and fresh resolution", () => {
    const preview = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-20" },
      ],
    };
    const fresh = {
      legs: [
        { resolved_strike: 25050, resolved_expiry: "2026-08-20" },
      ],
    };
    const changes = detectResolutionChanges(preview, fresh);
    expect(changes).toHaveLength(1);
    expect(changes[0].field).toBe("strike");
    expect(changes[0].oldValue).toBe(25000);
    expect(changes[0].newValue).toBe(25050);
  });

  it("detects expiry change between preview and fresh resolution", () => {
    const preview = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-20" },
      ],
    };
    const fresh = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-27" },
      ],
    };
    const changes = detectResolutionChanges(preview, fresh);
    expect(changes).toHaveLength(1);
    expect(changes[0].field).toBe("expiry");
  });

  it("returns empty when preview and fresh are identical", () => {
    const data = {
      legs: [
        { resolved_strike: 25000, resolved_expiry: "2026-08-20" },
        { resolved_strike: 25200, resolved_expiry: "2026-08-20" },
      ],
    };
    expect(detectResolutionChanges(data, { ...data })).toEqual([]);
  });
});
