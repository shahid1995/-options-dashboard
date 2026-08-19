import { describe, it, expect } from "vitest";
import {
  templateLegToFrontend,
  templateToFrontendLegs,
  frontendLegsToTemplatePayload,
  frontendLegsToUpdatePayload,
  legSummary,
  legCountLabel,
} from "./templates";

describe("templateLegToFrontend", () => {
  it("converts a backend template leg to frontend format", () => {
    const leg = {
      id: 1,
      template_id: 10,
      position: 0,
      action: "buy",
      option_type: "call",
      strike: 25000,
      expiry: "2026-08-28",
      quantity: 2,
      lot_size: 50,
      price: 142.5,
    };
    const result = templateLegToFrontend(leg);
    expect(result.type).toBe("call");
    expect(result.action).toBe("buy");
    expect(result.strike).toBe(25000);
    expect(result.qty).toBe(2);
    expect(result.expiry).toBe("2026-08-28");
    expect(result.price).toBe(142.5);
    expect(result.lotSize).toBe(50);
    expect(result.templateLegId).toBe(1);
    expect(result.id).toContain("tpl-10-0-");
  });

  it("uses 0 for null price", () => {
    const leg = {
      id: 1,
      template_id: 5,
      position: 0,
      action: "sell",
      option_type: "put",
      strike: 24500,
      expiry: "2026-08-28",
      quantity: 1,
      lot_size: 50,
      price: null,
    };
    const result = templateLegToFrontend(leg);
    expect(result.price).toBe(0);
  });
});

describe("templateToFrontendLegs", () => {
  it("converts and sorts legs by position", () => {
    const template = {
      legs: [
        { id: 2, template_id: 10, position: 1, action: "sell", option_type: "call", strike: 25500, expiry: "2026-08-28", quantity: 1, lot_size: 50, price: 100 },
        { id: 1, template_id: 10, position: 0, action: "buy", option_type: "call", strike: 24500, expiry: "2026-08-28", quantity: 1, lot_size: 50, price: 200 },
      ],
    };
    const result = templateToFrontendLegs(template);
    expect(result).toHaveLength(2);
    expect(result[0].strike).toBe(24500); // position 0 first
    expect(result[1].strike).toBe(25500); // position 1 second
  });

  it("handles empty legs array", () => {
    expect(templateToFrontendLegs({ legs: [] })).toEqual([]);
    expect(templateToFrontendLegs({})).toEqual([]);
  });
});

describe("frontendLegsToTemplatePayload", () => {
  it("builds a creation payload from frontend legs", () => {
    const legs = [
      { action: "buy", type: "call", strike: 24500, expiry: "2026-08-28", qty: 1, lotSize: 50, price: 200 },
      { action: "sell", type: "call", strike: 25500, expiry: "2026-08-28", qty: 1, lotSize: 50, price: 100 },
    ];
    const payload = frontendLegsToTemplatePayload("Bull Call Spread", "NIFTY", legs);
    expect(payload.name).toBe("Bull Call Spread");
    expect(payload.symbol).toBe("NIFTY");
    expect(payload.legs).toHaveLength(2);
    expect(payload.legs[0]).toEqual({
      action: "buy",
      option_type: "call",
      strike: 24500,
      expiry: "2026-08-28",
      quantity: 1,
      lot_size: 50,
      price: 200,
      position: 0,
    });
    expect(payload.legs[1].position).toBe(1);
  });

  it("defaults symbol to NIFTY and lot_size to 50", () => {
    const legs = [{ action: "buy", type: "put", strike: 25000, expiry: "2026-08-28", qty: 1 }];
    const payload = frontendLegsToTemplatePayload("Put Buy", "", legs);
    expect(payload.symbol).toBe("NIFTY");
    expect(payload.legs[0].lot_size).toBe(50);
  });
});

describe("frontendLegsToUpdatePayload", () => {
  it("includes only provided fields", () => {
    const payload = frontendLegsToUpdatePayload("Renamed", undefined, undefined);
    expect(payload).toEqual({ name: "Renamed" });
  });

  it("includes legs when provided", () => {
    const legs = [{ action: "buy", type: "call", strike: 24500, expiry: "2026-08-28", qty: 2, lotSize: 50, price: 150 }];
    const payload = frontendLegsToUpdatePayload(undefined, undefined, legs);
    expect(payload.legs).toHaveLength(1);
    expect(payload.legs[0].quantity).toBe(2);
  });
});

describe("legSummary", () => {
  it("returns human-readable leg summary", () => {
    const legs = [
      { action: "buy", type: "call", strike: 24500, qty: 1 },
      { action: "sell", type: "put", strike: 25000, qty: 2 },
    ];
    expect(legSummary(legs)).toBe("BUY 24500 CE \u00d71 \u00b7 SELL 25000 PE \u00d72");
  });

  it("returns Empty for no legs", () => {
    expect(legSummary([])).toBe("Empty");
    expect(legSummary(null)).toBe("Empty");
  });
});

describe("legCountLabel", () => {
  it("uses singular for 1 leg", () => {
    expect(legCountLabel(1)).toBe("1 leg");
  });

  it("uses plural for multiple legs", () => {
    expect(legCountLabel(3)).toBe("3 legs");
  });
});
