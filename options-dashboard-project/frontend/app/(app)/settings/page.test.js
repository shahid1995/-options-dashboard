import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Mock next/navigation
const mockRouterPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

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
  });
});

describe("SettingsPage — logged out state (polished auth card)", () => {
  const loggedOut = {
    user: null,
    loading: false,
    isLoggedIn: false,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  };

  beforeEach(() => {
    useAuth.mockReturnValue(loggedOut);
  });

  it("shows StrikeNova branding at the top", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("OD");
    expect(html).toContain("Options Dashboard");
    expect(html).toContain("NSE");
    expect(html).toContain("BSE INDEX OPTIONS");
  });

  it("shows Sign In / Create Account toggle tabs", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("Sign In");
    expect(html).toContain("Create Account");
  });

  it("shows email and password inputs", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("Email address");
    expect(html).toContain("Password");
  });

  it("shows 'or connect with' divider and Upstox OAuth button", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("or connect with");
    expect(html).toContain("Connect with Upstox");
  });

  it("does not show account, broker, or analytics sections when logged out", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).not.toContain("Broker Connection");
    expect(html).not.toContain("Analytics Token");
    expect(html).not.toContain("Sign Out");
  });
});

describe("SettingsPage — logged in state (polished sections)", () => {
  const mockUser = {
    user_id: "user-123",
    email: "test@example.com",
    display_name: "Test User",
    status: "active",
    identity_source: "email",
    last_login_at: "2026-08-29T10:00:00Z",
  };

  const loggedIn = {
    user: mockUser,
    loading: false,
    isLoggedIn: true,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  };

  beforeEach(() => {
    useAuth.mockReturnValue(loggedIn);
  });

  it("shows Account section with user identity", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("Account");
    expect(html).toContain("test@example.com");
    expect(html).toContain("Test User");
    expect(html).toContain("user-123");
    expect(html).toContain("ACTIVE");
    expect(html).toContain("EMAIL");
    expect(html).toContain("STATUS");
  });

  it("shows Sign Out button in Account header", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("Sign Out");
  });

  it("shows Broker Connection section with Upstox card", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("Broker Connection");
    expect(html).toContain("Upstox");
    expect(html).toContain("OAuth connection");
    expect(html).toContain("NOT CONNECTED");
    expect(html).toContain("API Key");
    expect(html).toContain("API Secret");
    expect(html).toContain("Store Credentials");
    expect(html).toContain("Connect via OAuth");
  });

  it("shows Analytics Token section", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("Analytics Token");
    expect(html).toContain("NOT CONNECTED");
    expect(html).toContain("Analytics Token");
  });

  it("never exposes tokens or credentials in rendered HTML", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).not.toContain("access_token");
    expect(html).not.toContain("client_secret");
    expect(html).not.toContain("refresh_token");
    expect(html).not.toContain("broker_token");
  });

  it("does not show login form when logged in", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).not.toContain("SIGN IN");
    expect(html).not.toContain("or connect with");
  });

  it("shows security footer text", () => {
    const html = renderToStaticMarkup(React.createElement(SettingsPage));
    expect(html).toContain("SESSION-SCOPED");
    expect(html).toContain("ENCRYPTED AT REST");
    expect(html).toContain("BYOB ARCHITECTURE");
  });
});
