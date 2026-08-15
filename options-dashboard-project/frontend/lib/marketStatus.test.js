import { describe, it, expect } from "vitest";
import { nseCalendarStatus, istDateIso, MARKET_STATUS_LABELS, MARKET_CLOSED_MSG, MARKET_UNKNOWN_MSG, priceModeLabel } from "./marketStatus";

// Helper: build a Date whose wall-clock time in IST is what we want.
// IST = UTC + 05:30, so 10:00 IST = 04:30 UTC.
const ist = (y, m, d, hh, mm, ss = 0) => new Date(Date.UTC(y, m - 1, d, hh - 5, mm - 30, ss));

describe("nseCalendarStatus", () => {
  it("is open during market hours on a weekday", () => {
    // Friday 2026-08-14 10:00 IST.
    expect(nseCalendarStatus(ist(2026, 8, 14, 10, 0)).status).toBe("open");
  });

  it("is closed before 09:15", () => {
    expect(nseCalendarStatus(ist(2026, 8, 14, 9, 14)).status).toBe("closed");
  });

  it("is open at exactly 09:15", () => {
    expect(nseCalendarStatus(ist(2026, 8, 14, 9, 15)).status).toBe("open");
  });

  it("is open at exactly 15:30", () => {
    expect(nseCalendarStatus(ist(2026, 8, 14, 15, 30)).status).toBe("open");
  });

  it("is closed one second after 15:30", () => {
    expect(nseCalendarStatus(ist(2026, 8, 14, 15, 30, 1)).status).toBe("closed");
  });

  it("is closed on Saturday even during market hours", () => {
    const st = nseCalendarStatus(ist(2026, 8, 15, 10, 0));
    expect(st.status).toBe("closed");
    expect(st.reason).toMatch(/Weekend/);
  });

  it("is closed on Sunday", () => {
    expect(nseCalendarStatus(ist(2026, 8, 16, 10, 0)).status).toBe("closed");
  });

  it("is closed on an NSE trading holiday (Republic Day, Monday)", () => {
    const st = nseCalendarStatus(ist(2026, 1, 26, 10, 0));
    expect(st.status).toBe("closed");
    expect(st.reason).toMatch(/holiday/i);
  });

  it("reports the IST trade date", () => {
    const st = nseCalendarStatus(ist(2026, 8, 14, 10, 0));
    expect(st.tradeDate).toBe("2026-08-14");
  });
});

describe("istDateIso", () => {
  it("returns the calendar date in India Standard Time", () => {
    // 2026-08-14 04:30 UTC == 2026-08-14 10:00 IST.
    expect(istDateIso(new Date("2026-08-14T04:30:00Z"))).toBe("2026-08-14");
    // 2026-08-13 23:30 UTC == 2026-08-14 05:00 IST (crosses midnight).
    expect(istDateIso(new Date("2026-08-13T23:30:00Z"))).toBe("2026-08-14");
  });
});

describe("market status copy", () => {
  it("exposes the exact required user-facing messages", () => {
    expect(MARKET_CLOSED_MSG).toBe("Market is closed. Paper order was not executed.");
    expect(MARKET_UNKNOWN_MSG).toBe("Unable to verify market status. Order was not executed.");
    expect(MARKET_STATUS_LABELS.open).toMatch(/MARKET OPEN/);
    expect(MARKET_STATUS_LABELS.closed).toMatch(/MARKET CLOSED/);
    expect(MARKET_STATUS_LABELS.unknown).toMatch(/UNABLE TO VERIFY/);
  });
});

describe("priceModeLabel", () => {
  it("labels live prices only while the market is verified open", () => {
    expect(priceModeLabel("open")).toBe("LIVE");
  });

  it("labels last/closing prices when the market is closed", () => {
    expect(priceModeLabel("closed")).toBe("LAST/CLOSE");
  });

  it("never labels unverifiable prices as live", () => {
    expect(priceModeLabel("unknown")).toBe("UNVERIFIED");
    expect(priceModeLabel(undefined)).toBe("UNVERIFIED");
  });
});
