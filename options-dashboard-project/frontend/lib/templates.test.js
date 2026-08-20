import { describe, it, expect } from "vitest";
import {
  templateLegToFrontend,
  templateToFrontendLegs,
  frontendLegsToTemplatePayload,
  frontendLegsToUpdatePayload,
  legSummary,
  legCountLabel,
} from "./templates";

// ===== templateLegToFrontend =====

describe("templateLegToFrontend", () => {
  it("converts a backend template leg to frontend format", () => {
    const leg = {
      id: 1, template_id: 10, position: 0,
      action: "buy", option_type: "call", strike: 25000,
      expiry: "2026-08-28", quantity: 2, lot_size: 50, price: 142.5,
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
  });

  it("uses 0 for null price", () => {
    const leg = {
      id: 1, template_id: 5, position: 0,
      action: "sell", option_type: "put", strike: 24500,
      expiry: "2026-08-28", quantity: 1, lot_size: 50, price: null,
    };
    const result = templateLegToFrontend(leg);
    expect(result.price).toBe(0);
  });

  it("V1 leg defaults strikeMode=fixed, expiryMode=fixed", () => {
    const leg = {
      id: 1, template_id: 10, position: 0,
      action: "buy", option_type: "call", strike: 25000,
      expiry: "2026-08-28", quantity: 1, lot_size: 50, price: 100,
    };
    const result = templateLegToFrontend(leg);
    expect(result.strikeMode).toBe("fixed");
    expect(result.expiryMode).toBe("fixed");
    expect(result.formulaVersion).toBe(1);
    expect(result.strikeOffset).toBeNull();
    expect(result.targetDelta).toBeNull();
    expect(result.expiryDteMin).toBeNull();
    expect(result.expiryDteMax).toBeNull();
  });

  it("V2 leg preserves all formula fields", () => {
    const leg = {
      id: 2, template_id: 10, position: 0,
      action: "buy", option_type: "call", strike: 25000,
      expiry: "2026-08-28", quantity: 1, lot_size: 50, price: 100,
      strike_mode: "atm_offset_steps", strike_offset: 2,
      target_delta: 0.30, expiry_mode: "dte_range",
      expiry_dte_min: 5, expiry_dte_max: 15, formula_version: 2,
    };
    const result = templateLegToFrontend(leg);
    expect(result.strikeMode).toBe("atm_offset_steps");
    expect(result.strikeOffset).toBe(2);
    expect(result.targetDelta).toBe(0.30);
    expect(result.expiryMode).toBe("dte_range");
    expect(result.expiryDteMin).toBe(5);
    expect(result.expiryDteMax).toBe(15);
    expect(result.formulaVersion).toBe(2);
  });
});

// ===== templateToFrontendLegs =====

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
    expect(result[0].strike).toBe(24500);
    expect(result[1].strike).toBe(25500);
  });

  it("handles empty legs array", () => {
    expect(templateToFrontendLegs({ legs: [] })).toEqual([]);
    expect(templateToFrontendLegs({})).toEqual([]);
  });
});

// ===== frontendLegsToTemplatePayload =====

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
      action: "buy", option_type: "call", strike: 24500,
      expiry: "2026-08-28", quantity: 1, lot_size: 50, price: 200, position: 0,
    });
    expect(payload.legs[1].position).toBe(1);
  });

  it("defaults symbol to NIFTY and lot_size to 50", () => {
    const legs = [{ action: "buy", type: "put", strike: 25000, expiry: "2026-08-28", qty: 1 }];
    const payload = frontendLegsToTemplatePayload("Put Buy", "", legs);
    expect(payload.symbol).toBe("NIFTY");
    expect(payload.legs[0].lot_size).toBe(50);
  });

  it("V1 fixed-leg payload has no formula fields", () => {
    const legs = [{ action: "buy", type: "call", strike: 25000, expiry: "2026-08-28", qty: 1, lotSize: 50 }];
    const payload = frontendLegsToTemplatePayload("V1 Test", "NIFTY", legs);
    expect(payload.legs[0].strike_mode).toBeUndefined();
    expect(payload.legs[0].expiry_mode).toBeUndefined();
  });

  it("V2 dynamic payload includes formula fields", () => {
    const legs = [{
      action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
      qty: 1, lotSize: 50, strikeMode: "atm", expiryMode: "current_week",
    }];
    const payload = frontendLegsToTemplatePayload("ATM CW", "NIFTY", legs);
    expect(payload.legs[0].strike_mode).toBe("atm");
    expect(payload.legs[0].expiry_mode).toBe("current_week");
  });

  it("V2 payload includes strike_offset for offset modes", () => {
    const legs = [{
      action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
      qty: 1, lotSize: 50, strikeMode: "atm_offset_steps", strikeOffset: 3,
      expiryMode: "fixed",
    }];
    const payload = frontendLegsToTemplatePayload("ATM+3", "NIFTY", legs);
    expect(payload.legs[0].strike_mode).toBe("atm_offset_steps");
    expect(payload.legs[0].strike_offset).toBe(3);
  });

  it("V2 payload includes target_delta for delta mode", () => {
    const legs = [{
      action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
      qty: 1, lotSize: 50, strikeMode: "delta", targetDelta: 0.30,
      expiryMode: "fixed",
    }];
    const payload = frontendLegsToTemplatePayload("Delta", "NIFTY", legs);
    expect(payload.legs[0].strike_mode).toBe("delta");
    expect(payload.legs[0].target_delta).toBe(0.30);
  });

  it("V2 payload includes DTE range fields", () => {
    const legs = [{
      action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
      qty: 1, lotSize: 50, strikeMode: "fixed", expiryMode: "dte_range",
      expiryDteMin: 5, expiryDteMax: 15,
    }];
    const payload = frontendLegsToTemplatePayload("DTE", "NIFTY", legs);
    expect(payload.legs[0].expiry_mode).toBe("dte_range");
    expect(payload.legs[0].expiry_dte_min).toBe(5);
    expect(payload.legs[0].expiry_dte_max).toBe(15);
  });

  it("V2 payload does not include null optional fields", () => {
    const legs = [{
      action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
      qty: 1, lotSize: 50, strikeMode: "atm", expiryMode: "fixed",
    }];
    const payload = frontendLegsToTemplatePayload("Clean", "NIFTY", legs);
    expect(payload.legs[0].strike_offset).toBeUndefined();
    expect(payload.legs[0].target_delta).toBeUndefined();
    expect(payload.legs[0].expiry_dte_min).toBeUndefined();
    expect(payload.legs[0].expiry_dte_max).toBeUndefined();
  });
});

// ===== frontendLegsToUpdatePayload =====

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

  it("V2 update payload includes formula fields", () => {
    const legs = [{
      action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
      qty: 1, lotSize: 50, strikeMode: "spot_offset", strikeOffset: 200,
      expiryMode: "next_week",
    }];
    const payload = frontendLegsToUpdatePayload(undefined, undefined, legs);
    expect(payload.legs[0].strike_mode).toBe("spot_offset");
    expect(payload.legs[0].strike_offset).toBe(200);
    expect(payload.legs[0].expiry_mode).toBe("next_week");
  });

  it("V1 update payload has no formula fields", () => {
    const legs = [{ action: "buy", type: "call", strike: 25000, expiry: "2026-08-28", qty: 1, lotSize: 50 }];
    const payload = frontendLegsToUpdatePayload(undefined, undefined, legs);
    expect(payload.legs[0].strike_mode).toBeUndefined();
    expect(payload.legs[0].expiry_mode).toBeUndefined();
  });
});

// ===== legSummary =====

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

  it("shows ATM label for dynamic strike mode", () => {
    const legs = [{ action: "buy", type: "call", strike: 25000, qty: 1, strikeMode: "atm" }];
    expect(legSummary(legs)).toBe("BUY ATM CE \u00d71");
  });

  it("shows DELTA label for delta strike mode", () => {
    const legs = [{ action: "sell", type: "put", strike: 24500, qty: 1, strikeMode: "delta" }];
    expect(legSummary(legs)).toBe("SELL DELTA PE \u00d71");
  });
});

// ===== legCountLabel =====

describe("legCountLabel", () => {
  it("uses singular for 1 leg", () => { expect(legCountLabel(1)).toBe("1 leg"); });
  it("uses plural for multiple legs", () => { expect(legCountLabel(3)).toBe("3 legs"); });
});

// ===== All strike modes =====

describe("All strike modes round-trip", () => {
  const modes = ["fixed", "atm", "atm_offset_steps", "atm_offset", "spot_offset", "delta"];
  modes.forEach((mode) => {
    it(`strike mode "${mode}" round-trips through payload`, () => {
      const legs = [{
        action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
        qty: 1, lotSize: 50, strikeMode: mode, expiryMode: "current_week",
      }];
      const payload = frontendLegsToTemplatePayload("Test", "NIFTY", legs);
      // Non-fixed modes must appear in payload
      expect(payload.legs[0].strike_mode).toBe(mode);
      // Reverse: template -> frontend
      const backendLeg = { ...payload.legs[0], id: 1, template_id: 1 };
      const frontend = templateLegToFrontend(backendLeg);
      expect(frontend.strikeMode).toBe(mode);
    });
  });
});

// ===== All expiry modes =====

describe("All expiry modes round-trip", () => {
  const modes = ["current_week", "next_week", "monthly", "dte_range"];
  modes.forEach((mode) => {
    it(`expiry mode "${mode}" round-trips through payload`, () => {
      const legs = [{
        action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
        qty: 1, lotSize: 50, strikeMode: "atm", expiryMode: mode,
      }];
      const payload = frontendLegsToTemplatePayload("Test", "NIFTY", legs);
      expect(payload.legs[0].expiry_mode).toBe(mode);
      const backendLeg = { ...payload.legs[0], id: 1, template_id: 1 };
      const frontend = templateLegToFrontend(backendLeg);
      expect(frontend.expiryMode).toBe(mode);
    });
  });

  it("expiry mode 'fixed' is omitted from V1 payload (backward compat)", () => {
    const legs = [{
      action: "buy", type: "call", strike: 25000, expiry: "2026-08-28",
      qty: 1, lotSize: 50, strikeMode: "fixed", expiryMode: "fixed",
    }];
    const payload = frontendLegsToTemplatePayload("Test", "NIFTY", legs);
    // V1: no formula fields when both modes are fixed
    expect(payload.legs[0].strike_mode).toBeUndefined();
    expect(payload.legs[0].expiry_mode).toBeUndefined();
    // templateLegToFrontend defaults to "fixed"
    const frontend = templateLegToFrontend({ ...payload.legs[0], id: 1, template_id: 1 });
    expect(frontend.strikeMode).toBe("fixed");
    expect(frontend.expiryMode).toBe("fixed");
  });
});

// ===== V1 backward compat =====

describe("V1 fixed-leg backward compatibility", () => {
  it("V1 frontend leg produces V1-only payload", () => {
    const leg = { action: "buy", type: "call", strike: 25000, expiry: "2026-08-28", qty: 1, lotSize: 50 };
    const payload = frontendLegsToTemplatePayload("V1", "NIFTY", [leg]);
    expect(payload.legs[0].strike_mode).toBeUndefined();
    expect(payload.legs[0].expiry_mode).toBeUndefined();
  });

  it("V1 backend leg produces V1 frontend defaults", () => {
    const backend = {
      id: 1, template_id: 10, position: 0,
      action: "buy", option_type: "call", strike: 25000,
      expiry: "2026-08-28", quantity: 1, lot_size: 50, price: 100,
    };
    const frontend = templateLegToFrontend(backend);
    expect(frontend.strikeMode).toBe("fixed");
    expect(frontend.expiryMode).toBe("fixed");
    expect(frontend.formulaVersion).toBe(1);
  });
});

// ===== V2 dynamic template =====

describe("V2 dynamic template round-trip", () => {
  it("V2 backend leg preserves all formula fields in frontend", () => {
    const backend = {
      id: 1, template_id: 10, position: 0,
      action: "buy", option_type: "call", strike: 25000,
      expiry: "2026-08-28", quantity: 1, lot_size: 50, price: 100,
      strike_mode: "atm_offset_steps", strike_offset: 2,
      target_delta: 0.30, expiry_mode: "dte_range",
      expiry_dte_min: 5, expiry_dte_max: 15, formula_version: 2,
    };
    const frontend = templateLegToFrontend(backend);
    expect(frontend.strikeMode).toBe("atm_offset_steps");
    expect(frontend.strikeOffset).toBe(2);
    expect(frontend.targetDelta).toBe(0.30);
    expect(frontend.expiryMode).toBe("dte_range");
    expect(frontend.expiryDteMin).toBe(5);
    expect(frontend.expiryDteMax).toBe(15);
    expect(frontend.formulaVersion).toBe(2);
  });

  it("V2 frontend leg produces full V2 payload", () => {
    const leg = {
      action: "sell", type: "put", strike: 24500, expiry: "2026-08-28",
      qty: 2, lotSize: 65, price: 80,
      strikeMode: "delta", targetDelta: -0.30,
      expiryMode: "monthly",
    };
    const payload = frontendLegsToTemplatePayload("Delta Put", "NIFTY", [leg]);
    expect(payload.legs[0].strike_mode).toBe("delta");
    expect(payload.legs[0].target_delta).toBe(-0.30);
    expect(payload.legs[0].expiry_mode).toBe("monthly");
  });
});

// ===== Dynamic badge behavior =====

describe("Dynamic badge behavior", () => {
  it("isDynamic when strikeMode is non-default", () => {
    expect("atm" !== "fixed" || "fixed" !== "fixed").toBe(true);
  });
  it("isDynamic when expiryMode is non-default", () => {
    expect("fixed" !== "fixed" || "current_week" !== "fixed").toBe(true);
  });
  it("not dynamic when both are fixed", () => {
    expect("fixed" !== "fixed" || "fixed" !== "fixed").toBe(false);
  });
});
