"use client";
import { useState, useEffect, useCallback } from "react";
import { captureGoogleIdTokenFromUrl } from "./session";
import { getStatus, getMe, logoutUser, loginEmail, registerEmail, loginGoogle } from "./api";

/**
 * Central auth hook for the StrikeNova frontend.
 *
 * - Checks session validity on mount
 * - Provides login (email), register, logout
 * - Exposes the authenticated user's identity
 * - Never exposes tokens or credentials
 *
 * Session is stored in HttpOnly Secure SameSite=None cookie set by the backend.
 * The frontend JavaScript CANNOT read the session cookie.
 */
export function useAuth() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Handle Google OAuth redirect callback on mount
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

  // Check auth status on mount and when session changes
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
    refresh: checkAuth,
  };
}
