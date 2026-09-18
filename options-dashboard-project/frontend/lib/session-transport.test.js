import { describe, expect, it, vi, beforeEach } from "vitest";

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

    expect(api.defaults.withCredentials).toBe(true);
    expect(seenConfig.headers["X-Session-Id"]).toBeUndefined();
    expect(JSON.stringify(seenConfig.headers)).not.toMatch(/session[_-]?id/i);
  });

  it("does not expose a session ID for WebSocket subprotocol authentication", () => {
    expect(chainWsProtocols()).toBeUndefined();
  });

  it("does not reference browser session storage or URL session capture", async () => {
    const source = await import("node:fs").then(({ readFileSync }) =>
      readFileSync(new URL("./session.js", import.meta.url), "utf8")
    );
    expect(source).not.toContain("localStorage");
    expect(source).not.toContain("sessionStorage");
    expect(source).not.toContain("captureSessionFromUrl");
    expect(source).not.toContain("session_id");
  });
});
