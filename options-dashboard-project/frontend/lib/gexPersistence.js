/**
 * GEX Phase 7.6 — Frontend Persistence Client
 *
 * Provides save/load functions for GEX snapshots via the backend API.
 * Gracefully degrades to in-memory-only mode when the backend is unavailable.
 *
 * No trading signals. No BUY/SELL logic.
 */

import { api, isAuthError } from "./api";

/**
 * Save a GEX snapshot to the backend.
 *
 * @param {object} snapshot — GEXSnapshot_v1 object
 * @returns {{ ok: boolean, id: number|null, duplicate: boolean }} or null on failure
 */
export async function saveSnapshot(snapshot) {
  try {
    const resp = await api.post("/gex/snapshots", snapshot);
    return resp.data;
  } catch (e) {
    // Backend unavailable or auth error — silent degradation
    if (isAuthError(e)) {
      console.warn("[GEX] Session expired — snapshot not persisted");
    }
    return null;
  }
}

/**
 * Load GEX snapshots from the backend.
 *
 * @param {string} symbol — e.g. "NIFTY"
 * @param {object} [options]
 * @param {string} [options.expiry] — filter by expiry
 * @param {number} [options.limit=200] — max snapshots
 * @param {string} [options.since] — ISO-8601 timestamp filter
 * @returns {Array} snapshots (oldest-first), or empty array on failure
 */
export async function loadSnapshots(symbol, options = {}) {
  try {
    const params = { symbol, limit: options.limit ?? 200 };
    if (options.expiry) params.expiry = options.expiry;
    if (options.since) params.since = options.since;

    const resp = await api.get("/gex/snapshots", { params });
    return resp.data.snapshots ?? [];
  } catch (e) {
    if (isAuthError(e)) {
      console.warn("[GEX] Session expired — cannot load historical snapshots");
    }
    return [];
  }
}

/**
 * Load the most recent GEX snapshot from the backend.
 *
 * @param {string} symbol
 * @param {string} [expiry]
 * @returns {object|null} snapshot or null
 */
export async function loadLatestSnapshot(symbol, expiry) {
  try {
    const params = { symbol };
    if (expiry) params.expiry = expiry;
    const resp = await api.get("/gex/snapshots/latest", { params });
    return resp.data;
  } catch {
    return null;
  }
}
