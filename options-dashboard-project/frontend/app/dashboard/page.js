"use client";
import { useEffect, useState } from "react";
import { getStatus, getExpiries, getChain } from "@/lib/api";

const C = {
  surface: "#12161F",
  border: "#242B3A",
  muted: "#8892A6",
  gold: "#C9A15A",
  green: "#4CAF7D",
  red: "#E15252",
};

export default function Dashboard() {
  const [loggedIn, setLoggedIn] = useState(null);
  const [expiries, setExpiries] = useState([]);
  const [expiry, setExpiry] = useState(null);
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);

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

  useEffect(() => {
    if (loggedIn && expiry) {
      getChain("NIFTY", expiry)
        .then(setChain)
        .catch((e) => setError(e.message));
    }
  }, [loggedIn, expiry]);

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
      </div>

      <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ color: C.muted, fontSize: 11 }}>
              <th style={{ padding: 8 }}>Delta</th>
              <th style={{ padding: 8 }}>IV</th>
              <th style={{ padding: 8 }}>OI</th>
              <th style={{ padding: 8 }}>Call LTP</th>
              <th style={{ padding: 8, color: C.gold }}>Strike</th>
              <th style={{ padding: 8 }}>Put LTP</th>
              <th style={{ padding: 8 }}>OI</th>
              <th style={{ padding: 8 }}>IV</th>
              <th style={{ padding: 8 }}>Delta</th>
            </tr>
          </thead>
          <tbody>
            {chain.chain.map((row) => (
              <tr key={row.strike} style={{ borderTop: `1px solid ${C.border}` }}>
                <td style={{ padding: 8 }}>{row.call.delta ?? "-"}</td>
                <td style={{ padding: 8 }}>{row.call.iv ?? "-"}</td>
                <td style={{ padding: 8 }}>{row.call.oi ?? "-"}</td>
                <td style={{ padding: 8, color: C.green }}>{row.call.ltp ?? "-"}</td>
                <td style={{ padding: 8, textAlign: "center", fontWeight: 600 }}>{row.strike}</td>
                <td style={{ padding: 8, color: C.red }}>{row.put.ltp ?? "-"}</td>
                <td style={{ padding: 8 }}>{row.put.oi ?? "-"}</td>
                <td style={{ padding: 8 }}>{row.put.iv ?? "-"}</td>
                <td style={{ padding: 8 }}>{row.put.delta ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
