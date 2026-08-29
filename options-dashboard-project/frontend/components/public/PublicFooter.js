"use client";
import { C } from "@/lib/ui";
import { PAGE_MAX } from "./styles";
import { useAuthModal } from "./AuthModalContext";

const FOOTER_COLS = [
  {
    heading: "Platform",
    links: [
      { label: "Features", href: "/features" },
      { label: "Strategy Lab", href: "/strategy-lab" },
      { label: "Market Intelligence", href: "/market-intelligence" },
      { label: "Paper Trading", href: "/paper-trading" },
    ],
  },
  {
    heading: "Resources",
    links: [
      { label: "How It Works", href: "/how-it-works" },
      { label: "About", href: "/about" },
    ],
  },
];

export default function PublicFooter() {
  const { open: openAuth } = useAuthModal();

  return (
    <footer style={{ borderTop: `1px solid ${C.border}`, background: "rgba(18, 22, 31, 0.4)" }}>
      <div
        style={{
          maxWidth: PAGE_MAX,
          margin: "0 auto",
          padding: "48px 20px 32px",
          display: "flex",
          flexWrap: "wrap",
          gap: 40,
          justifyContent: "space-between",
          alignItems: "flex-start",
        }}
      >
        {/* Brand */}
        <div style={{ maxWidth: 300, minWidth: 200 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                background: C.gold,
                color: "#0B0E14",
                display: "grid",
                placeItems: "center",
                fontWeight: 900,
                fontSize: 11,
              }}
            >
              OD
            </span>
            <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1.2, color: C.text }}>
              OPTIONS DASHBOARD
            </span>
          </div>
          <p style={{ fontSize: 13, color: C.faint, lineHeight: 1.65, margin: 0 }}>
            A professional options analysis and paper-trading platform for traders
            who want to turn market data into structured decisions.
          </p>
        </div>

        {/* Link columns */}
        <div style={{ display: "flex", gap: 48, flexWrap: "wrap" }}>
          {FOOTER_COLS.map((col) => (
            <div key={col.heading} style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 120 }}>
              <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, fontWeight: 600, marginBottom: 4 }}>
                {col.heading.toUpperCase()}
              </div>
              {col.links.map((link) => (
                <a key={link.label + link.href} className="od-link" href={link.href}>
                  {link.label}
                </a>
              ))}
            </div>
          ))}

          {/* Account column — buttons that open the modal */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 120 }}>
            <div style={{ fontSize: 11, letterSpacing: 1.5, color: C.faint, fontWeight: 600, marginBottom: 4 }}>
              ACCOUNT
            </div>
            <button
              onClick={openAuth}
              data-testid="footer-login-btn"
              className="od-link"
              style={{ background: "none", border: "none", textAlign: "left", cursor: "pointer", padding: 0, fontFamily: "inherit" }}
            >
              Log in
            </button>
            <button
              onClick={openAuth}
              data-testid="footer-get-started-btn"
              className="od-link"
              style={{ background: "none", border: "none", textAlign: "left", cursor: "pointer", padding: 0, fontFamily: "inherit" }}
            >
              Get Started
            </button>
          </div>
        </div>
      </div>

      {/* Bottom bar */}
      <div
        style={{
          maxWidth: PAGE_MAX,
          margin: "0 auto",
          padding: "20px 20px",
          borderTop: `1px solid ${C.border}`,
          display: "flex",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
          fontSize: 12,
          color: C.faint,
        }}
      >
        <span>&copy; {new Date().getFullYear()} Options Dashboard</span>
        <span>NSE &amp; BSE index derivatives &middot; For education and research only</span>
      </div>
    </footer>
  );
}
