"use client";
/**
 * GEX Intelligence Dashboard — Phase E (Market Intelligence)
 *
 * Dedicated page for historical GEX analytics, regime tracking,
 * gamma walls, gamma flip, and data quality.
 *
 * Establishes Market Intelligence hierarchy:
 *   Level 1 — Market State (regime, flip, walls, timestamp)
 *   Level 2 — Market Structure (GEX profile, wall concentration)
 *   Level 3 — Analytical Context (historical GEX, regime transitions)
 *   Level 4 — Interpretation (with caveats)
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
import { Metric, Badge, EmptyState, ErrorState, SegmentedControl } from "@/components/app/core";

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
  const [lastFetchTime, setLastFetchTime] = useState(null);

  // Loading/error states
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState({});

  // Data freshness indicator
  const dataFreshness = useMemo(() => {
    if (!lastFetchTime) return { label: "NO DATA", color: C.faint };
    const ageSec = (Date.now() - lastFetchTime) / 1000;
    if (ageSec < 30) return { label: "LIVE", color: C.green };
    if (ageSec < 120) return { label: `UPDATED ${Math.floor(ageSec)}s AGO`, color: C.gold };
    return { label: `STALE (${Math.floor(ageSec)}s)`, color: C.red };
  }, [lastFetchTime]);

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
      setLastFetchTime(Date.now());
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

  // Compute latest values for Market State panel
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
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 4,
              background: dataFreshness.color === C.green ? "rgba(34,197,94,0.15)" :
                          dataFreshness.color === C.gold ? "rgba(201,161,90,0.15)" :
                          dataFreshness.color === C.red ? "rgba(239,68,68,0.15)" : "transparent",
              color: dataFreshness.color,
              letterSpacing: 0.5,
            }}
          >
            {dataFreshness.label}
          </div>
          <div style={{ fontSize: 11, color: C.faint }}>
            Market-structure analytics · Not trading signals
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ marginBottom: 16 }}>
        <SegmentedControl
          options={tabs}
          value={activeTab}
          onChange={setActiveTab}
          aria-label="GEX Intelligence sections"
        />
      </div>

      {/* Content */}
      {loading ? (
        <EmptyState message="Loading GEX data..." />
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
              lastFetchTime={lastFetchTime}
              latestTimestamp={latestTimestamp}
              latestRegime={latestRegime}
              latestFlip={latestFlip}
              latestWalls={latestWalls}
              regimeColor={regimeColor}
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

function OverviewTab({
  history,
  regime,
  flip,
  walls,
  quality,
  errors,
  isMobile,
  lastFetchTime,
  latestTimestamp,
  latestRegime,
  latestFlip,
  latestWalls,
  regimeColor,
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Level 1 — Market State */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: C.faint, letterSpacing: 0.5, marginBottom: 8 }}>
          MARKET STATE
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr 1fr 1fr",
            gap: 8,
          }}
        >
          <Metric
            label="Gamma Regime"
            value={latestRegime ? latestRegime.regime.replace(/_/g, " ") : "—"}
            size="md"
            semantic={latestRegime?.regime === "POSITIVE_GAMMA" ? "positive" : latestRegime?.regime === "NEGATIVE_GAMMA" ? "negative" : "neutral"}
            hint="Current modeled gamma regime"
          />
          <Metric
            label="Gamma Flip"
            value={latestFlip?.flipStrike ? fmtIN(latestFlip.flipStrike) : "—"}
            size="md"
            semantic="strategy"
            hint="Modeled regime transition level"
          />
          <Metric
            label="Call Wall"
            value={latestWalls?.strongestPositive ? fmtIN(latestWalls.strongestPositive.strike) : "—"}
            size="md"
            semantic="positive"
            hint="Highest call-side GEX concentration"
          />
          <Metric
            label="Put Wall"
            value={latestWalls?.strongestNegative ? fmtIN(latestWalls.strongestNegative.strike) : "—"}
            size="md"
            semantic="negative"
            hint="Highest put-side GEX concentration"
          />
        </div>
      </div>

      {/* Level 2 — Market Structure */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
          gap: 12,
        }}
      >
        {/* Net GEX Summary */}
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.faint, letterSpacing: 0.5, marginBottom: 8 }}>
            NET GEX
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 8,
            }}
          >
            <Metric
              label="Net GEX"
              value={latestTimestamp ? fmtGex(latestTimestamp.netGex) : "—"}
              size="lg"
              semantic={latestTimestamp?.netGex >= 0 ? "positive" : "negative"}
              hint="Aggregate dealer gamma exposure"
            />
            <Metric
              label="Spot"
              value={latestTimestamp ? fmtIN(latestTimestamp.spot, 2) : "—"}
              size="lg"
              semantic="strategy"
              hint="Current underlying price"
            />
            <Metric
              label="Instruments"
              value={latestTimestamp ? fmtIN(latestTimestamp.instrumentCount) : "—"}
              size="sm"
              semantic="neutral"
              hint="Number of instruments"
            />
            <Metric
              label="Strikes"
              value={latestTimestamp ? fmtIN(latestTimestamp.strikeCount) : "—"}
              size="sm"
              semantic="neutral"
              hint="Number of strikes"
            />
          </div>
        </div>

        {/* Data Quality Summary */}
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.faint, letterSpacing: 0.5, marginBottom: 8 }}>
            DATA QUALITY
          </div>
          <GexDataQualityPanel quality={quality} compact />
          {lastFetchTime && (
            <div style={{ fontSize: 10, color: C.faint, marginTop: 8 }}>
              Last updated: {new Date(lastFetchTime).toLocaleTimeString()}
            </div>
          )}
        </div>
      </div>

      {/* Level 3 — Analytical Context */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: C.faint, letterSpacing: 0.5, marginBottom: 8 }}>
          HISTORICAL CONTEXT
        </div>
        <GexHistoryChart data={history} isMobile={isMobile} />
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
