import axios from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  withCredentials: true,
});

export const loginUrl = () => `${process.env.NEXT_PUBLIC_API_URL}/auth/login`;

export const getStatus = () => api.get("/auth/status").then((r) => r.data);

export const getExpiries = (symbol) =>
  api.get(`/chains/${symbol}/expiries`).then((r) => r.data);

export const getChain = (symbol, expiryDate) =>
  api
    .get(`/chains/${symbol}`, { params: { expiry_date: expiryDate } })
    .then((r) => r.data);
