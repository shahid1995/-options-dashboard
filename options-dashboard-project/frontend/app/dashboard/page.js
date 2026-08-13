"use client";
import { useEffect, useState, useRef, useMemo } from "react";
import { getStatus, getExpiries, getChain } from "@/lib/api";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";

const C = {
  surface: "#12161F",
  border: "#242B3A",
  muted: "#8892A6",
  gold: "#C9A15A",
  green: "#4CAF7D",
  red: "#E15252",
};

const WATCHLIST_KEY = "options_dashboard_watchlist_v1";
const PAPER_KEY = "options_dashboard_paper_v1";
const DEFAULT_STARTING_CAPITAL = 500000;

function fmtIN(n, decimals = 0) {
  if (n === null || n === undefined) return "-";
  return n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtChg(n) {
  if (n === null || n === undefined) return "-";
  const sign = n > 0 ? "+" : "";
  return `${sign}${fmtIN(n)}`;
}

export default function Dashboard() {
  const [loggedIn, setLoggedIn] = useState(null);
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState(null);
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);
  const [watchlist, setWatchlist] = useState([]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(WATCHLIST_KEY);
      if (saved) setWatchlist(JSON.parse(saved));
    } catch (e) {}
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watchlist));
    } catch (e) {}
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

  const [lastUpdated, setLastUpdated] = useState(null);
  const [centeredExpiry, setCenteredExpiry] = useState(null);
  const scrollRef = useRef(null);
  const [legs, setLegs] = useState([]);
  const [lotSize, setLotSize] = useState(65);

  // ---- Paper trading state ----
  const [paperCash, setPaperCash] = useState(DEFAULT_STARTING_CAPITAL);
  const [paperStartingCapital, setPaperStartingCapital] = useState(DEFAULT_STARTING_CAPITAL);
  const [paperPositions, setPaperPositions] = useState([]);
  const [paperHistory, setPaperHistory] = useState([]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(PAPER_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        setPaperCash(parsed.cash ?? DEFAULT_STARTING_CAPITAL);
        setPaperStartingCapital(parsed.startingCapital ?? DEFAULT_STARTING_CAPITAL);
        setPaperPositions(parsed.positions ?? []);
        setPaperHistory(parsed.history ?? []);
      }
    } catch (e) {}
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        PAPER_KEY,
        JSON.stringify({
          cash: paperCash,
          startingCapital: paperStartingCapital,
          positions: paperPositions,
          history: paperHistory,
        })
      );
    } catch (e) {}
  }, [paperCash, paperStartingCapital, paperPositions, paperHistory]);

  const spot = chain ? chain.underlying_spot_price : null;
  let atmStrike = null;
  if (chain && spot != null && chain.chain.length) {
    atmStrike = chain.chain.reduce((closest, row) =>
      Math.abs(row.strike - spot) < Math.abs(closest.strike - spot) ? row : closest
    ).strike;
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

  useEffect(() => {
    if (!loggedIn || !expiry) return;

    let cancelled = false;

    const fetchChain = () => {
      getChain("NIFTY", expiry)
        .then((data) => {
          if (cancelled) return;
          setChain(data);
          setLastUpdated(new Date());
          setError(null);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
    };

    fetchChain(); // fetch immediately
    const interval = setInterval(fetchChain, 5000); // then every 5 seconds

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [loggedIn, expiry]);

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
    const ltp = row ? (w.type === "call" ? row.call.ltp : row.put.ltp) : null;
    return { ...w, ltp };
  });

  const payoffSeries = useMemo(() => {
    if (!spot || legs.length === 0) return [];
    const range = spot * 0.2; // ±20% of spot
    const min = spot - range;
    const max = spot + range;
    const step = range / 40;
    const points = [];
    for (let price = min; price <= max; price += step) {
      let pnl = 0;
      legs.forEach((leg) => {
        const intrinsic =
          leg.type === "call" ? Math.max(0, price - leg.strike) : Math.max(0, leg.strike - price);
        const dir = leg.action === "buy" ? 1 : -1;
        pnl += dir * (intrinsic - leg.premium) * lotSize;
      });
      points.push({ price: Math.round(price), pnl: Math.round(pnl) });
    }
    return points;
  }, [spot, legs, lotSize]);

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

  // ---- Strategy builder ----
  const addLeg = (type, strike, premium) => {
    if (premium == null) return;
    setLegs((prev) => [
      ...prev,
      { id: `${type}-${strike}-${Date.now()}`, type, strike, action: "buy", premium },
    ]);
  };

  const toggleLegAction = (id) => {
    setLegs((prev) =>
      prev.map((l) => (l.id === id ? { ...l, action: l.action === "buy" ? "sell" : "buy" } : l))
    );
  };

  const removeLeg = (id) => setLegs((prev) => prev.filter((l) => l.id !== id));

  const maxProfit = payoffSeries.length ? Math.max(...payoffSeries.map((p) => p.pnl)) : 0;
  const maxLoss = payoffSeries.length ? Math.min(...payoffSeries.map((p) => p.pnl)) : 0;
  const openEndedUp =
    payoffSeries.length > 2 &&
    payoffSeries[payoffSeries.length - 1].pnl - payoffSeries[payoffSeries.length - 2].pnl > 1;
  const openEndedDown =
    payoffSeries.length > 2 && payoffSeries[1].pnl - payoffSeries[0].pnl < -1;

  // ---- Paper trading logic ----
  // dir: +1 for buy (long), -1 for sell (short)
  const dirOf = (action) => (action === "buy" ? 1 : -1);

  const getCurrentLtp = (position) => {
    if (!chain || position.expiry !== expiry) return null;
    const row = chain.chain.find((r) => r.strike === position.strike);
    if (!row) return null;
    return position.type === "call" ? row.call.ltp : row.put.ltp;
  };

  const executeLegsAsPaperTrade = () => {
    if (legs.length === 0) return;
    let cashDelta = 0;
    const newPositions = legs.map((leg) => {
      const dir = dirOf(leg.action);
      cashDelta -= dir * leg.premium * lotSize * 1; // 1 lot per leg
      return {
        id: `pos-${leg.type}-${leg.strike}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        symbol: "NIFTY",
        type: leg.type,
        strike: leg.strike,
        expiry,
        action: leg.action,
        qty: 1,
        lotSize,
        entryPremium: leg.premium,
        entryTime: new Date().toISOString(),
      };
    });
    setPaperCash((c) => c + cashDelta);
    setPaperPositions((prev) => [...prev, ...newPositions]);
    setLegs([]);
  };

  const closePosition = (id) => {
    const position = paperPositions.find((p) => p.id === id);
    if (!position) return;
    const exitPrice = getCurrentLtp(position);
    if (exitPrice == null) {
      alert("Can't close this position right now — switch to its expiry in the dropdown above so we have a live price for it, then try again.");
      return;
    }
    const dir = dirOf(position.action);
    const cashDelta = dir * exitPrice * position.lotSize * position.qty;
    const realizedPnl = dir * (exitPrice - position.entryPremium) * position.lotSize * position.qty;

    setPaperCash((c) => c + cashDelta);
    setPaperPositions((prev) => prev.filter((p) => p.id !== id));
    setPaperHistory((prev) => [
      {
        ...position,
        exitPrice,
        exitTime: new Date().toISOString(),
        realizedPnl,
      },
      ...prev,
    ]);
  };

  const resetPaperPortfolio = () => {
    if (!window.confirm("Reset your paper portfolio? This clears all open positions and trade history and can't be undone.")) return;
    setPaperCash(paperStartingCapital);
    setPaperPositions([]);
    setPaperHistory([]);
  };

  const positionsWithLtp = paperPositions.map((p) => {
    const ltp = getCurrentLtp(p);
    const dir = dirOf(p.action);
    const unrealizedPnl = ltp != null ? dir * (ltp - p.entryPremium) * p.lotSize * p.qty : null;
    return { ...p, currentLtp: ltp, unrealizedPnl };
  });

  const totalUnrealized = positionsWithLtp.reduce((sum, p) => sum + (p.unrealizedPnl ?? 0), 0);
  const equity = paperCash + positionsWithLtp.reduce((sum, p) => {
    if (p.currentLtp == null) return sum;
    return sum + dirOf(p.action) * p.currentLtp * p.lotSize * p.qty;
  }, 0);
  const totalPnl = equity - paperStartingCapital;
  const totalRealized = paperHistory.reduce((sum, h) => sum + h.realizedPnl, 0);

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
                    onAddCallLeg={() => addLeg("call", item.data.strike, item.data.call.ltp)}
                    onAddPutLeg={() => addLeg("put", item.data.strike, item.data.put.ltp)}
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

      {/* Strategy Builder */}
      <div style={{ marginTop: 16, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 18 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, flexWrap: "wrap", gap: 10 }}>
          <div style={{ fontSize: 13, color: C.muted, letterSpacing: 0.5 }}>STRATEGY BUILDER — payoff at expiry</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <label style={{ fontSize: 11.5, color: C.muted, display: "flex", alignItems: "center", gap: 6 }}>
              Lot size
              <input
                type="number"
                value={lotSize}
                onChange={(e) => setLotSize(Number(e.target.value) || 1)}
                style={{ width: 60, background: "#0B0E14", color: "#E7E9EE", border: `1px solid ${C.border}`, borderRadius: 6, padding: "3px 6px", fontSize: 12 }}
              />
            </label>
            {legs.length > 0 && (
              <>
                <button
                  onClick={executeLegsAsPaperTrade}
                  style={{ fontSize: 11.5, color: "#0B0E14", background: C.gold, border: "none", borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontWeight: 700 }}
                >
                  Execute as Paper Trade
                </button>
                <button onClick={() => setLegs([])} style={{ fontSize: 11, color: C.muted, background: "none", border: `1px solid ${C.border}`, borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}>
                  Clear all
                </button>
              </>
            )}
          </div>
        </div>

        <div style={{ fontSize: 11, color: "#5A6376", marginBottom: 12 }}>
          NSE revises lot sizes periodically — double check the current NIFTY lot size on your broker app or an NSE circular if you're not sure.
        </div>

        {legs.length === 0 ? (
          <div style={{ fontSize: 12.5, color: "#5A6376", padding: "16px 0" }}>
            No legs yet — click a CE or PE price in the chain above to add it here. Add a call and a put at the same strike to build a straddle, for example.
          </div>
        ) : (
          <>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
              {legs.map((l) => (
                <div key={l.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, padding: "6px 10px", borderRadius: 6, background: "#171C27", border: `1px solid ${C.border}` }}>
                  <button
                    onClick={() => toggleLegAction(l.id)}
                    title="Click to flip Buy/Sell"
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      fontWeight: 700,
                      color: l.action === "buy" ? C.green : C.red,
                    }}
                  >
                    {l.action === "buy" ? "BUY" : "SELL"}
                  </button>
                  <span>
                    {l.strike} {l.type === "call" ? "CE" : "PE"} @ {l.premium}
                  </span>
                  <button onClick={() => removeLeg(l.id)} style={{ background: "none", border: "none", color: "#5A6376", cursor: "pointer" }}>
                    ×
                  </button>
                </div>
              ))}
            </div>

            <div style={{ display: "flex", gap: 24, marginBottom: 14, flexWrap: "wrap" }}>
              <div style={{ fontSize: 13 }}>
                <span style={{ color: "#5A6376" }}>Max profit (in shown range): </span>
                <span style={{ color: C.green, fontWeight: 600 }}>
                  ₹{fmtIN(maxProfit)}
                  {openEndedUp ? "+ (unlimited upside)" : ""}
                </span>
              </div>
              <div style={{ fontSize: 13 }}>
                <span style={{ color: "#5A6376" }}>Max loss (in shown range): </span>
                <span style={{ color: C.red, fontWeight: 600 }}>
                  ₹{fmtIN(maxLoss)}
                  {openEndedDown ? "− (can extend further down)" : ""}
                </span>
              </div>
            </div>

            <div style={{ height: 240 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={payoffSeries}>
                  <CartesianGrid stroke={C.border} strokeDasharray="3 3" />
                  <XAxis dataKey="price" stroke="#5A6376" fontSize={11} tickFormatter={(v) => fmtIN(v)} />
                  <YAxis stroke="#5A6376" fontSize={11} tickFormatter={(v) => `₹${fmtIN(v)}`} />
                  <ReferenceLine y={0} stroke="#5A6376" />
                  {spot != null && (
                    <ReferenceLine x={Math.round(spot)} stroke={C.gold} strokeDasharray="4 2" label={{ value: "Spot", fill: C.gold, fontSize: 11, position: "top" }} />
                  )}
                  <Tooltip
                    contentStyle={{ background: "#171C27", border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 12 }}
                    labelFormatter={(v) => `Price: ₹${fmtIN(v)}`}
                    formatter={(v) => [`₹${fmtIN(v)}`, "P&L"]}
                  />
                  <Line type="monotone" dataKey="pnl" stroke={C.gold} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div style={{ fontSize: 10.5, color: "#5A6376", marginTop: 8 }}>
              Chart shown for prices within ±20% of spot. If your position has more long calls than short calls (or more long puts than short puts), actual profit/loss can extend further beyond what's charted here.
            </div>
          </>
        )}
      </div>

      {/* Paper Trading Portfolio */}
      <div style={{ marginTop: 16, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 18 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
          <div style={{ fontSize: 13, color: C.muted, letterSpacing: 0.5 }}>PAPER TRADING PORTFOLIO — simulated, no real money</div>
          <button onClick={resetPaperPortfolio} style={{ fontSize: 11, color: C.muted, background: "none", border: `1px solid ${C.border}`, borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}>
            Reset portfolio
          </button>
        </div>

        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 16 }}>
          <Stat label="Starting capital" value={`₹${fmtIN(paperStartingCapital)}`} />
          <Stat label="Cash" value={`₹${fmtIN(paperCash)}`} />
          <Stat label="Equity (mark-to-market)" value={`₹${fmtIN(equity)}`} color={C.gold} />
          <Stat label="Unrealized P&L" value={`₹${fmtIN(totalUnrealized)}`} color={totalUnrealized >= 0 ? C.green : C.red} />
          <Stat label="Realized P&L (closed trades)" value={`₹${fmtIN(totalRealized)}`} color={totalRealized >= 0 ? C.green : C.red} />
          <Stat label="Total P&L since start" value={`₹${fmtIN(totalPnl)}`} color={totalPnl >= 0 ? C.green : C.red} />
        </div>

        <div style={{ fontSize: 11, color: "#5A6376", marginBottom: 16 }}>
          This is a simplified simulator: it tracks premium paid/received but does not model real margin requirements for short (sell) positions, brokerage, or taxes. Use it to practice how strategies behave, not to estimate real capital needs.
        </div>

        <div style={{ fontSize: 12, color: C.muted, marginBottom: 8, fontWeight: 600 }}>Open Positions</div>
        {positionsWithLtp.length === 0 ? (
          <div style={{ fontSize: 12.5, color: "#5A6376", paddingBottom: 16 }}>
            No open positions. Build a strategy above and click "Execute as Paper Trade" to open one.
          </div>
        ) : (
          <div style={{ overflowX: "auto", marginBottom: 20 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr style={{ color: C.muted, fontSize: 10.5 }}>
                  <th style={{ padding: 6, textAlign: "left" }}>Position</th>
                  <th style={{ padding: 6 }}>Expiry</th>
                  <th style={{ padding: 6 }}>Qty (lots)</th>
                  <th style={{ padding: 6 }}>Entry</th>
                  <th style={{ padding: 6 }}>Current LTP</th>
                  <th style={{ padding: 6 }}>Unrealized P&L</th>
                  <th style={{ padding: 6 }}></th>
                </tr>
              </thead>
              <tbody>
                {positionsWithLtp.map((p) => (
                  <tr key={p.id} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: 6 }}>
                      <span style={{ color: p.action === "buy" ? C.green : C.red, fontWeight: 700 }}>{p.action.toUpperCase()}</span>{" "}
                      {p.symbol} {p.strike} {p.type === "call" ? "CE" : "PE"}
                    </td>
                    <td style={{ padding: 6, color: C.muted }}>{p.expiry}</td>
                    <td style={{ padding: 6 }}>{p.qty}</td>
                    <td style={{ padding: 6 }}>{p.entryPremium}</td>
                    <td style={{ padding: 6 }}>{p.currentLtp ?? "— (switch expiry to load)"}</td>
                    <td style={{ padding: 6, color: p.unrealizedPnl == null ? C.muted : p.unrealizedPnl >= 0 ? C.green : C.red }}>
                      {p.unrealizedPnl == null ? "-" : `₹${fmtIN(p.unrealizedPnl)}`}
                    </td>
                    <td style={{ padding: 6 }}>
                      <button
                        onClick={() => closePosition(p.id)}
                        style={{ fontSize: 11, color: C.text, background: "none", border: `1px solid ${C.border}`, borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}
                      >
                        Close
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ fontSize: 12, color: C.muted, marginBottom: 8, fontWeight: 600 }}>Trade History</div>
        {paperHistory.length === 0 ? (
          <div style={{ fontSize: 12.5, color: "#5A6376" }}>No closed trades yet.</div>
        ) : (
          <div style={{ overflowX: "auto", maxHeight: 240, overflowY: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr style={{ color: C.muted, fontSize: 10.5 }}>
                  <th style={{ padding: 6, textAlign: "left" }}>Position</th>
                  <th style={{ padding: 6 }}>Entry</th>
                  <th style={{ padding: 6 }}>Exit</th>
                  <th style={{ padding: 6 }}>Realized P&L</th>
                  <th style={{ padding: 6 }}>Closed</th>
                </tr>
              </thead>
              <tbody>
                {paperHistory.map((h, i) => (
                  <tr key={i} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: 6 }}>
                      <span style={{ color: h.action === "buy" ? C.green : C.red, fontWeight: 700 }}>{h.action.toUpperCase()}</span>{" "}
                      {h.symbol} {h.strike} {h.type === "call" ? "CE" : "PE"}
                    </td>
                    <td style={{ padding: 6 }}>{h.entryPremium}</td>
                    <td style={{ padding: 6 }}>{h.exitPrice}</td>
                    <td style={{ padding: 6, color: h.realizedPnl >= 0 ? C.green : C.red }}>₹{fmtIN(h.realizedPnl)}</td>
                    <td style={{ padding: 6, color: C.muted }}>{new Date(h.exitTime).toLocaleString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: "#5A6376" }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: color || "#E7E9EE" }}>{value}</div>
    </div>
  );
}

function Row({ row, isATM, isWatchedCall, isWatchedPut, onToggleCall, onTogglePut, onAddCallLeg, onAddPutLeg }) {
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
      <td style={{ padding: 6 }}>
        <button onClick={onAddCallLeg} title="Add as a strategy leg" style={{ background: "none", border: "none", color: C.green, fontWeight: 600, cursor: "pointer", fontSize: 12.5, padding: 0 }}>
          {c.ltp ?? "-"}
        </button>
      </td>
      <td style={{ padding: 6, textAlign: "center", fontWeight: 700 }}>{fmtIN(row.strike)}</td>
      <td style={{ padding: 6 }}>
        <button onClick={onAddPutLeg} title="Add as a strategy leg" style={{ background: "none", border: "none", color: C.red, fontWeight: 600, cursor: "pointer", fontSize: 12.5, padding: 0 }}>
          {p.ltp ?? "-"}
        </button>
      </td>
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

function Centered({ children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh" }}>
      {children}
    </div>
  );
}
