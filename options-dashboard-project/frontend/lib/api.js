import axios from "axios";
import { getSessionId } from "./session";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  withCredentials: true,
});

// Authenticate with the session ID captured from the OAuth callback; the
// session cookie alone doesn't survive third-party cookie blocking because
// the backend is on a different site.
api.interceptors.request.use((config) => {
  const sessionId = getSessionId();
  if (sessionId) config.headers["X-Session-Id"] = sessionId;
  return config;
});

// Surface the backend's error detail (or a clear network message) instead of
// axios's generic "Request failed with status code NNN".
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail) {
      error.message = detail;
    } else if (!error.response) {
      error.message = "Could not reach the server. Check your connection and try again.";
    }
    return Promise.reject(error);
  }
);

export const loginUrl = () => `${process.env.NEXT_PUBLIC_API_URL}/auth/login`;

export const isAuthError = (e) => e?.response?.status === 401;

export const getStatus = () => api.get("/auth/status").then((r) => r.data);

export const getExpiries = (symbol) =>
  api.get(`/chains/${symbol}/expiries`).then((r) => r.data);

export const getChain = (symbol, expiryDate) =>
  api
    .get(`/chains/${symbol}`, { params: { expiry_date: expiryDate } })
    .then((r) => r.data);

// ---- Paper trading journal (DB-backed, trades + legs tables) ----

export const submitPaperFill = (order) => api.post("/paper/fills", order).then((r) => r.data);

export const closePaperLeg = (tradeId, legId, exitPrice) =>
  api.post(`/paper/trades/${tradeId}/legs/${legId}/close`, { exit_price: exitPrice }).then((r) => r.data);

export const getPaperJournal = () => api.get("/paper/journal").then((r) => r.data);

export const getMarketStatus = () =>
  api.get("/paper/market-status").then((r) => ({ ...r.data, tradeDate: r.data.trade_date }));

// ---- Phase 5.0: server-authoritative paper trading ----
// The backend decides fills, positions, cash, realized P&L and order status;
// these endpoints expose that state. The frontend only displays it.

export const submitPaperExecution = (payload) =>
  api.post("/paper/executions", payload).then((r) => r.data);

export const exitPaperPosition = (positionId, payload) =>
  api.post(`/paper/positions/${positionId}/exit`, payload).then((r) => r.data);

// ---- Phase 5.2: bulk paper position exit ----
// Server-authoritative bulk operations: EXIT STRATEGY (one strategy
// execution) and EXIT ALL (every open position). The backend owns the bulk
// operation, validates everything up front, and is idempotent per key.

export const exitPaperStrategy = (executionId, payload) =>
  api.post(`/paper/executions/${executionId}/exit-all`, payload).then((r) => r.data);

export const exitAllPaperPositions = (payload) =>
  api.post("/paper/positions/exit-all", payload).then((r) => r.data);

export const getPaperPositions = () => api.get("/paper/positions").then((r) => r.data);

export const getPaperPositionsFiltered = (params = {}) =>
  api.get("/paper/positions", { params }).then((r) => r.data);

// ---- Phase 6.6.3: canonical orders endpoint with server-side filtering ----
// Backward-compatible: no params returns all orders.
// New params: status, symbol, action, option_type, kind,
//             strategy_execution_id, limit, offset.

export const getPaperOrders = () => api.get("/paper/orders").then((r) => r.data);

export const getPaperOrdersFiltered = (params = {}) =>
  api.get("/paper/orders", { params }).then((r) => r.data);

export const getPaperPortfolio = () => api.get("/paper/portfolio").then((r) => r.data);

export const getPaperReconcile = () => api.get("/paper/reconcile").then((r) => r.data);

export const resetPaperPortfolio = () =>
  api.post("/paper/portfolio/reset").then((r) => r.data);

// ---- Phase 6.6.5: Exit preview + confirmation ----

export const previewExitIntent = (payload) =>
  api.post("/paper/exit-intent/preview", payload).then((r) => r.data);

export const confirmExitIntent = (payload) =>
  api.post("/paper/exit-intent", payload).then((r) => r.data);

// ---- Phase 6.6.6: live position valuation ----

export const getPositionsValuation = () =>
  api.get("/paper/positions/valuation").then((r) => r.data);

// ---- Phase 5.1: portfolio & journal analytics ----
// ONE authoritative analytics response (summary + performance + equity curve
// + drawdown + strategy performance + positions + journal).

export const getPaperAnalytics = (params) =>
  api.get("/paper/analytics", { params }).then((r) => r.data);

// ---- Phase 6.0: capital & margin foundation ----
// Server-authoritative capital summary: premium outlay, broker margin,
// estimated capital, paper capital — each with source/status. Read-only.

export const getPaperCapital = () => api.get("/paper/capital").then((r) => r.data);

// ---- Phase 6.4.1: broker profile & connection diagnostics ----
// Read-only: verifies the authenticated Upstox connection and returns the
// NORMALIZED safe profile (never credentials). The backend serves a short
// user-scoped cache; pass refresh=true to bypass it (manual refresh). This
// is NOT polled — profile is not tick data.

export const getBrokerProfile = (refresh = false) =>
  api
    .get("/paper/broker/profile", { params: refresh ? { refresh: true } : {} })
    .then((r) => r.data);

export const chainWsUrl = (symbol, expiryDate) => {
  const base = process.env.NEXT_PUBLIC_API_URL || "";
  const wsBase = base.replace(/^http/, "ws");
  return `${wsBase}/chains/ws/${symbol}?expiry_date=${encodeURIComponent(expiryDate)}`;
};

// Browsers can't set custom headers on websockets, so the session ID rides
// along as the second entry of the subprotocol list (matched by the backend).
export const chainWsProtocols = () => {
  const sessionId = getSessionId();
  return sessionId ? ["options-dashboard-session", sessionId] : undefined;
};

// ---- Phase 6.7: strategy templates (CRUD) ----

export const getStrategyTemplates = () =>
  api.get("/paper/templates").then((r) => r.data);

export const createStrategyTemplate = (payload) =>
  api.post("/paper/templates", payload).then((r) => r.data);

export const getStrategyTemplate = (id) =>
  api.get(`/paper/templates/${id}`).then((r) => r.data);

export const updateStrategyTemplate = (id, payload) =>
  api.put(`/paper/templates/${id}`, payload).then((r) => r.data);

export const duplicateStrategyTemplate = (id, newName) =>
  api
    .post(`/paper/templates/${id}/duplicate`, null, { params: newName ? { new_name: newName } : {} })
    .then((r) => r.data);

export const deleteStrategyTemplate = (id) =>
  api.delete(`/paper/templates/${id}`).then((r) => r.data);

