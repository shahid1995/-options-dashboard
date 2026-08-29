import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Mock next/navigation before importing the component
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// Mock next/link (not used by AuthModal but good practice)
vi.mock("next/link", () => ({
  default: ({ children, ...props }) => React.createElement("a", props, children),
}));

// Mock next/script (used by some Next.js features)
vi.mock("next/script", () => ({
  default: ({ children, ...props }) => React.createElement("script", props, children),
}));

import AuthModal from "./AuthModal";

/**
 * AuthModal tests — rendered via SSR to verify structural correctness.
 * Interactive tests (click handlers, form submission) require a full React
 * rendering environment and are covered by integration/E2E tests.
 */

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  onAuth: vi.fn(),
};

const closedProps = {
  open: false,
  onClose: vi.fn(),
  onAuth: vi.fn(),
};

describe("AuthModal — rendering", () => {
  it("renders nothing when closed", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, closedProps));
    expect(html).toBe("");
  });

  it("renders the modal backdrop when open", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-label="Authentication"');
  });

  it("renders Sign In and Create Account tabs", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain("Sign In");
    expect(html).toContain("Create Account");
  });

  it("renders the OD logo / STRIKENOVA branding", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain("OD");
    expect(html).toContain("STRIKENOVA");
  });

  it("renders email and password inputs", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain('type="email"');
    expect(html).toContain('type="password"');
  });

  it("renders a submit button", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain('data-testid="auth-submit"');
  });

  it("renders a Connect with Upstox button", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain("Connect with Upstox");
    expect(html).toContain('data-testid="auth-upstox-btn"');
  });

  it("renders the Upstox OAuth URL", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain("/auth/login");
  });

  it("renders a close button", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain('data-testid="auth-modal-close"');
    expect(html).toContain('aria-label="Close"');
  });

  it("renders a divider between email form and Upstox", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain("or continue with");
  });

  it("renders the Terms of Service note", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain("Terms of Service");
    expect(html).toContain("encrypted");
  });

  it("does not render the display name field in Sign In mode", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    // Sign In tab is default — display name should not appear
    expect(html).not.toContain('id="auth-display-name"');
  });
});

describe("AuthModal — data attributes", () => {
  it("has data-testid on backdrop, panel, close, submit, and Upstox button", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain('data-testid="auth-modal-backdrop"');
    expect(html).toContain('data-testid="auth-modal-panel"');
    expect(html).toContain('data-testid="auth-modal-close"');
    expect(html).toContain('data-testid="auth-submit"');
    expect(html).toContain('data-testid="auth-upstox-btn"');
  });

  it("has data-testid on tab buttons", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain('data-testid="auth-tab-signin"');
    expect(html).toContain('data-testid="auth-tab-signup"');
  });

  it("has data-testid on Google Sign-In button", () => {
    const html = renderToStaticMarkup(React.createElement(AuthModal, defaultProps));
    expect(html).toContain('data-testid="auth-google-btn"');
  });
});
