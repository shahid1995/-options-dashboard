"use client";
import { useEffect, useState, useRef, useCallback } from "react";
import { getChain } from "@/lib/api";
import { C } from "@/lib/theme";
import { fmtIN, fmtChg } from "@/lib/format";
import { ltpOf, nearestStrike } from "@/lib/options";
import { loadJSON, saveJSON } from "@/lib/storage";
import { useMarketSession, usePoll } from "@/lib/hooks";
import Centered from "@/components/Centered";
import { loginGateFor } from "@/components/LoginGate";
import TopNav from "@/components/TopNav";
import ExpirySelect from "@/components/ExpirySelect";

const WATCHLIST_KEY = "options_dashboard_watchlist_v1";

export default function Dashboard() {
  const { loggedIn, expiries, expiry, setExpiry, error, setError } = useMarketSession("NIFTY");
  const [chain, setChain] = useState(null);
  const [watchlist, setWatchlist] = useState([]);

  useEffect(() => {
    const saved = loadJSON(WATCHLIST_KEY);
    if (saved) setWatchlist(saved);
  }, []);

  useEffect(() => {
    saveJSON(WATCHLIST_KEY, watchlist);
  }, [watchlist]);

  const [lastUpdated, setLastUpdated] = useState(null);
  const [centeredExpiry, setCenteredExpiry] = useState(null);
  const scrollRef = useRef(null);

  const spot = chain ? chain.underlying_spot_price : null;
  let atmStrike = null;
  if (chain && spot != null && chain.chain.length) {
    atmStrike = nearestStrike(chain.chain.map((r) => r.strike), spot);
  }

  // Center the view on the ATM strike once per expiry (not on every 5s poll)
  useEffect(() => {
    if (!chain || !scrollRef.current || atmStrike == null) return;
    if (centeredExpiry === expiry) return;
    const el = scrollRef.current.querySelector('[data-atm="true"]');
    if (el) {
      el.scrollIntoView({ block: "center" });
      setCenteredExpiry(expiry);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chain, expiry]);

  const fetchChain = useCallback(
    (isCancelled) => {
      getChain("NIFTY", expiry)
        .then((data) => {
          if (isCancelled()) return;
          setChain(data);
          setLastUpdated(new Date());
          setError(null);
        })
        .catch((e) => {
          if (!isCancelled()) setError(e.message);
        });
    },
    [expiry, setError]
  );

  usePoll(fetchChain, Boolean(loggedIn && expiry));

  const isWatched = (strike, type) =>
    watchlist.some((w) => w.strike === strike && w.type === type && w.expiry === expiry);

  const toggleWatch = (strike, type) => {
    setWatchlist((prev) => {
      const exists = prev.some((w) => w.strike === strike && w.type === type && w.expiry === expiry);
      if (exists) return prev.filter((w) => !(w.strike === strike && w.type === type && w.expiry === expiry));
      return [...prev, { strike, type, expiry, symbol: "NIFTY" }];
    });
  };

  const enrichedWatchlist = watchlist.map((w) => {
    if (!chain || w.expiry !== expiry) return { ...w, ltp: null };
    const row = chain.chain.find((r) => r.strike === w.strike);
    const ltp = row ? ltpOf(row, w.type) : null;
    return { ...w, ltp };
  });

  const gate = loginGateFor(loggedIn);
  if (gate) return gate;
  if (error) return <Centered>Something went wrong: {error}</Centered>;
  if (!chain) return <Centered>Loading chain…</Centered>;

  // Build table rows with a spot-marker row inserted at the right position
  const tableItems = [];
  chain.chain.forEach((row, i) => {
    const prevRow = chain.chain[i - 1];
    if (spot != null && prevRow && prevRow.strike < spot && row.strike > spot) {
      tableItems.push({ kind: "spot", value: spot });
    }
    tableItems.push({ kind: "row", data: row });
  });

  return (
    <div style={{ padding: 20 }}>
      <TopNav active="chain" />
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>NIFTY Option Chain</h1>
        <ExpirySelect expiry={expiry} expiries={expiries} onChange={setExpiry} />
        {spot != null && (
          <span style={{ color: C.muted, fontSize: 13 }}>
            Spot: <span style={{ color: C.gold, fontWeight: 600 }}>{fmtIN(spot, 2)}</span>
          </span>
        )}
        {lastUpdated && (
          <span style={{ color: C.muted, fontSize: 11, marginLeft: "auto" }}>
            <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: 3, background: C.green, marginRight: 6 }} />
            Updated {lastUpdated.toLocaleTimeString("en-IN")}
          </span>
        )}
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <div ref={scrollRef} style={{ flex: 3, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "auto", maxHeight: 560 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5, whiteSpace: "nowrap" }}>
            <thead style={{ position: "sticky", top: 0, background: C.surface, zIndex: 1 }}>
              <tr style={{ color: C.muted, fontSize: 10.5 }}>
                <th colSpan={9} style={{ padding: "8px 6px", textAlign: "center", color: C.green, borderBottom: `1px solid ${C.border}` }}>CALLS</th>
                <th style={{ borderBottom: `1px solid ${C.border}` }}></th>
                <th colSpan={9} style={{ padding: "8px 6px", textAlign: "center", color: C.red, borderBottom: `1px solid ${C.border}` }}>PUTS</th>
              </tr>
              <tr style={{ color: C.muted, fontSize: 10.5 }}>
                <th style={{ padding: 6 }}></th>
                <th style={{ padding: 6 }}>OI</th>
                <th style={{ padding: 6 }}>Chg OI</th>
                <th style={{ padding: 6 }}>Volume</th>
                <th style={{ padding: 6 }}>IV</th>
                <th style={{ padding: 6 }}>Vega</th>
                <th style={{ padding: 6 }}>Theta</th>
                <th style={{ padding: 6 }}>Gamma</th>
                <th style={{ padding: 6 }}>Delta</th>
                <th style={{ padding: 6, fontWeight: 700 }}>LTP</th>
                <th style={{ padding: 6, textAlign: "center", color: C.gold }}>Strike</th>
                <th style={{ padding: 6, fontWeight: 700 }}>LTP</th>
                <th style={{ padding: 6 }}>Delta</th>
                <th style={{ padding: 6 }}>Gamma</th>
                <th style={{ padding: 6 }}>Theta</th>
                <th style={{ padding: 6 }}>Vega</th>
                <th style={{ padding: 6 }}>IV</th>
                <th style={{ padding: 6 }}>Volume</th>
                <th style={{ padding: 6 }}>Chg OI</th>
                <th style={{ padding: 6 }}>OI</th>
                <th style={{ padding: 6 }}></th>
              </tr>
            </thead>
            <tbody>
              {tableItems.map((item, idx) =>
                item.kind === "spot" ? (
                  <tr key={`spot-${idx}`}>
                    <td colSpan={20} style={{ padding: 0 }}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: 10,
                          padding: "6px 0",
                          background: "rgba(201,161,90,0.08)",
                          borderTop: `1px dashed ${C.gold}`,
                          borderBottom: `1px dashed ${C.gold}`,
                        }}
                      >
                        <span style={{ fontSize: 10.5, color: C.gold, letterSpacing: 1, fontWeight: 700 }}>SPOT</span>
                        <span style={{ fontSize: 13, color: C.gold, fontWeight: 700 }}>{fmtIN(item.value, 2)}</span>
                      </div>
                    </td>
                  </tr>
                ) : (
                  <Row
                    key={item.data.strike}
                    row={item.data}
                    isATM={item.data.strike === atmStrike}
                    isWatchedCall={isWatched(item.data.strike, "call")}
                    isWatchedPut={isWatched(item.data.strike, "put")}
                    onToggleCall={() => toggleWatch(item.data.strike, "call")}
                    onTogglePut={() => toggleWatch(item.data.strike, "put")}
                  />
                )
              )}
            </tbody>
          </table>
        </div>

        <div style={{ flex: 1, minWidth: 220, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10 }}>
          <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.border}`, fontSize: 12, color: C.muted, letterSpacing: 0.5 }}>
            WATCHLIST
          </div>
          {enrichedWatchlist.length === 0 ? (
            <div style={{ padding: 16, fontSize: 12, color: C.muted }}>
              Tap the star next to any strike to pin it here.
            </div>
          ) : (
            <div style={{ padding: 8 }}>
              {enrichedWatchlist.map((w) => (
                <div
                  key={`${w.strike}-${w.type}-${w.expiry}`}
                  style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 8px", fontSize: 12.5, borderBottom: `1px solid ${C.border}` }}
                >
                  <div>
                    <div>{w.symbol} {w.strike} {w.type === "call" ? "CE" : "PE"}</div>
                    <div style={{ fontSize: 10.5, color: C.muted }}>{w.expiry}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ color: w.type === "call" ? C.green : C.red }}>{w.ltp != null ? w.ltp : "—"}</span>
                    <button onClick={() => toggleWatch(w.strike, w.type)} style={{ background: "none", border: "none", color: C.muted, cursor: "pointer", fontSize: 14 }}>
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

function Row({ row, isATM, isWatchedCall, isWatchedPut, onToggleCall, onTogglePut }) {
  const c = row.call;
  const p = row.put;
  return (
    <tr
      data-atm={isATM ? "true" : undefined}
      style={{
        borderTop: `1px solid ${C.border}`,
        background: isATM ? "rgba(201,161,90,0.06)" : "transparent",
      }}
    >
      <td style={{ padding: 6, textAlign: "center" }}>
        <StarButton active={isWatchedCall} onClick={onToggleCall} />
      </td>
      <td style={{ padding: 6 }}>{fmtIN(c.oi)}</td>
      <td style={{ padding: 6, color: c.chg_oi > 0 ? C.green : c.chg_oi < 0 ? C.red : C.muted }}>{fmtChg(c.chg_oi)}</td>
      <td style={{ padding: 6 }}>{fmtIN(c.volume)}</td>
      <td style={{ padding: 6 }}>{c.iv ?? "-"}</td>
      <td style={{ padding: 6 }}>{c.vega ?? "-"}</td>
      <td style={{ padding: 6 }}>{c.theta ?? "-"}</td>
      <td style={{ padding: 6 }}>{c.gamma ?? "-"}</td>
      <td style={{ padding: 6 }}>{c.delta ?? "-"}</td>
      <td style={{ padding: 6, color: C.green, fontWeight: 600 }}>{c.ltp ?? "-"}</td>
      <td style={{ padding: 6, textAlign: "center", fontWeight: 700 }}>{fmtIN(row.strike)}</td>
      <td style={{ padding: 6, color: C.red, fontWeight: 600 }}>{p.ltp ?? "-"}</td>
      <td style={{ padding: 6 }}>{p.delta ?? "-"}</td>
      <td style={{ padding: 6 }}>{p.gamma ?? "-"}</td>
      <td style={{ padding: 6 }}>{p.theta ?? "-"}</td>
      <td style={{ padding: 6 }}>{p.vega ?? "-"}</td>
      <td style={{ padding: 6 }}>{p.iv ?? "-"}</td>
      <td style={{ padding: 6 }}>{fmtIN(p.volume)}</td>
      <td style={{ padding: 6, color: p.chg_oi > 0 ? C.green : p.chg_oi < 0 ? C.red : C.muted }}>{fmtChg(p.chg_oi)}</td>
      <td style={{ padding: 6 }}>{fmtIN(p.oi)}</td>
      <td style={{ padding: 6, textAlign: "center" }}>
        <StarButton active={isWatchedPut} onClick={onTogglePut} />
      </td>
    </tr>
  );
}

function StarButton({ active, onClick }) {
  return (
    <button onClick={onClick} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 14, color: active ? C.gold : C.muted }}>
      {active ? "★" : "☆"}
    </button>
  );
}
