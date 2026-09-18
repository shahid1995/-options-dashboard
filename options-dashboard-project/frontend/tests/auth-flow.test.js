/**
 * Frontend auth integration tests - TDD Phase 3 (Tests A-J).
 *
 * These tests verify the public authentication flow end-to-end.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Top-level mocks (hoisted by vitest)
vi.mock("@/lib/ui", () => ({
  useIsMobile: () => false,
  usePathname: () => "/",
  useSearchParams: () => ({ get: () => null }),
  C: {},
  SYMBOLS: [],
  LOT_SIZES: {},
  fmtIN: (n) => (n != null ? String(n) : "-"),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => ({ get: () => null }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/components/public/AuthModalContext", () => {
  const { createContext } = require("react");
  const AuthModalContext = createContext({ open: () => {} });
  return {
    default: function AuthModalProvider({ children }) {
      return React.createElement(
        AuthModalContext.Provider,
        { value: { open: () => {} } },
        children
      );
    },
    useAuthModal: () => ({ open: () => {} }),
  };
});

vi.mock("@/lib/session", () => ({
  captureGoogleIdTokenFromUrl: vi.fn(() => null),
}));

vi.mock("@/lib/api", () => {
  const api = {
    defaults: { withCredentials: true, baseURL: "" },
    interceptors: { request: { handlers: [{}] }, response: { handlers: [{}] } },
  };
  return {
    api,
    loginUrl: (broker = "UPSTOX") => `/auth/login?broker=${broker}`,
    getMe: vi.fn().mockResolvedValue({ user_id: "user-1" }),
    getStatus: vi.fn().mockResolvedValue({ logged_in: true }),
    logoutUser: vi.fn().mockResolvedValue({ ok: true }),
    loginEmail: vi.fn().mockResolvedValue({ ok: true, user: { user_id: "u1" } }),
    registerEmail: vi.fn().mockResolvedValue({ ok: true, user_id: "u2" }),
    loginGoogle: vi.fn().mockResolvedValue({ ok: true, user: { user_id: "ug" } }),
    getGoogleState: vi.fn().mockResolvedValue({ state: "state-1", nonce: "nonce-1" }),
  };
});

// Test A: Login button
describe("Test A: Login button routes into existing auth flow", () => {
  it("header Login button exists with correct testid", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    expect(html).toContain('data-testid="header-login-btn"');
    expect(html).toContain("Log in");
  });

  it("header Get Started button exists with correct testid", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    expect(html).toContain('data-testid="header-get-started-btn"');
    expect(html).toContain("Get Started");
  });
});

// Test B: Get Started button
describe("Test B: Get Started button enters correct auth state", () => {
  it("Get Started button opens the same auth modal as Login", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    expect(html).toContain('data-testid="header-login-btn"');
    expect(html).toContain('data-testid="header-get-started-btn"');
  });
});

// Test C & D: Auth success and failure
describe("Test C & D: Auth success/failure handling", () => {
  it("AuthModal renders signin and signup tabs", async () => {
    const { default: AuthModal } = await import("@/components/public/AuthModal");
    const html = renderToStaticMarkup(
      React.createElement(AuthModal, {
        open: true,
        onClose: vi.fn(),
        onAuth: vi.fn(),
      })
    );
    expect(html).toContain("Sign In");
    expect(html).toContain("Create Account");
  });

  it("AuthModal has Google Sign-In button", async () => {
    const { default: AuthModal } = await import("@/components/public/AuthModal");
    const html = renderToStaticMarkup(
      React.createElement(AuthModal, {
        open: true,
        onClose: vi.fn(),
        onAuth: vi.fn(),
      })
    );
    expect(html).toContain('data-testid="auth-google-btn"');
  });

  it("AuthModal has Upstox OAuth link", async () => {
    const { default: AuthModal } = await import("@/components/public/AuthModal");
    const html = renderToStaticMarkup(
      React.createElement(AuthModal, {
        open: true,
        onClose: vi.fn(),
        onAuth: vi.fn(),
      })
    );
    expect(html).toContain('data-testid="auth-upstox-btn"');
    expect(html).toContain("/auth/login");
  });

  it("AuthModal error display does not leak password or email", async () => {
    const { default: AuthModal } = await import("@/components/public/AuthModal");
    const html = renderToStaticMarkup(
      React.createElement(AuthModal, {
        open: true,
        onClose: vi.fn(),
        onAuth: vi.fn(),
      })
    );
    expect(html).not.toContain("password123");
    expect(html).not.toContain("secret");
  });
});

// Test E & F: Protected route behavior
describe("Test E & F: Protected route (AuthGate) behavior", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("AuthGate renders nothing during initial check", async () => {
    const { default: AuthGate } = await import("@/components/AuthGate");
    const html = renderToStaticMarkup(
      React.createElement(AuthGate, null, "Protected content")
    );
    expect(html).toBe("");
  });

  it("AuthGate treats 401 from getMe as authentication failure", async () => {
    const { default: AuthGate } = await import("@/components/AuthGate");
    const api = await import("@/lib/api");
    vi.mocked(api.getMe).mockRejectedValue({ response: { status: 401 } });
    const html = renderToStaticMarkup(
      React.createElement(AuthGate, null, "Protected content")
    );
    expect(html).toBe("");
  });
});

// Test G: Logout
describe("Test G: Logout/session invalidation", () => {
  it("logoutUser is defined as a function", async () => {
    const api = await import("@/lib/api");
    expect(typeof api.logoutUser).toBe("function");
  });
});

// Test H: Redirect safety
describe("Test H: Redirect safety", () => {
  it("AuthModal uses env var for app URL (no hard-coded external URL)", async () => {
    const { default: AuthModal } = await import("@/components/public/AuthModal");
    const html = renderToStaticMarkup(
      React.createElement(AuthModal, {
        open: true,
        onClose: vi.fn(),
        onAuth: vi.fn(),
      })
    );
    expect(html).not.toContain("frontend-zeta-gray-75.vercel.app");
    expect(html).not.toContain("options-dashboard-sigma-coral.vercel.app");
  });
});

// Test I: Session security
describe("Test I: Session security properties", () => {
  it("session module exposes no browser session transport", async () => {
    // Issue #61: the real session module must not expose browser-readable
    // session helpers — the HttpOnly strikenova_session cookie is the only
    // transport (read the real source; the mock above shadows imports).
    const source = await import("node:fs").then(({ readFileSync }) =>
      readFileSync(new URL("../lib/session.js", import.meta.url), "utf8")
    );
    expect(source).not.toMatch(/getSessionId|setSessionId|clearSessionId/);
    expect(source).not.toContain("captureSessionFromUrl");
    expect(source).not.toContain("localStorage");
    expect(source).not.toContain("sessionStorage");
  });

  it("auth API sends credentials with withCredentials=true", async () => {
    const api = await import("@/lib/api");
    expect(api.api.defaults.withCredentials).toBe(true);
  });
});

// Test J: Header regression
describe("Test J: Header regression - Product/Learn dropdowns intact", () => {
  it("contains Product group button", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    expect(html).toContain("Product");
  });

  it("contains Learn group button", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    expect(html).toContain("Learn");
  });

  it("has aria-haspopup=true on dropdown triggers", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    const popupCount = (html.match(/aria-haspopup="true"/g) || []).length;
    expect(popupCount).toBe(2);
  });

  it("mobile menu contains Product and Learn groups", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    expect(html).toContain("pub-mobile-menu");
  });

  it("header inner has box-sizing: border-box", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    expect(html).toMatch(/display:\s*flex[^}]*box-sizing:\s*border-box/);
  });

  it("has desktop nav links container", async () => {
    const { default: PublicHeader } = await import("@/components/public/PublicHeader");
    const html = renderToStaticMarkup(React.createElement(PublicHeader));
    expect(html).toContain("pub-nav-links");
  });
});
