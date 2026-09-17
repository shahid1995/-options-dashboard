import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("./session", () => ({
  getSessionId: vi.fn(() => "browser-secret"),
}));

describe("secure browser session transport", () => {
  let api;
  let chainWsProtocols;

  beforeEach(async () => {
    vi.resetModules();
    ({ api, chainWsProtocols } = await import("./api"));
  });

  it("does not copy a browser-readable session into the API request headers", async () => {
    let seenConfig;
    api.defaults.adapter = async (config) => {
      seenConfig = config;
      return {
        data: { ok: true },
        status: 200,
        statusText: "OK",
        headers: {},
        config,
      };
    };

    await api.get("/auth/me");

    expect(seenConfig.headers["X-Session-Id"]).toBeUndefined();
    expect(JSON.stringify(seenConfig.headers)).not.toContain("browser-secret");
  });

  it("does not expose a session ID for WebSocket subprotocol authentication", () => {
    expect(chainWsProtocols()).toBeUndefined();
  });
});
