from pathlib import Path
import re

ROOT = Path("options-dashboard-project")


def must_replace(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{label}: expected {count} matches, found {actual}")
    return text.replace(old, new, count)


# ---------------------------------------------------------------------------
# Frontend session transport
# ---------------------------------------------------------------------------
(ROOT / "frontend/lib/session.js").write_text(
    '''const captureGoogleIdTokenFromUrl = () => {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash;
  if (!hash || !hash.includes("id_token=")) return null;

  const params = new URLSearchParams(hash.substring(1));
  const idToken = params.get("id_token");
  if (!idToken) return null;

  let redirectPath = "/dashboard";
  try {
    const stateStr = params.get("state");
    if (stateStr) {
      const state = JSON.parse(decodeURIComponent(stateStr));
      if (state.redirect) redirectPath = state.redirect;
    }
  } catch {}

  window.history.replaceState(null, "", window.location.pathname + window.location.search);

  let oauthState = null;
  try {
    const stateStr = params.get("state");
    if (stateStr) oauthState = stateStr;
  } catch {}

  return { idToken, redirectPath, state: oauthState };
};

export { captureGoogleIdTokenFromUrl };
''',
    encoding="utf-8",
)

(ROOT / "frontend/components/AuthGate.js").write_text(
    '''"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getMe } from "@/lib/api";

/**
 * Central auth guard for the (app) route group.
 *
 * /auth/me is the authoritative platform-identity check. Broker connectivity
 * is deliberately not part of this decision: a logged-in user may have no
 * broker connected.
 *
 * Authentication failures redirect to the public landing page. Network or
 * server failures do not log the user out; they render a retryable state
 * because an outage is not evidence that the session is invalid.
 */
export default function AuthGate({ children }) {
  const [state, setState] = useState("checking");
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    const verify = async () => {
      try {
        await getMe();
        if (!cancelled) {
          setError("");
          setState("authenticated");
        }
      } catch (err) {
        if (cancelled) return;
        const status = err?.response?.status;
        if (status === 401 || status === 403) {
          router.replace("/");
          return;
        }
        setError("We couldn't verify your session. Check your connection and try again.");
        setState("error");
      }
    };

    verify();
    return () => { cancelled = true; };
  }, [router, retryKey]);

  if (state === "checking") return null;

  if (state === "error") {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
        <div style={{ textAlign: "center", maxWidth: 440 }}>
          <p style={{ fontSize: 14, marginBottom: 16 }}>{error}</p>
          <button type="button" onClick={() => setRetryKey((value) => value + 1)}>Retry</button>
        </div>
      </div>
    );
  }

  return children;
}
''',
    encoding="utf-8",
)

api_path = ROOT / "frontend/lib/api.js"
api = api_path.read_text(encoding="utf-8")
api = re.sub(
    r'^import axios from "axios";\nimport \{ getSessionId \} from "\./session";\n\nexport const api = axios\.create\(\{\n  baseURL: process\.env\.NEXT_PUBLIC_API_URL,\n  withCredentials: true,\n\}\);\n\n.*?api\.interceptors\.request\.use\(\(config\) => \{.*?\n\}\);\n\n',
    'import axios from "axios";\n\nexport const api = axios.create({\n  baseURL: process.env.NEXT_PUBLIC_API_URL,\n  withCredentials: true,\n});\n\n',
    api,
    count=1,
    flags=re.S | re.M,
)
api = re.sub(
    r'// Browsers can.*?export const chainWsProtocols = \(\) => \{.*?\n\};\n',
    '// WebSocket connections automatically include the HttpOnly session cookie.\nexport const chainWsProtocols = () => undefined;\n',
    api,
    count=1,
    flags=re.S,
)
if "getSessionId" in api or 'X-Session-Id' in api or 'chainWsProtocols = () => {' in api:
    raise SystemExit("api.js still contains browser session transport")
api_path.write_text(api, encoding="utf-8")

(ROOT / "frontend/lib/useAuth.js").write_text(
    '''"use client";
import { useState, useEffect, useCallback } from "react";
import { captureGoogleIdTokenFromUrl } from "./session";
import {
  getStatus,
  getMe,
  logoutUser,
  loginEmail,
  registerEmail,
  loginGoogle,
  getAccountSession,
  logoutAccount,
} from "./api";

/**
 * Central auth hook for the StrikeNova frontend.
 *
 * Platform authentication is cookie-based. JavaScript never receives the
 * session credential. Broker connectivity remains a separate concern.
 */
export function useAuth() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const googleResult = captureGoogleIdTokenFromUrl();
    if (googleResult) {
      loginWithGoogle(googleResult.idToken, googleResult.state).catch(() => {});
    }
  }, []);

  const checkAuth = useCallback(async () => {
    try {
      const status = await getStatus();
      if (!status.logged_in) {
        setUser(null);
        setLoading(false);
        return;
      }
      const me = await getMe();
      setUser(me);
      setError(null);
    } catch (e) {
      setUser(null);
      if (e?.response?.status !== 401) {
        setError(e.message || "Failed to check auth status");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = useCallback(async (email, password) => {
    setError(null);
    try {
      const result = await loginEmail(email, password);
      setUser(result.user || null);
      return result;
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message || "Login failed";
      setError(msg);
      throw new Error(msg);
    }
  }, []);

  const register = useCallback(async (email, password, displayName) => {
    setError(null);
    try {
      const result = await registerEmail(email, password, displayName);
      return result;
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message || "Registration failed";
      setError(msg);
      throw new Error(msg);
    }
  }, []);

  const loginWithGoogle = useCallback(async (credential, state) => {
    setError(null);
    try {
      const result = await loginGoogle(credential, state);
      setUser(result.user || null);
      return result;
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message || "Google login failed";
      setError(msg);
      throw new Error(msg);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutUser();
    } catch {
      // Local UI state is cleared even if the server is unavailable.
    }
    setUser(null);
  }, []);

  const checkAccountSession = useCallback(async () => {
    try {
      const result = await getAccountSession();
      setUser(result.user || null);
      setError(null);
      return result;
    } catch (e) {
      setUser(null);
      if (e?.response?.status !== 401) {
        setError(e.message || "Failed to check account session");
      }
      return null;
    }
  }, []);

  const logoutAccountSession = useCallback(async () => {
    try {
      await logoutAccount();
    } catch {
      // Local UI state is cleared even if the server is unavailable.
    }
    setUser(null);
  }, []);

  return {
    user,
    loading,
    error,
    isLoggedIn: !!user,
    login,
    loginWithGoogle,
    register,
    logout,
    checkAccountSession,
    logoutAccountSession,
    refresh: checkAuth,
  };
}
''',
    encoding="utf-8",
)

shell_path = ROOT / "frontend/components/Shell.js"
shell = shell_path.read_text(encoding="utf-8")
shell = must_replace(shell, '''      try {\n        const { getSessionId } = await import("@/lib/session");\n        const { getStatus, getMe } = await import("@/lib/api");\n        const session = getSessionId();\n        if (!session) return;\n        const status = await getStatus();\n        if (status.logged_in) {\n          const me = await getMe();\n          setAuthUser(me);\n        }\n      } catch {}\n''', '''      try {\n        const { getStatus, getMe } = await import("@/lib/api");\n        const status = await getStatus();\n        if (status.logged_in) {\n          const me = await getMe();\n          setAuthUser(me);\n        }\n      } catch {}\n''', "Shell bootstrap")
shell = must_replace(shell, '''    try {\n      const { logoutUser } = await import("@/lib/api");\n      const { clearSessionId } = await import("@/lib/session");\n      await logoutUser();\n      clearSessionId();\n    } catch {}\n''', '''    try {\n      const { logoutUser } = await import("@/lib/api");\n      await logoutUser();\n    } catch {}\n''', "Shell logout")
shell_path.write_text(shell, encoding="utf-8")

modal_path = ROOT / "frontend/components/public/AuthModal.js"
modal = modal_path.read_text(encoding="utf-8")
modal = modal.replace('import { setSessionId } from "@/lib/session";\n', "", 1)
modal = must_replace(modal, '''  const handleAuthSuccess = (data) => {\n    if (data?.session_id) setSessionId(data.session_id);\n    setSuccess("Authenticated! Redirecting…");\n    setLoading(false);\n    setTimeout(() => {\n      onClose();\n      const appUrl = process.env.NEXT_PUBLIC_APP_URL || "";\n      if (data?.session_id && appUrl) {\n        // Cross-origin handoff: navigate to authenticated app with session in fragment\n        window.location.assign(`${appUrl}/dashboard#session_id=${encodeURIComponent(data.session_id)}`);\n      } else {\n        // Fallback: same-origin navigation\n        if (onAuth) onAuth();\n        else router.push("/dashboard");\n      }\n    }, 400);\n  };\n''', '''  const handleAuthSuccess = () => {\n    setSuccess("Authenticated! Redirecting…");\n    setLoading(false);\n    setTimeout(() => {\n      onClose();\n      const appUrl = process.env.NEXT_PUBLIC_APP_URL || "";\n      if (appUrl) {\n        window.location.assign(`${appUrl}/dashboard`);\n      } else if (onAuth) {\n        onAuth();\n      } else {\n        router.replace("/dashboard");\n      }\n    }, 400);\n  };\n''', "AuthModal handoff")
modal_path.write_text(modal, encoding="utf-8")

# ---------------------------------------------------------------------------
# Backend transport
# ---------------------------------------------------------------------------
(ROOT / "backend/app/routers/deps.py").write_text(
    '''from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db

SESSION_COOKIE_NAME = "strikenova_session"


def get_session_id(
    x_session_id: str | None = Header(default=None),
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> str | None:
    """Resolve the browser session from the HttpOnly cookie first."""
    return session_id or x_session_id


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    access_token: str | None


def _extract_session_id(x_session_id: str | None, session_id_cookie: str | None) -> str:
    sid = session_id_cookie or x_session_id
    if not sid:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return sid


def _resolve_user(db: Session, sid: str) -> AuthenticatedUser:
    from app.identity import get_active_session, User
    from app.services import token_store

    broker_token = token_store.get_token(sid)
    session = get_active_session(db, sid)
    if session is None:
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")

    user = db.query(User).filter(User.id == session.user_id).one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=403, detail="StrikeNova account is not active.")
    return AuthenticatedUser(user_id=user.id, access_token=broker_token)


def get_current_user(
    x_session_id: str | None = Header(default=None),
    session_id_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AuthenticatedUser:
    sid = _extract_session_id(x_session_id, session_id_cookie)
    from app.db import SessionLocal
    own_db = SessionLocal()
    try:
        return _resolve_user(own_db, sid)
    finally:
        own_db.close()


class CurrentUser:
    def __call__(
        self,
        db: Session = Depends(get_db),
        x_session_id: str | None = Header(default=None),
        session_id_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ) -> AuthenticatedUser:
        sid = _extract_session_id(x_session_id, session_id_cookie)
        return _resolve_user(db, sid)
''',
    encoding="utf-8",
)

chains_path = ROOT / "backend/app/routers/chains.py"
chains = chains_path.read_text(encoding="utf-8")
chains = chains.replace('\nWS_SESSION_PROTOCOL = "options-dashboard-session"\n', '\n', 1)
chains = must_replace(chains, '''def ws_session(websocket: WebSocket) -> tuple[str | None, str | None]:\n    """Extracts the session ID from the websocket handshake.\n\n    Browsers can't set custom headers on websockets, so the frontend sends the\n    session ID as the second entry of the Sec-WebSocket-Protocol list (falling\n    back to the session cookie). Returns (session_id, subprotocol_to_accept)."""\n    requested = websocket.headers.get("sec-websocket-protocol")\n    if requested:\n        parts = [p.strip() for p in requested.split(",")]\n        if len(parts) == 2 and parts[0] == WS_SESSION_PROTOCOL:\n            return parts[1], WS_SESSION_PROTOCOL\n    return websocket.cookies.get("session_id"), None\n''', '''def ws_session(websocket: WebSocket) -> tuple[str | None, str | None]:\n    """Resolve the platform session from the canonical HttpOnly cookie only."""\n    return websocket.cookies.get("strikenova_session"), None\n''', "WebSocket transport")
chains_path.write_text(chains, encoding="utf-8")

# Auth router: preserve all account-security behavior, changing only browser session transport.
auth_path = ROOT / "backend/app/routers/auth.py"
auth = auth_path.read_text(encoding="utf-8")
auth = auth.replace('SESSION_COOKIE = "session_id"', 'SESSION_COOKIE_NAME = "strikenova_session"\nSESSION_COOKIE_TTL = 60 * 60 * 24', 1)
auth = re.sub(r"\bSESSION_COOKIE\b", "SESSION_COOKIE_NAME", auth)

auth = must_replace(auth, '''    # Send the user back to the dashboard. The session ID is passed in the\n    # URL fragment because it is not sent to servers as a query parameter.\n    response = RedirectResponse(\n        f"{settings.FRONTEND_ORIGIN}/dashboard#session_id={session_id}"\n    )\n    response.set_cookie(\n        SESSION_COOKIE_NAME,\n        session_id,\n        httponly=True,\n        secure=True,\n        samesite="none",\n        max_age=60 * 60 * 24,\n    )\n    return response''', '''    # The session is stored in the HttpOnly cookie, never the URL.\n    response = RedirectResponse(f"{settings.FRONTEND_ORIGIN}/dashboard")\n    response.set_cookie(\n        SESSION_COOKIE_NAME,\n        session_id,\n        httponly=True,\n        secure=True,\n        samesite="none",\n        max_age=SESSION_COOKIE_TTL,\n        path="/",\n    )\n    return response''', "OAuth callback transport")

auth = must_replace(auth, '''def login_email(\n    email: str = Body(..., embed=True),\n    password: str = Body(..., embed=True),\n    db: Session = Depends(get_db),\n):''', '''def login_email(\n    email: str = Body(..., embed=True),\n    password: str = Body(..., embed=True),\n    response: Response = None,\n    db: Session = Depends(get_db),\n):''', "legacy email login signature")

auth = must_replace(auth, '''def google_auth(\n    credential: str = Body(..., embed=True),\n    state: str | None = Body(default=None, embed=True),\n    db: Session = Depends(get_db),\n):''', '''def google_auth(\n    credential: str = Body(..., embed=True),\n    state: str | None = Body(default=None, embed=True),\n    response: Response = None,\n    db: Session = Depends(get_db),\n):''', "google login signature")

session_return = '''    create_session_record(db, user.id, session_id)\n    db.commit()\n\n    return {\n        "ok": True,\n        "session_id": session_id,\n'''
session_secure = '''    create_session_record(db, user.id, session_id)\n    db.commit()\n\n    response.set_cookie(\n        SESSION_COOKIE_NAME, session_id, httponly=True, secure=True,\n        samesite="none", max_age=SESSION_COOKIE_TTL, path="/"\n    )\n\n    return {\n        "ok": True,\n'''
auth = must_replace(auth, session_return, session_secure, "legacy login response contracts", count=2)

auth = must_replace(auth, '''    return {\n        "ok": True,\n        "session_id": session_id,\n        "user": {\n''', '''    return {\n        "ok": True,\n        "user": {\n''', "account login response")
auth = auth.replace('max_age=60 * 60 * 24,', 'max_age=SESSION_COOKIE_TTL,')
auth_path.write_text(auth, encoding="utf-8")

# Final source invariants.
assert 'getSessionId' not in (ROOT / "frontend/components/AuthGate.js").read_text(encoding="utf-8")
assert 'X-Session-Id' not in api_path.read_text(encoding="utf-8")
assert 'chainWsProtocols = () => undefined' in api_path.read_text(encoding="utf-8")
assert 'setSessionId' not in modal_path.read_text(encoding="utf-8")
assert 'clearSessionId' not in shell_path.read_text(encoding="utf-8")
assert 'SESSION_COOKIE_NAME = "strikenova_session"' in auth
assert '"session_id": session_id' not in auth
assert 'strikenova_session' in chains_path.read_text(encoding="utf-8")
print("Issue 61 secure transport reconciliation applied")
