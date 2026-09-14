"use client";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
import { PAGE_MAX } from "./styles";
import { useAuthModal } from "./AuthModalContext";

const FOOTER_COLS = [
  {
    heading: "Product",
    links: [
      { label: "Features", href: "/features" },
      { label: "Market Intelligence", href: "/market-intelligence" },
      { label: "Strategy Lab", href: "/strategy-lab" },
      { label: "Paper Trading", href: "/paper-trading" },
    ],
  },
  {
    heading: "Learn",
    links: [
      { label: "How It Works", href: "/how-it-works" },
      { label: "About", href: "/about" },
    ],
  },
];

export default function PublicFooter() {
  const { open: openAuth } = useAuthModal();

  return (
    <footer
      role="contentinfo"
      style={{
        borderTop: `1px solid ${COLOR.border}`,
        background: COLOR.surfaceDeep,
      }}
    >
      <div
        style={{
          maxWidth: PAGE_MAX,
          margin: "0 auto",
          padding: `${SPACE.sectionLg} ${SPACE.compLg} ${SPACE.section}`,
          display: "flex",
          flexWrap: "wrap",
          gap: SPACE.section,
          justifyContent: "space-between",
          alignItems: "flex-start",
        }}
      >
        {/* Brand */}
        <div style={{ maxWidth: 300, minWidth: 200, flex: "1 1 240px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: SPACE.small, marginBottom: SPACE.comp }}>
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: RADIUS.sm,
                background: COLOR.strategy,
                color: "#0B0E14",
                display: "grid",
                placeItems: "center",
                fontWeight: 900,
                fontSize: 10,
              }}
            >
              SN
            </span>
            <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1.2, color: COLOR.textPrimary }}>
              STRIKENOVA
            </span>
          </div>
          <p style={{ fontSize: 13, color: COLOR.textMuted, lineHeight: 1.65, margin: 0 }}>
            Options intelligence for structured decisions.
          </p>
        </div>

        {/* Link columns */}
        <div style={{ display: "flex", gap: SPACE.section, flexWrap: "wrap", flex: "2 1 320px" }}>
          {FOOTER_COLS.map((col) => (
            <div key={col.heading.toUpperCase()} style={{ display: "flex", flexDirection: "column", gap: SPACE.small, minWidth: 120 }}>
              <div
                style={{
                  fontSize: TYPE.caption.size,
                  letterSpacing: TYPE.caption.letterSpacing,
                  color: COLOR.textFaint,
                  fontWeight: 600,
                  marginBottom: SPACE.micro,
                  textTransform: "uppercase",
                }}
              >
                {col.heading.toUpperCase()}
              </div>
              {col.links.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  className="od-link ds-focus-ring"
                  style={{ borderRadius: RADIUS.sm }}
                >
                  {link.label}
                </a>
              ))}
            </div>
          ))}

          {/* ACCOUNT column — buttons that open the modal */}
          <div style={{ display: "flex", flexDirection: "column", gap: SPACE.small, minWidth: 120 }}>
            <div
              style={{
                fontSize: TYPE.caption.size,
                letterSpacing: TYPE.caption.letterSpacing,
                color: COLOR.textFaint,
                fontWeight: 600,
                marginBottom: SPACE.micro,
                textTransform: "uppercase",
              }}
            >
              ACCOUNT
            </div>
            <button
              onClick={openAuth}
              data-testid="footer-login-btn"
              className="od-link ds-focus-ring"
              style={{
                background: "none",
                border: "none",
                textAlign: "left",
                cursor: "pointer",
                padding: 0,
                fontFamily: "inherit",
                borderRadius: RADIUS.sm,
              }}
            >
              Log in
            </button>
            <button
              onClick={openAuth}
              data-testid="footer-get-started-btn"
              className="od-link ds-focus-ring"
              style={{
                background: "none",
                border: "none",
                textAlign: "left",
                cursor: "pointer",
                padding: 0,
                fontFamily: "inherit",
                borderRadius: RADIUS.sm,
              }}
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
          padding: `${SPACE.comp} ${SPACE.compLg}`,
          borderTop: `1px solid ${COLOR.border}`,
          display: "flex",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: SPACE.small,
          fontSize: 12,
          color: COLOR.textFaint,
        }}
      >
        <span>&copy; {new Date().getFullYear()} StrikeNova</span>
        <span>NSE &amp; BSE index derivatives &middot; For education and research only</span>
      </div>
    </footer>
  );
}
