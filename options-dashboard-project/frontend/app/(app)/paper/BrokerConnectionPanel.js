"use client";
import { useMemo, useState } from "react";
import { C } from "@/lib/ui";
import { capitalDisplay } from "@/lib/capital";
import {
  CONNECTION_STATE,
  DIAGNOSTIC_STATUS,
  brokerCapabilities,
  buildBrokerDiagnostics,
  isBrokerSessionExpired,
  profileAvailable,
} from "@/lib/brokerDiagnostics";

const panel = { background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14, minWidth: 0 };
const sectionTitle = { fontSize: 12, fontWeight: 800, letterSpacing: 0.8, color: C.muted, marginBottom: 8 };

const STATUS_COLORS = {
  [DIAGNOSTIC_STATUS.AVAILABLE]: C.green,
  [DIAGNOSTIC_STATUS.UNAVAILABLE]: C.red,
  [DIAGNOSTIC_STATUS.PARTIAL]: C.gold,
  [DIAGNOSTIC_STATUS.UNKNOWN]: C.faint,
};

const CONNECTION_COLORS = {
  [CONNECTION_STATE.CONNECTED]: C.green,
  [CONNECTION_STATE.PARTIAL]: C.gold,
  [CONNECTION_STATE.DISCONNECTED]: C.red,
};

const CONNECTION_LABELS = {
  [CONNECTION_STATE.CONNECTED]: "UPSTOX CONNECTED",
  [CONNECTION_STATE.PARTIAL]: "UPSTOX PARTIAL",
  [CONNECTION_STATE.DISCONNECTED]: "UPSTOX DISCONNECTED",
};

const fmtVerified = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

function HealthChip({ status, message }) {
  const color = STATUS_COLORS[status] ?? C.faint;
  return (
    <span
      title={message ?? status}
      style={{
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: 0.6,
        color,
        background: "rgba(0,0,0,0.18)",
        border: `1px solid ${color}55`,
        borderRadius: 999,
        padding: "2px 9px",
        whiteSpace: "nowrap",
      }}
    >
      {status}
    </span>
  );
}

function HealthRow({ item }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 10,
        padding: "6px 0",
        borderBottom: `1px solid ${C.border}`,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: C.text }}>{item.name}</div>
        {item.message && (
          <div style={{ fontSize: 9, color: C.faint, marginTop: 1 }}>{item.message}</div>
        )}
      </div>
      <HealthChip status={item.status} message={item.message} />
    </div>
  );
}

function DetailField({ label, value }) {
  if (value == null || value === "") return null;
  return (
    <div style={{ padding: "4px 0", borderBottom: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 10, letterSpacing: 1, color: C.faint }}>{label}</div>
      <div style={{ fontSize: 11.5, fontWeight: 700, color: C.text, marginTop: 1, wordBreak: "break-word" }}>{String(value)}</div>
    </div>
  );
}

export default function BrokerConnectionPanel({ profile, capital, marketStatus, optionChain, loading, error, onRefresh, checkedAt, defaultDetailsOpen = false }) {
  const [detailsOpen, setDetailsOpen] = useState(defaultDetailsOpen);

  const capitalDisplayData = useMemo(() => capitalDisplay(capital), [capital]);
  const diagnostics = useMemo(
    () =>
      buildBrokerDiagnostics({
        profile,
        capital: capitalDisplayData,
        marketStatus,
        optionChain,
        checkedAt,
      }),
    [profile, capitalDisplayData, marketStatus, optionChain, checkedAt]
  );
  const capabilities = useMemo(() => brokerCapabilities(profile?.profile ?? null), [profile]);
  const profileData = profile?.profile ?? null;
  const connected = profileAvailable(profile);
  const sessionExpired = isBrokerSessionExpired(profile);
  const verifiedAt = fmtVerified(profile?.generated_at ?? null);
  const detailRows = [
    ["USER", profileData?.user_name],
    ["EMAIL", profileData?.email],
    ["USER ID", profileData?.user_id],
    ["ACCOUNT TYPE", profileData?.account_type ?? profileData?.user_type],
    ["BROKER", profileData?.broker],
    ["EXCHANGES", profileData?.exchanges?.join(", ")],
    ["PRODUCTS", profileData?.products?.join(", ")],
    ["ORDER TYPES", profileData?.order_types?.join(", ")],
    ["POA", profileData?.poa == null ? null : profileData.poa ? "Yes" : "No"],
    ["DDPI", profileData?.ddpi == null ? null : profileData.ddpi ? "Yes" : "No"],
  ].filter(([, v]) => v != null && v !== "");

  return (
    <div style={panel}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: 0.8, color: C.text }}>🔌 BROKER CONNECTION</div>
          <span
            style={{
              fontSize: 9.5,
              fontWeight: 800,
              letterSpacing: 0.6,
              color: CONNECTION_COLORS[diagnostics.connection] ?? C.faint,
              background: "rgba(0,0,0,0.18)",
              border: `1px solid ${(CONNECTION_COLORS[diagnostics.connection] ?? C.faint)}55`,
              borderRadius: 999,
              padding: "3px 10px",
              whiteSpace: "nowrap",
            }}
          >
            {loading && !profile ? "CHECKING…" : CONNECTION_LABELS[diagnostics.connection] ?? "UNKNOWN"}
          </span>
        </div>
        <button
          onClick={onRefresh}
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
          {loading ? "Refreshing…" : "↻ Refresh Connection"}
        </button>
      </div>

      {error && !profile && (
        <div style={{ fontSize: 11, color: C.gold, marginBottom: 10 }}>⚠️ {error}</div>
      )}

      {sessionExpired ? (
        <div style={{ background: "rgba(225,82,82,0.08)", border: `1px solid ${C.red}55`, borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: C.red }}>BROKER SESSION EXPIRED</div>
          <div style={{ fontSize: 10.5, color: C.muted, marginTop: 2 }}>
            {profile?.message ?? "Your Upstox session is no longer valid. Reconnect your broker to verify the connection."}
          </div>
          <a
            href="/"
            style={{
              display: "inline-block",
              marginTop: 8,
              fontSize: 11,
              fontWeight: 700,
              color: "#0B0E14",
              background: C.gold,
              border: "none",
              borderRadius: 6,
              padding: "6px 12px",
              textDecoration: "none",
            }}
          >
            Reconnect Broker
          </a>
        </div>
      ) : !connected ? (
        <div style={{ background: "rgba(224,163,58,0.07)", border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>
          <div style={{ fontSize: 11.5, fontWeight: 800, color: C.muted }}>BROKER CONNECTION · UNAVAILABLE</div>
          <div style={{ fontSize: 10.5, color: C.muted, marginTop: 2 }}>
            {profile?.message ? `Reason: ${profile.message}` : "Upstox profile temporarily unavailable."}
          </div>
        </div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8, marginBottom: 12 }}>
            <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 8.5, letterSpacing: 1, color: C.faint }}>USER</div>
              <div style={{ fontSize: 12, fontWeight: 800, color: C.text, marginTop: 1 }}>{profileData?.user_name ?? "—"}</div>
            </div>
            <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 8.5, letterSpacing: 1, color: C.faint }}>ACCOUNT</div>
              <div style={{ fontSize: 12, fontWeight: 800, color: C.text, marginTop: 1 }}>
                {profileData?.account_type ?? profileData?.user_type ?? "—"}
              </div>
            </div>
            <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 8.5, letterSpacing: 1, color: C.faint }}>STATUS</div>
              <div style={{ fontSize: 12, fontWeight: 800, color: profileData?.is_active === false ? C.red : C.green, marginTop: 1 }}>
                {profileData?.is_active == null ? "—" : profileData.is_active ? "ACTIVE" : "INACTIVE"}
              </div>
            </div>
            <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 8.5, letterSpacing: 1, color: C.faint }}>LAST VERIFIED</div>
              <div style={{ fontSize: 11, fontWeight: 700, color: C.text, marginTop: 1 }}>
                {verifiedAt ?? "—"}
                {profile?.cached && <span style={{ color: C.gold, marginLeft: 5 }}>· CACHED</span>}
              </div>
            </div>
          </div>

          <div style={sectionTitle}>CONNECTION HEALTH</div>
          <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "2px 10px", marginBottom: 12 }}>
            {diagnostics.items.map((item) => (
              <HealthRow key={item.name} item={item} />
            ))}
          </div>

          {capabilities.length > 0 && (
            <>
              <div style={sectionTitle}>ACCOUNT CAPABILITIES</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                {capabilities.map((cap) => (
                  <span
                    key={cap.key}
                    title={`${cap.detail ?? ""} · ${cap.source}`}
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      letterSpacing: 0.4,
                      color: cap.enabled ? C.green : C.faint,
                      background: C.surface2,
                      border: `1px solid ${cap.enabled ? "rgba(76,175,125,0.4)" : C.border}`,
                      borderRadius: 999,
                      padding: "2px 8px",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {cap.enabled ? "✓" : "—"} {cap.label} · {cap.stateWord}
                  </span>
                ))}
              </div>
            </>
          )}

          <button
            onClick={() => setDetailsOpen((v) => !v)}
            style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.6, color: C.gold, background: "none", border: "none", cursor: "pointer", padding: 0 }}
          >
            {detailsOpen ? "▾ HIDE PROFILE DETAILS" : "▸ SHOW PROFILE DETAILS"}
          </button>
          {detailsOpen && (
            <div style={{ marginTop: 8, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "4px 12px" }}>
              {detailRows.map(([label, value]) => (
                <DetailField key={label} label={label} value={value} />
              ))}
              {detailRows.length === 0 && (
                <div style={{ fontSize: 10.5, color: C.faint, padding: "8px 0" }}>No additional profile details reported by the broker.</div>
              )}
            </div>
          )}
        </>
      )}

      <div style={{ fontSize: 9, color: C.faint, letterSpacing: 0.4, marginTop: 10 }}>
        READ-ONLY BROKER DIAGNOSTICS · VERIFIED SERVER-SIDE VIA THE AUTHENTICATED UPSTOX SESSION · NEVER CREDENTIALS · PROFILE IS NOT TICK DATA
      </div>
    </div>
  );
}
