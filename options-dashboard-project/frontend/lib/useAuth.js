"use client";
import { useState, useEffect, useCallback } from "react";
import { captureGoogleIdTokenFromUrl } from "./session";
import { getMe, logoutUser, loginEmail, registerEmail, loginGoogle, getAccountSession, logoutAccount } from "./api";

/**
 * Central auth hook for the StrikeNova frontend.
 *
 * - Checks session validity on mount
 * - Provides login (email), register, logout
 * - Exposes the authenticated user's identity
 * - Never exposes tokens or credentials
 */
export function useAuth() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Handle Google OAuth redirect callback on mount. The platform session
  // itself travels ONLY via the HttpOnly strikenova_session cookie (Issue
  // #61) — never via URL fragments, storage, or custom headers.
  useEffect(() => {
    const googleResult = captureGoogleIdTokenFromUrl();
    if (googleResult) {
      // Send the Google id_token to our backend (state is MANDATORY — the
      // backend validates the HMAC state and its nonce binding).
      loginWithGoogle(googleResult.idToken, googleResult.state).catch(() => {
        // Error is already handled by loginWithGoogle
      });
    }
  }, []);

  // Check auth on mount and when session changes. /auth/me is the
  // authoritative check: the browser presents the HttpOnly cookie and the
  // server resolves the durable UserSession. 401/403 mean logged out;
  // anything else (5xx/network) is surfaced as a retryable error — never a
  // silent local logout.
  const checkAuth = useCallback(async () => {
    try {
      const me = await getMe();
      setUser(me);
      setError(null);
    } catch (e) {
      setUser(null);
      const status = e?.response?.status;
      if (status !== 401 && status !== 403) {
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
      // Session arrives as the HttpOnly strikenova_session cookie — the
      // response body carries user info only.
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
      // Session arrives as the HttpOnly strikenova_session cookie — the
      // response body carries user info only.
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
      // Ignore logout errors — clear local state regardless
    }
    // The server revoked the durable session; the browser drops the cookie.
    setUser(null);
  }, []);

  // ---- Account-security session behavior (2026-09-16 plan Task 1) ----

  // Resolve the account session server-side via GET /auth/account/session.
  // The durable UserSession record is the authority — never client state.
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

  // Logout via the account endpoint (revokes the durable session), then
  // clear local state regardless of the outcome.
  const logoutAccountSession = useCallback(async () => {
    try {
      await logoutAccount();
    } catch {
      // Ignore logout errors — clear local state regardless
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
