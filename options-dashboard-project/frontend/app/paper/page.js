"use client";
import { useEffect, useState, useMemo, useCallback, useRef } from "react";
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
import { STRATEGIES, STRATEGY_CATEGORIES, strategiesFor } from "@/lib/strategies";
import { historyToCsv, strategyStats, recordEquityPoint, isWithinMarketHours, sanitizeEquityHistory } from "@/lib/paperUtils";
import { loadJSON, saveJSON } from "@/lib/storage";
import { C, TopNav, SymbolTabs, Centered, SessionExpired, Stat, StepButton, ShapeIcon, fmtIN, LOT_SIZES, useIsMobile } from "@/lib/ui";
import {
  ComposedChart, Bar, Line, Area, LineChart, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";

const PAPER_KEY = "options_dashboard_paper_v1";
const DEFAULT_STARTING_CAPITAL = 500000;
const JOURNAL_PAGE_SIZE = 10;
const DRAFTS_KEY = "options_dashboard_drafts_v1";
const SAVED_KEY = "options_dashboard_saved_v1";

const LEG_COLORS = [C.green, C.red, "#5B9BD5", "#B48AD9", "#E0A33A", "#5AC8C8", "#F283B4", "#7FBF7F"];

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

const fmtExpiry = (iso) => {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
};

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

  // ---- New UI state for the 40/60 strategy-lab layout ----
  const [shift, setShift] = useState(0);
  const [width, setWidth] = useState(0);
  const [hedge, setHedge] = useState(0);
  const [builderTab, setBuilderTab] = useState("ready");
  const [showAddLeg, setShowAddLeg] = useState(false);
  const [drafts, setDrafts] = useState([]);
  const [savedStrategies, setSavedStrategies] = useState([]);
  const [fundsOpen, setFundsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [spotChg, setSpotChg] = useState(null);
  const firstSpotRef = useRef(null);

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
    firstSpotRef.current = null;
    setSpotChg(null);
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

  // Draft portfolios + saved strategies (localStorage)
  useEffect(() => {
    setDrafts(loadJSON(DRAFTS_KEY, []));
    setSavedStrategies(loadJSON(SAVED_KEY, []));
  }, []);

  useEffect(() => {
    saveJSON(DRAFTS_KEY, drafts);
  }, [drafts]);

  useEffect(() => {
    saveJSON(SAVED_KEY, savedStrategies);
  }, [savedStrategies]);

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

  // Session change % for the header (vs the first spot seen for this symbol).
  useEffect(() => {
    if (spot == null) return;
    if (firstSpotRef.current == null) firstSpotRef.current = spot;
    else setSpotChg(((spot - firstSpotRef.current) / firstSpotRef.current) * 100);
  }, [spot]);

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

  // Strategy Chart data: one line per leg plus the combined position.
  const legPayoffData = useMemo(() => {
    if (strikesSorted.length === 0 || legs.length === 0) return [];
    return strikesSorted.map((strike) => {
      const point = { strike };
      let combined = 0;
      legs.forEach((l, i) => {
        const intrinsic = l.type === "call" ? Math.max(0, strike - l.strike) : Math.max(0, l.strike - strike);
        const dir = l.action === "buy" ? 1 : -1;
        const pnl = dir * (intrinsic - l.price) * l.qty * lotSize * multiplier;
        point[`leg${i}`] = Math.round(pnl);
        combined += pnl;
      });
      point.combined = Math.round(combined);
      return point;
    });
  }, [strikesSorted, legs, lotSize, multiplier]);

  const maxProfit = payoffData.length ? Math.max(...payoffData.map((p) => p.pnl)) : 0;
  const maxLoss = payoffData.length ? Math.min(...payoffData.map((p) => p.pnl)) : 0;

  // Detect truly unbounded wings by sampling far beyond the chain's shown range.
  const lowExtreme = spot != null && legs.length ? pnlAtPrice(spot * 0.25) : null;
  const highExtreme = spot != null && legs.length ? pnlAtPrice(spot * 4) : null;
  const maxProfitUnlimited =
    legs.length > 0 && ((lowExtreme != null && lowExtreme > maxProfit) || (highExtreme != null && highExtreme > maxProfit));
  const maxLossUnlimited =
    legs.length > 0 && ((lowExtreme != null && lowExtreme < maxLoss) || (highExtreme != null && highExtreme < maxLoss));

  const netPerLot = legs.reduce((sum, l) => {
    const dir = l.action === "buy" ? 1 : -1;
    return sum + dir * l.price * l.qty;
  }, 0);
  const netTotal = netPerLot * lotSize * multiplier;

  const roiPct = legs.length && netTotal !== 0 ? (maxProfit / Math.abs(netTotal)) * 100 : null;
  const rewardRisk = legs.length && maxLoss < 0 ? maxProfit / Math.abs(maxLoss) : null;

  // Underlying price(s) where the payoff crosses zero (linear interpolation
  // between neighbouring strikes).
  const breakevens = useMemo(() => {
    const out = [];
    for (let i = 0; i < payoffData.length - 1; i++) {
      const a = payoffData[i];
      const b = payoffData[i + 1];
      if ((a.pnl >= 0 && b.pnl <= 0) || (a.pnl <= 0 && b.pnl >= 0)) {
        const denom = a.pnl - b.pnl;
        const t = denom === 0 ? 0 : a.pnl / denom;
        out.push(Math.round(a.strike + t * (b.strike - a.strike)));
      }
    }
    return out;
  }, [payoffData]);

  const targetPrice = spot ? spot * (1 + targetPct / 100) : null;
  const targetPnl = targetPrice != null ? pnlAtPrice(targetPrice) : null;

  const daysToExpiry = expiry
    ? Math.max(0, Math.ceil((new Date(`${expiry}T00:00:00`) - new Date()) / 86400000))
    : null;
  const expiryFillPct = daysToExpiry != null ? Math.min(100, Math.max(0, ((30 - daysToExpiry) / 30) * 100)) : 0;

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
    setShift(0);
    setWidth(0);
    setHedge(0);
    setShowAddLeg(false);

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
    // Multi-expiry strategies (calendar / diagonal) need the other expiries'
    // chains too; build a strike->row map for every expiry fetched so far.
    const chainByStrikeForExpiry = {};
    expiries.forEach((exp) => {
      const ch = chainCache[exp];
      if (ch) chainByStrikeForExpiry[exp] = new Map(ch.chain.map((r) => [r.strike, r]));
    });
    const ctx = { strikes: strikesSorted, atmIndex, chainByStrike, expiry, expiries, chainByStrikeForExpiry };
    setLegs(strategyDef.build(ctx));
    setStrategyName(strategyDef.name);
    setShift(0);
    setWidth(0);
    setHedge(0);
    setShowAddLeg(false);
  };

  // ---- Strategy adjustment tools (Shift / Width / Hedge) ----
  const moveLegByStrikes = (l, steps) => {
    if (!steps || !l) return l;
    const legChain = chainCache[l.expiry];
    const strikes = legChain ? legChain.chain.map((r) => r.strike).sort((a, b) => a - b) : strikesSorted;
    if (strikes.length === 0) return l;
    const idx = strikes.indexOf(l.strike);
    if (idx === -1) return l;
    const newIdx = Math.min(Math.max(idx + steps, 0), strikes.length - 1);
    const newStrike = strikes[newIdx];
    const row = legChain?.chain.find((r) => r.strike === newStrike) ?? chainByStrike.get(newStrike);
    const price = row ? (l.type === "call" ? row.call.ltp : row.put.ltp) : l.price;
    return { ...l, strike: newStrike, price: price ?? l.price };
  };

  const resetAdjustments = () => {
    setShift(0);
    setWidth(0);
    setHedge(0);
  };

  const applyShift = (delta) => {
    setLegs((prev) => prev.map((l) => moveLegByStrikes(l, delta)));
    setShift((s) => s + delta);
    setStrategyName(null);
  };

  const applyWidth = (delta) => {
    setLegs((prev) =>
      prev.map((l) => {
        const legChain = chainCache[l.expiry];
        const strikes = legChain ? legChain.chain.map((r) => r.strike).sort((a, b) => a - b) : strikesSorted;
        const spotRef = legChain?.underlying_spot_price ?? spot;
        if (strikes.length === 0 || spotRef == null) return l;
        let atmIdx = 0;
        let bestDiff = Infinity;
        strikes.forEach((s, i) => {
          const d = Math.abs(s - spotRef);
          if (d < bestDiff) {
            bestDiff = d;
            atmIdx = i;
          }
        });
        const idx = strikes.indexOf(l.strike);
        if (idx === -1) return l;
        const off = idx - atmIdx;
        // Legs above ATM ride up, legs below ride down, ATM legs drift with
        // their side — widening pushes wings out, narrowing pulls them in.
        const dir = off === 0 ? (l.type === "call" ? 1 : -1) : Math.sign(off);
        return moveLegByStrikes(l, dir * delta);
      })
    );
    setWidth((w) => w + delta);
    setStrategyName(null);
  };

  const applyHedge = (delta) => {
    const nextHedge = Math.max(0, hedge + delta);
    if (nextHedge === hedge) return;
    if (delta > 0) {
      // Add a protective long OTM leg, alternating call/put sides and creeping
      // further OTM with each level (level 1 = long call +4, 2 = long put -4,
      // 3 = long call +5, 4 = long put -5, ...).
      const level = nextHedge;
      const side = level % 2 === 1 ? "call" : "put";
      const offset = 4 + Math.floor((level - 1) / 2);
      const sign = side === "call" ? 1 : -1;
      const strikeIdx = Math.min(Math.max(atmIndex + sign * offset, 0), strikesSorted.length - 1);
      const strike = strikesSorted[strikeIdx];
      if (strike == null) return;
      const row = chainByStrike.get(strike);
      const price = row ? (side === "call" ? row.call.ltp : row.put.ltp) : 0;
      const newLeg = {
        id: `hedge-${side}-${strike}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        type: side,
        strike,
        action: "buy",
        qty: 1,
        expiry,
        price: price ?? 0,
        hedge: true,
      };
      setLegs((prev) => [...prev, newLeg]);
    } else {
      setLegs((prev) => {
        const hedgeLegs = prev.filter((l) => l.hedge);
        if (hedgeLegs.length === 0) return prev;
        const last = hedgeLegs[hedgeLegs.length - 1];
        return prev.filter((l) => l.id !== last.id);
      });
    }
    setHedge(nextHedge);
    setStrategyName(null);
  };

  // ---- Draft portfolios & saved strategies ----
  const addCustomLeg = ({ action, type, strike, qty, price }) => {
    if (!strike || qty < 1) return;
    setLegs((prev) => [
      ...prev,
      { id: `${type}-${strike}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, type, strike, action, qty, expiry, price: Number(price) || 0 },
    ]);
    setStrategyName(null);
    setShowAddLeg(false);
  };

  const saveDraft = () => {
    if (legs.length === 0) return;
    const suggested = strategyName ?? `Draft ${drafts.length + 1}`;
    const name = window.prompt("Name this draft portfolio:", suggested);
    if (name === null) return;
    setDrafts((prev) => [
      { id: `draft-${Date.now()}`, name: name.trim() || suggested, symbol, expiry, legs: legs.map((l) => ({ ...l })), createdAt: new Date().toISOString() },
      ...prev,
    ]);
  };

  const deleteDraft = (id) => setDrafts((prev) => prev.filter((d) => d.id !== id));

  const loadDraft = (d) => {
    const sameSymbol = (d.symbol ?? "NIFTY") === symbol;
    setStrategyName(null);
    resetAdjustments();
    setShowAddLeg(false);
    if (sameSymbol) {
      setLegs(d.legs.map((l) => ({ ...l })));
      setExpiry(d.expiry ?? null);
      if (d.expiry && !chainCache[d.expiry]) loadChain(d.expiry);
    } else {
      // The symbol-change effect resets the builder; re-apply the draft's legs
      // after it has run.
      setSymbol(d.symbol ?? "NIFTY");
      setTimeout(() => {
        setLegs(d.legs.map((l) => ({ ...l })));
        setExpiry(d.expiry ?? null);
        if (d.expiry && !chainCache[d.expiry]) loadChain(d.expiry);
      }, 0);
    }
  };

  const toggleSaved = (id) =>
    setSavedStrategies((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const savedList = STRATEGIES.filter((s) => savedStrategies.includes(s.id));

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

  const panel = { background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14, minWidth: 0 };
  const popover = {
    position: "absolute",
    right: 0,
    top: "calc(100% + 8px)",
    zIndex: 60,
    background: "#0F131B",
    border: `1px solid ${C.border}`,
    borderRadius: 10,
    boxShadow: "0 18px 50px rgba(0,0,0,0.55)",
    padding: "12px 14px",
    minWidth: 280,
  };
  const headerBtn = {
    fontSize: 11.5,
    color: C.text,
    background: C.surface2,
    border: `1px solid ${C.border}`,
    borderRadius: 7,
    padding: "6px 12px",
    cursor: "pointer",
  };
  const tabBtn = (active) => ({
    fontSize: 10.5,
    padding: "5px 11px",
    borderRadius: 6,
    border: `1px solid ${active ? C.gold : "transparent"}`,
    background: active ? "rgba(201,161,90,0.1)" : "transparent",
    color: active ? C.gold : C.muted,
    cursor: "pointer",
    fontWeight: active ? 700 : 400,
  });
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

  const columnScroll = {
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: 14,
    height: isMobile ? "auto" : "100%",
    overflowY: isMobile ? "visible" : "auto",
    paddingRight: isMobile ? 0 : 4,
    paddingBottom: isMobile ? 0 : 2,
  };

  return (
    <div style={{ padding: isMobile ? 10 : 16 }}>
      <TopNav active="paper" />
      <style>{`
        .paper-row:hover { background: rgba(201,161,90,0.05); }
        .od-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
        .od-scroll::-webkit-scrollbar-thumb { background: #242B3A; border-radius: 4px; }
        .od-scroll::-webkit-scrollbar-track { background: transparent; }
      `}</style>

      {/* ---------- Terminal header bar ---------- */}
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
          padding: "10px 14px",
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: fluid(13, 15), fontWeight: 800, letterSpacing: 0.5 }}>
            📊 <span style={{ color: C.gold }}>{symbol}</span>
          </span>
          {spot != null && (
            <span style={{ fontSize: fluid(13, 16), fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmtIN(spot, 2)}</span>
          )}
          {spotChg != null && (
            <span style={{ fontSize: 11.5, fontWeight: 700, color: spotChg >= 0 ? C.green : C.red, fontVariantNumeric: "tabular-nums" }}>
              {spotChg >= 0 ? "▲" : "▼"} {Math.abs(spotChg).toFixed(2)}% <span style={{ color: C.faint, fontWeight: 400 }}>session</span>
            </span>
          )}
          <span style={badge("SIMULATED MODE", C.gold, "rgba(201,161,90,0.12)", "rgba(201,161,90,0.35)")}>SIMULATED</span>
        </div>

        <div style={{ fontSize: 11.5, color: C.muted, letterSpacing: 1.2, textAlign: "center" }}>
          PAPER TRADING PORTFOLIO <span style={{ color: C.gold }}>· SIMULATED MODE</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Funds & Margins */}
          <div style={{ position: "relative" }}>
            <button onClick={() => { setFundsOpen((v) => !v); setSettingsOpen(false); }} style={headerBtn}>
              💵 Funds &amp; Margins
            </button>
            {fundsOpen && (
              <div style={popover}>
                <div style={{ fontSize: 10, letterSpacing: 1, color: C.faint, marginBottom: 8 }}>FUNDS &amp; MARGINS (MTM)</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 14px" }}>
                  <Stat label="Starting capital" value={`₹${fmtIN(paperStartingCapital)}`} fs={12.5} />
                  <Stat label="Cash" value={`₹${fmtIN(paperCash)}`} fs={12.5} />
                  <Stat label="Equity (MTM)" value={`₹${fmtIN(equity)}`} fs={12.5} color={C.gold} />
                  <Stat label="Total P&L" value={`₹${fmtIN(totalPnl)}`} fs={12.5} color={totalPnl >= 0 ? C.green : C.red} />
                  <Stat label="Unrealized" value={`₹${fmtIN(totalUnrealized)}`} fs={12.5} color={totalUnrealized >= 0 ? C.green : C.red} />
                  <Stat label="Realized" value={`₹${fmtIN(totalRealized)}`} fs={12.5} color={totalRealized >= 0 ? C.green : C.red} />
                  <Stat label="Win rate" value={journal?.stats.closed_trades ? `${(journal.stats.win_rate * 100).toFixed(1)}%` : "—"} fs={12.5} />
                  <Stat
                    label="Profit factor"
                    value={journal?.stats.profit_factor != null ? journal.stats.profit_factor.toFixed(2) : "—"}
                    fs={12.5}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Settings */}
          <div style={{ position: "relative" }}>
            <button onClick={() => { setSettingsOpen((v) => !v); setFundsOpen(false); }} style={headerBtn}>
              ⚙️ Settings
            </button>
            {settingsOpen && (
              <div style={popover}>
                <div style={{ fontSize: 10, letterSpacing: 1, color: C.faint, marginBottom: 8 }}>SETTINGS &amp; RESETS</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
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
            )}
          </div>

          <span style={{ fontSize: fluid(12, 14) }}>
            <span style={{ color: C.faint }}>💵 </span>
            <span style={{ color: C.gold, fontWeight: 700 }}>₹{fmtIN(equity, 2)}</span>
          </span>
        </div>
      </div>

      {!primaryChain ? (
        <Centered>Loading chain…</Centered>
      ) : (
        /* ============ OUTER 40 / 60 SPLIT (independent column scroll) ============ */
        <div
          className="od-scroll"
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : "4fr 6fr",
            gap: 14,
            alignItems: "stretch",
            height: isMobile ? "auto" : "calc(100vh - 178px)",
            minHeight: isMobile ? 0 : 520,
          }}
        >
          {/* ================= ZONE A · CONTROL SIDEBAR (40%) ================= */}
          <aside style={columnScroll}>
            {/* ---------- New Strategy builder ---------- */}
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
                      fontSize: 14,
                      fontWeight: 800,
                      lineHeight: 1,
                      flexShrink: 0,
                    }}
                  >
                    🛠️
                  </span>
                  <div>
                    <div style={{ fontSize: fluid(12, 14), fontWeight: 800, letterSpacing: 0.8, color: C.text }}>NEW STRATEGY BUILDER</div>
                    <div style={{ fontSize: 10, color: C.faint, letterSpacing: 0.4 }}>build legs from the live chain</div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <button onClick={resetLegPrices} style={{ fontSize: 11, color: C.gold, background: "none", border: "none", cursor: "pointer" }}>
                    ↻ Reset Prices
                  </button>
                  <button onClick={() => { setLegs([]); resetAdjustments(); setShowAddLeg(false); }} style={{ fontSize: 11, color: C.muted, background: "none", border: "none", cursor: "pointer" }}>
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

              {/* Legs table */}
              <div style={{ overflowX: "auto", marginTop: 10 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr style={{ color: C.muted, fontSize: 9.5, textAlign: "left" }}>
                      <th style={{ padding: 4 }}>B/S</th>
                      <th style={{ padding: 4 }}>Expiry</th>
                      <th style={{ padding: 4 }}>Strike</th>
                      <th style={{ padding: 4 }}>Type</th>
                      <th style={{ padding: 4 }}>Lots</th>
                      <th style={{ padding: 4 }}>Price</th>
                      <th style={{ padding: 4 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {legs.length === 0 ? (
                      <tr>
                        <td colSpan={7} style={{ padding: "14px 4px", color: C.faint, fontSize: 11, lineHeight: 1.5 }}>
                          No legs yet — pick a ready-made strategy below or hit <b>Add / Edit</b> to build one manually.
                        </td>
                      </tr>
                    ) : (
                      legs.map((l) => (
                        <tr key={l.id} style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: 4 }}>
                            <button
                              onClick={() => updateLeg(l.id, { action: l.action === "buy" ? "sell" : "buy" })}
                              title="Toggle buy / sell"
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
                            <select
                              value={l.expiry ?? ""}
                              onChange={(e) => changeLegExpiry(l.id, e.target.value)}
                              style={{ background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "2px 2px", fontSize: 10, width: 74, maxWidth: 74 }}
                            >
                              {expiries.map((exp) => (
                                <option key={exp} value={exp}>
                                  {fmtExpiry(exp)}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td style={{ padding: 4 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
                              <StepButton onClick={() => changeLegStrike(l.id, -1)}>−</StepButton>
                              <span style={{ minWidth: 44, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>{fmtIN(l.strike)}</span>
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
                              style={{ width: 54, background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "2px 4px", fontSize: 10.5 }}
                            />
                          </td>
                          <td style={{ padding: 4 }}>
                            <button
                              onClick={() => removeLeg(l.id)}
                              title="Remove leg"
                              style={{ background: "none", border: "none", color: C.faint, cursor: "pointer", fontSize: 12 }}
                            >
                              🗑️
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {legs.length > 0 && (
                <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
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
              )}

              {/* Strategy adjustment steppers */}
              <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                <StepperRow label="Shift" value={shift} onDec={() => applyShift(-1)} onInc={() => applyShift(1)} title="Move every leg one strike up or down" />
                <StepperRow label="Width" value={width} onDec={() => applyWidth(-1)} onInc={() => applyWidth(1)} title="Push wings away from / pull toward the ATM strike" />
                <StepperRow label="Hedge" value={hedge} onDec={() => applyHedge(-1)} onInc={() => applyHedge(1)} title="Add / remove a protective long OTM leg" />
              </div>

              {/* Action row */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1.35fr", gap: 8, marginTop: 12 }}>
                <button
                  onClick={() => setShowAddLeg((v) => !v)}
                  style={{
                    fontSize: 11.5,
                    fontWeight: 700,
                    color: showAddLeg ? C.gold : C.text,
                    background: showAddLeg ? "rgba(201,161,90,0.1)" : C.surface2,
                    border: `1px solid ${showAddLeg ? C.gold : C.border}`,
                    borderRadius: 8,
                    padding: "8px 6px",
                    cursor: "pointer",
                  }}
                >
                  {showAddLeg ? "Close" : "Add / Edit"}
                </button>
                <button
                  onClick={saveDraft}
                  title="Save the current legs as a draft portfolio"
                  style={{ fontSize: 11.5, fontWeight: 700, color: C.text, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 6px", cursor: "pointer" }}
                >
                  Add to Drafts
                </button>
                <button
                  onClick={executeTradeAll}
                  style={{ fontSize: 11.5, fontWeight: 800, color: "#0B0E14", background: C.gold, border: "none", borderRadius: 8, padding: "8px 6px", cursor: "pointer" }}
                >
                  Trade All
                </button>
              </div>

              {showAddLeg && (
                <AddLegForm onAdd={addCustomLeg} chainByStrike={chainByStrike} strikesSorted={strikesSorted} atmIndex={atmIndex} />
              )}
            </div>

            {/* ---------- Lower navigation: ready-made / positions / saved / drafts ---------- */}
            <div style={panel}>
              <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap", borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                {[
                  ["ready", "Ready-made"],
                  ["positions", "Positions"],
                  ["saved", "Saved Strategies"],
                  ["drafts", "Draft Portfolios"],
                ].map(([key, label]) => (
                  <button key={key} onClick={() => setBuilderTab(key)} style={tabBtn(builderTab === key)}>
                    {label}
                  </button>
                ))}
              </div>

              {/* Ready-made strategies with category filter + thumbnails */}
              {builderTab === "ready" && (
                <>
                  <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
                    {STRATEGY_CATEGORIES.map((cat) => (
                      <button
                        key={cat}
                        onClick={() => setCategory(cat)}
                        style={{
                          padding: "4px 12px",
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
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(132px, 1fr))", gap: 8 }}>
                    {strategiesFor(category).map((s) => (
                      <button
                        key={s.id}
                        onClick={() => loadStrategy(s)}
                        style={{
                          position: "relative",
                          display: "flex",
                          flexDirection: "column",
                          gap: 6,
                          background: C.surface2,
                          border: `1px solid ${C.border}`,
                          borderRadius: 8,
                          padding: "10px 10px 8px",
                          cursor: "pointer",
                          textAlign: "left",
                        }}
                      >
                        <div style={{ width: "100%", flexShrink: 0 }}>
                          <ShapeIcon shape={s.shape} />
                        </div>
                        <span style={{ fontSize: 11.5, fontWeight: 700, color: C.text, lineHeight: 1.25 }}>{s.name}</span>
                        <span
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleSaved(s.id);
                          }}
                          title={savedStrategies.includes(s.id) ? "Remove from saved" : "Save strategy"}
                          style={{ position: "absolute", top: 6, right: 8, fontSize: 13, color: savedStrategies.includes(s.id) ? C.gold : C.faint, cursor: "pointer" }}
                        >
                          {savedStrategies.includes(s.id) ? "★" : "☆"}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}

              {/* Open positions quick view */}
              {builderTab === "positions" &&
                (positionsWithLtp.length === 0 ? (
                  <div style={{ fontSize: 11.5, color: C.faint, padding: "8px 0" }}>No open positions. Trade a strategy to see it here.</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {positionsWithLtp.map((p) => (
                      <div key={p.id} style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: 11.5, fontWeight: 700 }}>
                              <span style={{ color: p.action === "buy" ? C.green : C.red }}>{p.action.toUpperCase()}</span> {p.symbol}{" "}
                              {fmtIN(p.strike)} {p.type === "call" ? "CE" : "PE"}×{p.qty}
                            </div>
                            <div style={{ fontSize: 10, color: C.faint }}>{p.strategyName ?? "Custom"} · {p.expiry}</div>
                          </div>
                          <div style={{ textAlign: "right", flexShrink: 0 }}>
                            <div style={{ fontSize: 11.5, fontWeight: 700, color: p.unrealizedPnl == null ? C.muted : p.unrealizedPnl >= 0 ? C.green : C.red }}>
                              {p.unrealizedPnl == null ? "—" : `${p.unrealizedPnl >= 0 ? "+" : ""}₹${fmtIN(p.unrealizedPnl)}`}
                            </div>
                            <button
                              onClick={() => closePosition(p.id)}
                              style={{ fontSize: 10, color: C.text, background: "none", border: `1px solid ${C.border}`, borderRadius: 5, padding: "2px 8px", cursor: "pointer", marginTop: 2 }}
                            >
                              Close
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}

              {/* Bookmarked ready-made strategies */}
              {builderTab === "saved" &&
                (savedList.length === 0 ? (
                  <div style={{ fontSize: 11.5, color: C.faint, padding: "8px 0", lineHeight: 1.5 }}>
                    Nothing saved yet. Tap the ☆ on any ready-made strategy card to bookmark it here.
                  </div>
                ) : (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(132px, 1fr))", gap: 8 }}>
                    {savedList.map((s) => (
                      <button
                        key={s.id}
                        onClick={() => {
                          loadStrategy(s);
                          setBuilderTab("ready");
                        }}
                        style={{
                          position: "relative",
                          display: "flex",
                          flexDirection: "column",
                          gap: 6,
                          background: C.surface2,
                          border: `1px solid ${C.border}`,
                          borderRadius: 8,
                          padding: "10px 10px 8px",
                          cursor: "pointer",
                          textAlign: "left",
                        }}
                      >
                        <div style={{ width: "100%", flexShrink: 0 }}>
                          <ShapeIcon shape={s.shape} />
                        </div>
                        <span style={{ fontSize: 11.5, fontWeight: 700, color: C.text, lineHeight: 1.25 }}>{s.name}</span>
                        <span
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleSaved(s.id);
                          }}
                          title="Remove from saved"
                          style={{ position: "absolute", top: 6, right: 8, fontSize: 13, color: C.gold, cursor: "pointer" }}
                        >
                          ★
                        </span>
                      </button>
                    ))}
                  </div>
                ))}

              {/* Draft portfolios */}
              {builderTab === "drafts" &&
                (drafts.length === 0 ? (
                  <div style={{ fontSize: 11.5, color: C.faint, padding: "8px 0", lineHeight: 1.5 }}>
                    No drafts yet. Build a strategy and press <b>Add to Drafts</b> to park it here for later.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {drafts.map((d) => (
                      <div key={d.id} style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: 11.5, fontWeight: 700 }}>{d.name}</div>
                            <div style={{ fontSize: 10, color: C.faint }}>
                              {d.symbol} · {d.expiry} · {d.legs.length} leg{d.legs.length === 1 ? "" : "s"}
                            </div>
                          </div>
                          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                            <button
                              onClick={() => loadDraft(d)}
                              style={{ fontSize: 10.5, color: C.gold, background: "none", border: `1px solid ${C.border}`, borderRadius: 5, padding: "3px 9px", cursor: "pointer" }}
                            >
                              Load
                            </button>
                            <button
                              onClick={() => deleteDraft(d.id)}
                              title="Delete draft"
                              style={{ fontSize: 11, color: C.red, background: "none", border: `1px solid ${C.border}`, borderRadius: 5, padding: "3px 8px", cursor: "pointer" }}
                            >
                              🗑️
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
            </div>
          </aside>

          {/* ================= ZONE B · MAIN PERFORMANCE WORKSPACE (60%) ================= */}
          <section style={columnScroll}>
            {/* Header row: risk / reward summary blocks */}
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(4, 1fr)", gap: 10 }}>
              <SummaryBlock
                label="Max Profit"
                value={!legs.length ? "—" : maxProfitUnlimited ? "Unlimited" : `+₹${fmtIN(maxProfit)}`}
                sub={roiPct != null ? `+${roiPct.toFixed(1)}% on premium` : "shown range"}
                color={C.green}
              />
              <SummaryBlock
                label="Max Loss"
                value={!legs.length ? "—" : maxLossUnlimited ? "Unlimited" : `−₹${fmtIN(Math.abs(maxLoss))}`}
                sub={netTotal < 0 ? "credit received" : netTotal > 0 ? "debit paid" : "shown range"}
                color={C.red}
              />
              <SummaryBlock
                label="Breakeven"
                value={!legs.length ? "—" : breakevens.length ? breakevens.map((b) => fmtIN(b)).join(" · ") : "—"}
                sub="P&L = 0 at expiry"
                color={C.gold}
              />
              <SummaryBlock
                label="Reward / Risk"
                value={!legs.length ? "—" : rewardRisk != null ? rewardRisk.toFixed(2) : "—"}
                sub="max profit ÷ max loss"
                color={rewardRisk != null && rewardRisk >= 1 ? C.green : C.text}
              />
            </div>

            {/* Feature navigation + interactive workspace */}
            <div style={panel}>
              <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap", borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                {[
                  ["graph", "Payoff Graph"],
                  ["table", "P&L Table"],
                  ["greeks", "Greeks"],
                  ["strategyChart", "Strategy Chart"],
                ].map(([key, label]) => (
                  <button key={key} onClick={() => setPayoffTab(key)} style={tabBtn(payoffTab === key)}>
                    {label}
                  </button>
                ))}
              </div>

              {legs.length === 0 ? (
                <div style={{ fontSize: 12, color: C.faint, padding: "40px 0", textAlign: "center" }}>
                  Add legs to see the payoff graph, P&amp;L table, Greeks and strategy chart here.
                </div>
              ) : payoffTab === "graph" ? (
                <>
                  <div style={{ height: isMobile ? 260 : 360 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={payoffData}>
                        <CartesianGrid stroke={C.border} strokeDasharray="3 3" />
                        <XAxis dataKey="strike" stroke={C.faint} fontSize={10.5} tickFormatter={(v) => fmtIN(v)} />
                        <YAxis yAxisId="pnl" stroke={C.faint} fontSize={10.5} tickFormatter={(v) => `₹${fmtIN(v)}`} />
                        <YAxis yAxisId="oi" orientation="right" stroke={C.faint} fontSize={10.5} tickFormatter={(v) => fmtIN(v)} />
                        <ReferenceLine yAxisId="pnl" y={0} stroke={C.faint} />
                        {spot != null && (
                          <ReferenceLine yAxisId="pnl" x={strikesSorted.reduce((a, b) => (Math.abs(b - spot) < Math.abs(a - spot) ? b : a))} stroke={C.gold} strokeDasharray="4 2" />
                        )}
                        <Tooltip contentStyle={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11.5 }} />
                        <Bar yAxisId="oi" dataKey="callOI" fill="rgba(225,82,82,0.5)" name="Call OI" />
                        <Bar yAxisId="oi" dataKey="putOI" fill="rgba(76,175,125,0.5)" name="Put OI" />
                        <Line yAxisId="pnl" type="monotone" dataKey="pnl" stroke={C.gold} strokeWidth={2} dot={false} name="P&L" />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Bottom controls: target slider + date-to-expiry timeline */}
                  <div style={{ marginTop: 12, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 6 }}>
                      <span style={{ fontSize: 11.5, color: C.muted }}>
                        <span style={{ color: C.text, fontWeight: 700 }}>{symbol}</span> Target:{" "}
                        <span style={{ color: C.gold, fontWeight: 700 }}>{targetPrice != null ? fmtIN(targetPrice, 2) : "—"}</span>
                        <span style={{ color: targetPct >= 0 ? C.green : C.red, fontWeight: 700 }}>
                          {" "}({targetPct >= 0 ? "+" : ""}
                          {targetPct}%)
                        </span>
                      </span>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <StepButton onClick={() => setTargetPct((v) => Math.max(-15, +(v - 0.5).toFixed(1)))}>−</StepButton>
                        <span style={{ fontSize: 10.5, color: C.muted }}>0.5%</span>
                        <StepButton onClick={() => setTargetPct((v) => Math.min(15, +(v + 0.5).toFixed(1)))}>+</StepButton>
                      </div>
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
                    {daysToExpiry != null && (
                      <div style={{ marginTop: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                          <span style={{ fontSize: 11, color: C.muted }}>
                            Date to expiry: <span style={{ color: C.gold, fontWeight: 700 }}>{fmtExpiry(expiry)}</span>
                          </span>
                          <span style={{ fontSize: 11, fontWeight: 700, color: daysToExpiry <= 3 ? C.red : C.muted }}>
                            {daysToExpiry === 0 ? "EXPIRY DAY" : `D-${daysToExpiry}`}
                          </span>
                        </div>
                        <div style={{ position: "relative", height: 6, borderRadius: 3, background: "#0B0E14", overflow: "hidden" }}>
                          <div
                            style={{
                              position: "absolute",
                              top: 0,
                              bottom: 0,
                              left: 0,
                              width: `${expiryFillPct}%`,
                              background: "linear-gradient(90deg, rgba(201,161,90,0.45), #C9A15A)",
                              borderRadius: 3,
                            }}
                          />
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 9.5, color: C.faint }}>
                          <span>NOW</span>
                          <span>payoff shown at expiry</span>
                        </div>
                      </div>
                    )}
                  </div>

                  <div style={{ fontSize: 10, color: C.faint, marginTop: 8 }}>
                    Bars show live open interest (red = Call OI, green = Put OI) at each strike, at expiry payoff.
                  </div>
                </>
              ) : payoffTab === "table" ? (
                <div style={{ overflowY: "auto", maxHeight: 420 }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                    <thead>
                      <tr style={{ color: C.muted, fontSize: 10 }}>
                        <th style={{ padding: 6, textAlign: "left" }}>Underlying at expiry</th>
                        <th style={{ padding: 6 }}>P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {payoffData.map((d) => (
                        <tr key={d.strike} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: 6 }}>{fmtIN(d.strike)}</td>
                          <td style={{ padding: 6, color: d.pnl >= 0 ? C.green : C.red }}>₹{fmtIN(d.pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : payoffTab === "greeks" ? (
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
                        <tr key={r.leg.id} className="paper-row" style={{ borderTop: `1px solid ${C.border}` }}>
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
              ) : (
                /* Strategy Chart: one payoff line per leg + combined */
                <div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 10 }}>
                    <div style={{ fontSize: 12, color: C.text, fontWeight: 700 }}>Leg-by-leg payoff at expiry</div>
                    <div style={{ fontSize: 10.5, color: C.muted }}>Each line is one leg's P&amp;L vs the underlying; the gold line is the combined position.</div>
                  </div>
                  <div style={{ height: isMobile ? 260 : 340 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={legPayoffData}>
                        <CartesianGrid stroke={C.border} strokeDasharray="3 3" />
                        <XAxis dataKey="strike" stroke={C.faint} fontSize={10.5} tickFormatter={(v) => fmtIN(v)} />
                        <YAxis stroke={C.faint} fontSize={10.5} tickFormatter={(v) => `₹${fmtIN(v)}`} />
                        <ReferenceLine y={0} stroke={C.faint} />
                        <Tooltip contentStyle={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 11.5 }} />
                        {legs.map((l, i) => (
                          <Line
                            key={l.id}
                            type="monotone"
                            dataKey={`leg${i}`}
                            stroke={LEG_COLORS[i % LEG_COLORS.length]}
                            strokeWidth={1.5}
                            dot={false}
                            name={`${l.action.toUpperCase()} ${fmtIN(l.strike)} ${l.type === "call" ? "CE" : "PE"}`}
                          />
                        ))}
                        <Line type="monotone" dataKey="combined" stroke={C.gold} strokeWidth={2.5} dot={false} name="Combined" />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
                    {legs.map((l, i) => (
                      <span key={l.id} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, color: C.muted }}>
                        <span style={{ width: 10, height: 3, borderRadius: 2, background: LEG_COLORS[i % LEG_COLORS.length] }} />
                        {l.action.toUpperCase()} {fmtIN(l.strike)} {l.type === "call" ? "CE" : "PE"}×{l.qty * multiplier}
                      </span>
                    ))}
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, color: C.muted }}>
                      <span style={{ width: 10, height: 3, borderRadius: 2, background: C.gold }} />
                      Combined
                    </span>
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
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 220, fontSize: 12, color: C.faint, textAlign: "center", padding: "0 20px" }}>
                  The equity curve builds while you trade during market hours (09:15–15:30 IST). Trade a few paper positions and it will draw here.
                </div>
              ) : (
                <div style={{ height: 220 }}>
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
      <div style={{ marginTop: 14, ...panel, padding: 18 }}>
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

/* ---------- Small presentational helpers ---------- */

function SummaryBlock({ label, value, sub, color }) {
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", minWidth: 0 }}>
      <div style={{ fontSize: 9.5, letterSpacing: 1, color: C.faint }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: fluid(13, 16), fontWeight: 800, color: color || C.text, marginTop: 2, whiteSpace: "nowrap" }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

function StepperRow({ label, value, onDec, onInc, title }) {
  return (
    <div
      title={title}
      style={{ display: "flex", alignItems: "center", gap: 6, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "6px 10px", flex: 1, minWidth: 0 }}
    >
      <span style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.5, color: C.muted, marginRight: "auto" }}>{label}</span>
      <StepButton onClick={onDec}>−</StepButton>
      <span style={{ minWidth: 22, textAlign: "center", fontSize: 12.5, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{value}</span>
      <StepButton onClick={onInc}>+</StepButton>
    </div>
  );
}

function AddLegForm({ onAdd, chainByStrike, strikesSorted, atmIndex }) {
  const [action, setAction] = useState("buy");
  const [type, setType] = useState("call");
  const [strike, setStrike] = useState("");
  const [qty, setQty] = useState(1);
  const [price, setPrice] = useState("");

  // Auto-fill the live premium whenever strike or type changes (manual edits
  // survive until one of those changes).
  useEffect(() => {
    if (!strike) return;
    const row = chainByStrike.get(Number(strike));
    const live = row ? (type === "call" ? row.call.ltp : row.put.ltp) : null;
    if (live != null) setPrice(String(live));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strike, type]);

  const atmStrike = strikesSorted[Math.min(Math.max(atmIndex, 0), strikesSorted.length - 1)] ?? "";

  const submit = () => {
    const s = Number(strike);
    if (!s) return;
    onAdd({ action, type, strike: s, qty: Math.max(1, Number(qty) || 1), price: Number(price) || 0 });
  };

  const field = { background: C.surface2, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: "4px 6px", fontSize: 11, width: 58 };
  const toggle = (active) => ({
    fontSize: 10.5,
    fontWeight: 700,
    padding: "4px 8px",
    borderRadius: 4,
    border: `1px solid ${active ? C.gold : C.border}`,
    background: active ? "rgba(201,161,90,0.1)" : "transparent",
    color: active ? C.gold : C.muted,
    cursor: "pointer",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12, background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: 10 }}>
      <div style={{ fontSize: 10, letterSpacing: 1, color: C.faint }}>ADD LEG MANUALLY</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button onClick={() => setAction(action === "buy" ? "sell" : "buy")} style={toggle(true)}>
          {action === "buy" ? "BUY" : "SELL"}
        </button>
        <button onClick={() => setType(type === "call" ? "put" : "call")} style={toggle(true)}>
          {type === "call" ? "CE" : "PE"}
        </button>
        <input type="number" value={strike} onChange={(e) => setStrike(e.target.value)} placeholder={atmStrike ? String(atmStrike) : "strike"} style={{ ...field, width: 84 }} />
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10.5, color: C.muted }}>
          Qty
          <input type="number" min={1} value={qty} onChange={(e) => setQty(Number(e.target.value))} style={{ ...field, width: 46 }} />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10.5, color: C.muted }}>
          Price
          <input type="number" step="0.05" value={price} onChange={(e) => setPrice(e.target.value)} style={{ ...field, width: 64 }} />
        </label>
        <button onClick={submit} style={{ fontSize: 11, fontWeight: 700, color: "#0B0E14", background: C.gold, border: "none", borderRadius: 6, padding: "6px 12px", cursor: "pointer" }}>
          Add Leg
        </button>
      </div>
    </div>
  );
}
