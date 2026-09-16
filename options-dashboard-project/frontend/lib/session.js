/**
 * Secure session management for StrikeNova.
 *
 * The session is stored in an HttpOnly Secure SameSite=None cookie set by
 * the backend. The frontend JavaScript CANNOT read the session cookie.
 *
 * This module provides minimal helpers for session lifecycle that do NOT
 * expose the session identifier to JavaScript:
 *
 * - clearSessionId(): removes any legacy localStorage entry (migration aid)
 * - captureGoogleIdTokenFromUrl(): handles Google OAuth redirect callback
 *
 * The actual session transport is handled entirely by the browser's cookie jar.
 * All API requests use withCredentials: true (configured in api.js) so the
 * HttpOnly cookie is sent automatically.
 */

/**
 * Clear any legacy session ID from localStorage.
 * This is a migration helper for users who have the old localStorage entry.
 * After the migration period, this function can be removed.
 */
export const clearSessionId = () => {
  try {
    window.localStorage.removeItem("options_dashboard_session_id");
  } catch (e) {}
};

/**
 * Legacy helper — no longer needed with HttpOnly cookies.
 * Kept for backward compatibility during transition.
 */
export const getSessionId = () => null;

/**
 * Legacy helper — no longer needed with HttpOnly cookies.
 * Kept for backward compatibility during transition.
 */
export const setSessionId = () => {};

/**
 * Legacy helper — no longer needed with HttpOnly cookies.
 * The backend no longer returns session_id in URL fragments.
 * Kept for backward compatibility during transition.
 */
export const captureSessionFromUrl = () => {};

/**
 * Reads #id_token=... left by Google OAuth redirect flow.
 * Returns { idToken, redirectPath } and IMMEDIATELY scrubs the URL.
 * Security: the JWT is stripped from the address bar before any async work.
 */
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
