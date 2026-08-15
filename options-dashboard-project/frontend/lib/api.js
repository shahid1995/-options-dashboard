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
