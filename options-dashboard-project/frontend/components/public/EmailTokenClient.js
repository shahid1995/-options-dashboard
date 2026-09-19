"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { C } from "@/lib/ui";
import { useAuthModal } from "@/components/public/AuthModalContext";
import { verifyEmail, resetPassword, verifyEmailChange } from "@/lib/api";

/**
 * Landing surface for the single-use tokens delivered by transactional email
 * (Phase 10.2 account security):
 *
 *   /verify-email?token=…          -> POST /auth/account/verify-email
 *   /reset-password?token=…        -> POST /auth/account/reset-password
 *   /verify-email-change?token=…   -> POST /auth/account/verify-email-change
 *
 * The raw token exists ONLY in the URL while this page opens and in transient
 * component state — it is never stored, never logged, and the URL is
 * rewritten as soon as it is read so the token does not linger in browser
 * history. These are unauthenticated public routes by design: possession of
 * a valid single-use token is the entitlement proof, enforced server-side.
 */

const PANEL = {
  maxWidth: 460,
  margin: "0 auto",
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 16,
  padding: "40px 32px",
  textAlign: "center",
};

const INPUT_STYLE = {
  width: "100%",
  padding: "12px 14px",
  borderRadius: 8,
  border: `1px solid ${C.border}`,
  background: "rgba(11,14,20,0.6)",
  color: C.text,
  fontSize: 14,
  outline: "none",
  fontFamily: "inherit",
  boxSizing: "border-box",
};

const STATE_COLORS = {
  verifying: C.muted,
  token_ready: C.text,
  success: C.green,
  error: C.red,
};

function Icon({ state }) {
  const glyph = state === "success" ? "✓" : state === "error" ? "✕" : "…";
  const bg =
    state === "success"
      ? "rgba(76,175,125,0.12)"
      : state === "error"
        ? "rgba(225,82,82,0.12)"
        : "rgba(201,161,90,0.12)";
  const color =
    state === "success" ? C.green : state === "error" ? C.red : C.gold;
  return (
    <div
      data-testid={`token-icon-${state}`}
      style={{
        width: 56,
        height: 56,
        borderRadius: "50%",
        background: bg,
        color,
        display: "grid",
        placeItems: "center",
        fontSize: 26,
        fontWeight: 800,
        margin: "0 auto 20px",
      }}
    >
      {glyph}
    </div>
  );
}

const TITLES = {
  verify: "Email verification",
  "email-change": "Email address change",
  reset: "Password reset",
};

export default function EmailTokenClient({ mode }) {
  const searchParams = useSearchParams();
  const { open: openAuth } = useAuthModal();
  // Transient state only. The token never leaves this component and is
  // never persisted anywhere.
  const [token, setToken] = useState(null);
  const [state, setState] = useState("verifying");
  const [message, setMessage] = useState("Please wait…");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const raw = searchParams.get("token");
    // Strip the query immediately: the address bar and this history entry no
    // longer carry the raw token.
    window.history.replaceState(null, "", window.location.pathname);

    if (!raw) {
      setState("error");
      setMessage("This link is incomplete. Open the most recent email and use its link.");
      return;
    }
    setToken(raw);

    if (mode === "reset") {
      // The emailed reset link only proves the request; the new password is
      // chosen on this page (transient component state, never persisted).
      setState("token_ready");
      setMessage("Choose a new password for your account.");
      return;
    }

    let cancelled = false;
    const call =
      mode === "email-change" ? verifyEmailChange(raw) : verifyEmail(raw);
    call
      .then((res) => {
        if (cancelled) return;
        setState("success");
        setMessage(
          mode === "email-change"
            ? res?.message || "Your email address has been updated."
            : res?.message || "Your email address is verified. You can sign in now.",
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setState("error");
        setMessage(
          err?.status === 400
            ? "This link is invalid or has already been used. Request a new email."
            : err?.message ||
                "Something went wrong. Try the link again or request a new email.",
        );
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const handleResetSubmit = async (e) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setState("error");
      setMessage("The two passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await resetPassword(token, newPassword);
      setState("success");
      setMessage("Your password has been updated. Sign in with your new password.");
    } catch (err) {
      setState("error");
      setMessage(
        err?.status === 400
          ? "This reset link is invalid, expired, or has already been used. Request a new reset email."
          : err?.message || "Could not update the password. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const stateKey = state === "verifying" ? "verifying" : state;

  return (
    <div
      data-testid={`email-token-page-${mode}`}
      style={{
        minHeight: "70vh",
        display: "grid",
        placeItems: "center",
        padding: "60px 20px",
      }}
    >
      <div style={PANEL}>
        <Icon state={stateKey} />
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: 1.6,
            color: C.gold,
            marginBottom: 10,
          }}
        >
          STRIKENOVA
        </div>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: C.text, marginBottom: 12 }}>
          {TITLES[mode]}
        </h1>

        <div
          data-testid={`token-state-${stateKey}`}
          style={{
            fontSize: 14,
            lineHeight: 1.6,
            color: STATE_COLORS[state] || C.muted,
          }}
        >
          {message}
        </div>

        {state === "verifying" && (
          <div style={{ marginTop: 8, fontSize: 13, color: C.faint }}>
            Please wait…
          </div>
        )}

        {mode === "reset" && state === "token_ready" && (
          <form
            data-testid="token-reset-form"
            onSubmit={handleResetSubmit}
            style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 20 }}
          >
            <input
              type="password"
              data-testid="token-new-password"
              placeholder="New password (min. 8 characters)"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
              style={INPUT_STYLE}
            />
            <input
              type="password"
              data-testid="token-confirm-password"
              placeholder="Confirm new password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
              style={INPUT_STYLE}
            />
            <button
              type="submit"
              data-testid="token-reset-submit"
              disabled={busy}
              style={{
                padding: "12px 24px",
                borderRadius: 8,
                border: "none",
                background: C.gold,
                color: "#0B0E14",
                fontSize: 14,
                fontWeight: 700,
                cursor: busy ? "default" : "pointer",
                opacity: busy ? 0.7 : 1,
                fontFamily: "inherit",
              }}
            >
              {busy ? "Updating…" : "Set new password"}
            </button>
          </form>
        )}

        {state === "success" && (
          <button
            type="button"
            data-testid="token-continue-signin"
            onClick={() => openAuth()}
            style={{
              marginTop: 24,
              width: "100%",
              padding: "12px 24px",
              borderRadius: 8,
              border: "none",
              background: C.gold,
              color: "#0B0E14",
              fontSize: 14,
              fontWeight: 700,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            Continue to sign in
          </button>
        )}
      </div>
    </div>
  );
}
