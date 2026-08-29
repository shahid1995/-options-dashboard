"use client";
import { useState, useEffect, useRef } from "react";
import { C, useIsMobile } from "@/lib/ui";
import { PAGE_MAX } from "./styles";
import { useAuthModal } from "./AuthModalContext";

const NAV_LINKS = [
  { label: "Product", children: [
    { label: "Features", href: "/features" },
    { label: "Market Intelligence", href: "/market-intelligence" },
    { label: "Strategy Lab", href: "/strategy-lab" },
    { label: "Paper Trading", href: "/paper-trading" },
  ]},
  { label: "Learn", children: [
    { label: "How It Works", href: "/how-it-works" },
    { label: "About", href: "/about" },
  ]},
];

export default function PublicHeader() {
  const isMobile = useIsMobile();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState(null);
  const navRef = useRef(null);
  const { open: openAuth } = useAuthModal();

  // Close dropdown on outside click
  useEffect(() => {
    if (!expandedGroup) return;
    const handleClick = (e) => {
      if (navRef.current && !navRef.current.contains(e.target)) {
        setExpandedGroup(null);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [expandedGroup]);

  // Close mobile menu on Escape
  useEffect(() => {
    if (!mobileOpen) return;
    const handleKey = (e) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [mobileOpen]);

  const toggleGroup = (label) => {
    setExpandedGroup((prev) => (prev === label ? null : label));
  };

  return (
    <>
      <nav
        ref={navRef}
        style={{
          position: "sticky",
          top: 0,
          zIndex: 100,
          background: "rgba(11, 14, 20, 0.88)",
          backdropFilter: "blur(14px)",
          WebkitBackdropFilter: "blur(14px)",
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        <div
          style={{
            maxWidth: PAGE_MAX,
            margin: "0 auto",
            padding: "0 20px",
            height: 60,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
          }}
        >
          {/* Logo */}
          <a href="/" aria-label="Options Dashboard — Home" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
            <span
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: C.gold,
                color: "#0B0E14",
                display: "grid",
                placeItems: "center",
                fontWeight: 900,
                fontSize: 13,
                letterSpacing: -0.5,
                flexShrink: 0,
              }}
            >
              OD
            </span>
            <span>
              <span style={{ display: "block", fontSize: 13.5, fontWeight: 800, letterSpacing: 1.2, color: C.text, lineHeight: 1.2 }}>
                OPTIONS DASHBOARD
              </span>
              <span style={{ display: "block", fontSize: 11, color: C.faint, letterSpacing: 1, lineHeight: 1.2 }}>
                NSE &middot; BSE INDEX OPTIONS
              </span>
            </span>
          </a>

          {/* Desktop nav links */}
          {!isMobile && (
            <div className="pub-nav-links" style={{ display: "flex", alignItems: "center", gap: 28 }}>
              {NAV_LINKS.map((group) => (
                <div key={group.label} style={{ position: "relative" }}>
                  <button
                    onClick={() => toggleGroup(group.label)}
                    aria-expanded={expandedGroup === group.label}
                    aria-haspopup="true"
                    style={{
                      background: "none",
                      border: "none",
                      color: C.muted,
                      fontSize: 14,
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      padding: 0,
                      fontFamily: "inherit",
                    }}
                  >
                    {group.label}
                    <span style={{ fontSize: 10, opacity: 0.6 }}>&#9662;</span>
                  </button>
                  {expandedGroup === group.label && (
                    <div
                      style={{
                        position: "absolute",
                        top: "100%",
                        left: 0,
                        marginTop: 8,
                        background: "rgba(18, 22, 31, 0.98)",
                        border: `1px solid ${C.border}`,
                        borderRadius: 8,
                        padding: "6px 0",
                        minWidth: 200,
                        boxShadow: "0 12px 40px rgba(0,0,0,0.4)",
                      }}
                    >
                      {group.children.map((child) => (
                        <a
                          key={child.href}
                          href={child.href}
                          onClick={() => setExpandedGroup(null)}
                          style={{
                            display: "block",
                            padding: "8px 18px",
                            fontSize: 14,
                            color: C.muted,
                            textDecoration: "none",
                            transition: "color 0.15s, background 0.15s",
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.color = C.gold; e.currentTarget.style.background = "rgba(201,161,90,0.06)"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.color = C.muted; e.currentTarget.style.background = "transparent"; }}
                        >
                          {child.label}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Right side */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
            <button
              onClick={openAuth}
              data-testid="header-login-btn"
              style={{
                fontSize: 14,
                color: C.muted,
                textDecoration: "none",
                padding: "6px 12px",
                borderRadius: 6,
                transition: "color 0.15s",
                background: "none",
                border: "none",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = C.gold; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = C.muted; }}
            >
              Log in
            </button>
            <button
              onClick={openAuth}
              data-testid="header-get-started-btn"
              className="od-btn-gold"
              style={{ padding: "7px 16px", fontSize: 14, cursor: "pointer" }}
            >
              Get Started
            </button>

            {/* Mobile hamburger */}
            <button
              className="pub-nav-mobile-toggle"
              onClick={() => setMobileOpen((v) => !v)}
              aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={mobileOpen}
              aria-controls="mobile-nav-menu"
              style={{
                display: "none",
                background: "none",
                border: `1px solid ${C.border}`,
                borderRadius: 6,
                color: C.muted,
                fontSize: 18,
                cursor: "pointer",
                padding: "4px 8px",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {mobileOpen ? "\u2715" : "\u2630"}
            </button>
          </div>
        </div>
      </nav>

      {/* Mobile menu overlay */}
      {mobileOpen && (
        <div
          id="mobile-nav-menu"
          className="pub-mobile-menu"
          role="dialog"
          aria-modal="true"
          aria-label="Navigation menu"
          style={{
            position: "fixed",
            top: 60,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 99,
            background: "rgba(11, 14, 20, 0.96)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            overflowY: "auto",
          }}
        >
          <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: "24px 20px", display: "flex", flexDirection: "column", gap: 6 }}>
            {NAV_LINKS.map((group) => (
              <div key={group.label}>
                <button
                  onClick={() => toggleGroup(group.label)}
                  aria-expanded={expandedGroup === group.label}
                  style={{
                    width: "100%",
                    background: "none",
                    border: "none",
                    color: C.text,
                    fontSize: 16,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "12px 0",
                    borderBottom: `1px solid ${C.border}`,
                    fontFamily: "inherit",
                  }}
                >
                  {group.label}
                  <span style={{ fontSize: 12, color: C.muted, transition: "transform 0.2s", transform: expandedGroup === group.label ? "rotate(180deg)" : "none" }}>
                    &#9662;
                  </span>
                </button>
                {expandedGroup === group.label && (
                  <div style={{ paddingLeft: 16, paddingBottom: 8 }}>
                    {group.children.map((child) => (
                      <a
                        key={child.href}
                        href={child.href}
                        onClick={() => setMobileOpen(false)}
                        style={{ display: "block", fontSize: 14, color: C.muted, textDecoration: "none", padding: "10px 0" }}
                      >
                        {child.label}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <div style={{ display: "flex", gap: 12, marginTop: 20, flexWrap: "wrap" }}>
              <button
                onClick={() => { setMobileOpen(false); openAuth(); }}
                data-testid="mobile-login-btn"
                className="od-btn-ghost"
                style={{ flex: 1, justifyContent: "center", cursor: "pointer" }}
              >
                Log in
              </button>
              <button
                onClick={() => { setMobileOpen(false); openAuth(); }}
                data-testid="mobile-get-started-btn"
                className="od-btn-gold"
                style={{ flex: 1, justifyContent: "center", cursor: "pointer" }}
              >
                Get Started
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
