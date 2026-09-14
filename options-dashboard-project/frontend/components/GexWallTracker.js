"use client";
/**
 * Gamma Wall Tracker — Phase E (Market Intelligence)
 *
 * Displays the strongest call and put gamma walls from /gex/walls data.
 * Shows strike, GEX concentration, distance from spot.
 *
 * Uses Phase D primitives: ChartContainer, Metric, Badge, EmptyState.
 *
 * No directional interpretation. Structural positioning context only.
 */
import { useMemo } from "react";
import { C, fmtIN } from "@/lib/ui";
import { ChartContainer, Metric, Badge, EmptyState } from "@/components/app/core";

function fmtGex(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(1)} L`;
  return `${sign}${fmtIN(v)}`;
}

export default function GexWallTracker({ data, isMobile = false }) {
  const latest = useMemo(() => {
    if (!data?.walls?.length) return null;
    return data.walls[data.walls.length - 1];
  }, [data]);

  if (!latest) {
    return (
      <ChartContainer
        title="GAMMA WALLS"
        eyebrow="POSITIONING CONCENTRATION"
        caption="Strikes with highest |GEX| concentration · Structural levels, not targets"
      >
        <EmptyState message="No wall data available." />
      </ChartContainer>
    );
  }

  const spot = latest.spot;
  const hasPositive = latest.strongestPositive != null;
  const hasNegative = latest.strongestNegative != null;

  return (
    <ChartContainer
      title="GAMMA WALLS"
      eyebrow="POSITIONING CONCENTRATION"
      caption="Strikes with highest |GEX| concentration · Structural levels, not targets"
      source={spot ? `Spot ${fmtIN(spot, 2)}` : undefined}
    >
      {/* Primary walls - Call and Put */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
          gap: 12,
          paddingBottom: 12,
        }}
      >
        {hasPositive && (
          <div>
            <div style={{ marginBottom: 6 }}>
              <Badge variant="positive">CALL GAMMA WALL</Badge>
            </div>
            <Metric
              label="Strike"
              value={fmtIN(latest.strongestPositive.strike)}
              size="lg"
              semantic="positive"
              hint="Highest call-side GEX concentration"
            />
            <div style={{ marginTop: 6, fontSize: 12, color: C.faint }}>
              GEX: <span style={{ color: C.green, fontWeight: 600 }}>{fmtGex(latest.strongestPositive.gex)}</span>
            </div>
            {latest.strongestPositive.distancePct != null && (
              <div style={{ fontSize: 11, color: C.faint, marginTop: 2 }}>
                {(latest.strongestPositive.distancePct * 100).toFixed(2)}% from spot
              </div>
            )}
            {latest.strongestPositive.rank && (
              <div style={{ fontSize: 10, color: C.faint, marginTop: 2 }}>
                Rank #{latest.strongestPositive.rank}
              </div>
            )}
          </div>
        )}
        {hasNegative && (
          <div>
            <div style={{ marginBottom: 6 }}>
              <Badge variant="negative">PUT GAMMA WALL</Badge>
            </div>
            <Metric
              label="Strike"
              value={fmtIN(latest.strongestNegative.strike)}
              size="lg"
              semantic="negative"
              hint="Highest put-side GEX concentration"
            />
            <div style={{ marginTop: 6, fontSize: 12, color: C.faint }}>
              GEX: <span style={{ color: C.red, fontWeight: 600 }}>{fmtGex(latest.strongestNegative.gex)}</span>
            </div>
            {latest.strongestNegative.distancePct != null && (
              <div style={{ fontSize: 11, color: C.faint, marginTop: 2 }}>
                {(latest.strongestNegative.distancePct * 100).toFixed(2)}% from spot
              </div>
            )}
            {latest.strongestNegative.rank && (
              <div style={{ fontSize: 10, color: C.faint, marginTop: 2 }}>
                Rank #{latest.strongestNegative.rank}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Additional walls list */}
      {(latest.positiveWalls?.length > 1 || latest.negativeWalls?.length > 1) && (
        <div style={{ marginTop: 8 }}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: C.muted,
              letterSpacing: 0.5,
              marginBottom: 8,
            }}
          >
            ALL WALLS
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {latest.positiveWalls?.slice(0, 5).map((w, i) => (
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
                <span style={{ color: C.green, fontWeight: 600 }}>CALL {fmtIN(w.strike)}</span>
                <span style={{ color: C.faint }}>{fmtGex(w.gex)}</span>
              </div>
            ))}
            {latest.negativeWalls?.slice(0, 5).map((w, i) => (
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
                <span style={{ color: C.red, fontWeight: 600 }}>PUT {fmtIN(w.strike)}</span>
                <span style={{ color: C.faint }}>{fmtGex(w.gex)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </ChartContainer>
  );
}
