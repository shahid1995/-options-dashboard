"use client";
import { useEffect, useRef, useState } from "react";
import { getChain, chainWsUrl, chainWsProtocols, isAuthError } from "./api";

const POLL_INTERVAL_MS = 5000;

// Live chain feed: tries the backend websocket first and falls back to HTTP
// polling if it can't connect. Reports auth expiry via `sessionExpired`.
export function useChainFeed(symbol, expiry, enabled) {
  const [chain, setChain] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState(null); // "live" | "polling"
  const [sessionExpired, setSessionExpired] = useState(false);
  const [noBrokerToken, setNoBrokerToken] = useState(false);
  const chainRef = useRef(null);
  // Track whether HTTP endpoint already determined the auth state
  const authStateDetermined = useRef(false);

  useEffect(() => {
    setChain(null);
    chainRef.current = null;
    setError(null);
    if (!enabled || !symbol || !expiry) return;

    let cancelled = false;
    let ws = null;
    let pollTimer = null;
    let gotWsData = false;

    const onData = (data) => {
      if (cancelled) return;
      setChain(data);
      chainRef.current = data;
      setLastUpdated(new Date());
      setError(null);
    };

    const poll = () => {
      getChain(symbol, expiry)
        .then(onData)
        .catch((e) => {
          if (cancelled) return;
          if (isAuthError(e)) {
            setSessionExpired(true);
            authStateDetermined.current = true;
            clearInterval(pollTimer);
          } else if (e?.response?.status === 403) {
            // Phase A fix: 403 = valid StrikeNova session but no broker token
            setNoBrokerToken(true);
            authStateDetermined.current = true;
            clearInterval(pollTimer);
          } else {
            setError(e.message);
          }
        });
    };

    const startPolling = () => {
      if (cancelled || pollTimer) return;
      setMode("polling");
      poll();
      pollTimer = setInterval(poll, POLL_INTERVAL_MS);
    };

    try {
      ws = new WebSocket(chainWsUrl(symbol, expiry), chainWsProtocols());
      ws.onmessage = (event) => {
        gotWsData = true;
        setMode("live");
        try {
          onData(JSON.parse(event.data));
        } catch (e) {}
      };
      ws.onclose = (event) => {
        if (cancelled) return;
        if (event.code === 4401) {
          // 4401 means no broker token — could be expired session OR
          // platform-only session (Google/email without broker).
          // Do NOT immediately set sessionExpired; let the HTTP fallback
          // determine the correct state (401=expired, 403=no broker).
          startPolling();
        } else {
          startPolling();
        }
      };
      ws.onerror = () => {
        if (!cancelled && !gotWsData) startPolling();
      };
    } catch (e) {
      startPolling();
    }

    return () => {
      cancelled = true;
      if (ws) ws.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [symbol, expiry, enabled]);

  return { chain, lastUpdated, error, mode, sessionExpired, noBrokerToken };
}
