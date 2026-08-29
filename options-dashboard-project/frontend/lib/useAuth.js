"use client";
import { useState, useEffect, useCallback } from "react";
import {
  getSessionId,
  setSessionId,
  clearSessionId,
  captureSessionFromUrl,
} from "./session";
import { getStatus, getMe, logoutUser, loginEmail, registerEmail, loginGoogle } from "./api";

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

  const loginWithGoogle = useCallback(async (credential) => {
    setError(null);
    try {
      const result = await loginGoogle(credential);
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
