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
