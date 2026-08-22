"use client";
import { useEffect, useState, useCallback } from "react";
import { C, Centered, SessionExpired, useIsMobile } from "@/lib/ui";
import {
  getPaperCapital,
  getPaperAnalytics,
  getPaperPositions,
  getPaperPositionsFiltered,
  isAuthError,
} from "@/lib/api";
import { captureSessionFromUrl } from "@/lib/session";
import { getStatus } from "@/lib/api";
import CapitalPanel from "../paper/CapitalPanel";
import PortfolioAnalyticsPanel from "../paper/PortfolioAnalyticsPanel";

/**
 * Phase 2.1b — Portfolio page
 * Extracts capital + portfolio analytics from the /paper monolith.
 * Fetches its own data through the existing APIs.
 */

export default function PortfolioPage() {
  const [loggedIn, setLoggedIn] = useState(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [error, setError] = useState(null);
  const isMobile = useIsMobile();

  // Data state
  const [capital, setCapital] = useState(null);
  const [capitalError, setCapitalError] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [analyticsError, setAnalyticsError] = useState(null);
  const [positions, setPositions] = useState([]);
  const [positionsLtp, setPositionsLtp] = useState([]);
  const [loading, setLoading] = useState(true);

  // Auth check
  useEffect(() => {
    captureSessionFromUrl();
    getStatus()
      .then((s) => setLoggedIn(s.logged_in))
      .catch((e) => {
        setError(e.message);
        setLoggedIn(false);
      });
  }, []);

  const loadPortfolio = useCallback(async () => {
    setLoading(true);
    try {
      const [analyticsData, capitalData, positionsData] = await Promise.all([
        getPaperAnalytics(),
        getPaperCapital(),
        getPaperPositionsFiltered({ all: true, limit: 500 }),
      ]);
      setAnalytics(analyticsData);
      setCapital(capitalData);
      setPositionsLtp(positionsData);
      setCapitalError(null);
      setAnalyticsError(null);
    } catch (e) {
      if (isAuthError(e)) {
        setSessionExpired(true);
        return;
      }
      setCapitalError(e.message);
      setAnalyticsError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    loadPortfolio();
  }, [loggedIn, loadPortfolio]);

  if (loggedIn === null) {
    return <Centered>Checking login…</Centered>;
  }
  if (sessionExpired) return <SessionExpired />;
  if (error && !capital && !analytics) {
    return <Centered>Something went wrong: {error}</Centered>;
  }

  return (
    <div style={{ maxWidth: 1400 }}>
      {/* Page Header */}
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Portfolio
        </h1>
        <p style={{ fontSize: 13, color: C.muted, margin: 0 }}>
          Capital allocation, risk controls, and performance analytics
        </p>
      </div>

      {/* Capital Panel */}
      <div style={{ marginBottom: 16 }}>
        <CapitalPanel
          capital={capital}
          loading={loading}
          error={capitalError}
        />
      </div>

      {/* Portfolio Analytics Panel */}
      <PortfolioAnalyticsPanel
        analytics={analytics}
        positionsWithLtp={positionsLtp}
        capital={capital}
        loading={loading}
        error={analyticsError}
      />

      {/* Refresh button */}
      <div style={{ marginTop: 16 }}>
        <button
          onClick={loadPortfolio}
          disabled={loading}
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: C.gold,
            background: "rgba(201,161,90,0.08)",
            border: `1px solid ${C.gold}66`,
            borderRadius: 6,
            padding: "5px 12px",
            cursor: loading ? "default" : "pointer",
            opacity: loading ? 0.5 : 1,
          }}
        >
          {loading ? "Refreshing…" : "↻ Refresh Portfolio"}
        </button>
      </div>
    </div>
  );
}
