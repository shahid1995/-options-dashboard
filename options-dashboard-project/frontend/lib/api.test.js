import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { isAuthError, chainWsUrl, submitPaperFill, closePaperLeg, getPaperJournal, getMarketStatus, api } from "./api";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("isAuthError", () => {
  it("is true for axios errors with a 401 response", () => {
    expect(isAuthError({ response: { status: 401 } })).toBe(true);
  });

  it("is false for other statuses and shapeless errors", () => {
    expect(isAuthError({ response: { status: 502 } })).toBe(false);
    expect(isAuthError(new Error("network"))).toBe(false);
    expect(isAuthError(null)).toBe(false);
  });
});

describe("chainWsUrl", () => {
  it("derives a ws:// URL from the API base and encodes the expiry", () => {
    expect(chainWsUrl("NIFTY", "2026-08-27")).toBe("ws://localhost:8000/chains/ws/NIFTY?expiry_date=2026-08-27");
  });

  it("maps https to wss", () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com");
    expect(chainWsUrl("BANKNIFTY", "2026-08-27")).toBe("wss://api.example.com/chains/ws/BANKNIFTY?expiry_date=2026-08-27");
  });
});

describe("paper journal api", () => {
  it("posts an executed fill to /paper/fills", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: 1 } });
    const order = { symbol: "NIFTY", strategy_tag: "Long Call", legs: [] };
    await submitPaperFill(order);
    expect(spy).toHaveBeenCalledWith("/paper/fills", order);
    spy.mockRestore();
  });

  it("posts a leg close with the exit price", async () => {
    const spy = vi.spyOn(api, "post").mockResolvedValue({ data: { status: "closed" } });
    await closePaperLeg(7, 3, 45.5);
    expect(spy).toHaveBeenCalledWith("/paper/trades/7/legs/3/close", { exit_price: 45.5 });
    spy.mockRestore();
  });

  it("gets the journal from /paper/journal", async () => {
    const spy = vi.spyOn(api, "get").mockResolvedValue({ data: { account: { balance: 500000 } } });
    await getPaperJournal();
    expect(spy).toHaveBeenCalledWith("/paper/journal");
    spy.mockRestore();
  });

  it("gets the market status from /paper/market-status and normalizes trade_date", async () => {
    const spy = vi.spyOn(api, "get").mockResolvedValue({ data: { status: "open", open: true, source: "upstox", trade_date: "2026-08-14" } });
    const st = await getMarketStatus();
    expect(spy).toHaveBeenCalledWith("/paper/market-status");
    expect(st.status).toBe("open");
    expect(st.tradeDate).toBe("2026-08-14");
    spy.mockRestore();
  });
});
