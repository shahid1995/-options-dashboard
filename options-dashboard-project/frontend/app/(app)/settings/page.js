"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { C } from "@/lib/ui";
import { useAuth } from "@/lib/useAuth";
import {
  loginUrl,
  connectBroker,
  connectAnalyticsToken,
  getAnalyticsTokenStatus,
  removeAnalyticsToken,
} from "@/lib/api";

/**
 * Phase 10.2B-5 — Settings / Account verification page (polished UX).
 *
 * Minimal UI to manually verify:
 * - Login state and user identity
 * - Broker connection (BYOB credentials)
 * - Analytics Token status
 *
 * Does NOT redesign the application. Does NOT expose tokens or credentials.
 */

// ─── Shared styles ─────────────────────────────────────────────────────────

const card = {
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 12,
  padding: 20,
  marginBottom: 16,
};

const sectionTitle = {
  fontSize: 11,
  fontWeight: 800,
  letterSpacing: 1,
  color: C.muted,
  textTransform: "uppercase",
};

const inputBase = {
  width: "100%",
  background: C.surface2,
  border: `1px solid ${C.border}`,
  borderRadius: 8,
  padding: "10px 14px",
  fontSize: 13,
  color: C.text,
  outline: "none",
  transition: "border-color 0.15s",
  fontFamily: "inherit",
  boxSizing: "border-box",
};

const btnPrimary = {
  width: "100%",
  fontSize: 13,
  fontWeight: 700,
  color: "#0B0E14",
  background: C.gold,
  border: "none",
  borderRadius: 8,
  padding: "10px 20px",
  cursor: "pointer",
  fontFamily: "inherit",
  letterSpacing: 0.3,
};

const btnOutline = {
  width: "100%",
  fontSize: 13,
  fontWeight: 700,
  color: C.gold,
  background: "transparent",
  border: `1px solid ${C.gold}55`,
  borderRadius: 8,
  padding: "10px 20px",
  cursor: "pointer",
  fontFamily: "inherit",
  letterSpacing: 0.3,
};

const btnDanger = {
  fontSize: 12,
  fontWeight: 700,
  color: C.red,
  background: "rgba(225,82,82,0.08)",
  border: `1px solid ${C.red}44`,
  borderRadius: 8,
  padding: "8px 16px",
  cursor: "pointer",
  fontFamily: "inherit",
};

const divider = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  margin: "16px 0",
  fontSize: 11,
  color: C.faint,
  letterSpacing: 0.5,
};

const dividerLine = {
  flex: 1,
  height: 1,
  background: C.border,
};

// ─── Helpers ───────────────────────────────────────────────────────────────

function StatusChip({ active, label }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 0.5,
        color: active ? C.green : C.red,
        background: active ? "rgba(76,175,125,0.1)" : "rgba(225,82,82,0.1)",
        border: `1px solid ${active ? "rgba(76,175,125,0.25)" : "rgba(225,82,82,0.25)"}`,
        borderRadius: 999,
        padding: "3px 10px",
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 3,
          background: active ? C.green : C.red,
          flexShrink: 0,
        }}
      />
      {label}
    </span>
  );
}

function InfoTile({ label, value, color }) {
  if (value == null || value === "") return null;
  return (
    <div
      style={{
        background: C.surface2,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: "10px 12px",
        minWidth: 0,
      }}
    >
      <div style={{ fontSize: 9, letterSpacing: 1, color: C.faint, marginBottom: 3 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 12.5,
          fontWeight: 700,
          color: color || C.text,
          wordBreak: "break-word",
          lineHeight: 1.3,
        }}
      >
        {String(value)}
      </div>
    </div>
  );
}

function FlashMessage({ text, isError }) {
  if (!text) return null;
  return (
    <div
      style={{
        fontSize: 12,
        padding: "8px 12px",
        borderRadius: 8,
        color: isError ? C.red : C.green,
        background: isError ? "rgba(225,82,82,0.08)" : "rgba(76,175,125,0.08)",
        border: `1px solid ${isError ? "rgba(225,82,82,0.2)" : "rgba(76,175,125,0.2)"}`,
        lineHeight: 1.4,
      }}
    >
      {text}
    </div>
  );
}

// ─── Auth form (logged out) ────────────────────────────────────────────────

function AuthForm({ authLogin, authRegister }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [isError, setIsError] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage(null);
    setIsError(false);
    try {
      if (mode === "register") {
        await authRegister(email, password, displayName);
        setMessage("Account created. You can now sign in.");
        setMode("login");
        setPassword("");
      } else {
        await authLogin(email, password);
      }
    } catch (err) {
      setMessage(err.message);
      setIsError(true);
    } finally {
      setLoading(false);
    }
  };

  const toggleMode = () => {
    setMode((m) => (m === "login" ? "register" : "login"));
    setMessage(null);
    setIsError(false);
  };

  return (
    <div
      style={{
        maxWidth: 400,
        margin: "40px auto 0",
      }}
    >
      {/* Brand header */}
      <div style={{ textAlign: "center", marginBottom: 28 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: C.gold,
            color: "#0B0E14",
            display: "inline-grid",
            placeItems: "center",
            fontWeight: 900,
            fontSize: 15,
            letterSpacing: -0.5,
            marginBottom: 12,
          }}
        >
          OD
        </div>
        <div style={{ fontSize: 16, fontWeight: 800, color: C.text, letterSpacing: 0.5 }}>
          Options Dashboard
        </div>
        <div style={{ fontSize: 11, color: C.faint, letterSpacing: 1, marginTop: 2 }}>
          NSE · BSE INDEX OPTIONS
        </div>
      </div>

      {/* Auth card */}
      <div style={card}>
        {/* Mode toggle */}
        <div
          style={{
            display: "flex",
            background: C.surface2,
            borderRadius: 8,
            padding: 3,
            marginBottom: 20,
            border: `1px solid ${C.border}`,
          }}
        >
          {["login", "register"].map((m) => (
            <button
              key={m}
              onClick={() => {
                setMode(m);
                setMessage(null);
                setIsError(false);
              }}
              style={{
                flex: 1,
                fontSize: 12,
                fontWeight: 700,
                letterSpacing: 0.3,
                padding: "8px 0",
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                fontFamily: "inherit",
                transition: "all 0.15s",
                background: mode === m ? C.gold : "transparent",
                color: mode === m ? "#0B0E14" : C.muted,
              }}
            >
              {m === "login" ? "Sign In" : "Create Account"}
            </button>
          ))}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {mode === "register" && (
            <input
              type="text"
              placeholder="Display name (optional)"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              style={inputBase}
              onFocus={(e) => { e.target.style.borderColor = C.gold; }}
              onBlur={(e) => { e.target.style.borderColor = C.border; }}
            />
          )}
          <input
            type="email"
            placeholder="Email address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={inputBase}
            onFocus={(e) => { e.target.style.borderColor = C.gold; }}
            onBlur={(e) => { e.target.style.borderColor = C.border; }}
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            style={inputBase}
            onFocus={(e) => { e.target.style.borderColor = C.gold; }}
            onBlur={(e) => { e.target.style.borderColor = C.border; }}
          />

          <FlashMessage text={message} isError={isError} />

          <button
            type="submit"
            disabled={loading}
            style={{ ...btnPrimary, opacity: loading ? 0.6 : 1 }}
          >
            {loading ? "Working…" : mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        {/* Divider */}
        <div style={divider}>
          <div style={dividerLine} />
          <span>or connect with</span>
          <div style={dividerLine} />
        </div>

        {/* Upstox OAuth */}
        <a
          href={loginUrl()}
          style={{
            ...btnOutline,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            textDecoration: "none",
          }}
        >
          <span style={{ fontSize: 14 }}>🔗</span>
          Connect with Upstox
        </a>
      </div>

      {/* Footer */}
      <div style={{ textAlign: "center", fontSize: 11, color: C.faint, marginTop: 4 }}>
        {mode === "login" ? (
          <>
            Don&apos;t have an account?{" "}
            <button onClick={toggleMode} style={{ color: C.gold, background: "none", border: "none", cursor: "pointer", fontSize: 11, fontFamily: "inherit" }}>
              Create one
            </button>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <button onClick={toggleMode} style={{ color: C.gold, background: "none", border: "none", cursor: "pointer", fontSize: 11, fontFamily: "inherit" }}>
              Sign in
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Account section ───────────────────────────────────────────────────────

function AccountSection({ user, onLogout }) {
  return (
    <div style={card}>
      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <div style={sectionTitle}>Account</div>
        <button onClick={onLogout} style={btnDanger}>
          Sign Out
        </button>
      </div>

      {/* Info grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 8,
          marginBottom: 8,
        }}
      >
        <InfoTile label="EMAIL" value={user.email} />
        <InfoTile
          label="STATUS"
          value={user.status?.toUpperCase()}
          color={user.status === "active" ? C.green : C.red}
        />
        <InfoTile label="SOURCE" value={user.identity_source?.toUpperCase()} />
        <InfoTile label="DISPLAY NAME" value={user.display_name} />
        <InfoTile label="USER ID" value={user.user_id} />
        <InfoTile
          label="LAST LOGIN"
          value={
            user.last_login_at
              ? new Date(user.last_login_at).toLocaleString("en-IN", {
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : null
          }
        />
      </div>

      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 4 }}>
        SESSION-SCOPED · NO TOKENS OR CREDENTIALS EXPOSED
      </div>
    </div>
  );
}

// ─── Broker connection section ─────────────────────────────────────────────

function BrokerSection() {
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [isError, setIsError] = useState(false);

  const handleConnect = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage(null);
    setIsError(false);
    try {
      const result = await connectBroker("UPSTOX", apiKey, apiSecret);
      setMessage(`Credentials stored. Status: ${result.status}`);
      setApiKey("");
      setApiSecret("");
    } catch (err) {
      setMessage(err?.response?.data?.detail || err.message || "Failed to store credentials");
      setIsError(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={card}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <div style={sectionTitle}>Broker Connection</div>
        <StatusChip active={false} label="NOT CONNECTED" />
      </div>

      {/* Broker card */}
      <div
        style={{
          background: C.surface2,
          border: `1px solid ${C.border}`,
          borderRadius: 10,
          padding: 14,
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <span style={{ fontSize: 16 }}>🔗</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>Upstox</div>
            <div style={{ fontSize: 11, color: C.muted }}>OAuth connection · Trading + Market Data</div>
          </div>
        </div>
      </div>

      {/* Credentials form */}
      <form onSubmit={handleConnect} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <input
          type="text"
          placeholder="API Key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required
          style={inputBase}
          onFocus={(e) => { e.target.style.borderColor = C.gold; }}
          onBlur={(e) => { e.target.style.borderColor = C.border; }}
        />
        <input
          type="password"
          placeholder="API Secret"
          value={apiSecret}
          onChange={(e) => setApiSecret(e.target.value)}
          required
          style={inputBase}
          onFocus={(e) => { e.target.style.borderColor = C.gold; }}
          onBlur={(e) => { e.target.style.borderColor = C.border; }}
        />

        <FlashMessage text={message} isError={isError} />

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button
            type="submit"
            disabled={loading}
            style={{ ...btnPrimary, flex: "1 1 160px", opacity: loading ? 0.6 : 1 }}
          >
            {loading ? "Storing…" : "Store Credentials"}
          </button>
          <a
            href={loginUrl()}
            style={{
              ...btnOutline,
              flex: "1 1 160px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              textDecoration: "none",
            }}
          >
            Connect via OAuth →
          </a>
        </div>
      </form>

      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 10 }}>
        CREDENTIALS ENCRYPTED AT REST · NEVER LOGGED OR EXPOSED · BYOB ARCHITECTURE
      </div>
    </div>
  );
}

// ─── Analytics Token section ───────────────────────────────────────────────

function AnalyticsTokenSection() {
  const [hasToken, setHasToken] = useState(null);
  const [tokenInput, setTokenInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [isError, setIsError] = useState(false);

  const checkStatus = useCallback(async () => {
    try {
      const result = await getAnalyticsTokenStatus();
      setHasToken(result.has_analytics_token);
    } catch {
      setHasToken(null);
    }
  }, []);

  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  const handleStore = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage(null);
    setIsError(false);
    try {
      await connectAnalyticsToken(tokenInput);
      setMessage("Analytics Token stored successfully.");
      setTokenInput("");
      checkStatus();
    } catch (err) {
      setMessage(err?.response?.data?.detail || err.message || "Failed to store token");
      setIsError(true);
    } finally {
      setLoading(false);
    }
  };

  const handleRemove = async () => {
    setLoading(true);
    setMessage(null);
    setIsError(false);
    try {
      await removeAnalyticsToken();
      setMessage("Analytics Token removed.");
      checkStatus();
    } catch (err) {
      setMessage(err?.response?.data?.detail || err.message || "Failed to remove token");
      setIsError(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={card}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 14,
        }}
      >
        <div style={sectionTitle}>Analytics Token</div>
        <StatusChip
          active={hasToken === true}
          label={
            hasToken === null
              ? "CHECKING…"
              : hasToken
                ? "CONNECTED"
                : "NOT CONNECTED"
          }
        />
      </div>

      {hasToken ? (
        <div>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 12, lineHeight: 1.5 }}>
            Your Upstox Analytics Token is stored and will be used for background GEX data capture.
          </div>
          <button onClick={handleRemove} disabled={loading} style={{ ...btnDanger, opacity: loading ? 0.6 : 1 }}>
            {loading ? "Removing…" : "Remove Analytics Token"}
          </button>
        </div>
      ) : (
        <form onSubmit={handleStore} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 2, lineHeight: 1.5 }}>
            Store your Upstox Analytics Token for read-only market data access (1-year validity).
          </div>
          <input
            type="password"
            placeholder="Analytics Token"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            required
            style={inputBase}
            onFocus={(e) => { e.target.style.borderColor = C.gold; }}
            onBlur={(e) => { e.target.style.borderColor = C.border; }}
          />
          <FlashMessage text={message} isError={isError} />
          <button
            type="submit"
            disabled={loading}
            style={{ ...btnPrimary, opacity: loading ? 0.6 : 1 }}
          >
            {loading ? "Storing…" : "Store Analytics Token"}
          </button>
        </form>
      )}

      {message && hasToken && (
        <div style={{ marginTop: 10 }}>
          <FlashMessage text={message} isError={isError} />
        </div>
      )}

      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 10 }}>
        READ-ONLY · 1-YEAR VALIDITY · ENCRYPTED AT REST · NEVER EXPOSED IN UI/LOGS
      </div>
    </div>
  );
}

// ─── Main Settings page ────────────────────────────────────────────────────

export default function SettingsPage() {
  const { user, loading, isLoggedIn, login, register, logout } = useAuth();
  const router = useRouter();

  const handleLogout = useCallback(async () => {
    await logout();
    router.replace("/");
  }, [logout, router]);

  if (loading) {
    return (
      <div style={{ maxWidth: 700 }}>
        <div style={{ textAlign: "center", padding: "60px 20px", color: C.muted, fontSize: 13 }}>
          Checking authentication…
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 700 }}>
      {!isLoggedIn ? (
        <AuthForm authLogin={login} authRegister={register} />
      ) : (
        <>
          <AccountSection user={user} onLogout={handleLogout} />
          <BrokerSection />
          <AnalyticsTokenSection />
        </>
      )}
    </div>
  );
}
