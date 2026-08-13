import { describe, it, expect } from "vitest";
import { makeAlert, ltpFor, evaluateAlerts, describeAlert } from "./alerts";

const rows = [
  { strike: 100, call: { ltp: 12 }, put: { ltp: 8 } },
  { strike: 110, call: { ltp: 6 }, put: { ltp: 15 } },
  { strike: 120, call: {}, put: null },
];

describe("makeAlert", () => {
  it("builds an untriggered alert with the given fields", () => {
    const a = makeAlert({ symbol: "NIFTY", expiry: "2026-08-27", strike: 100, type: "call", condition: "above", level: 15 });
    expect(a).toMatchObject({ symbol: "NIFTY", expiry: "2026-08-27", strike: 100, type: "call", condition: "above", level: 15, triggeredAt: null });
    expect(a.id).toContain("alert-NIFTY-100-call-above");
  });
});

describe("ltpFor", () => {
  it("returns the call or put LTP for a strike", () => {
    expect(ltpFor(rows, 100, "call")).toBe(12);
    expect(ltpFor(rows, 110, "put")).toBe(15);
  });

  it("returns null for unknown strikes or missing sides", () => {
    expect(ltpFor(rows, 999, "call")).toBeNull();
    expect(ltpFor(rows, 120, "call")).toBeNull();
    expect(ltpFor(rows, 120, "put")).toBeNull();
  });
});

describe("evaluateAlerts", () => {
  const now = () => "2026-08-13T10:00:00Z";
  const base = { symbol: "NIFTY", expiry: "2026-08-27" };

  it("fires 'above' alerts when LTP >= level", () => {
    const alerts = [makeAlert({ ...base, strike: 100, type: "call", condition: "above", level: 12 })];
    const { alerts: next, fired } = evaluateAlerts(alerts, rows, "NIFTY", "2026-08-27", now);
    expect(fired).toHaveLength(1);
    expect(fired[0].ltp).toBe(12);
    expect(next[0].triggeredAt).toBe("2026-08-13T10:00:00Z");
  });

  it("fires 'below' alerts when LTP <= level", () => {
    const alerts = [makeAlert({ ...base, strike: 110, type: "call", condition: "below", level: 10 })];
    const { fired } = evaluateAlerts(alerts, rows, "NIFTY", "2026-08-27", now);
    expect(fired).toHaveLength(1);
  });

  it("does not fire when the condition is not met", () => {
    const alerts = [makeAlert({ ...base, strike: 100, type: "call", condition: "above", level: 50 })];
    const { alerts: next, fired } = evaluateAlerts(alerts, rows, "NIFTY", "2026-08-27", now);
    expect(fired).toHaveLength(0);
    expect(next[0].triggeredAt).toBeNull();
  });

  it("skips already-triggered alerts and other symbols/expiries", () => {
    const triggered = { ...makeAlert({ ...base, strike: 100, type: "call", condition: "above", level: 1 }), triggeredAt: "earlier" };
    const otherSymbol = makeAlert({ ...base, symbol: "BANKNIFTY", strike: 100, type: "call", condition: "above", level: 1 });
    const otherExpiry = makeAlert({ ...base, expiry: "2026-09-03", strike: 100, type: "call", condition: "above", level: 1 });
    const { alerts: next, fired } = evaluateAlerts([triggered, otherSymbol, otherExpiry], rows, "NIFTY", "2026-08-27", now);
    expect(fired).toHaveLength(0);
    expect(next[0].triggeredAt).toBe("earlier");
    expect(next[1].triggeredAt).toBeNull();
    expect(next[2].triggeredAt).toBeNull();
  });

  it("skips alerts whose strike has no LTP", () => {
    const alerts = [makeAlert({ ...base, strike: 120, type: "call", condition: "above", level: 1 })];
    const { fired } = evaluateAlerts(alerts, rows, "NIFTY", "2026-08-27", now);
    expect(fired).toHaveLength(0);
  });
});

describe("describeAlert", () => {
  it("formats call/above alerts", () => {
    const a = makeAlert({ symbol: "NIFTY", expiry: "e", strike: 100, type: "call", condition: "above", level: 15 });
    expect(describeAlert(a)).toBe("NIFTY 100 CE ≥ 15");
  });

  it("formats put/below alerts", () => {
    const a = makeAlert({ symbol: "BANKNIFTY", expiry: "e", strike: 200, type: "put", condition: "below", level: 9 });
    expect(describeAlert(a)).toBe("BANKNIFTY 200 PE ≤ 9");
  });
});
