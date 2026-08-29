"use client";
import { useState, useEffect, useCallback } from "react";
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
 * Phase 10.2B-5 — Settings / Account verification page.
 *
 * Minimal UI to manually verify:
 * - Login state and user identity
 * - Broker connection (BYOB credentials)
 * - Analytics Token status
 *
 * Does NOT redesign the application. Does NOT expose tokens or credentials.
 */

const panel = {
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 10,
  padding: 16,
  marginBottom: 16,
};
const sectionTitle = {
  fontSize: 12,
  fontWeight: 800,
  letterSpacing: 0.8,
  color: C.muted,
  marginBottom: 10,
};
const inputStyle = {
  background: C.surface2,
  border: `1px solid ${C.border}`,
  borderRadius: 6,
  padding: "8px 12px",
  fontSize: 13,
  color: C.text,
  width: "100%",
  outline: "none",
};
const btnGold = {
  fontSize: 12,
  fontWeight: 700,
  color: "#0B0E14",
  background: C.gold,
  border: "none",
  borderRadius: 6,
  padding: "8px 16px",
  cursor: "pointer",
};
const btnGhost = {
  fontSize: 12,
  fontWeight: 700,
  color: C.gold,
  background: "rgba(201,161,90,0.08)",
  border: `1px solid ${C.gold}66`,
  borderRadius: 6,
  padding: "8px 16px",
  cursor: "pointer",
};
const btnDanger = {
  fontSize: 12,
  fontWeight: 700,
  color: C.red,
  background: "rgba(225,82,82,0.08)",
  border: `1px solid ${C.red}55`,
  borderRadius: 6,
  padding: "8px 16px",
  cursor: "pointer",
};
const statusDot = (active) => ({
  display: "inline-block",
  width: 8,
  height: 8,
  borderRadius: 4,
  background: active ? C.green : C.red,
  marginRight: 6,
});

// ---------------------------------------------------------------------------
// Info field helper
// ---------------------------------------------------------------------------

function InfoField({ label, value, color }) {
  if (value == null || value === "") return null;
  return (
    <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
      <div style={{ fontSize: 9, letterSpacing: 1, color: C.faint }}>{label}</div>
      <div style={{ fontSize: 12, fontWeight: 700, color: color || C.text, marginTop: 2, wordBreak: "break-word" }}>
        {String(value)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Login / Signup form (shown when not logged in)
// ---------------------------------------------------------------------------

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
        // Login sets session; page will re-render as isLoggedIn becomes true
      }
    } catch (err) {
      setMessage(err.message);
      setIsError(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={panel}>
      <div style={sectionTitle}>
        {mode === "login" ? "SIGN IN" : "CREATE ACCOUNT"}
      </div>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          style={inputStyle}
        />
        {mode === "register" && (
          <input
            type="text"
            placeholder="Display name (optional)"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            style={inputStyle}
          />
        )}
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          style={inputStyle}
        />
        {message && (
          <div
            style={{
              fontSize: 12,
              padding: "8px 12px",
              borderRadius: 6,
              color: isError ? C.red : C.green,
              background: isError ? "rgba(225,82,82,0.08)" : "rgba(76,175,125,0.08)",
              border: `1px solid ${isError ? C.red : C.green}33`,
            }}
          >
            {message}
          </div>
        )}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button type="submit" disabled={loading} style={{ ...btnGold, opacity: loading ? 0.6 : 1 }}>
            {loading ? "Working…" : mode === "login" ? "Sign In" : "Create Account"}
          </button>
          <button
            type="button"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setMessage(null);
            }}
            style={btnGhost}
          >
            {mode === "login" ? "Create Account" : "Sign In Instead"}
          </button>
        </div>
      </form>
      <div style={{ marginTop: 12, fontSize: 11, color: C.faint }}>
        Or{" "}
        <a href={loginUrl()} style={{ color: C.gold }}>
          sign in with Upstox
        </a>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Account section (shown when logged in)
// ---------------------------------------------------------------------------

function AccountSection({ user, onLogout }) {
  return (
    <div style={panel}>
      <div style={sectionTitle}>ACCOUNT</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginBottom: 12 }}>
        <InfoField label="EMAIL" value={user.email} />
        <InfoField label="DISPLAY NAME" value={user.display_name} />
        <InfoField label="USER ID" value={user.user_id} />
        <InfoField label="STATUS" value={user.status?.toUpperCase()} color={user.status === "active" ? C.green : C.red} />
        <InfoField label="IDENTITY SOURCE" value={user.identity_source?.toUpperCase()} />
        <InfoField label="LAST LOGIN" value={user.last_login_at ? new Date(user.last_login_at).toLocaleString("en-IN") : null} />
      </div>
      <button onClick={onLogout} style={btnDanger}>
        Sign Out
      </button>
      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 8 }}>
        SESSION-SCOPED · NO TOKENS OR CREDENTIALS EXPOSED
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Broker Connection section
// ---------------------------------------------------------------------------

function BrokerSection() {
  const [broker, setBroker] = useState("UPSTOX");
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
      const result = await connectBroker(broker, apiKey, apiSecret);
      setMessage(`Broker credentials stored. Connection status: ${result.status}`);
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
    <div style={panel}>
      <div style={sectionTitle}>BROKER CONNECTION</div>
      <div style={{ fontSize: 11, color: C.muted, marginBottom: 10 }}>
        Store your Upstox Developer App credentials. The actual connection is made via OAuth.
      </div>
      <form onSubmit={handleConnect} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <select
          value={broker}
          onChange={(e) => setBroker(e.target.value)}
          style={{ ...inputStyle, cursor: "pointer" }}
        >
          <option value="UPSTOX">Upstox</option>
        </select>
        <input
          type="text"
          placeholder="API Key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required
          style={inputStyle}
        />
        <input
          type="password"
          placeholder="API Secret"
          value={apiSecret}
          onChange={(e) => setApiSecret(e.target.value)}
          required
          style={inputStyle}
        />
        {message && (
          <div
            style={{
              fontSize: 12,
              padding: "8px 12px",
              borderRadius: 6,
              color: isError ? C.red : C.green,
              background: isError ? "rgba(225,82,82,0.08)" : "rgba(76,175,125,0.08)",
              border: `1px solid ${isError ? C.red : C.green}33`,
            }}
          >
            {message}
          </div>
        )}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button type="submit" disabled={loading} style={{ ...btnGold, opacity: loading ? 0.6 : 1 }}>
            {loading ? "Storing…" : "Store Broker Credentials"}
          </button>
          <a href={loginUrl()} style={{ ...btnGhost, textDecoration: "none", display: "inline-flex", alignItems: "center" }}>
            Connect via OAuth →
          </a>
        </div>
      </form>
      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 8 }}>
        CREDENTIALS ARE ENCRYPTED AT REST · NEVER LOGGED OR EXPOSED · BYOB ARCHITECTURE
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Analytics Token section
// ---------------------------------------------------------------------------

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
    <div style={panel}>
      <div style={sectionTitle}>ANALYTICS TOKEN</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ ...statusDot(hasToken === true) }} />
        <span style={{ fontSize: 12, fontWeight: 700, color: hasToken ? C.green : C.muted }}>
          {hasToken === null ? "Checking…" : hasToken ? "Connected" : "Not Connected"}
        </span>
      </div>

      {hasToken ? (
        <div>
          <button onClick={handleRemove} disabled={loading} style={btnDanger}>
            {loading ? "Removing…" : "Remove Analytics Token"}
          </button>
          {message && (
            <div
              style={{
                fontSize: 12,
                padding: "8px 12px",
                borderRadius: 6,
                marginTop: 10,
                color: isError ? C.red : C.green,
                background: isError ? "rgba(225,82,82,0.08)" : "rgba(76,175,125,0.08)",
                border: `1px solid ${isError ? C.red : C.green}33`,
              }}
            >
              {message}
            </div>
          )}
        </div>
      ) : (
        <form onSubmit={handleStore} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <input
            type="password"
            placeholder="Upstox Analytics Token"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            required
            style={inputStyle}
          />
          {message && (
            <div
              style={{
                fontSize: 12,
                padding: "8px 12px",
                borderRadius: 6,
                color: isError ? C.red : C.green,
                background: isError ? "rgba(225,82,82,0.08)" : "rgba(76,175,125,0.08)",
                border: `1px solid ${isError ? C.red : C.green}33`,
              }}
            >
              {message}
            </div>
          )}
          <button type="submit" disabled={loading} style={{ ...btnGold, opacity: loading ? 0.6 : 1 }}>
            {loading ? "Storing…" : "Store Analytics Token"}
          </button>
        </form>
      )}
      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 8 }}>
        READ-ONLY MARKET DATA ACCESS · 1-YEAR VALIDITY · ENCRYPTED AT REST · NEVER EXPOSED IN UI/LOGS
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Settings page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const { user, loading, isLoggedIn, login, register, logout } = useAuth();

  if (loading) {
    return (
      <div style={{ maxWidth: 700 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: "0 0 4px" }}>Settings</h1>
        <p style={{ fontSize: 13, color: C.muted }}>Checking authentication…</p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 700 }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Settings
        </h1>
        <p style={{ fontSize: 13, color: C.muted, margin: 0 }}>
          Account, broker connection, and analytics token management
        </p>
      </div>

      {!isLoggedIn ? (
        <AuthForm authLogin={login} authRegister={register} />
      ) : (
        <>
          <AccountSection user={user} onLogout={logout} />
          <BrokerSection />
          <AnalyticsTokenSection />
        </>
      )}
    </div>
  );
}
