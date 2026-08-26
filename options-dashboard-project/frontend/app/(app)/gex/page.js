"use client";
/**
 * GEX Intelligence Dashboard — Phase 8D
 *
 * Dedicated page for historical GEX analytics, regime tracking,
 * gamma walls, gamma flip, and data quality.
 *
 * All GEX methodology follows the Phase 7.1 formula:
 *   raw_gex = gamma × OI × spot² × 0.01
 *   CE = +raw_gex
 *   PE = -raw_gex
 *
 * No directional trading signals. Market-structure intelligence only.
 */
import { useEffect, useState, useMemo } from "react";
import { C, fmtIN, useIsMobile } from "@/lib/ui";
import { AppPanel, SectionTitle } from "@/components/app/styles";
import {
  getGexHistory,
  getGexRegime,
  getGexFlip,
  getGexWalls,
  getGexDataQuality,
  isAuthError,
} from "@/lib/api";
import GexHistoryChart from "@/components/GexHistoryChart";
import GexRegimeTimeline from "@/components/GexRegimeTimeline";
import GexWallTracker from "@/components/GexWallTracker";
import GexFlipPanel from "@/components/GexFlipPanel";
import GexDataQualityPanel from "@/components/GexDataQualityPanel";

export default function GexPage() {
  const isMobile = useIsMobile();
  const [loggedIn, setLoggedIn] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");

  // Data states
  const [history, setHistory] = useState(null);
  const [regime, setRegime] = useState(null);
  const [flip, setFlip] = useState(null);
  const [walls, setWalls] = useState(null);
  const [quality, setQuality] = useState(null);

  // Loading/error states
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState({});

  // Check auth
  useEffect(() => {
    import("@/lib/api").then(({ getStatus }) =>
      getStatus()
        .then((s) => setLoggedIn(s.logged_in))
        .catch(() => setLoggedIn(false))
    );
  }, []);

  // Fetch all GEX data
  useEffect(() => {
    if (!loggedIn) return;
    setLoading(true);
    setErrors({});

    const fetchData = async () => {
      const results = {};
      const fetches = [
        ["history", () => getGexHistory({ limit: 500 })],
        ["regime", () => getGexRegime({ limit: 500 })],
        ["flip", () => getGexFlip({ limit: 200 })],
        ["walls", () => getGexWalls({ limit: 200, top_n: 5 })],
        ["quality", () => getGexDataQuality()],
      ];

      for (const [key, fn] of fetches) {
        try {
          results[key] = await fn();
        } catch (e) {
          if (isAuthError(e)) {
            setLoggedIn(false);
            return;
          }
          setErrors((prev) => ({ ...prev, [key]: e.message }));
        }
      }

      setHistory(results.history || null);
      setRegime(results.regime || null);
      setFlip(results.flip || null);
      setWalls(results.walls || null);
      setQuality(results.quality || null);
      setLoading(false);
    };

    fetchData();
  }, [loggedIn]);

  if (loggedIn === null) {
    return (
      <div style={{ padding: 24, color: C.muted, fontSize: 13 }}>
        Loading...
      </div>
    );
  }

  if (!loggedIn) {
    return (
      <div style={{ padding: 24, color: C.muted, fontSize: 13 }}>
        Please log in to view GEX Intelligence.
      </div>
    );
  }

  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "history", label: "Historical GEX" },
    { key: "regime", label: "Regime" },
    { key: "walls", label: "Gamma Walls" },
    { key: "flip", label: "Gamma Flip" },
    { key: "quality", label: "Data Quality" },
  ];

  return (
    <div style={{ padding: isMobile ? 12 : 20 }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <h1
          style={{
            fontSize: 18,
            fontWeight: 800,
            color: C.text,
            margin: 0,
            letterSpacing: 0.3,
          }}
        >
          GEX INTELLIGENCE
        </h1>
        <div style={{ fontSize: 11, color: C.faint }}>
          Market-structure analytics · Not trading signals
        </div>
      </div>

      {/* Tabs */}
      <div
        style={{
          display: "flex",
          gap: 6,
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              fontSize: 11,
              padding: "5px 12px",
              borderRadius: 5,
              border: `1px solid ${activeTab === tab.key ? C.gold : C.border}`,
              background:
                activeTab === tab.key ? "rgba(201,161,90,0.1)" : "transparent",
              color: activeTab === tab.key ? C.gold : C.muted,
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div
          style={{
            ...AppPanel,
            padding: 40,
            textAlign: "center",
            color: C.muted,
            fontSize: 13,
          }}
        >
          Loading GEX data...
        </div>
      ) : (
        <>
          {activeTab === "overview" && (
            <OverviewTab
              history={history}
              regime={regime}
              flip={flip}
              walls={walls}
              quality={quality}
              errors={errors}
              isMobile={isMobile}
            />
          )}
          {activeTab === "history" && (
            <HistoryTab history={history} error={errors.history} isMobile={isMobile} />
          )}
          {activeTab === "regime" && (
            <RegimeTab regime={regime} error={errors.regime} isMobile={isMobile} />
          )}
          {activeTab === "walls" && (
            <WallsTab walls={walls} error={errors.walls} isMobile={isMobile} />
          )}
          {activeTab === "flip" && (
            <FlipTab flip={flip} error={errors.flip} isMobile={isMobile} />
          )}
          {activeTab === "quality" && (
            <QualityTab quality={quality} error={errors.quality} isMobile={isMobile} />
          )}
        </>
      )}
    </div>
  );
}

/* ── Overview Tab ─────────────────────────────────────────────────── */

function OverviewTab({ history, regime, flip, walls, quality, errors, isMobile }) {
  const latestTimestamp = history?.timestamps?.length
    ? history.timestamps[history.timestamps.length - 1]
    : null;

  const latestRegime = regime?.regimes?.length
    ? regime.regimes[regime.regimes.length - 1]
    : null;

  const latestFlip = flip?.flips?.length
    ? flip.flips[flip.flips.length - 1]
    : null;

  const latestWalls = walls?.walls?.length
    ? walls.walls[walls.walls.length - 1]
    : null;

  const regimeColor = (r) => {
    if (r === "POSITIVE_GAMMA") return C.green;
    if (r === "NEGATIVE_GAMMA") return C.red;
    return C.muted;
  };

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
        gap: 12,
      }}
    >
      {/* Net GEX Card */}
      <div style={AppPanel}>
        <div style={SectionTitle}>NET GEX</div>
        <div style={{ fontSize: 28, fontWeight: 800, color: C.text, marginBottom: 4 }}>
          {latestTimestamp ? fmtGex(latestTimestamp.netGex) : "—"}
        </div>
        <div style={{ fontSize: 11, color: C.faint }}>
          {latestTimestamp
            ? `${fmtIN(latestTimestamp.instrumentCount)} instruments · ${fmtIN(latestTimestamp.strikeCount)} strikes`
            : "No data"}
        </div>
        {latestTimestamp && (
          <div style={{ fontSize: 10, color: C.faint, marginTop: 4 }}>
            Spot: {fmtIN(latestTimestamp.spot, 2)}
          </div>
        )}
      </div>

      {/* Regime Card */}
      <div style={AppPanel}>
        <div style={SectionTitle}>GAMMA REGIME</div>
        <div
          style={{
            fontSize: 18,
            fontWeight: 800,
            color: latestRegime ? regimeColor(latestRegime.regime) : C.muted,
            marginBottom: 4,
          }}
        >
          {latestRegime ? latestRegime.regime.replace(/_/g, " ") : "—"}
        </div>
        {latestRegime?.regimeTransition && (
          <div style={{ fontSize: 11, color: C.faint }}>
            Transition: {latestRegime.regimeTransition}
          </div>
        )}
        {latestRegime && (
          <div style={{ fontSize: 10, color: C.faint, marginTop: 4 }}>
            Net GEX: {fmtGex(latestRegime.netGex)}
          </div>
        )}
      </div>

      {/* Gamma Flip Card */}
      <div style={AppPanel}>
        <div style={SectionTitle}>GAMMA FLIP</div>
        <div style={{ fontSize: 18, fontWeight: 800, color: C.gold, marginBottom: 4 }}>
          {latestFlip?.flipStrike ? fmtIN(latestFlip.flipStrike) : "—"}
        </div>
        {latestFlip && (
          <>
            <div style={{ fontSize: 11, color: C.faint }}>
              Status: {latestFlip.status}
            </div>
            {latestFlip.flipConfidence != null && (
              <div style={{ fontSize: 10, color: C.faint, marginTop: 4 }}>
                Confidence: {(latestFlip.flipConfidence * 100).toFixed(0)}%
              </div>
            )}
          </>
        )}
      </div>

      {/* Walls Summary Card */}
      <div style={AppPanel}>
        <div style={SectionTitle}>GAMMA WALLS</div>
        {latestWalls ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {latestWalls.strongestPositive && (
              <div style={{ fontSize: 12 }}>
                <span style={{ color: C.green, fontWeight: 700 }}>CALL WALL</span>{" "}
                <span style={{ color: C.text }}>{fmtIN(latestWalls.strongestPositive.strike)}</span>
                <span style={{ color: C.faint, fontSize: 10, marginLeft: 6 }}>
                  {fmtGex(latestWalls.strongestPositive.gex)}
                </span>
              </div>
            )}
            {latestWalls.strongestNegative && (
              <div style={{ fontSize: 12 }}>
                <span style={{ color: C.red, fontWeight: 700 }}>PUT WALL</span>{" "}
                <span style={{ color: C.text }}>{fmtIN(latestWalls.strongestNegative.strike)}</span>
                <span style={{ color: C.faint, fontSize: 10, marginLeft: 6 }}>
                  {fmtGex(latestWalls.strongestNegative.gex)}
                </span>
              </div>
            )}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: C.muted }}>No wall data</div>
        )}
      </div>

      {/* Data Quality Card */}
      <div style={{ ...AppPanel, gridColumn: isMobile ? "auto" : "1 / -1" }}>
        <div style={SectionTitle}>DATA QUALITY</div>
        <GexDataQualityPanel quality={quality} compact />
      </div>
    </div>
  );
}

/* ── History Tab ──────────────────────────────────────────────────── */

function HistoryTab({ history, error, isMobile }) {
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!history?.timestamps?.length) {
    return <EmptyState message="No historical GEX data available." />;
  }
  return <GexHistoryChart data={history} isMobile={isMobile} />;
}

/* ── Regime Tab ───────────────────────────────────────────────────── */

function RegimeTab({ regime, error, isMobile }) {
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!regime?.regimes?.length) {
    return <EmptyState message="No regime data available." />;
  }
  return <GexRegimeTimeline data={regime} isMobile={isMobile} />;
}

/* ── Walls Tab ────────────────────────────────────────────────────── */

function WallsTab({ walls, error, isMobile }) {
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!walls?.walls?.length) {
    return <EmptyState message="No wall data available." />;
  }
  return <GexWallTracker data={walls} isMobile={isMobile} />;
}

/* ── Flip Tab ─────────────────────────────────────────────────────── */

function FlipTab({ flip, error, isMobile }) {
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!flip?.flips?.length) {
    return <EmptyState message="No flip data available." />;
  }
  return <GexFlipPanel data={flip} isMobile={isMobile} />;
}

/* ── Quality Tab ──────────────────────────────────────────────────── */

function QualityTab({ quality, error, isMobile }) {
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!quality) {
    return <EmptyState message="No data quality information available." />;
  }
  return <GexDataQualityPanel quality={quality} />;
}

/* ── Shared helpers ───────────────────────────────────────────────── */

function fmtGex(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function EmptyState({ message }) {
  return (
    <div style={{ ...AppPanel, padding: 40, textAlign: "center" }}>
      <div style={{ fontSize: 13, color: C.muted }}>{message}</div>
    </div>
  );
}

function ErrorState({ message }) {
  return (
    <div style={{ ...AppPanel, padding: 40, textAlign: "center" }}>
      <div style={{ fontSize: 13, color: C.red, marginBottom: 8 }}>
        Unable to load GEX data
      </div>
      <div style={{ fontSize: 11, color: C.faint }}>{message}</div>
    </div>
  );
}
