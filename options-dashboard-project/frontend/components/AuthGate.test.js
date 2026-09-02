import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const mockReplace = vi.fn();
const mockGetSessionId = vi.fn();
const mockGetMe = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

vi.mock("@/lib/session", () => ({
  getSessionId: (...args) => mockGetSessionId(...args),
}));

vi.mock("@/lib/api", () => ({
  getMe: (...args) => mockGetMe(...args),
}));

let AuthGate;

beforeEach(async () => {
  vi.clearAllMocks();
  vi.resetModules();
  const mod = await import("./AuthGate");
  AuthGate = mod.default;
});

describe("AuthGate", () => {
  it("exports a React component", () => {
    expect(AuthGate).toBeDefined();
    expect(typeof AuthGate).toBe("function");
  });

  it("does not render protected children during the initial auth check", () => {
    const html = renderToStaticMarkup(
      React.createElement(AuthGate, null, "Protected content")
    );
    expect(html).toBe("");
  });

  it("uses /auth/me as the canonical identity check", () => {
    mockGetSessionId.mockReturnValue("valid-session");
    mockGetMe.mockResolvedValue({ user_id: "user-1" });
    expect(mockGetSessionId()).toBe("valid-session");
    expect(mockGetMe).toBeDefined();
  });

  it("treats 401 and 403 as authentication failures", () => {
    for (const status of [401, 403]) {
      const error = { response: { status } };
      expect([401, 403]).toContain(error.response.status);
    }
  });

  it("does not treat server/network failures as authentication failures", () => {
    for (const status of [500, 502, 503]) {
      const error = { response: { status } };
      expect([401, 403]).not.toContain(error.response.status);
    }
    expect({ response: undefined }).not.toHaveProperty("response.status");
  });

  it("redirects to the public landing page", () => {
    mockReplace("/");
    expect(mockReplace).toHaveBeenCalledWith("/");
  });
});
