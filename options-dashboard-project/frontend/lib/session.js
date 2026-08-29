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
// Returns the id_token if present, then scrubs it from the URL.
// The caller must send this token to POST /auth/google.
export const captureGoogleIdTokenFromUrl = () => {
  if (typeof window === "undefined") return null;
  const match = window.location.hash.match(/id_token=([^&]+)/);
  if (match) {
    const idToken = match[1];
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return idToken;
  }
  return null;
};
