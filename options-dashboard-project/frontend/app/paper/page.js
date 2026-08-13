"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
import { getStatus, getExpiries, getChain } from "@/lib/api";
import { STRATEGY_CATEGORIES, strategiesFor } from "@/lib/strategies";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";

const C = {
  surface: "#12161F",
  surface2: "#171C27",
  border: "#242B3A",
  muted: "#8892A6",
  faint: "#5A6376",
  text: "#E7E9EE",
  gold: "#C9A15A",
  green: "#4CAF7D",
  red: "#E15252",
};

const PAPER_KEY = "options_dashboard_paper_v1";
const DEFAULT_STARTING_CAPITAL = 500000;

function fmtIN(n, decimals = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export default function PaperTradingPage() {
  // ---- All hooks declared up top, unconditionally ----
  const [loggedIn, setLoggedIn] = useState(null);
  const [error, setError] = useState(null);
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState(null);
  const [chainCache, setChainCache] = useState({}); // { [expiryDate]: chainResponse }

  const [legs, setLegs] = useState([]);
  const [multiplier, setMultiplier] = useState(1);
  const [lotSize, setLotSize] = useState(65);
  const [category, setCategory] = useState("Bullish");
  const [payoffTab, setPayoffTab] = useState("graph");
  const [targetPct, setTargetPct] = useState(0);

  const [paperCash, setPaperCash] = useState(DEFAULT_STARTING_CAPITAL);
  const [paperStartingCapital, setPaperStartingCapital] = useState(DEFAULT_STARTING_CAPITAL);
  const [paperPositions, setPaperPositions] = useState([]);
  const [paperHistory, setPaperHistory] = useState([]);

  const loadChain = useCallback(async (expiryDate) => {
    if (!expiryDate) return;
    try {
      const data = await getChain("NIFTY", expiryDate);
      setChainCache((prev) => ({ ...prev, [expiryDate]: data }));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    getStatus().then((s) => setLoggedIn(s.logged_in)).catch(() => setLoggedIn(false));
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    getExpiries("NIFTY")
      .then((d) => {
        setExpiries(d.expiries);
        if (d.expiries.length) setExpiry(d.expiries[0]);
      })
      .catch((e) => setError(e.message));
  }, [loggedIn]);

  // Poll the primary expiry's chain every 5s
  useEffect(() => {
    if (!loggedIn || !expiry) return;
    let cancelled = false;
    const tick = () => {
      if (!cancelled) loadChain(expiry);
    };
    tick();
    const interval = setInterval(tick, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [loggedIn, expiry, loadChain]);

  // Load / save paper trading state to the browser
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
        JSON.stringify({ cash: paperCash, startingCapital: paperStartingCapital, positions: paperPositions, history: paperHistory })
      );
    } catch (e) {}
  }, [paperCash, paperStartingCapital, paperPositions, paperHistory]);

  const primaryChain = chainCache[expiry];
  const spot = primaryChain?.underlying_spot_price ?? null;

  const strikesSorted = useMemo(
    () => (primaryChain ? primaryChain.chain.map((r) => r.strike).sort((a, b) => a - b) : []),
    [primaryChain]
  );

  const chainByStrike = useMemo(() => {
    const map = new Map();
    if (primaryChain) primaryChain.chain.forEach((r) => map.set(r.strike, r));
    return map;
  }, [primaryChain]);

  const atmIndex = useMemo(() => {
    if (!spot || strikesSorted.length === 0) return 0;
    let best = 0;
    let bestDiff = Infinity;
    strikesSorted.forEach((s, i) => {
      const diff = Math.abs(s - spot);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = i;
      }
    });
    return best;
  }, [spot, strikesSorted]);

  // P&L at a given underlying price, for the current legs
  const pnlAtPrice = useCallback(
    (price) => {
      let pnl = 0;
      legs.forEach((l) => {
        const intrinsic = l.type === "call" ? Math.max(0, price - l.strike) : Math.max(0, l.strike - price);
        const dir = l.action === "buy" ? 1 : -1;
        pnl += dir * (intrinsic - l.price) * l.qty * lotSize * multiplier;
      });
      return pnl;
    },
    [legs, lotSize, multiplier]
  );

  // Payoff chart data: one point per real strike (so OI bars line up), plus P&L line
  const payoffData = useMemo(() => {
    if (strikesSorted.length === 0) return [];
    return strikesSorted.map((strike) => {
      const row = chainByStrike.get(strike);
      return {
        strike,
        pnl: legs.length ? Math.round(pnlAtPrice(strike)) : 0,
        callOI: row?.call.oi ?? 0,
        putOI: row?.put.oi ?? 0,
      };
    });
  }, [strikesSorted, chainByStrike, legs, pnlAtPrice]);

  const maxProfit = payoffData.length ? Math.max(...payoffData.map((p) => p.pnl)) : 0;
  const maxLoss = payoffData.length ? Math.min(...payoffData.map((p) => p.pnl)) : 0;

  const targetPrice = spot ? spot * (1 + targetPct / 100) : null;
  const targetPnl = targetPrice != null ? pnlAtPrice(targetPrice) : null;

  const netPerLot = legs.reduce((sum, l) => {
    const dir = l.action === "buy" ? 1 : -1;
    return sum + dir * l.price * l.qty;
  }, 0);
  const netTotal = netPerLot * lotSize * multiplier;

  const greeksRows = useMemo(() => {
    return legs.map((l) => {
      const legChain = chainCache[l.expiry];
      const row = legChain?.chain.find((r) => r.strike === l.strike);
      const g = row ? (l.type === "call" ? row.call : row.put) : null;
      const dir = l.action === "buy" ? 1 : -1;
      const mult = dir * l.qty * lotSize * multiplier;
      return {
        leg: l,
        delta: g?.delta != null ? g.delta * mult : null,
        gamma: g?.gamma != null ? g.gamma * mult : null,
        theta: g?.theta != null ? g.theta * mult : null,
        vega: g?.vega != null ? g.vega * mult : null,
      };
    });
  }, [legs, chainCache, lotSize, multiplier]);

  const greeksTotals = greeksRows.reduce(
    (acc, r) => ({
      delta: acc.delta + (r.delta ?? 0),
      gamma: acc.gamma + (r.gamma ?? 0),
      theta: acc.theta + (r.theta ?? 0),
      vega: acc.vega + (r.vega ?? 0),
    }),
    { delta: 0, gamma: 0, theta: 0, vega: 0 }
  );

  // ---- Paper trading (positions) ----
  const dirOf = (action) => (action === "buy" ? 1 : -1);

  const getCurrentLtp = (position) => {
    const posChain = chainCache[position.expiry];
    if (!posChain) return null;
    const row = posChain.chain.find((r) => r.strike === position.strike);
    if (!row) return null;
    return position.type === "call" ? row.call.ltp : row.put.ltp;
  };

  const executeTradeAll = () => {
    if (legs.length === 0) return;
    let cashDelta = 0;
    const newPositions = legs.map((l) => {
      const dir = dirOf(l.action);
      const effectiveQty = l.qty * multiplier;
      cashDelta -= dir * l.price * lotSize * effectiveQty;
      return {
        id: `pos-${l.type}-${l.strike}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        symbol: "NIFTY",
        type: l.type,
        strike: l.strike,
        expiry: l.expiry,
        action: l.action,
        qty: effectiveQty,
        lotSize,
        entryPremium: l.price,
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
      alert("No live price cached for this position's expiry yet. Select that expiry in the builder above once to load it, then try closing again.");
      return;
    }
    const dir = dirOf(position.action);
    const cashDelta = dir * exitPrice * position.lotSize * position.qty;
    const realizedPnl = dir * (exitPrice - position.entryPremium) * position.lotSize * position.qty;
    setPaperCash((c) => c + cashDelta);
    setPaperPositions((prev) => prev.filter((p) => p.id !== id));
    setPaperHistory((prev) => [{ ...position, exitPrice, exitTime: new Date().toISOString(), realizedPnl }, ...prev]);
  };

  const resetPaperPortfolio = () => {
    if (!window.confirm("Reset your paper portfolio? This clears all open positions and trade history.")) return;
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
  const equity = paperCash + positionsWithLtp.reduce((sum, p) => (p.currentLtp == null ? sum : sum + dirOf(p.action) * p.currentLtp * p.lotSize * p.qty), 0);
  const totalPnl = equity - paperStartingCapital;
  const totalRealized = paperHistory.reduce((sum, h) => sum + h.realizedPnl, 0);

  // ---- Leg editing helpers ----
  const addLegFromChain = (type, strike) => {
    const row = chainByStrike.get(strike);
    const price = row ? (type === "call" ? row.call.ltp : row.put.ltp) : 0;
    setLegs((prev) => [
      ...prev,
      { id: `${type}-${strike}-${Date.now()}`, type, strike, action: "buy", qty: 1, expiry, price: price ?? 0 },
    ]);
  };

  const updateLeg = (id, patch) => {
    setLegs((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  };

  const removeLeg = (id) => setLegs((prev) => prev.filter((l) => l.id !== id));

  const resetLegPrices = () => {
    setLegs((prev) =>
      prev.map((l) => {
        const legChain = chainCache[l.expiry];
        const row = legChain?.chain.find((r) => r.strike === l.strike);
        const price = row ? (l.type === "call" ? row.call.ltp : row.put.ltp) : l.price;
        return { ...l, price: price ?? l.price };
      })
    );
  };

  const changeLegStrike = (id, direction) => {
    const l = legs.find((x) => x.id === id);
    if (!l) return;
    const legChain = chainCache[l.expiry];
    const strikes = legChain ? legChain.chain.map((r) => r.strike).sort((a, b) => a - b) : strikesSorted;
    const idx = strikes.indexOf(l.strike);
    const newIdx = Math.min(Math.max(idx + direction, 0), strikes.length - 1);
    const newStrike = strikes[newIdx];
    const row = legChain?.chain.find((r) => r.strike === newStrike) ?? chainByStrike.get(newStrike);
    const price = row ? (l.type === "call" ? row.call.ltp : row.put.ltp) : l.price;
    updateLeg(id, { strike: newStrike, price: price ?? l.price });
  };

  const changeLegExpiry = (id, newExpiry) => {
    updateLeg(id, { expiry: newExpiry });
    if (!chainCache[newExpiry]) loadChain(newExpiry);
  };

  const loadStrategy = (strategyDef) => {
    if (!primaryChain) return;
    const ctx = { strikes: strikesSorted, atmIndex, chainByStrike, expiry };
    setLegs(strategyDef.build(ctx));
  };

  // ---- Render ----
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

  return (
    <div style={{ padding: 20 }}>
      <TopNav active="paper" />

      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>Strategy Builder</h1>
        <select
          value={expiry ?? ""}
          onChange={(e) => setExpiry(e.target.value)}
          style={{ background: C.surface, color: C.text, border: `1px solid ${C.border}`, borderRadius: 6, padding: "6px 10px" }}
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
        {error && <span style={{ color: C.red, fontSize: 12 }}>{error}</span>}
      </div>

      {!primaryChain ? (
        <Centered>Loading chain…</Centered>
      ) : (
        <>
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
            {/* Left column: builder + readymade */}
            <div style={{ flex: "1 1 520px", minWidth: 480 }}>
              {/* Leg builder */}
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16, marginBottom: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>New Strategy</div>
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <button onClick={resetLegPrices} style={{ fontSize: 11.5, color: C.gold, background: "none", border: "none", cursor: "pointer" }}>
                      ↻ Reset Prices
                    </button>
                    <button onClick={() => setLegs([])} style={{ fontSize: 11.5, color: C.muted, background: "none", border: "none", cursor: "pointer" }}>
                      Clear New Trades
                    </button>
                  </div>
                </div>

                {legs.length === 0 ? (
                  <div style={{ fontSize: 12.5, color: C.faint, padding: "16px 0" }}>
                    No legs yet. Click a ready-made strategy below, or add legs from the option chain on the Option Chain page.
                  </div>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <thead>
                        <tr style={{ color: C.muted, fontSize: 10.5, textAlign: "left" }}>
                          <th style={{ padding: 5 }}>B/S</th>
                          <th style={{ padding: 5 }}>Expiry</th>
                          <th style={{ padding: 5 }}>Strike</th>
                          <th style={{ padding: 5 }}>Type</th>
                          <th style={{ padding: 5 }}>Lots</th>
                          <th style={{ padding: 5 }}>Price</th>
                          <th style={{ padding: 5 }}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {legs.map((l) => (
                          <tr key={l.id} style={{ borderTop: `1px solid ${C.border}` }}>
                            <td style={{ padding: 5 }}>
                              <button
                                onClick={() => updateLeg(l.id, { action: l.action === "buy" ? "sell" : "buy" })}
                                style={{
                                  background: l.action === "buy" ? C.green : C.red,
                                  color: "#0B0E14",
                                  border: "none",
                                  borderRadius: 4,
                                  padding: "3px 8px",
                                  fontWeight: 700,
                                  cursor: "pointer",
                                  fontSize: 11,
                                }}
                              >
                                {l.action === "buy" ? "B" : "S"}
                              </button>
                            </td>
                            <td style={{ padding: 5 }}>
                              <select
                                value={l.expiry}
                                onChange={(e) => changeLegExpiry(l.id, e.target.value)}
                                style={{ background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "3px 4px", fontSize: 11 }}
                              >
                                {expiries.map((exp) => (
                                  <option key={exp} value={exp}>
                                    {exp}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td style={{ padding: 5 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                <StepButton onClick={() => changeLegStrike(l.id, -1)}>−</StepButton>
                                <span style={{ minWidth: 52, textAlign: "center" }}>{fmtIN(l.strike)}</span>
                                <StepButton onClick={() => changeLegStrike(l.id, 1)}>+</StepButton>
                              </div>
                            </td>
                            <td style={{ padding: 5 }}>
                              <button
                                onClick={() => updateLeg(l.id, { type: l.type === "call" ? "put" : "call" })}
                                style={{ background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "3px 8px", cursor: "pointer", fontSize: 11 }}
                              >
                                {l.type === "call" ? "CE" : "PE"}
                              </button>
                            </td>
                            <td style={{ padding: 5 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                <StepButton onClick={() => updateLeg(l.id, { qty: Math.max(1, l.qty - 1) })}>−</StepButton>
                                <span style={{ minWidth: 20, textAlign: "center" }}>{l.qty}</span>
                                <StepButton onClick={() => updateLeg(l.id, { qty: l.qty + 1 })}>+</StepButton>
                              </div>
                            </td>
                            <td style={{ padding: 5 }}>
                              <input
                                type="number"
                                value={l.price}
                                onChange={(e) => updateLeg(l.id, { price: Number(e.target.value) || 0 })}
                                style={{ width: 64, background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "3px 5px", fontSize: 11 }}
                              />
                            </td>
                            <td style={{ padding: 5 }}>
                              <button onClick={() => removeLeg(l.id)} style={{ background: "none", border: "none", color: C.faint, cursor: "pointer", fontSize: 14 }}>
                                ×
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {legs.length > 0 && (
                  <>
                    <div style={{ display: "flex", gap: 20, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
                      <label style={{ fontSize: 11.5, color: C.muted, display: "flex", alignItems: "center", gap: 6 }}>
                        Multiplier
                        <input
                          type="number"
                          min={1}
                          value={multiplier}
                          onChange={(e) => setMultiplier(Math.max(1, Number(e.target.value) || 1))}
                          style={{ width: 50, background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "3px 5px", fontSize: 11 }}
                        />
                      </label>
                      <label style={{ fontSize: 11.5, color: C.muted, display: "flex", alignItems: "center", gap: 6 }}>
                        Lot size
                        <input
                          type="number"
                          min={1}
                          value={lotSize}
                          onChange={(e) => setLotSize(Math.max(1, Number(e.target.value) || 1))}
                          style={{ width: 60, background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "3px 5px", fontSize: 11 }}
                        />
                      </label>
                      <div style={{ fontSize: 12 }}>
                        <span style={{ color: C.faint }}>{netPerLot >= 0 ? "Price Pay" : "Price Receive"}: </span>
                        <span style={{ fontWeight: 600 }}>{Math.abs(netPerLot).toFixed(2)}</span>
                      </div>
                      <div style={{ fontSize: 12 }}>
                        <span style={{ color: C.faint }}>{netTotal >= 0 ? "Premium Pay" : "Premium Receive"}: </span>
                        <span style={{ fontWeight: 600 }}>₹{fmtIN(Math.abs(netTotal))}</span>
                      </div>
                    </div>

                    <button
                      onClick={executeTradeAll}
                      style={{ marginTop: 14, background: C.gold, color: "#0B0E14", border: "none", borderRadius: 8, padding: "10px 20px", fontWeight: 700, cursor: "pointer", fontSize: 13 }}
                    >
                      Trade All (Paper)
                    </button>
                  </>
                )}
              </div>

              {/* Readymade strategies */}
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16 }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Ready-made Strategies</div>
                <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
                  {STRATEGY_CATEGORIES.map((cat) => (
                    <button
                      key={cat}
                      onClick={() => setCategory(cat)}
                      style={{
                        padding: "6px 14px",
                        borderRadius: 20,
                        fontSize: 12,
                        border: `1px solid ${category === cat ? C.gold : C.border}`,
                        background: category === cat ? "rgba(201,161,90,0.1)" : "transparent",
                        color: category === cat ? C.gold : C.muted,
                        cursor: "pointer",
                      }}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
                  {strategiesFor(category).map((s) => (
                    <button
                      key={s.id}
                      onClick={() => loadStrategy(s)}
                      style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "12px 10px", cursor: "pointer", textAlign: "left" }}
                    >
                      <ShapeIcon shape={s.shape} />
                      <div style={{ fontSize: 11.5, color: C.text, marginTop: 6 }}>{s.name}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Right column: payoff graph */}
            <div style={{ flex: "1 1 420px", minWidth: 380, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16 }}>
              <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
                {[
                  ["graph", "Payoff Graph"],
                  ["table", "P&L Table"],
                  ["greeks", "Greeks"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setPayoffTab(key)}
                    style={{
                      fontSize: 12,
                      padding: "6px 12px",
                      borderRadius: 6,
                      border: `1px solid ${payoffTab === key ? C.gold : C.border}`,
                      background: payoffTab === key ? "rgba(201,161,90,0.1)" : "transparent",
                      color: payoffTab === key ? C.gold : C.muted,
                      cursor: "pointer",
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {legs.length === 0 ? (
                <div style={{ fontSize: 12.5, color: C.faint, padding: "30px 0" }}>
                  Add legs to see the payoff graph, table, and Greeks here.
                </div>
              ) : payoffTab === "graph" ? (
                <>
                  <div style={{ display: "flex", gap: 20, marginBottom: 10, flexWrap: "wrap" }}>
                    <Stat label="Max profit (shown range)" value={`₹${fmtIN(maxProfit)}`} color={C.green} />
                    <Stat label="Max loss (shown range)" value={`₹${fmtIN(maxLoss)}`} color={C.red} />
                  </div>
                  <div style={{ height: 300 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={payoffData}>
                        <CartesianGrid stroke={C.border} strokeDasharray="3 3" />
                        <XAxis dataKey="strike" stroke={C.faint} fontSize={10.5} tickFormatter={(v) => fmtIN(v)} />
                        <YAxis yAxisId="pnl" stroke={C.faint} fontSize={10.5} tickFormatter={(v) => `₹${fmtIN(v)}`} />
                        <YAxis yAxisId="oi" orientation="right" stroke={C.faint} fontSize={10.5} tickFormatter={(v) => fmtIN(v)} />
                        <ReferenceLine yAxisId="pnl" y={0} stroke={C.faint} />
                        {spot != null && <ReferenceLine yAxisId="pnl" x={strikesSorted.reduce((a, b) => (Math.abs(b - spot) < Math.abs(a - spot) ? b : a))} stroke={C.gold} strokeDasharray="4 2" />}
                        <Tooltip contentStyle={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11.5 }} />
                        <Bar yAxisId="oi" dataKey="callOI" fill="rgba(225,82,82,0.5)" name="Call OI" />
                        <Bar yAxisId="oi" dataKey="putOI" fill="rgba(76,175,125,0.5)" name="Put OI" />
                        <Line yAxisId="pnl" type="monotone" dataKey="pnl" stroke={C.gold} strokeWidth={2} dot={false} name="P&L" />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>

                  <div style={{ marginTop: 14 }}>
                    <div style={{ fontSize: 11.5, color: C.muted, marginBottom: 6 }}>
                      Target price: <span style={{ color: C.gold, fontWeight: 600 }}>{targetPrice != null ? fmtIN(targetPrice, 2) : "-"}</span>{" "}
                      ({targetPct >= 0 ? "+" : ""}
                      {targetPct}%)
                    </div>
                    <input
                      type="range"
                      min={-15}
                      max={15}
                      step={0.5}
                      value={targetPct}
                      onChange={(e) => setTargetPct(Number(e.target.value))}
                      style={{ width: "100%" }}
                    />
                    {targetPnl != null && (
                      <div style={{ fontSize: 12.5, marginTop: 6 }}>
                        Projected {targetPnl >= 0 ? "profit" : "loss"}:{" "}
                        <span style={{ color: targetPnl >= 0 ? C.green : C.red, fontWeight: 700 }}>₹{fmtIN(Math.abs(targetPnl))}</span>
                      </div>
                    )}
                  </div>

                  <div style={{ fontSize: 10.5, color: C.faint, marginTop: 10 }}>
                    Bars show live open interest (red = Call OI, green = Put OI) at each strike, at expiry payoff.
                  </div>
                </>
              ) : payoffTab === "table" ? (
                <div style={{ overflowY: "auto", maxHeight: 420 }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                    <thead>
                      <tr style={{ color: C.muted, fontSize: 10.5 }}>
                        <th style={{ padding: 6, textAlign: "left" }}>Underlying at expiry</th>
                        <th style={{ padding: 6 }}>P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {payoffData.map((d) => (
                        <tr key={d.strike} style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: 6 }}>{fmtIN(d.strike)}</td>
                          <td style={{ padding: 6, color: d.pnl >= 0 ? C.green : C.red }}>₹{fmtIN(d.pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginBottom: 12 }}>
                    <thead>
                      <tr style={{ color: C.muted, fontSize: 10.5, textAlign: "left" }}>
                        <th style={{ padding: 6 }}>Leg</th>
                        <th style={{ padding: 6 }}>Delta</th>
                        <th style={{ padding: 6 }}>Gamma</th>
                        <th style={{ padding: 6 }}>Theta</th>
                        <th style={{ padding: 6 }}>Vega</th>
                      </tr>
                    </thead>
                    <tbody>
                      {greeksRows.map((r) => (
                        <tr key={r.leg.id} style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: 6 }}>
                            {r.leg.action.toUpperCase()} {r.leg.strike} {r.leg.type === "call" ? "CE" : "PE"}
                          </td>
                          <td style={{ padding: 6 }}>{r.delta != null ? r.delta.toFixed(2) : "-"}</td>
                          <td style={{ padding: 6 }}>{r.gamma != null ? r.gamma.toFixed(4) : "-"}</td>
                          <td style={{ padding: 6 }}>{r.theta != null ? r.theta.toFixed(2) : "-"}</td>
                          <td style={{ padding: 6 }}>{r.vega != null ? r.vega.toFixed(2) : "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr style={{ borderTop: `2px solid ${C.border}`, fontWeight: 700 }}>
                        <td style={{ padding: 6 }}>Total</td>
                        <td style={{ padding: 6 }}>{greeksTotals.delta.toFixed(2)}</td>
                        <td style={{ padding: 6 }}>{greeksTotals.gamma.toFixed(4)}</td>
                        <td style={{ padding: 6 }}>{greeksTotals.theta.toFixed(2)}</td>
                        <td style={{ padding: 6 }}>{greeksTotals.vega.toFixed(2)}</td>
                      </tr>
                    </tfoot>
                  </table>
                  <div style={{ fontSize: 10.5, color: C.faint }}>
                    Position-level Greeks = each leg's Greek × direction × lots × lot size × multiplier, summed.
                  </div>
                </div>
              )}
            </div>
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
              <Stat label="Realized P&L" value={`₹${fmtIN(totalRealized)}`} color={totalRealized >= 0 ? C.green : C.red} />
              <Stat label="Total P&L since start" value={`₹${fmtIN(totalPnl)}`} color={totalPnl >= 0 ? C.green : C.red} />
            </div>

            <div style={{ fontSize: 11, color: C.faint, marginBottom: 16 }}>
              Simplified simulator: tracks premium paid/received, not real margin requirements, brokerage, or taxes.
            </div>

            <div style={{ fontSize: 12, color: C.muted, marginBottom: 8, fontWeight: 600 }}>Open Positions</div>
            {positionsWithLtp.length === 0 ? (
              <div style={{ fontSize: 12.5, color: C.faint, paddingBottom: 16 }}>No open positions.</div>
            ) : (
              <div style={{ overflowX: "auto", marginBottom: 20 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                  <thead>
                    <tr style={{ color: C.muted, fontSize: 10.5 }}>
                      <th style={{ padding: 6, textAlign: "left" }}>Position</th>
                      <th style={{ padding: 6 }}>Expiry</th>
                      <th style={{ padding: 6 }}>Qty</th>
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
                          <span style={{ color: p.action === "buy" ? C.green : C.red, fontWeight: 700 }}>{p.action.toUpperCase()}</span> {p.symbol} {p.strike} {p.type === "call" ? "CE" : "PE"}
                        </td>
                        <td style={{ padding: 6, color: C.muted }}>{p.expiry}</td>
                        <td style={{ padding: 6 }}>{p.qty}</td>
                        <td style={{ padding: 6 }}>{p.entryPremium}</td>
                        <td style={{ padding: 6 }}>{p.currentLtp ?? "-"}</td>
                        <td style={{ padding: 6, color: p.unrealizedPnl == null ? C.muted : p.unrealizedPnl >= 0 ? C.green : C.red }}>
                          {p.unrealizedPnl == null ? "-" : `₹${fmtIN(p.unrealizedPnl)}`}
                        </td>
                        <td style={{ padding: 6 }}>
                          <button onClick={() => closePosition(p.id)} style={{ fontSize: 11, color: C.text, background: "none", border: `1px solid ${C.border}`, borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}>
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
              <div style={{ fontSize: 12.5, color: C.faint }}>No closed trades yet.</div>
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
                          <span style={{ color: h.action === "buy" ? C.green : C.red, fontWeight: 700 }}>{h.action.toUpperCase()}</span> {h.symbol} {h.strike} {h.type === "call" ? "CE" : "PE"}
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
        </>
      )}
    </div>
  );
}

function StepButton({ onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{ width: 20, height: 20, lineHeight: "18px", background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, cursor: "pointer", fontSize: 12, padding: 0 }}
    >
      {children}
    </button>
  );
}

function Stat({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: C.faint }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: color || C.text }}>{value}</div>
    </div>
  );
}

function ShapeIcon({ shape }) {
  const paths = {
    riseUp: "M4 26 L16 26 L28 6",
    fallUp: "M4 6 L16 6 L28 26",
    riseCapped: "M4 26 L12 26 L20 10 L28 10",
    fallCapped: "M4 10 L12 10 L20 26 L28 26",
    plateau: "M4 20 L10 20 L14 10 L20 10 L24 20 L28 20",
    peak: "M4 22 L12 22 L16 8 L20 22 L28 22",
    vUp: "M4 6 L14 22 L16 24 L18 22 L28 6",
  };
  return (
    <svg width="100%" height="32" viewBox="0 0 32 32">
      <path d={paths[shape] || paths.riseUp} stroke={C.green} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function TopNav({ active }) {
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
      <a
        href="/dashboard"
        style={{
          fontSize: 12.5,
          padding: "6px 14px",
          borderRadius: 6,
          border: `1px solid ${active === "chain" ? C.gold : C.border}`,
          background: active === "chain" ? "rgba(201,161,90,0.1)" : "transparent",
          color: active === "chain" ? C.gold : C.muted,
          textDecoration: "none",
        }}
      >
        Option Chain
      </a>
      <a
        href="/paper"
        style={{
          fontSize: 12.5,
          padding: "6px 14px",
          borderRadius: 6,
          border: `1px solid ${active === "paper" ? C.gold : C.border}`,
          background: active === "paper" ? "rgba(201,161,90,0.1)" : "transparent",
          color: active === "paper" ? C.gold : C.muted,
          textDecoration: "none",
        }}
      >
        Paper Trading
      </a>
    </div>
  );
}

function Centered({ children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh" }}>
      {children}
    </div>
  );
}
