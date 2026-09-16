"use client";
import { useState, useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { useIsMobile } from "@/lib/ui";
import { COLOR, TYPE, SPACE, RADIUS } from "@/components/public/tokens";
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

function isActive(currentPath, href) {
  if (href === "/") return currentPath === "/";
  return currentPath === href || currentPath.startsWith(href + "/");
}

export default function PublicHeader() {
  const isMobile = useIsMobile();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState(null);
  const navRef = useRef(null);
  const mobileMenuRef = useRef(null);
  const mobileToggleRef = useRef(null);
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

  // Close mobile menu on Escape — return focus to toggle button
  useEffect(() => {
    if (!mobileOpen) return;
    const handleKey = (e) => {
      if (e.key === "Escape") {
        setMobileOpen(false);
        mobileToggleRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [mobileOpen]);

  // Close mobile menu on outside click
  useEffect(() => {
    if (!mobileOpen) return;
    const handleClick = (e) => {
      if (mobileMenuRef.current && !mobileMenuRef.current.contains(e.target)) {
        setMobileOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [mobileOpen]);

  const toggleGroup = (label) => {
    setExpandedGroup((prev) => (prev === label ? null : label));
  };

  return (
    <>
      <nav
        ref={navRef}
        aria-label="Main navigation"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 100,
          background: "rgba(11, 14, 20, 0.88)",
          backdropFilter: "blur(14px)",
          WebkitBackdropFilter: "blur(14px)",
          borderBottom: `1px solid ${COLOR.border}`,
        }}
      >
        <div
          style={{
            maxWidth: PAGE_MAX,
            margin: "0 auto",
            padding: `0 ${SPACE.compLg}`,
            height: 60,
            display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: SPACE.compLg,
              boxSizing: "border-box",
              width: "100%",
            }}
            >
            {/* Logo */}
          <a
            href="/"
            aria-label="StrikeNova — Home"
            className="ds-focus-ring"
            style={{
              display: "flex",
              alignItems: "center",
              gap: SPACE.small,
              textDecoration: "none",
              borderRadius: RADIUS.sm,
            }}
          >
            <span
              style={{
                width: 32,
                height: 32,
                borderRadius: RADIUS.md,
                background: COLOR.strategy,
                color: "#0B0E14",
                display: "grid",
                placeItems: "center",
                fontWeight: 900,
                fontSize: 11,
                letterSpacing: -0.5,
                flexShrink: 0,
              }}
            >
              SN
            </span>
            <span>
              <span style={{ display: "block", fontSize: 13.5, fontWeight: 800, letterSpacing: 1.2, color: COLOR.textPrimary, lineHeight: 1.2 }}>
                STRIKENOVA
              </span>
              <span style={{ display: "block", fontSize: 11, color: COLOR.textMuted, letterSpacing: 1, lineHeight: 1.2 }}>
                OPTIONS INTELLIGENCE
              </span>
            </span>
          </a>

          {/* Desktop nav links */}
          {!isMobile && (
            <div className="pub-nav-links" style={{ display: "flex", alignItems: "center", gap: SPACE.section }}>
              {NAV_LINKS.map((group) => {
                const groupActive = group.children.some((child) => isActive(pathname, child.href));
                return (
                  <div key={group.label} style={{ position: "relative" }}>
                    <button
                      onClick={() => toggleGroup(group.label)}
                      aria-expanded={expandedGroup === group.label}
                      aria-haspopup="true"
                      className="ds-focus-ring"
                      style={{
                        background: "none",
                        border: "none",
                        color: groupActive ? COLOR.strategy : COLOR.textSecondary,
                        fontSize: 14,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: SPACE.micro,
                        padding: 0,
                        fontFamily: "inherit",
                        fontWeight: groupActive ? 600 : 400,
                        borderRadius: RADIUS.sm,
                      }}
                    >
                      {group.label}
                      <span aria-hidden="true" style={{ fontSize: 10, opacity: 0.6 }}>&#9662;</span>
                    </button>
                    {groupActive && (
                      <div style={{ position: "absolute", bottom: -8, left: 0, right: 0, height: 2, background: COLOR.strategy, borderRadius: 1 }} />
                    )}
                    {expandedGroup === group.label && (
                      <div
                        style={{
                          position: "absolute",
                          top: "100%",
                          left: 0,
                          marginTop: SPACE.small,
                          background: "rgba(18, 22, 31, 0.98)",
                          border: `1px solid ${COLOR.border}`,
                          borderRadius: RADIUS.md,
                          padding: `${SPACE.xs} 0`,
                          minWidth: 200,
                          boxShadow: "0 12px 40px rgba(0,0,0,0.4)",
                        }}
                      >
                        {group.children.map((child) => {
                          const childActive = isActive(pathname, child.href);
                          return (
                            <a
                              key={child.href}
                              href={child.href}
                              onClick={() => setExpandedGroup(null)}
                              className="ds-focus-ring"
                              style={{
                                display: "block",
                                padding: `${SPACE.small} ${SPACE.compLg}`,
                                fontSize: 14,
                                color: childActive ? COLOR.strategy : COLOR.textSecondary,
                                textDecoration: "none",
                                transition: "color 0.15s, background 0.15s",
                                fontWeight: childActive ? 600 : 400,
                                borderRadius: RADIUS.sm,
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.color = COLOR.strategy; e.currentTarget.style.background = COLOR.strategyDim; }}
                              onMouseLeave={(e) => { e.currentTarget.style.color = childActive ? COLOR.strategy : COLOR.textSecondary; e.currentTarget.style.background = "transparent"; }}
                            >
                              {child.label}
                            </a>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Right side */}
          <div style={{ display: "flex", alignItems: "center", gap: SPACE.small, flexShrink: 0 }}>
            <button
              onClick={openAuth}
              data-testid="header-login-btn"
              className="ds-focus-ring"
              style={{
                fontSize: 14,
                color: COLOR.textSecondary,
                textDecoration: "none",
                padding: `${SPACE.small} ${SPACE.comp}`,
                borderRadius: RADIUS.md,
                transition: "color 0.15s",
                background: "none",
                border: "none",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = COLOR.strategy; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = COLOR.textSecondary; }}
            >
              Log in
            </button>
            <button
              onClick={openAuth}
              data-testid="header-get-started-btn"
              className="od-btn-gold ds-focus-ring"
              style={{ padding: `${SPACE.small} ${SPACE.compLg}`, fontSize: 14, cursor: "pointer", borderRadius: RADIUS.md, border: "none", fontFamily: "inherit" }}
            >
              Get Started
            </button>

            {/* Mobile hamburger */}
            <button
              ref={mobileToggleRef}
              className="pub-nav-mobile-toggle ds-focus-ring"
              onClick={() => setMobileOpen((v) => !v)}
              aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={mobileOpen}
              aria-controls="mobile-nav-menu"
              style={{
                background: "none",
                border: `1px solid ${COLOR.border}`,
                borderRadius: RADIUS.md,
                color: COLOR.textSecondary,
                fontSize: 18,
                cursor: "pointer",
                padding: `${SPACE.small} ${SPACE.comp}`,
                alignItems: "center",
                justifyContent: "center",
                minWidth: 44,
                minHeight: 44,
              }}
            >
              {mobileOpen ? "\u2715" : "\u2630"}
            </button>
          </div>
        </div>
      </nav>

      {/* Mobile menu overlay */}
      <div
        ref={mobileMenuRef}
        id="mobile-nav-menu"
        className="pub-mobile-menu"
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
        aria-hidden={!mobileOpen}
        style={{
          position: "fixed",
          top: 60,
          left: 0,
          width: "100vw",
          bottom: 0,
          zIndex: 99,
          background: "rgba(11, 14, 20, 0.96)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          overflowY: "auto",
          opacity: mobileOpen ? 1 : 0,
          transform: mobileOpen ? "translateY(0)" : "translateY(-8px)",
          transition: "opacity 0.2s cubic-bezier(0.22, 1, 0.36, 1), transform 0.2s cubic-bezier(0.22, 1, 0.36, 1)",
          pointerEvents: mobileOpen ? "auto" : "none",
        }}
      >
          <div style={{ maxWidth: PAGE_MAX, margin: "0 auto", padding: `${SPACE.cardLg} ${SPACE.compLg}`, display: "flex", flexDirection: "column", gap: SPACE.xs, boxSizing: "border-box", width: "100%" }}>
            {NAV_LINKS.map((group) => {
              const groupActive = group.children.some((child) => isActive(pathname, child.href));
              return (
                <div key={group.label}>
                  <button
                    onClick={() => toggleGroup(group.label)}
                    aria-expanded={expandedGroup === group.label}
                    className="ds-focus-ring"
                    style={{
                      width: "100%",
                      background: "none",
                      border: "none",
                      color: groupActive ? COLOR.strategy : COLOR.textPrimary,
                      fontSize: 16,
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: `${SPACE.comp} 0`,
                      borderBottom: `1px solid ${COLOR.border}`,
                      fontFamily: "inherit",
                      fontWeight: groupActive ? 600 : 400,
                      borderRadius: RADIUS.sm,
                    }}
                  >
                    {group.label}
                    <span aria-hidden="true" style={{ fontSize: 12, color: COLOR.textMuted, transition: "transform 0.2s", transform: expandedGroup === group.label ? "rotate(180deg)" : "none" }}>
                      &#9662;
                    </span>
                  </button>
                  {expandedGroup === group.label && (
                    <div style={{ paddingLeft: SPACE.comp, paddingBottom: SPACE.small }}>
                      {group.children.map((child) => {
                        const childActive = isActive(pathname, child.href);
                        return (
                          <a
                            key={child.href}
                            href={child.href}
                            onClick={() => setMobileOpen(false)}
                            className="ds-focus-ring"
                            style={{
                              display: "block",
                              fontSize: 14,
                              color: childActive ? COLOR.strategy : COLOR.textSecondary,
                              textDecoration: "none",
                              padding: `${SPACE.small} 0`,
                              fontWeight: childActive ? 600 : 400,
                              borderRadius: RADIUS.sm,
                            }}
                          >
                            {child.label}
                          </a>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
            <div style={{ display: "flex", gap: SPACE.comp, marginTop: SPACE.cardLg, flexWrap: "wrap" }}>
              <button
                onClick={() => { setMobileOpen(false); openAuth(); }}
                data-testid="mobile-login-btn"
                className="od-btn-ghost ds-focus-ring"
                style={{ flex: 1, justifyContent: "center", cursor: "pointer", borderRadius: RADIUS.md, fontFamily: "inherit" }}
              >
                Log in
              </button>
              <button
                onClick={() => { setMobileOpen(false); openAuth(); }}
                data-testid="mobile-get-started-btn"
                className="od-btn-gold ds-focus-ring"
                style={{ flex: 1, justifyContent: "center", cursor: "pointer", borderRadius: RADIUS.md, border: "none", fontFamily: "inherit" }}
              >
                Get Started
              </button>
            </div>
          </div>
      </div>
    </>
  );
}
