const SESSION_KEY = "options_dashboard_session_id";

// The backend and frontend live on different sites (Railway/Vercel), so
// browsers that block third-party cookies drop the session cookie on API
// calls. Instead, the OAuth callback passes the session ID in the URL
// fragment; we store it here and send it as an X-Session-Id header.

export const getSessionId = () => {
  try {
    return window.localStorage.getItem(SESSION_KEY);
  } catch (e) {
    return null;
  }
};

export const setSessionId = (id) => {
  try {
    window.localStorage.setItem(SESSION_KEY, id);
  } catch (e) {}
};

export const clearSessionId = () => {
  try {
    window.localStorage.removeItem(SESSION_KEY);
  } catch (e) {}
};

// Reads #session_id=... left by the OAuth callback redirect, stores it, and
// scrubs it from the URL so it doesn't linger in the address bar or history.
export const captureSessionFromUrl = () => {
  if (typeof window === "undefined") return;
  const match = window.location.hash.match(/session_id=([A-Za-z0-9_-]+)/);
  if (match) {
    setSessionId(match[1]);
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
};

// Reads #id_token=... left by Google OAuth redirect flow.
// Returns { idToken, redirectPath } and IMMEDIATELY scrubs the URL.
// Security: the JWT is stripped from the address bar before any async work.
export const captureGoogleIdTokenFromUrl = () => {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash;
  if (!hash || !hash.includes("id_token=")) return null;

  // Parse the hash fragment: #state=...&iss=...&id_token=...
  const params = new URLSearchParams(hash.substring(1));
  const idToken = params.get("id_token");
  if (!idToken) return null;

  // Extract redirect path from state parameter
  let redirectPath = "/dashboard";
  try {
    const stateStr = params.get("state");
    if (stateStr) {
      const state = JSON.parse(decodeURIComponent(stateStr));
      if (state.redirect) redirectPath = state.redirect;
    }
  } catch {
    // Ignore malformed state — default to /dashboard
  }

  // CRITICAL: strip the token from the URL bar immediately
  window.history.replaceState(null, "", window.location.pathname + window.location.search);

  // Also capture the state parameter (for nonce binding)
  let oauthState = null;
  try {
    const stateStr = params.get("state");
    if (stateStr) oauthState = stateStr;
  } catch {}

  return { idToken, redirectPath, state: oauthState };
};
