"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
import {
  getStatus,
  getExpiries,
  getChain,
  isAuthError,
  submitPaperFill,
  closePaperLeg,
  getPaperJournal,
} from "@/lib/api";
import { captureSessionFromUrl } from "@/lib/session";
import { STRATEGY_CATEGORIES, strategiesFor } from "@/lib/strategies";
import { historyToCsv, strategyStats, recordEquityPoint, isWithinMarketHours, sanitizeEquityHistory } from "@/lib/paperUtils";
import { C, TopNav, SymbolTabs, Centered, SessionExpired, Stat, StepButton, ShapeIcon, fmtIN, LOT_SIZES, useIsMobile } from "@/lib/ui";
import {
  ComposedChart, Bar, Line, Area, LineChart, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";

const PAPER_KEY = "options_dashboard_paper_v1";
const DEFAULT_STARTING_CAPITAL = 500000;
const JOURNAL_PAGE_SIZE = 10;

const fmtJournalDate = (iso) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

// Fluid type scale: interpolates px font-size from `min` (narrow screens) up to
// `max` (≥1920px viewports) so headings stay crisp on high-res displays.
const fluid = (min, max) => `clamp(${min}px, ${min}px + ${((max - min) * 100) / 1920}vw, ${max}px)`;

export default function PaperTradingPage() {
  // ---- All hooks declared up top, unconditionally ----
  const [loggedIn, setLoggedIn] = useState(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [error, setError] = useState(null);
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState(null);
  const [chainCache, setChainCache] = useState({}); // { [expiryDate]: chainResponse }
  const isMobile = useIsMobile();

  const [legs, setLegs] = useState([]);
  const [strategyName, setStrategyName] = useState(null);
  const [multiplier, setMultiplier] = useState(1);
  const [lotSize, setLotSize] = useState(LOT_SIZES.NIFTY);
  const [category, setCategory] = useState("Bullish");
  const [payoffTab, setPayoffTab] = useState("graph");
  const [targetPct, setTargetPct] = useState(0);

  const [paperCash, setPaperCash] = useState(DEFAULT_STARTING_CAPITAL);
  const [paperStartingCapital, setPaperStartingCapital] = useState(DEFAULT_STARTING_CAPITAL);
  const [paperPositions, setPaperPositions] = useState([]);
  const [paperHistory, setPaperHistory] = useState([]);
  const [equityHistory, setEquityHistory] = useState([]);
  const [journal, setJournal] = useState(null);
  const [journalError, setJournalError] = useState(null);
  const [journalPage, setJournalPage] = useState(0);

  const loadChain = useCallback(async (expiryDate) => {
    if (!expiryDate) return;
    try {
      const data = await getChain(symbol, expiryDate);
      setChainCache((prev) => ({ ...prev, [expiryDate]: data }));
      setError(null);
    } catch (e) {
      if (isAuthError(e)) setSessionExpired(true);
      else setError(e.message);
    }
  }, [symbol]);

  useEffect(() => {
    captureSessionFromUrl();
    getStatus()
      .then((s) => setLoggedIn(s.logged_in))
      .catch((e) => {
        setError(e.message);
        setLoggedIn(false);
      });
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    setExpiry(null);
    setExpiries([]);
    setChainCache({});
    setLegs([]);
    setStrategyName(null);
    setLotSize(LOT_SIZES[symbol] ?? LOT_SIZES.NIFTY);
    getExpiries(symbol)
      .then((d) => {
        setExpiries(d.expiries);
        if (d.expiries.length) setExpiry(d.expiries[0]);
      })
      .catch((e) => {
        if (isAuthError(e)) setSessionExpired(true);
        else setError(e.message);
      });
  }, [loggedIn, symbol]);

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
        setEquityHistory(sanitizeEquityHistory(parsed.equityHistory ?? []));
      }
    } catch (e) {
      console.warn("Could not load paper portfolio from localStorage:", e);
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        PAPER_KEY,
        JSON.stringify({ cash: paperCash, startingCapital: paperStartingCapital, positions: paperPositions, history: paperHistory, equityHistory })
      );
    } catch (e) {
      console.warn("Could not save paper portfolio to localStorage:", e);
    }
  }, [paperCash, paperStartingCapital, paperPositions, paperHistory, equityHistory]);

  // Load the DB-backed paper journal (account, stats, trade log).
  const loadJournal = useCallback(() => {
    getPaperJournal()
      .then(setJournal)
      .catch((e) => setJournalError(e.message));
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    loadJournal();
  }, [loggedIn, loadJournal]);

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
        symbol,
        type: l.type,
        strike: l.strike,
        expiry: l.expiry,
        action: l.action,
        qty: effectiveQty,
        lotSize,
        entryPremium: l.price,
        entryTime: new Date().toISOString(),
        strategyName: strategyName ?? "Custom",
      };
    });
    setPaperCash((c) => c + cashDelta);
    setPaperPositions((prev) => [...prev, ...newPositions]);
    setLegs([]);
    setStrategyName(null);

    // Auto-log the fill into the DB journal (trades + legs). Best-effort: the
    // local simulator stays the source of truth if the backend is unreachable.
    const order = {
      symbol,
      strategy_tag: strategyName ?? "Custom",
      starting_capital: paperStartingCapital,
      legs: legs.map((l) => ({
        symbol,
        expiration_date: l.expiry,
        strike_price: l.strike,
        option_type: l.type,
        action: l.action,
        premium: l.price,
        quantity: l.qty * multiplier,
        lot_size: lotSize,
      })),
    };
    submitPaperFill(order)
      .then((created) => {
        const legIds = new Map(created.legs.map((lg, i) => [newPositions[i]?.id, lg.id]));
        setPaperPositions((prev) =>
          prev.map((p) => (legIds.has(p.id) ? { ...p, tradeId: created.id, legId: legIds.get(p.id) } : p))
        );
        loadJournal();
      })
      .catch((e) => {
        console.warn("Paper journal sync failed (trade kept locally):", e.message);
      });
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

    // Sync the exit to the DB journal; the backend closes the whole trade
    // once its last leg is closed (computing multi-leg net credit/debit).
    if (position.tradeId && position.legId) {
      closePaperLeg(position.tradeId, position.legId, exitPrice)
        .then(loadJournal)
        .catch((e) => console.warn("Journal leg close sync failed:", e.message));
    }
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
  const perStrategy = useMemo(() => strategyStats(paperHistory), [paperHistory]);

  // Record an equity snapshot (at most one per minute, market hours only) while
  // data is live. Off-market the chain is frozen, so points would only draw a
  // flat line; skipping unchanged values also keeps holiday sessions clean.
  useEffect(() => {
    if (!primaryChain) return;
    if (!isWithinMarketHours(new Date())) return;
    setEquityHistory((prev) =>
      recordEquityPoint(prev, Math.round(equity), Date.now(), 500, 60000, { skipFlat: true })
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primaryChain]);

  const exportHistoryCsv = () => {
    const blob = new Blob([historyToCsv(paperHistory)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `paper-trades-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ---- Leg editing helpers ----
  const addLegFromChain = (type, strike) => {
    const row = chainByStrike.get(strike);
    const price = row ? (type === "call" ? row.call.ltp : row.put.ltp) : 0;
    setStrategyName(null);
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
    setStrategyName(strategyDef.name);
  };

  // ---- Zone C rows: DB journal (source of truth) + any local-only closed
  // trades that never synced (deduped by tradeId). ----
  const journalIds = new Set((journal?.trades ?? []).map((t) => String(t.id)));
  const localOnly = paperHistory.filter((h) => !(h.tradeId && journalIds.has(String(h.tradeId))));
  const logRows = journal
    ? [...journal.trades, ...localOnly.map((h) => ({ local: true, ...h }))]
    : journalError
      ? paperHistory.map((h) => ({ local: true, ...h }))
      : [];
  const logPageCount = Math.max(1, Math.ceil(logRows.length / JOURNAL_PAGE_SIZE));
  const logPage = Math.min(journalPage, logPageCount - 1);
  const logPageRows = logRows.slice(logPage * JOURNAL_PAGE_SIZE, logPage * JOURNAL_PAGE_SIZE + JOURNAL_PAGE_SIZE);

  // ---- Render ----
  if (loggedIn === null) return <Centered>Checking login…</Centered>;
  if (error && loggedIn === false) return <Centered>Something went wrong: {error}</Centered>;
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
  if (sessionExpired) return <SessionExpired />;

  const panel = { background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16, minWidth: 0 };
  const badge = (label, color, bg, bd) => ({
    padding: "2px 10px",
    borderRadius: 999,
    fontSize: 10.5,
    fontWeight: 700,
    letterSpacing: 0.5,
    color,
    background: bg,
    border: `1px solid ${bd}`,
  });
  const eqLast = equityHistory.length ? equityHistory[equityHistory.length - 1].equity : null;
  const eqColor = eqLast != null ? (eqLast >= paperStartingCapital ? C.green : C.red) : C.gold;
  const eqDelta = eqLast != null ? eqLast - paperStartingCapital : null;

  return (
    <div style={{ padding: isMobile ? 10 : 20 }}>
      <TopNav active="paper" />
      <style>{`
        .paper-row:hover { background: rgba(201,161,90,0.05); }
      `}</style>

      {/* ---------- Portfolio header bar ---------- */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: 10,
          padding: "12px 16px",
          marginBottom: 16,
        }}
      >
        <div style={{ fontSize: fluid(14, 17), fontWeight: 800, letterSpacing: 1.5 }}>
          📊 <span style={{ color: C.gold }}>PAPA TRADING</span>
        </div>
        <div style={{ fontSize: 11.5, color: C.muted, letterSpacing: 1.2, textAlign: "center" }}>
          PAPER TRADING PORTFOLIO <span style={{ color: C.gold }}>· SIMULATED MODE</span>
        </div>
        <div style={{ fontSize: fluid(13, 16) }}>
          <span style={{ color: C.faint }}>💵 Balance: </span>
          <span style={{ color: C.gold, fontWeight: 700 }}>₹{fmtIN(equity, 2)}</span>
        </div>
      </div>

      {!primaryChain ? (
        <Centered>Loading chain…</Centered>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : "clamp(320px, 30vw, 450px) minmax(0, 1fr)",
            gap: 16,
            alignItems: "start",
          }}
        >
          {/* Zone A widened ~50% (300px -> up to 450px) while staying fluid; the
              Zone B column absorbs the rest via minmax(0, 1fr). */}
          {/* ================= ZONE A · CONTROL SIDEBAR ================= */}
          <aside style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
            {/* New Strategy builder */}
            <div style={panel}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: 8,
                      background: "rgba(201,161,90,0.12)",
                      border: "1px solid rgba(201,161,90,0.4)",
                      color: C.gold,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 16,
                      fontWeight: 800,
                      lineHeight: 1,
                      flexShrink: 0,
                    }}
                  >
                    +
                  </span>
                  <div>
                    <div style={{ fontSize: fluid(12, 14), fontWeight: 800, letterSpacing: 0.8, color: C.text }}>CREATE NEW STRATEGY</div>
                    <div style={{ fontSize: 10, color: C.faint, letterSpacing: 0.4 }}>build legs from the live chain</div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <button onClick={resetLegPrices} style={{ fontSize: 11, color: C.gold, background: "none", border: "none", cursor: "pointer" }}>
                    ↻ Reset Prices
                  </button>
                  <button onClick={() => setLegs([])} style={{ fontSize: 11, color: C.muted, background: "none", border: "none", cursor: "pointer" }}>
                    Clear Trades
                  </button>
                </div>
              </div>

              <SymbolTabs symbol={symbol} onChange={setSymbol} />
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <select
                  value={expiry ?? ""}
                  onChange={(e) => setExpiry(e.target.value)}
                  style={{ background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 6, padding: "5px 8px", fontSize: 11.5, flex: 1, minWidth: 120 }}
                >
                  {expiries.map((exp) => (
                    <option key={exp} value={exp}>
                      {exp}
                    </option>
                  ))}
                </select>
                {spot != null && (
                  <span style={{ color: C.muted, fontSize: 12 }}>
                    Spot: <span style={{ color: C.gold, fontWeight: 600 }}>{fmtIN(spot, 2)}</span>
                  </span>
                )}
              </div>
              {error && <div style={{ color: C.red, fontSize: 11.5, marginTop: 8 }}>{error}</div>}

              {legs.length === 0 ? (
                <div style={{ fontSize: 12, color: C.faint, padding: "14px 0" }}>
                  No legs yet. Pick a ready-made strategy below, or use the Option Chain page to build one.
                </div>
              ) : (
                <>
                  <div style={{ overflowX: "auto", marginTop: 10 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                      <thead>
                        <tr style={{ color: C.muted, fontSize: 10, textAlign: "left" }}>
                          <th style={{ padding: 4 }}>B/S</th>
                          <th style={{ padding: 4 }}>Strike</th>
                          <th style={{ padding: 4 }}>Type</th>
                          <th style={{ padding: 4 }}>Lots</th>
                          <th style={{ padding: 4 }}>Price</th>
                          <th style={{ padding: 4 }}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {legs.map((l) => (
                          <tr key={l.id} style={{ borderTop: `1px solid ${C.border}` }}>
                            <td style={{ padding: 4 }}>
                              <button
                                onClick={() => updateLeg(l.id, { action: l.action === "buy" ? "sell" : "buy" })}
                                style={{
                                  background: l.action === "buy" ? C.green : C.red,
                                  color: "#0B0E14",
                                  border: "none",
                                  borderRadius: 4,
                                  padding: "2px 7px",
                                  fontWeight: 700,
                                  cursor: "pointer",
                                  fontSize: 10.5,
                                }}
                              >
                                {l.action === "buy" ? "B" : "S"}
                              </button>
                            </td>
                            <td style={{ padding: 4 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
                                <StepButton onClick={() => changeLegStrike(l.id, -1)}>−</StepButton>
                                <span style={{ minWidth: 44, textAlign: "center" }}>{fmtIN(l.strike)}</span>
                                <StepButton onClick={() => changeLegStrike(l.id, 1)}>+</StepButton>
                              </div>
                            </td>
                            <td style={{ padding: 4 }}>
                              <button
                                onClick={() => updateLeg(l.id, { type: l.type === "call" ? "put" : "call" })}
                                style={{ background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "2px 7px", cursor: "pointer", fontSize: 10.5 }}
                              >
                                {l.type === "call" ? "CE" : "PE"}
                              </button>
                            </td>
                            <td style={{ padding: 4 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
                                <StepButton onClick={() => updateLeg(l.id, { qty: Math.max(1, l.qty - 1) })}>−</StepButton>
                                <span
                                  style={{ minWidth: 18, textAlign: "center" }}
                                  title={multiplier > 1 ? `${l.qty} base lots × ${multiplier} multiplier` : undefined}
                                >
                                  {l.qty * multiplier}
                                </span>
                                <StepButton onClick={() => updateLeg(l.id, { qty: l.qty + 1 })}>+</StepButton>
                              </div>
                            </td>
                            <td style={{ padding: 4 }}>
                              <input
                                type="number"
                                value={l.price}
                                onChange={(e) => updateLeg(l.id, { price: Number(e.target.value) || 0 })}
                                style={{ width: 56, background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "2px 4px", fontSize: 10.5 }}
                              />
                            </td>
                            <td style={{ padding: 4 }}>
                              <button onClick={() => removeLeg(l.id)} style={{ background: "none", border: "none", color: C.faint, cursor: "pointer", fontSize: 13 }}>
                                ×
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
                    <label style={{ fontSize: 11, color: C.muted, display: "flex", alignItems: "center", gap: 6 }}>
                      ×Multiplier
                      <input
                        type="number"
                        min={1}
                        value={multiplier}
                        onChange={(e) => setMultiplier(Math.max(1, Number(e.target.value) || 1))}
                        style={{ width: 46, background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "2px 4px", fontSize: 10.5 }}
                      />
                    </label>
                    <div style={{ fontSize: 11.5 }}>
                      <span style={{ color: C.faint }}>{netPerLot >= 0 ? "Pay" : "Receive"}: </span>
                      <span style={{ fontWeight: 600 }}>{Math.abs(netPerLot).toFixed(2)}</span>
                    </div>
                    <div style={{ fontSize: 11.5 }}>
                      <span style={{ color: C.faint }}>{netTotal >= 0 ? "Premium Pay" : "Premium Receive"}: </span>
                      <span style={{ fontWeight: 600 }}>₹{fmtIN(Math.abs(netTotal))}</span>
                    </div>
                  </div>

                  <button
                    onClick={executeTradeAll}
                    style={{ marginTop: 12, width: "100%", background: C.gold, color: "#0B0E14", border: "none", borderRadius: 8, padding: "10px 16px", fontWeight: 700, cursor: "pointer", fontSize: 12.5 }}
                  >
                    Trade All (Paper)
                  </button>
                </>
              )}
            </div>

            {/* Ready-made strategies */}
            <div style={panel}>
              <div style={{ fontSize: fluid(12, 14), fontWeight: 800, letterSpacing: 0.8, color: C.text, marginBottom: 10 }}>💎 READY-MADE STRATEGIES</div>
              <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
                {STRATEGY_CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setCategory(cat)}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 16,
                      fontSize: 11,
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
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
                {strategiesFor(category).map((s) => (
                  <button
                    key={s.id}
                    onClick={() => loadStrategy(s)}
                    style={{ display: "flex", alignItems: "center", gap: 10, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", cursor: "pointer", textAlign: "left", width: "100%", minWidth: 0 }}
                  >
                    <span style={{ width: 34, flexShrink: 0 }}>
                      <ShapeIcon shape={s.shape} />
                    </span>
                    <span style={{ fontSize: fluid(11, 12.5), color: C.text, lineHeight: 1.3 }}>{s.name}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Settings & resets */}
            <div style={panel}>
              <div style={{ fontSize: fluid(12, 14), fontWeight: 800, letterSpacing: 0.8, color: C.text, marginBottom: 10 }}>⚙️ SETTINGS & RESETS</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <button
                  onClick={resetPaperPortfolio}
                  style={{ fontSize: 11.5, color: C.red, background: "rgba(225,82,82,0.08)", border: "1px solid rgba(225,82,82,0.35)", borderRadius: 6, padding: "8px 10px", cursor: "pointer" }}
                >
                  Reset Paper Portfolio
                </button>
                <button
                  onClick={exportHistoryCsv}
                  style={{ fontSize: 11.5, color: C.gold, background: "none", border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 10px", cursor: "pointer" }}
                >
                  Export Trades CSV
                </button>
              </div>
            </div>
          </aside>

          {/* ================= ZONE B · ANALYTICS & MONITORING ================= */}
          <section style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
            {/* Stats strip */}
            <div style={panel}>
              <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(${isMobile ? 118 : 132}px, 1fr))`, gap: 14 }}>
                <Stat label="Starting capital" value={`₹${fmtIN(paperStartingCapital)}`} fs={fluid(14, 18)} />
                <Stat label="Cash" value={`₹${fmtIN(paperCash)}`} fs={fluid(14, 18)} />
                <Stat label="Equity (MTM)" value={`₹${fmtIN(equity)}`} color={C.gold} fs={fluid(14, 18)} />
                <Stat label="Unrealized P&L" value={`₹${fmtIN(totalUnrealized)}`} color={totalUnrealized >= 0 ? C.green : C.red} fs={fluid(14, 18)} />
                <Stat label="Realized P&L" value={`₹${fmtIN(totalRealized)}`} color={totalRealized >= 0 ? C.green : C.red} fs={fluid(14, 18)} />
                <Stat
                  label="Win rate"
                  value={journal?.stats.closed_trades ? `${(journal.stats.win_rate * 100).toFixed(1)}%` : "—"}
                  fs={fluid(14, 18)}
                />
                <Stat
                  label="Profit factor"
                  value={
                    journal
                      ? journal.stats.profit_factor != null
                        ? journal.stats.profit_factor.toFixed(2)
                        : journal.stats.closed_trades && journal.stats.gross_profit > 0
                          ? "∞"
                          : "—"
                      : "—"
                  }
                  fs={fluid(14, 18)}
                />
                <Stat label="Total P&L" value={`₹${fmtIN(totalPnl)}`} color={totalPnl >= 0 ? C.green : C.red} fs={fluid(14, 18)} />
              </div>
            </div>

            {/* Charts row: payoff (40%) + account growth equity curve (60%) */}
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "2fr 3fr", gap: 16, alignItems: "stretch" }}>
              {/* Payoff graph / P&L table / Greeks */}
              <div style={panel}>
                <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
                  {[
                    ["graph", "Payoff Graph"],
                    ["table", "P&L Table"],
                    ["greeks", "Greeks"],
                  ].map(([key, label]) => (
                    <button
                      key={key}
                      onClick={() => setPayoffTab(key)}
                      style={{
                        fontSize: 11,
                        padding: "5px 10px",
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
                  <div style={{ fontSize: 12, color: C.faint, padding: "28px 0", textAlign: "center" }}>
                    Add legs to see the payoff graph, table, and Greeks here.
                  </div>
                ) : payoffTab === "graph" ? (
                  <>
                    <div style={{ display: "flex", gap: 20, marginBottom: 10, flexWrap: "wrap" }}>
                      <Stat label="Max profit (shown range)" value={`₹${fmtIN(maxProfit)}`} color={C.green} />
                      <Stat label="Max loss (shown range)" value={`₹${fmtIN(maxLoss)}`} color={C.red} />
                    </div>
                    <div style={{ height: 280 }}>
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

                    <div style={{ marginTop: 12 }}>
                      <div style={{ fontSize: 11, color: C.muted, marginBottom: 6 }}>
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
                        <div style={{ fontSize: 12, marginTop: 6 }}>
                          Projected {targetPnl >= 0 ? "profit" : "loss"}:{" "}
                          <span style={{ color: targetPnl >= 0 ? C.green : C.red, fontWeight: 700 }}>₹{fmtIN(Math.abs(targetPnl))}</span>
                        </div>
                      )}
                    </div>

                    <div style={{ fontSize: 10, color: C.faint, marginTop: 10 }}>
                      Bars show live open interest (red = Call OI, green = Put OI) at each strike, at expiry payoff.
                    </div>
                  </>
                ) : payoffTab === "table" ? (
                  <div style={{ overflowY: "auto", maxHeight: 340 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                      <thead>
                        <tr style={{ color: C.muted, fontSize: 10 }}>
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
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5, marginBottom: 10 }}>
                      <thead>
                        <tr style={{ color: C.muted, fontSize: 10, textAlign: "left" }}>
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
                    <div style={{ fontSize: 10, color: C.faint }}>
                      Position-level Greeks = each leg's Greek × direction × lots × lot size × multiplier, summed.
                    </div>
                  </div>
                )}
              </div>

              {/* Account growth (equity curve) */}
              <div style={panel}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <div style={{ fontSize: fluid(12, 14), fontWeight: 800, letterSpacing: 0.8, color: C.text }}>📈 ACCOUNT GROWTH (EQUITY CURVE)</div>
                    {eqDelta != null && (
                      <span
                        style={{
                          fontSize: 10.5,
                          fontWeight: 700,
                          color: eqDelta >= 0 ? C.green : C.red,
                          background: eqDelta >= 0 ? "rgba(76,175,125,0.1)" : "rgba(225,82,82,0.1)",
                          border: `1px solid ${eqDelta >= 0 ? "rgba(76,175,125,0.35)" : "rgba(225,82,82,0.35)"}`,
                          borderRadius: 999,
                          padding: "2px 9px",
                        }}
                      >
                        {eqDelta >= 0 ? "▲" : "▼"} {fmtIN(Math.abs(eqDelta))} vs start
                      </span>
                    )}
                  </div>
                  {equityHistory.length > 1 && (
                    <div style={{ fontSize: 11, color: C.faint }}>
                      Last: <span style={{ color: eqColor, fontWeight: 700 }}>₹{fmtIN(eqLast)}</span>
                    </div>
                  )}
                </div>
                {equityHistory.length <= 1 ? (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 280, fontSize: 12, color: C.faint, textAlign: "center", padding: "0 20px" }}>
                    The equity curve builds while you trade during market hours (09:15–15:30 IST). Trade a few paper positions and it will draw here.
                  </div>
                ) : (
                  <div style={{ height: 280 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={equityHistory}>
                        <CartesianGrid stroke={C.border} strokeDasharray="3 3" />
                        <XAxis
                          dataKey="time"
                          stroke={C.faint}
                          fontSize={10.5}
                          tickFormatter={(t) => new Date(t).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                        />
                        <YAxis stroke={C.faint} fontSize={10.5} domain={["auto", "auto"]} tickFormatter={(v) => `₹${fmtIN(v)}`} width={80} />
                        <ReferenceLine y={paperStartingCapital} stroke={C.faint} strokeDasharray="4 2" />
                        <Tooltip
                          contentStyle={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11.5 }}
                          labelFormatter={(t) => new Date(t).toLocaleString("en-IN")}
                          formatter={(v) => [`₹${fmtIN(v)}`, "Equity"]}
                        />
                        <defs>
                          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={eqColor} stopOpacity={0.3} />
                            <stop offset="100%" stopColor={eqColor} stopOpacity={0.02} />
                          </linearGradient>
                        </defs>
                        <Area type="monotone" dataKey="equity" stroke="none" fill="url(#eqFill)" />
                        <Line type="monotone" dataKey="equity" stroke={eqColor} strokeWidth={2} dot={false} name="Equity" />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </div>

            {/* Real-time active positions & P&L */}
            <div style={panel}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <div style={{ fontSize: fluid(12, 14), fontWeight: 800, letterSpacing: 0.8, color: C.text }}>⚡ ACTIVE POSITIONS & LIVE P&L</div>
                  {positionsWithLtp.length > 0 && (
                    <span
                      style={{
                        fontSize: 10.5,
                        fontWeight: 700,
                        color: totalUnrealized >= 0 ? C.green : C.red,
                        background: totalUnrealized >= 0 ? "rgba(76,175,125,0.1)" : "rgba(225,82,82,0.1)",
                        border: `1px solid ${totalUnrealized >= 0 ? "rgba(76,175,125,0.35)" : "rgba(225,82,82,0.35)"}`,
                        borderRadius: 999,
                        padding: "2px 9px",
                      }}
                    >
                      {totalUnrealized >= 0 ? "+" : "−"}₹{fmtIN(Math.abs(totalUnrealized))} unrealized
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 10.5, color: C.faint }}>mark-to-market · simplified simulator (no margin/brokerage/taxes)</div>
              </div>
              {positionsWithLtp.length === 0 ? (
                <div style={{ fontSize: 12.5, color: C.faint, padding: "18px 0" }}>No open positions.</div>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                    <thead>
                      <tr style={{ color: C.muted, fontSize: 10.5 }}>
                        <th style={{ padding: 6, textAlign: "left" }}>Ticker</th>
                        <th style={{ padding: 6, textAlign: "left" }}>Strategy</th>
                        <th style={{ padding: 6 }}>Qty</th>
                        <th style={{ padding: 6 }}>Entry Price</th>
                        <th style={{ padding: 6 }}>Current LTP</th>
                        <th style={{ padding: 6 }}>Live P&L</th>
                        <th style={{ padding: 6 }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {positionsWithLtp.map((p) => (
                        <tr key={p.id} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: 6 }}>
                            <div>
                              <span style={{ color: p.action === "buy" ? C.green : C.red, fontWeight: 700 }}>{p.action.toUpperCase()}</span> {p.symbol} {fmtIN(p.strike)} {p.type === "call" ? "CE" : "PE"}
                            </div>
                            <div style={{ fontSize: 10, color: C.faint }}>{p.expiry}</div>
                          </td>
                          <td style={{ padding: 6, color: C.muted }}>{p.strategyName ?? "Custom"}</td>
                          <td style={{ padding: 6 }}>{p.qty}</td>
                          <td style={{ padding: 6 }}>{p.entryPremium}</td>
                          <td style={{ padding: 6 }}>{p.currentLtp ?? "-"}</td>
                          <td style={{ padding: 6, color: p.unrealizedPnl == null ? C.muted : p.unrealizedPnl >= 0 ? C.green : C.red }}>
                            {p.unrealizedPnl == null ? "-" : `${p.unrealizedPnl >= 0 ? "+" : ""}₹${fmtIN(p.unrealizedPnl)}`}
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
            </div>
          </section>
        </div>
      )}

      {/* ================= ZONE C · TRANSACTION LOG & HISTORICAL JOURNAL ================= */}
      <div style={{ marginTop: 16, ...panel, padding: 18 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div style={{ fontSize: fluid(13, 15), fontWeight: 800, letterSpacing: 0.5, color: C.text }}>📝 TRANSACTION LOG & HISTORICAL JOURNAL</div>
            {logRows.length > 0 && (
              <span
                style={{
                  fontSize: 10.5,
                  color: C.muted,
                  background: C.surface2,
                  border: `1px solid ${C.border}`,
                  borderRadius: 999,
                  padding: "2px 9px",
                }}
              >
                {logRows.length} records
              </span>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            {paperHistory.length > 0 && (
              <button
                onClick={exportHistoryCsv}
                style={{ fontSize: 11, color: C.gold, background: "none", border: `1px solid ${C.border}`, borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}
              >
                Export CSV
              </button>
            )}
            {logRows.length > JOURNAL_PAGE_SIZE && (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <button
                  onClick={() => setJournalPage((p) => Math.max(0, p - 1))}
                  disabled={logPage === 0}
                  style={{ fontSize: 11, color: C.text, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, padding: "4px 10px", cursor: logPage === 0 ? "default" : "pointer", opacity: logPage === 0 ? 0.4 : 1 }}
                >
                  ← Prev
                </button>
                <span style={{ fontSize: 11, color: C.muted }}>
                  Page {logPage + 1} / {logPageCount} · {logRows.length} rows
                </span>
                <button
                  onClick={() => setJournalPage((p) => Math.min(logPageCount - 1, p + 1))}
                  disabled={logPage >= logPageCount - 1}
                  style={{ fontSize: 11, color: C.text, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, padding: "4px 10px", cursor: logPage >= logPageCount - 1 ? "default" : "pointer", opacity: logPage >= logPageCount - 1 ? 0.4 : 1 }}
                >
                  Next →
                </button>
              </div>
            )}
          </div>
        </div>

        {perStrategy.length > 0 && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
            {perStrategy.map((s) => (
              <span
                key={s.strategyName}
                style={{ fontSize: 10.5, color: C.muted, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 999, padding: "3px 10px" }}
              >
                {s.strategyName} · {s.trades} closed · {(s.winRate * 100).toFixed(0)}% win ·{" "}
                <span style={{ color: s.totalPnl >= 0 ? C.green : C.red, fontWeight: 600 }}>₹{fmtIN(s.totalPnl)}</span>
              </span>
            ))}
          </div>
        )}

        {journal === null && !journalError ? (
          <div style={{ fontSize: 12.5, color: C.faint }}>Loading journal…</div>
        ) : (
          <>
            {journalError && (
              <div style={{ fontSize: 11.5, color: C.muted, marginBottom: 10, lineHeight: 1.6 }}>
                Journal sync is unavailable right now ({journalError}). Showing this browser's local history — local paper trading still
                works, and fills will log to the database once the backend is reachable.
              </div>
            )}
            {logRows.length === 0 ? (
              <div style={{ fontSize: 12.5, color: C.faint }}>
                {journalError
                  ? "No closed trades in this browser yet."
                  : "No journal entries yet — submit a paper order and it will be logged here automatically."}
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                  <thead>
                    <tr style={{ color: C.muted, fontSize: 10.5 }}>
                      <th style={{ padding: 6, textAlign: "left" }}>Status</th>
                      <th style={{ padding: 6, textAlign: "left" }}>Strategy Tag</th>
                      <th style={{ padding: 6, textAlign: "left" }}>Strike / Legs</th>
                      <th style={{ padding: 6 }}>Net Entry</th>
                      <th style={{ padding: 6 }}>Realized P&L</th>
                      <th style={{ padding: 6 }}>Opened</th>
                      <th style={{ padding: 6 }}>Closed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logPageRows.map((r, i) => {
                      if (r.local) {
                        const h = r;
                        return (
                          <tr key={`local-${h.entryTime}-${i}`} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                            <td style={{ padding: 6 }}>
                              <span style={badge("CLOSED", h.realizedPnl >= 0 ? C.green : C.red, "rgba(136,146,166,0.1)", "rgba(136,146,166,0.3)")}>CLOSED</span>
                            </td>
                            <td style={{ padding: 6 }}>
                              <div style={{ fontWeight: 700 }}>{h.strategyName ?? "Custom"}</div>
                              <div style={{ color: C.faint, fontSize: 11 }}>{h.symbol}</div>
                            </td>
                            <td style={{ padding: 6, color: C.muted }}>
                              {h.action.toUpperCase()} {fmtIN(h.strike)} {h.type === "call" ? "CE" : "PE"}×{h.qty}
                            </td>
                            <td style={{ padding: 6, color: C.muted }}>Entry {fmtIN(h.entryPremium)}</td>
                            <td style={{ padding: 6, color: h.realizedPnl >= 0 ? C.green : C.red }}>
                              {`${h.realizedPnl >= 0 ? "+" : ""}₹${fmtIN(h.realizedPnl)}`}
                            </td>
                            <td style={{ padding: 6, color: C.muted, fontSize: 11.5 }}>{fmtJournalDate(h.entryTime)}</td>
                            <td style={{ padding: 6, color: C.muted, fontSize: 11.5 }}>{fmtJournalDate(h.exitTime)}</td>
                          </tr>
                        );
                      }
                      const t = r;
                      const realized = t.realized_pnl;
                      const credit = t.entry_net < 0;
                      return (
                        <tr key={t.id} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: 6 }}>
                            {t.status === "open" ? (
                              <span style={badge("OPEN", C.gold, "rgba(201,161,90,0.12)", "rgba(201,161,90,0.35)")}>OPEN</span>
                            ) : (
                              <span style={badge("CLOSED", realized >= 0 ? C.green : C.red, "rgba(136,146,166,0.1)", "rgba(136,146,166,0.3)")}>CLOSED</span>
                            )}
                          </td>
                          <td style={{ padding: 6 }}>
                            <div style={{ fontWeight: 700 }}>{t.strategy_tag}</div>
                            <div style={{ color: C.faint, fontSize: 11 }}>{t.symbol}</div>
                          </td>
                          <td style={{ padding: 6, color: C.muted }}>
                            {t.legs
                              .map((l) => `${l.action === "sell" ? "S" : "B"} ${fmtIN(l.strike_price)} ${l.option_type === "call" ? "CE" : "PE"}×${l.quantity}`)
                              .join(" · ")}
                          </td>
                          <td style={{ padding: 6, color: credit ? C.green : C.muted }}>
                            {credit ? `Credit ${fmtIN(Math.abs(t.entry_net))}` : `Debit ${fmtIN(t.entry_net)}`}
                          </td>
                          <td style={{ padding: 6, color: realized == null ? C.muted : realized >= 0 ? C.green : C.red }}>
                            {realized == null ? "—" : `${realized >= 0 ? "+" : ""}₹${fmtIN(realized)}`}
                          </td>
                          <td style={{ padding: 6, color: C.muted, fontSize: 11.5 }}>{fmtJournalDate(t.entry_at)}</td>
                          <td style={{ padding: 6, color: C.muted, fontSize: 11.5 }}>{t.exit_at ? fmtJournalDate(t.exit_at) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
