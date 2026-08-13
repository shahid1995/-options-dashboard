"use client";
import { useEffect, useState } from "react";
import { getStatus, getExpiries } from "@/lib/api";

export const CHAIN_POLL_MS = 5000;

// Checks login status, then loads the expiry list for a symbol and selects
// the nearest expiry. Shared by every page that shows chain data.
export function useMarketSession(symbol) {
  const [loggedIn, setLoggedIn] = useState(null);
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getStatus()
      .then((s) => setLoggedIn(s.logged_in))
      .catch(() => setLoggedIn(false));
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    getExpiries(symbol)
      .then((d) => {
        setExpiries(d.expiries);
        if (d.expiries.length) setExpiry(d.expiries[0]);
      })
      .catch((e) => setError(e.message));
  }, [loggedIn, symbol]);

  return { loggedIn, expiries, expiry, setExpiry, error, setError };
}

// Calls `fn` immediately and then on an interval while `enabled` is true.
// `fn` receives an `isCancelled` getter so async work can bail out after
// the effect is cleaned up. `fn` should be stable (wrap it in useCallback).
export function usePoll(fn, enabled, intervalMs = CHAIN_POLL_MS) {
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const tick = () => fn(() => cancelled);
    tick();
    const interval = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [fn, enabled, intervalMs]);
}
