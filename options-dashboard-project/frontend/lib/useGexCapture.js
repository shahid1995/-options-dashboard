/**
 * GEX Phase 7.6 — Live Snapshot Capture Hook
 *
 * Connects useChainFeed → captureGexSnapshot → GexRingBuffer → persistence.
 *
 * Flow:
 *   1. Chain data arrives from useChainFeed (3–5s intervals)
 *   2. When capture interval elapsed: create snapshot via captureGexSnapshot
 *   3. Validate snapshot via validateGexSnapshot
 *   4. Push to ring buffer
 *   5. Optionally persist to backend
 *   6. Expose analytics via computeGexAnalytics
 *
 * No trading signals. No BUY/SELL logic.
 * Snapshot capture is opt-in: returns null buffer if not enabled.
 */

"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { captureGexSnapshot, GexRingBuffer, validateGexSnapshot, DEFAULT_MAX_SNAPSHOTS, DEFAULT_SNAPSHOT_INTERVAL_MS } from "./calculations/gexHistory";
import { computeGexAnalytics } from "./calculations/gexAnalytics";
import { spotSweep, findGammaWalls } from "./calculations/gexPhase72";
import { reconstructChainRows } from "./calculations/gexHistory";
import { loadSnapshots, saveSnapshot } from "./gexPersistence";

/**
 * Hook for capturing GEX snapshots from the live chain feed.
 *
 * @param {object|null} chain — chain data from useChainFeed
 * @param {object} options
 * @param {string} [options.symbol] — underlying symbol (default: chain.symbol)
 * @param {string} [options.valuationDate] — ISO YYYY-MM-DD for DTE (default: today)
 * @param {boolean} [options.persistToBackend=true] — whether to persist snapshots
 * @param {boolean} [options.loadHistory=true] — whether to load historical snapshots on mount
 * @param {number} [options.bufferSize] — ring buffer max size
 * @param {number} [options.captureIntervalMs] — capture interval
 * @param {boolean} [options.enableSweep=false] — run Phase 7.2 spot sweep at capture time
 * @returns {{ buffer: GexRingBuffer|null, analytics: object|null, captureCount: number, latestSnapshot: object|null }}
 */
export function useGexCapture(chain, options = {}) {
  const {
    symbol = null,
    valuationDate = null,
    persistToBackend = true,
    loadHistory = true,
    bufferSize = DEFAULT_MAX_SNAPSHOTS,
    captureIntervalMs = DEFAULT_SNAPSHOT_INTERVAL_MS,
    enableSweep = false,
  } = options;

  const bufferRef = useRef(null);
  const [analytics, setAnalytics] = useState(null);
  const [captureCount, setCaptureCount] = useState(0);
  const [latestSnapshot, setLatestSnapshot] = useState(null);
  const [loaded, setLoaded] = useState(false);

  // Initialize ring buffer
  useEffect(() => {
    bufferRef.current = new GexRingBuffer(bufferSize, captureIntervalMs);
  }, [bufferSize, captureIntervalMs]);

  // Load historical snapshots on mount
  useEffect(() => {
    if (!loadHistory || !symbol || loaded) return;

    let cancelled = false;
    (async () => {
      try {
        const snapshots = await loadSnapshots(symbol, { limit: bufferSize });
        if (!cancelled && snapshots.length > 0 && bufferRef.current) {
          bufferRef.current.load(snapshots);
          setCaptureCount(bufferRef.current.size());
          // Compute analytics from loaded history
          const result = computeGexAnalytics(bufferRef.current, { valuationDate });
          setAnalytics(result);
        }
      } catch {
        // Backend unavailable — start fresh
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();

    return () => { cancelled = true; };
  }, [symbol, loadHistory, bufferSize, valuationDate, loaded]);

  // Capture snapshots from chain data
  useEffect(() => {
    if (!chain || !bufferRef.current) return;

    const buf = bufferRef.current;
    if (!buf.shouldCapture()) return;

    const spot = chain.underlying_spot_price;
    if (!spot || !Number.isFinite(spot) || spot <= 0) return;

    const effectiveSymbol = symbol ?? chain.symbol ?? "NIFTY";
    const now = new Date();

    // Create snapshot
    const snapshot = captureGexSnapshot(chain, spot, now, {
      symbol: effectiveSymbol,
      valuationDate: valuationDate ?? now.toISOString().slice(0, 10),
    });

    if (!snapshot) return;

    // Optional: Phase 7.2 sweep enrichment
    if (enableSweep) {
      try {
        const chainRows = reconstructChainRows(snapshot);
        const valuation = valuationDate ?? now.toISOString().slice(0, 10);
        const sweep = spotSweep(chainRows, {
          spot,
          symbol: effectiveSymbol,
          valuationDate: valuation,
        });
        if (sweep && sweep.status !== "unavailable") {
          snapshot.sweepData = {
            gammaFlipSpot: sweep.gammaFlip.primaryFlip?.crossingSpot ?? null,
            gammaFlipDistancePct: sweep.gammaFlip.distanceFromSpotPct ?? null,
            gammaFlipDirection: sweep.gammaFlip.primaryFlip?.direction ?? null,
            callWallStrikes: (sweep.gammaWalls.callWalls ?? []).map((w) => w.strike),
            putWallStrikes: (sweep.gammaWalls.putWalls ?? []).map((w) => w.strike),
            sweepStatus: sweep.status,
          };
        }
      } catch {
        // Sweep failed — continue without sweep data
      }
    }

    // Validate
    const validation = validateGexSnapshot(snapshot);
    if (!validation.valid) {
      console.warn("[GEX] Snapshot validation failed:", validation.issues);
      return;
    }

    // Push to ring buffer
    buf.push(snapshot);
    setCaptureCount(buf.size());
    setLatestSnapshot(snapshot);

    // Compute analytics
    const result = computeGexAnalytics(buf, { valuationDate });
    setAnalytics(result);

    // Persist to backend (fire-and-forget)
    if (persistToBackend) {
      saveSnapshot(snapshot).catch(() => {});
    }
  }, [chain, symbol, valuationDate, persistToBackend]);

  return {
    buffer: bufferRef.current,
    analytics,
    captureCount,
    latestSnapshot,
  };
}
