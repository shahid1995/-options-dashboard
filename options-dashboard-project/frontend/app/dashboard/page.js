"use client";
import { useEffect, useState } from "react";
import { getStatus, getExpiries, getChain } from "@/lib/api";

const C = {
  surface: "#12161F",
  border: "#242B3A",
  muted: "#8892A6",
  gold: "#C9A15A",
  green: "#4CAF7D",
  red: "#E15252",
};

const WATCHLIST_KEY = "options_dashboard_watchlist_v1";

export default function Dashboard() {
  const [loggedIn, setLoggedIn] = useState(null);
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState(null);
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);
  const [watchlist, setWatchlist] = useState([]);

  // Load saved watchlist from the browser once, on first render
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(WATCHLIST_KEY);
      if (saved) setWatchlist(JSON.parse(saved));
    } catch (e) {
      // ignore malformed/missing storage
    }
  }, []);

  // Save the watchlist to the browser any time it changes
  useEffect(() => {
    try {
      window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watchlist));
    } catch (e) {
      // storage might be unavailable (private browsing etc.) - fail silently
    }
  }, [watchlist]);

  useEffect(() => {
    getStatus()
      .then((s) => setLoggedIn(s.logged_in))
      .catch(() => setLoggedIn(false));
  }, []);

  useEffect(() => {
    if (loggedIn) {
      getExpiries("NIFTY")
        .then((d) => {
          setExpiries(d.expiries);
          if (d.expiries.length) setExpiry(d.expiries[0]);
        })
        .catch((e) => setError(e.message));
    }
  }, [loggedIn]);

  useEffect(() => {
    if (loggedIn && expiry) {
      getChain("NIFTY", expiry)
        .then(setChain)
        .catch((e) => setError(e.message));
    }
  }, [loggedIn, expiry]);

  const isWatched = (strike, type) =>
    watchlist.some((w) => w.strike === strike && w.type === type && w.expiry === expiry);

  const toggleWatch = (strike, type) => {
    setWatchlist((prev) => {
      const exists = prev.some((w) => w.strike === strike && w.type === type && w.expiry === expiry);
      if (exists) {
        return prev.filter((w) => !(w.strike === strike && w.type === type && w.expiry === expiry));
      }
      return [...prev, { strike, type, expiry, symbol: "NIFTY" }];
    });
  };

  // For each watchlist item, try to find its current live price from the
  // chain we already loaded (only works if it matches the currently
  // selected expiry - otherwise we just show the strike/type saved).
  const enrichedWatchlist = watchlist.map((w) => {
    if (!chain || w.expiry !== expiry) return { ...w, ltp: null };
    const row = chain.chain.find((r) => r.strike === w.strike);
    const ltp = row ? (w.type === "call" ? row.call.ltp : row.put.ltp) : null;
    return { ...w, ltp };
  });

  if (loggedIn === null) return <Centered>Checking login…</Centered>;
  if (loggedIn === false)
    return (
      <Centered>
        Not logged in.{" "}
        <a href="/" style={{ color: C.gold }}>
          Go back and log in
        </a>
        .
      </Centered>
    );
  if (error) return <Centered>Something went wrong: {error}</Centered>;
  if (!chain) return <Centered>Loading chain…</Centered>;

  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>NIFTY Option Chain</h1>
        <select
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
          style={{ background: C.surface, color: "#E7E9EE", border: `1px solid ${C.border}`, borderRadius: 6, padding: "6px 10px" }}
        >
          {expiries.map((exp) => (
            <option key={exp} value={exp}>
              {exp}
            </option>
          ))}
        </select>
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        {/* Option chain table */}
        <div style={{ flex: 3, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ color: C.muted, fontSize: 11 }}>
                <th style={{ padding: 8 }}></th>
                <th style={{ padding: 8 }}>Delta</th>
                <th style={{ padding: 8 }}>IV</th>
                <th style={{ padding: 8 }}>OI</th>
                <th style={{ padding: 8 }}>Call LTP</th>
                <th style={{ padding: 8, color: C.gold }}>Strike</th>
                <th style={{ padding: 8 }}>Put LTP</th>
                <th style={{ padding: 8 }}>OI</th>
                <th style={{ padding: 8 }}>IV</th>
                <th style={{ padding: 8 }}>Delta</th>
                <th style={{ padding: 8 }}></th>
              </tr>
            </thead>
            <tbody>
              {chain.chain.map((row) => (
                <tr key={row.strike} style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: 8, textAlign: "center" }}>
                    <StarButton active={isWatched(row.strike, "call")} onClick={() => toggleWatch(row.strike, "call")} />
                  </td>
                  <td style={{ padding: 8 }}>{row.call.delta ?? "-"}</td>
                  <td style={{ padding: 8 }}>{row.call.iv ?? "-"}</td>
                  <td style={{ padding: 8 }}>{row.call.oi ?? "-"}</td>
                  <td style={{ padding: 8, color: C.green }}>{row.call.ltp ?? "-"}</td>
                  <td style={{ padding: 8, textAlign: "center", fontWeight: 600 }}>{row.strike}</td>
                  <td style={{ padding: 8, color: C.red }}>{row.put.ltp ?? "-"}</td>
                  <td style={{ padding: 8 }}>{row.put.oi ?? "-"}</td>
                  <td style={{ padding: 8 }}>{row.put.iv ?? "-"}</td>
                  <td style={{ padding: 8 }}>{row.put.delta ?? "-"}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>
                    <StarButton active={isWatched(row.strike, "put")} onClick={() => toggleWatch(row.strike, "put")} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Watchlist panel */}
        <div style={{ flex: 1, minWidth: 220, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10 }}>
          <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.border}`, fontSize: 12, color: C.muted, letterSpacing: 0.5 }}>
            WATCHLIST
          </div>
          {enrichedWatchlist.length === 0 ? (
            <div style={{ padding: 16, fontSize: 12, color: C.muted }}>
              Tap the star next to any strike to pin it here. It's saved in this browser, so it'll still be here next time you visit.
            </div>
          ) : (
            <div style={{ padding: 8 }}>
              {enrichedWatchlist.map((w) => (
                <div
                  key={`${w.strike}-${w.type}-${w.expiry}`}
                  style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 8px", fontSize: 12.5, borderBottom: `1px solid ${C.border}` }}
                >
                  <div>
                    <div>
                      {w.symbol} {w.strike} {w.type === "call" ? "CE" : "PE"}
                    </div>
                    <div style={{ fontSize: 10.5, color: C.muted }}>{w.expiry}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ color: w.type === "call" ? C.green : C.red }}>
                      {w.ltp != null ? w.ltp : "—"}
                    </span>
                    <button
                      onClick={() => toggleWatch(w.strike, w.type)}
                      style={{ background: "none", border: "none", color: C.muted, cursor: "pointer", fontSize: 14 }}
                      title="Remove"
                    >
                      ×
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StarButton({ active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{ background: "none", border: "none", cursor: "pointer", fontSize: 14, color: active ? C.gold : C.muted }}
      title={active ? "Remove from watchlist" : "Add to watchlist"}
    >
      {active ? "★" : "☆"}
    </button>
  );
}

function Centered({ children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh" }}>
      {children}
    </div>
  );
}
