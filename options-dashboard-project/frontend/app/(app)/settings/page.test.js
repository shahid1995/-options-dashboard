import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Mock the useAuth hook and API modules
vi.mock("@/lib/useAuth", () => ({
  useAuth: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  loginUrl: () => "http://localhost:8000/auth/login",
  connectBroker: vi.fn(),
  connectAnalyticsToken: vi.fn(),
  getAnalyticsTokenStatus: vi.fn(),
  removeAnalyticsToken: vi.fn(),
}));

// We need to import SettingsPage after mocking so the mocks take effect.
// However, since SettingsPage is a client component that uses hooks,
// we test the rendered HTML output for each state.
import SettingsPage from "./page";
import { useAuth } from "@/lib/useAuth";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsPage — loading state", () => {
  it("shows loading message when auth is loading", () => {
    useAuth.mockReturnValue({
      user: null,
      loading: true,
      isLoggedIn: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    });
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("Checking authentication");
    expect(html).toContain("Settings");
  });
});

describe("SettingsPage — logged out state", () => {
  it("shows login form with email/password fields", () => {
    useAuth.mockReturnValue({
      user: null,
      loading: false,
      isLoggedIn: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    });
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("SIGN IN");
    expect(html).toContain("Email");
    expect(html).toContain("Password");
    expect(html).toContain("Sign In");
    expect(html).toContain("Create Account");
    expect(html).toContain("sign in with Upstox");
  });

  it("does not show account or broker sections when logged out", () => {
    useAuth.mockReturnValue({
      user: null,
      loading: false,
      isLoggedIn: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    });
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).not.toContain("ACCOUNT");
    expect(html).not.toContain("BROKER CONNECTION");
    expect(html).not.toContain("ANALYTICS TOKEN");
  });
});

describe("SettingsPage — logged in state", () => {
  const mockUser = {
    user_id: "user-123",
    email: "test@example.com",
    display_name: "Test User",
    status: "active",
    identity_source: "email",
    last_login_at: "2026-08-29T10:00:00Z",
  };

  beforeEach(() => {
    useAuth.mockReturnValue({
      user: mockUser,
      loading: false,
      isLoggedIn: true,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    });
  });

  it("shows account section with user identity", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("ACCOUNT");
    expect(html).toContain("test@example.com");
    expect(html).toContain("Test User");
    expect(html).toContain("user-123");
    expect(html).toContain("ACTIVE");
    expect(html).toContain("EMAIL");
    expect(html).toContain("DISPLAY NAME");
  });

  it("shows broker connection section", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("BROKER CONNECTION");
    expect(html).toContain("API Key");
    expect(html).toContain("API Secret");
    expect(html).toContain("Store Broker Credentials");
    expect(html).toContain("Connect via OAuth");
  });

  it("shows analytics token section", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("ANALYTICS TOKEN");
    expect(html).toContain("Upstox Analytics Token");
    expect(html).toContain("Store Analytics Token");
  });

  it("shows sign out button", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("Sign Out");
  });

  it("never exposes tokens or credentials in rendered HTML", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    // The rendered HTML should never contain actual token values
    expect(html).not.toContain("access_token");
    expect(html).not.toContain("api_secret");
    expect(html).not.toContain("refresh_token");
    expect(html).not.toContain("broker_token");
  });

  it("does not show login form when logged in", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).not.toContain("SIGN IN");
  });

  it("shows security footer text", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("SESSION-SCOPED");
    expect(html).toContain("ENCRYPTED AT REST");
  });
});
