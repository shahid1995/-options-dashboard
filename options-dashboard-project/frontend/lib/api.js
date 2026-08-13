import axios from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  withCredentials: true,
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

export const chainWsUrl = (symbol, expiryDate) => {
  const base = process.env.NEXT_PUBLIC_API_URL || "";
  const wsBase = base.replace(/^http/, "ws");
  return `${wsBase}/chains/ws/${symbol}?expiry_date=${encodeURIComponent(expiryDate)}`;
};
