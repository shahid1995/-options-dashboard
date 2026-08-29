"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import { C } from "@/lib/ui";
import { loginUrl, registerEmail, loginEmail, loginGoogle } from "@/lib/api";
import { setSessionId } from "@/lib/session";
import { useRouter } from "next/navigation";

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

const INPUT_FOCUS = { borderColor: C.gold };

const GOLD_BTN = {
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
  transition: "opacity 0.15s",
};

const GHOST_BTN = {
  width: "100%",
  padding: "12px 24px",
  borderRadius: 8,
  border: `1px solid ${C.border}`,
  background: "transparent",
  color: C.text,
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "inherit",
  transition: "border-color 0.15s, background 0.15s",
};

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

/**
 * Native Google Sign-In button using Google Identity Services directly.
 * More reliable than @react-oauth/google because it manages its own
 * script loading and renders the Google button natively.
 */
function GoogleSignInButton({ onSuccess, onError }) {
  const buttonRef = useRef(null);
  const googleInitialized = useRef(false);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !buttonRef.current) return;

    // Load the GIS script if not already loaded
    const loadGIS = () => {
      if (window.google?.accounts?.id) {
        initializeGoogle();
        return;
      }

      const script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.defer = true;
      script.onload = () => initializeGoogle();
      script.onerror = () => onError("Failed to load Google Sign-In. Please try again.");
      document.body.appendChild(script);
    };

    const initializeGoogle = () => {
      if (googleInitialized.current) return;
      googleInitialized.current = true;

      try {
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (response) => {
            if (response.credential) {
              onSuccess(response.credential);
            } else {
              onError("Google sign-in was cancelled.");
            }
          },
          auto_select: false,
          cancel_on_tap_outside: true,
        });

        // Render the Google button into the ref
        window.google.accounts.id.renderButton(buttonRef.current, {
          type: "standard",
          theme: "outline",
          size: "large",
          width: buttonRef.current.offsetWidth || 340,
          text: "continue_with",
          shape: "rectangular",
        });
      } catch (err) {
        onError("Google Sign-In initialization failed.");
      }
    };

    loadGIS();
  }, [onSuccess, onError]);

  if (!GOOGLE_CLIENT_ID) {
    return (
      <div data-testid="auth-google-btn" style={{ marginBottom: 12 }}>
        <div style={{
          padding: "12px",
          textAlign: "center",
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          color: C.faint,
          fontSize: 13,
        }}>
          Google Sign-In not configured
        </div>
      </div>
    );
  }

  return (
    <div data-testid="auth-google-btn" style={{ marginBottom: 12 }}>
      <div ref={buttonRef} style={{ width: "100%" }} />
    </div>
  );
}

export default function AuthModal({ open, onClose, onAuth }) {
  const router = useRouter();
  const [tab, setTab] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const panelRef = useRef(null);

  // Reset state on open/close
  useEffect(() => {
    if (!open) return;
    setTab("signin");
    setEmail("");
    setPassword("");
    setDisplayName("");
    setError("");
    setSuccess("");
    setLoading(false);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Lock body scroll
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  if (!open) return null;

  const handleAuthSuccess = (data) => {
    if (data?.session_id) setSessionId(data.session_id);
    setSuccess("Authenticated! Redirecting…");
    setLoading(false);
    setTimeout(() => {
      onClose();
      if (onAuth) onAuth();
      else router.push("/dashboard");
    }, 400);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      const fn = tab === "signin" ? loginEmail : registerEmail;
      const args = tab === "signin" ? [email, password] : [email, password, displayName];
      const data = await fn(...args);
      handleAuthSuccess(data);
    } catch (err) {
      setError(err.message || "Authentication failed. Please try again.");
      setLoading(false);
    }
  };

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div
      data-testid="auth-modal-backdrop"
      onClick={handleBackdrop}
      role="dialog"
      aria-modal="true"
      aria-label="Authentication"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.65)",
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
        padding: 20,
      }}
    >
      <div
        ref={panelRef}
        data-testid="auth-modal-panel"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 400,
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: 16,
          padding: "32px 28px 28px",
          position: "relative",
          boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        {/* Close button */}
        <button
          data-testid="auth-modal-close"
          onClick={onClose}
          aria-label="Close"
          style={{
            position: "absolute",
            top: 14,
            right: 14,
            background: "none",
            border: "none",
            color: C.muted,
            fontSize: 20,
            cursor: "pointer",
            padding: "4px 8px",
            lineHeight: 1,
            borderRadius: 4,
          }}
        >
          ✕
        </button>

        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, marginBottom: 4 }}>
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                background: C.gold,
                color: "#0B0E14",
                display: "grid",
                placeItems: "center",
                fontWeight: 900,
                fontSize: 11,
              }}
            >
              OD
            </span>
            <span style={{ fontSize: 14, fontWeight: 800, letterSpacing: 1.2, color: C.text }}>
              STRIKENOVA
            </span>
          </div>
          <div style={{ fontSize: 18, fontWeight: 700, color: C.text, marginTop: 8 }}>
            {tab === "signin" ? "Welcome back" : "Create your account"}
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", borderRadius: 8, border: `1px solid ${C.border}`, overflow: "hidden", marginBottom: 20 }}>
          {[
            { key: "signin", label: "Sign In" },
            { key: "signup", label: "Create Account" },
          ].map((t) => (
            <button
              key={t.key}
              data-testid={`auth-tab-${t.key}`}
              onClick={() => { setTab(t.key); setError(""); setSuccess(""); }}
              style={{
                flex: 1,
                padding: "9px 0",
                background: tab === t.key ? "rgba(201,161,90,0.12)" : "transparent",
                border: "none",
                borderBottom: tab === t.key ? `2px solid ${C.gold}` : "2px solid transparent",
                color: tab === t.key ? C.gold : C.muted,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: "inherit",
                transition: "color 0.15s, background 0.15s",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div
            data-testid="auth-error"
            style={{
              marginBottom: 14,
              padding: "10px 14px",
              borderRadius: 8,
              border: `1px solid ${C.red}`,
              background: "rgba(225,82,82,0.08)",
              color: C.red,
              fontSize: 13,
            }}
          >
            {error}
          </div>
        )}

        {/* Success */}
        {success && (
          <div
            data-testid="auth-success"
            style={{
              marginBottom: 14,
              padding: "10px 14px",
              borderRadius: 8,
              border: `1px solid ${C.green}`,
              background: "rgba(76,175,125,0.08)",
              color: C.green,
              fontSize: 13,
            }}
          >
            {success}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit}>
          {tab === "signup" && (
            <div style={{ marginBottom: 12 }}>
              <label htmlFor="auth-display-name" style={{ display: "block", fontSize: 12, color: C.muted, marginBottom: 4 }}>
                Display Name
              </label>
              <input
                id="auth-display-name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Your name"
                required
                style={INPUT_STYLE}
                onFocus={(e) => { e.target.style.borderColor = C.gold; }}
                onBlur={(e) => { e.target.style.borderColor = C.border; }}
              />
            </div>
          )}

          <div style={{ marginBottom: 12 }}>
            <label htmlFor="auth-email" style={{ display: "block", fontSize: 12, color: C.muted, marginBottom: 4 }}>
              Email
            </label>
            <input
              id="auth-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
              autoComplete="email"
              style={INPUT_STYLE}
              onFocus={(e) => { e.target.style.borderColor = C.gold; }}
              onBlur={(e) => { e.target.style.borderColor = C.border; }}
            />
          </div>

          <div style={{ marginBottom: 18 }}>
            <label htmlFor="auth-password" style={{ display: "block", fontSize: 12, color: C.muted, marginBottom: 4 }}>
              Password
            </label>
            <input
              id="auth-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={tab === "signin" ? "Enter your password" : "Min. 8 characters"}
              required
              minLength={tab === "signup" ? 8 : undefined}
              autoComplete={tab === "signin" ? "current-password" : "new-password"}
              style={INPUT_STYLE}
              onFocus={(e) => { e.target.style.borderColor = C.gold; }}
              onBlur={(e) => { e.target.style.borderColor = C.border; }}
            />
          </div>

          <button
            type="submit"
            data-testid="auth-submit"
            disabled={loading}
            style={{ ...GOLD_BTN, opacity: loading ? 0.7 : 1 }}
          >
            {loading ? "Please wait…" : tab === "signin" ? "Sign In" : "Create Account"}
          </button>
        </form>

        {/* Divider */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "20px 0" }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: 12, color: C.faint, whiteSpace: "nowrap" }}>or continue with</span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>

        {/* Google Sign-In */}
        <GoogleSignInButton
          onSuccess={async (credential) => {
            setLoading(true);
            setError("");
            try {
              const data = await loginGoogle(credential);
              handleAuthSuccess(data);
            } catch (err) {
              setError(err.message || "Google login failed. Please try again.");
              setLoading(false);
            }
          }}
          onError={(msg) => setError(msg)}
        />

        {/* Upstox OAuth */}
        <a
          href={loginUrl()}
          data-testid="auth-upstox-btn"
          style={{
            ...GHOST_BTN,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            textDecoration: "none",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.gold; e.currentTarget.style.background = "rgba(201,161,90,0.06)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.background = "transparent"; }}
        >
          <span style={{ fontWeight: 800, color: "#4FACFE", fontSize: 15 }}>&#8593;</span>
          Connect with Upstox
        </a>

        {/* Footer note */}
        <div style={{ marginTop: 20, textAlign: "center", fontSize: 11, color: C.faint, lineHeight: 1.5 }}>
          By continuing, you agree to our Terms of Service.
          <br />
          Your credentials are encrypted and never shared.
        </div>
      </div>
    </div>
  );
}
