/**
 * Email token landing pages (Issue #69 gate fix).
 *
 * The backend transactional emails link to /verify-email?token=…,
 * /reset-password?token=… and /verify-email-change?token=… (account_security
 * link builders). Before this fix those routes did not exist — every emailed
 * link 404ed. These tests pin the route wiring and the markup-level security
 * invariant that the raw single-use token is never rendered into the page.
 *
 * Note: repo tests use renderToStaticMarkup (no DOM environment), so
 * client-side effects (the actual token consumption calls) are exercised by
 * the live browser E2E in the Issue #69 gate evidence instead.
 */

import { describe, it, expect, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("@/lib/ui", () => ({
  useIsMobile: () => false,
  C: {
    surface: "#111",
    border: "#222",
    gold: "#C9A15A",
    text: "#EEE",
    muted: "#999",
    green: "#4CAF7D",
    red: "#E15252",
    faint: "#666",
  },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: (k) => (k === "token" ? "e2e-test-token-value" : null) }),
}));

vi.mock("@/components/public/AuthModalContext", () => ({
  useAuthModal: () => ({ open: () => {} }),
}));

vi.mock("@/lib/api", () => ({
  verifyEmail: vi.fn(() => Promise.resolve({ message: "ok" })),
  resetPassword: vi.fn(() => Promise.resolve({})),
  verifyEmailChange: vi.fn(() => Promise.resolve({ message: "ok" })),
}));

import EmailTokenClient from "./EmailTokenClient";
import VerifyEmailPage from "@/app/(public)/verify-email/page";
import ResetPasswordPage from "@/app/(public)/reset-password/page";
import VerifyEmailChangePage from "@/app/(public)/verify-email-change/page";

const render = (el) => renderToStaticMarkup(React.createElement(el));

describe("EmailTokenClient — route wiring", () => {
  it("/verify-email wires mode=verify with the verification surface", () => {
    const html = render(VerifyEmailPage);
    expect(html).toContain("email-token-page-verify");
    expect(html).toContain("Email verification");
  });

  it("/reset-password wires mode=reset with the reset surface", () => {
    const html = render(ResetPasswordPage);
    expect(html).toContain("email-token-page-reset");
    expect(html).toContain("Password reset");
  });

  it("/verify-email-change wires mode=email-change", () => {
    const html = render(VerifyEmailChangePage);
    expect(html).toContain("email-token-page-email-change");
    expect(html).toContain("Email address change");
  });
});

describe("EmailTokenClient — markup-level security invariants", () => {
  it("never renders the raw token into the page markup", () => {
    for (const Page of [VerifyEmailPage, ResetPasswordPage, VerifyEmailChangePage]) {
      expect(render(Page)).not.toContain("e2e-test-token-value");
    }
  });

  it("starts in a neutral pending state — no error, no auth state change", () => {
    const html = render(VerifyEmailPage);
    // The client renders a neutral 'checking' state; consumption happens in a
    // client-side effect, never during markup render.
    expect(html).toContain("token-state-verifying");
    expect(html).not.toContain("token-state-error");
  });

  it("makes no API call during markup render", async () => {
    const { verifyEmail, resetPassword, verifyEmailChange } = await import("@/lib/api");
    render(VerifyEmailPage);
    render(ResetPasswordPage);
    render(VerifyEmailChangePage);
    expect(verifyEmail).not.toHaveBeenCalled();
    expect(resetPassword).not.toHaveBeenCalled();
    expect(verifyEmailChange).not.toHaveBeenCalled();
  });
});

describe("EmailTokenClient — page metadata", () => {
  it("all three routes are exported with noindex metadata", async () => {
    const modV = await import("@/app/(public)/verify-email/page");
    const modR = await import("@/app/(public)/reset-password/page");
    const modC = await import("@/app/(public)/verify-email-change/page");
    for (const mod of [modV, modR, modC]) {
      expect(mod.metadata.robots.index).toBe(false);
      expect(mod.metadata.robots.follow).toBe(false);
    }
  });
});
