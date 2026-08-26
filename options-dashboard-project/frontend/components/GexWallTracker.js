"use client";
/**
 * Gamma Wall Tracker — Phase 8D
 *
 * Displays the strongest call and put gamma walls from /gex/walls data.
 * Shows strike, GEX concentration, distance from spot.
 *
 * No directional interpretation. Structural positioning context only.
 */
import { useMemo } from "react";
import { C, fmtIN } from "@/lib/ui";
import { AppPanel, SectionTitle } from "@/components/app/styles";

function fmtGex(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(1)} L`;
  return `${sign}${fmtIN(v)}`;
}

function WallCard({ wall, type, spot }) {
  if (!wall) return null;
  const color = type === "call" ? C.green : C.red;
  const label = type === "call" ? "CALL GAMMA WALL" : "PUT GAMMA WALL";
  const distancePct = wall.distancePct != null ? (wall.distancePct * 100).toFixed(2) : null;

  return (
    <div
      style={{
        background: C.surface2,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: "10px 14px",
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 700, color, letterSpacing: 0.5, marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 800, color: C.text, marginBottom: 4 }}>
        {fmtIN(wall.strike)}
      </div>
      <div style={{ fontSize: 12, color: C.faint }}>
        GEX: {fmtGex(wall.gex)}
      </div>
      {distancePct != null && (
        <div style={{ fontSize: 11, color: C.faint, marginTop: 2 }}>
          {distancePct}% from spot
        </div>
      )}
      {wall.rank && (
        <div style={{ fontSize: 10, color: C.faint, marginTop: 2 }}>
          Rank #{wall.rank}
        </div>
      )}
    </div>
  );
}

export default function GexWallTracker({ data, isMobile = false }) {
  const latest = useMemo(() => {
    if (!data?.walls?.length) return null;
    return data.walls[data.walls.length - 1];
  }, [data]);

  if (!latest) {
    return (
      <div style={AppPanel}>
        <div style={SectionTitle}>GAMMA WALLS</div>
        <div style={{ padding: 24, textAlign: "center", color: C.muted, fontSize: 12 }}>
          No wall data available.
        </div>
      </div>
    );
  }

  const spot = latest.spot;

  return (
    <div style={AppPanel}>
      <div style={SectionTitle}>GAMMA WALLS</div>

      {spot && (
        <div style={{ fontSize: 11, color: C.faint, marginBottom: 12 }}>
          Spot: {fmtIN(spot, 2)}
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
          gap: 10,
          marginBottom: 16,
        }}
      >
        <WallCard wall={latest.strongestPositive} type="call" spot={spot} />
        <WallCard wall={latest.strongestNegative} type="put" spot={spot} />
      </div>

      {/* Additional walls list */}
      {(latest.positiveWalls?.length > 1 || latest.negativeWalls?.length > 1) && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, letterSpacing: 0.5, marginBottom: 6 }}>
            ALL WALLS
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {latest.positiveWalls?.map((w, i) => (
              <div
                key={`pos-${i}`}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "4px 8px",
                  borderRadius: 4,
                  background: `${C.green}08`,
                  fontSize: 11,
                }}
              >
                <span style={{ color: C.green }}>CALL {fmtIN(w.strike)}</span>
                <span style={{ color: C.faint }}>{fmtGex(w.gex)}</span>
              </div>
            ))}
            {latest.negativeWalls?.map((w, i) => (
              <div
                key={`neg-${i}`}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "4px 8px",
                  borderRadius: 4,
                  background: `${C.red}08`,
                  fontSize: 11,
                }}
              >
                <span style={{ color: C.red }}>PUT {fmtIN(w.strike)}</span>
                <span style={{ color: C.faint }}>{fmtGex(w.gex)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ fontSize: 10, color: C.faint, marginTop: 12, textAlign: "center" }}>
        Gamma walls = strikes with highest |GEX| concentration · Structural levels, not targets
      </div>
    </div>
  );
}
