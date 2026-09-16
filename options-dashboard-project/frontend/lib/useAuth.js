"use client";
import { useState, useEffect, useCallback } from "react";
import { captureGoogleIdTokenFromUrl } from "./session";
import { getStatus, getMe, logoutUser, loginEmail, registerEmail, loginGoogle, getAccountSession, logoutAccount } from "./api";

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

  // Capture session from OAuth callback URL fragment on mount
  useEffect(() => {
    captureSessionFromUrl();

    // Handle Google OAuth redirect callback
    const googleResult = captureGoogleIdTokenFromUrl();
    if (googleResult) {
      // Send the Google id_token to our backend (state is MANDATORY — the
      // backend validates the HMAC state and its nonce binding).
      loginWithGoogle(googleResult.idToken, googleResult.state).catch(() => {
        // Error is already handled by loginWithGoogle
      });
    }
  }, []);

  // Check auth status on mount and when session changes
  const checkAuth = useCallback(async () => {
    try {
      const session = getSessionId();
      if (!session) {
        setUser(null);
        setLoading(false);
        return;
      }
      const status = await getStatus();
      if (!status.logged_in) {
        clearSessionId();
        setUser(null);
        setLoading(false);
        return;
      }
      const me = await getMe();
      setUser(me);
      setError(null);
    } catch (e) {
      clearSessionId();
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
      if (result.session_id) {
        setSessionId(result.session_id);
      }
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
      if (result.session_id) {
        setSessionId(result.session_id);
      }
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
    clearSessionId();
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
