import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { isAuthError, chainWsUrl } from "./api";

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
