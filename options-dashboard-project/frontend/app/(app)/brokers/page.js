"use client";
import { useEffect, useState, useCallback } from "react";
import { C, Centered, SessionExpired } from "@/lib/ui";
import {
  getBrokerProfile,
  getPaperCapital,
  getMarketStatus,
  isAuthError,
} from "@/lib/api";
import { captureSessionFromUrl } from "@/lib/session";
import { getStatus } from "@/lib/api";
import BrokerConnectionPanel from "../paper/BrokerConnectionPanel";

/**
 * Phase 2.1c — Brokers page
 * Extracts broker connection from the /paper monolith.
 * Fetches its own data through the existing APIs.
 * No credentials or tokens are exposed to the frontend.
 */

export default function BrokersPage() {
  const [loggedIn, setLoggedIn] = useState(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [error, setError] = useState(null);

  // Data state
  const [brokerProfile, setBrokerProfile] = useState(null);
  const [brokerProfileError, setBrokerProfileError] = useState(null);
  const [brokerProfileLoading, setBrokerProfileLoading] = useState(false);
  const [capital, setCapital] = useState(null);
  const [marketStatus, setMarketStatus] = useState(null);
  const [checkedAt, setCheckedAt] = useState(null);

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

  const loadBrokerProfile = useCallback(async (refresh = false) => {
    setBrokerProfileLoading(true);
    try {
      const [profileResult, capitalResult, marketResult] = await Promise.all([
        getBrokerProfile(refresh),
        getPaperCapital(),
        getMarketStatus(),
      ]);
      setBrokerProfile(profileResult);
      setCapital(capitalResult);
      setMarketStatus(marketResult);
      setBrokerProfileError(null);
      setCheckedAt(new Date().toISOString());
    } catch (e) {
      if (isAuthError(e)) {
        setSessionExpired(true);
        return;
      }
      setBrokerProfileError(e.message || "Failed to load broker profile");
    } finally {
      setBrokerProfileLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    loadBrokerProfile();
  }, [loggedIn, loadBrokerProfile]);

  if (loggedIn === null) {
    return <Centered>Checking login…</Centered>;
  }
  if (sessionExpired) return <SessionExpired />;
  if (error && !brokerProfile) {
    return <Centered>Something went wrong: {error}</Centered>;
  }

  return (
    <div style={{ maxWidth: 900 }}>
      {/* Page Header */}
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, marginBottom: 4 }}>
          Brokers
        </h1>
        <p style={{ fontSize: 13, color: C.muted, margin: 0 }}>
          Broker accounts, connection, capabilities, and funds
        </p>
      </div>

      {/* Broker Connection Panel */}
      <BrokerConnectionPanel
        profile={brokerProfile}
        capital={capital}
        marketStatus={marketStatus}
        optionChain={null}
        loading={brokerProfileLoading}
        error={brokerProfileError}
        onRefresh={() => loadBrokerProfile(true)}
        checkedAt={checkedAt}
        defaultDetailsOpen={true}
      />
    </div>
  );
}
