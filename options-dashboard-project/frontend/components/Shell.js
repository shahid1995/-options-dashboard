"use client";
import { useState, useEffect, useCallback } from "react";
import { usePathname } from "next/navigation";
import { C, useIsMobile } from "@/lib/ui";

/**
 * Phase 2.1 — Restructured navigation
 * 4 workflow-aligned sections, 7 primary routes, 3 legacy redirects
 */
const NAV_SECTIONS = [
  {
    label: "MARKET",
    items: [
      { key: "dashboard", href: "/dashboard", label: "Dashboard", icon: "📊" },
      { key: "gex", href: "/gex", label: "GEX Intelligence", icon: "🎯" },
    ],
  },
  {
    label: "BUILD",
    items: [
      { key: "paper", href: "/paper", label: "Strategy Builder", icon: "⚡" },
    ],
  },
  {
    label: "MANAGE",
    items: [
      { key: "positions", href: "/positions", label: "Positions", icon: "📐" },
      { key: "portfolio", href: "/portfolio", label: "Portfolio", icon: "💼" },
      { key: "orders", href: "/orders", label: "Orders", icon: "📋" },
    ],
  },
  {
    label: "SYSTEM",
    items: [
      { key: "brokers", href: "/brokers", label: "Brokers", icon: "🔗" },
      { key: "settings", href: "/settings", label: "Settings", icon: "⚙️" },
    ],
  },
];

/**
 * Legacy route mapping — maps old paths to active nav keys.
 * Old routes still resolve (no broken links) but highlight the correct nav item.
 */
const ROUTE_KEY_MAP = {
  "/dashboard": "dashboard",
  "/gex": "gex",
  "/paper": "paper",
  "/positions": "positions",
  "/portfolio": "portfolio",
  "/orders": "orders",
  "/brokers": "brokers",
  "/settings": "settings",
  // Legacy redirects
  "/market": "dashboard",
  "/strategies": "paper",
  "/activity": "orders",
};

function getActiveKey(pathname) {
  if (!pathname) return "dashboard";
  if (ROUTE_KEY_MAP[pathname]) return ROUTE_KEY_MAP[pathname];
  for (const [route, key] of Object.entries(ROUTE_KEY_MAP)) {
    if (pathname.startsWith(route + "/")) return key;
  }
  return "dashboard";
}

/* ---------- Top Bar ---------- */

function TopBar({ executionMode, marketStatus, sidebarOpen, onToggleSidebar, authUser, onLogout }) {
  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        height: 48,
        background: C.surface,
        borderBottom: `1px solid ${C.border}`,
        display: "flex",
        alignItems: "center",
        padding: "0 16px",
        zIndex: 100,
        gap: 12,
      }}
    >
      {/* Hamburger (mobile) */}
      <button
        onClick={onToggleSidebar}
        style={{
          display: "none",
          background: "none",
          border: "none",
          color: C.muted,
          fontSize: 18,
          cursor: "pointer",
          padding: 4,
        }}
        className="shell-hamburger"
        aria-label="Toggle navigation"
      >
        {sidebarOpen ? "✕" : "☰"}
      </button>

      {/* App title */}
      <div
        style={{
          fontSize: 14,
          fontWeight: 700,
          color: C.gold,
          letterSpacing: 0.5,
          whiteSpace: "nowrap",
        }}
      >
        Options Dashboard
      </div>

      {/* Execution mode badge */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginLeft: 8,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1,
            padding: "3px 8px",
            borderRadius: 4,
            background:
              executionMode === "PAPER"
                ? "rgba(201,161,90,0.15)"
                : "rgba(76,175,125,0.15)",
            color: executionMode === "PAPER" ? C.gold : C.green,
            border: `1px solid ${executionMode === "PAPER" ? "rgba(201,161,90,0.3)" : "rgba(76,175,125,0.3)"}`,
          }}
        >
          {executionMode}
        </span>
        <span style={{ fontSize: 10, color: C.faint }}>
          {executionMode === "PAPER"
            ? "Simulated — no broker orders"
            : executionMode === "LIVE"
              ? "Live — orders sent to broker"
              : "Simulated — no broker orders"}
        </span>
      </div>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Market status indicator */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: 3,
            background:
              marketStatus === "open"
                ? C.green
                : marketStatus === "closed"
                  ? C.red
                  : C.faint,
          }}
        />
        <span style={{ fontSize: 11, color: C.muted, letterSpacing: 0.5 }}>
          {marketStatus === "open"
            ? "MARKET OPEN"
            : marketStatus === "closed"
              ? "MARKET CLOSED"
              : "MARKET UNKNOWN"}
        </span>
      </div>

      {/* Auth indicator */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {authUser ? (
          <>
            <a
              href="/settings"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 11,
                fontWeight: 600,
                color: C.muted,
                textDecoration: "none",
                padding: "3px 10px",
                borderRadius: 6,
                border: `1px solid ${C.border}`,
                background: "rgba(76,175,125,0.06)",
                transition: "border-color 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.green; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.border; }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 3,
                  background: C.green,
                  flexShrink: 0,
                }}
              />
              {authUser.display_name || authUser.email || "Account"}
            </a>
            <button
              onClick={onLogout}
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: C.muted,
                background: "none",
                border: `1px solid ${C.border}`,
                borderRadius: 6,
                padding: "4px 10px",
                cursor: "pointer",
                fontFamily: "inherit",
                transition: "color 0.15s, border-color 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = C.red; e.currentTarget.style.borderColor = C.red; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = C.muted; e.currentTarget.style.borderColor = C.border; }}
            >
              Sign Out
            </button>
          </>
        ) : (
          <a
            href="/settings"
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: C.gold,
              textDecoration: "none",
              padding: "3px 10px",
              borderRadius: 6,
              border: `1px solid ${C.gold}44`,
              transition: "border-color 0.15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.gold; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = `${C.gold}44`; }}
          >
            Sign In
          </a>
        )}
      </div>
    </div>
  );
}

/* ---------- Sidebar ---------- */

function Sidebar({ activeKey, isMobile, isOpen, onClose }) {
  return (
    <nav
      className={`shell-sidebar${isOpen ? " shell-open" : ""}`}
      style={{
        position: "fixed",
        top: 48,
        left: 0,
        bottom: 0,
        width: isOpen ? 220 : 0,
        minWidth: isOpen ? 220 : 0,
        background: C.surface,
        borderRight: isOpen ? `1px solid ${C.border}` : "none",
        overflow: "hidden",
        transition: "width 0.2s ease, min-width 0.2s ease",
        zIndex: 90,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: isOpen ? "12px 0" : 0,
          display: "flex",
          flexDirection: "column",
          gap: 2,
          minWidth: 220,
        }}
      >
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1.5,
                color: C.faint,
                padding: "12px 16px 4px",
                textTransform: "uppercase",
              }}
            >
              {section.label}
            </div>
            {section.items.map((item) => {
              const isActive = activeKey === item.key;
              return (
                <a
                  key={item.key}
                  href={item.href}
                  onClick={isMobile ? onClose : undefined}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "8px 16px",
                    fontSize: 13,
                    fontWeight: isActive ? 600 : 400,
                    color: isActive ? C.gold : C.muted,
                    textDecoration: "none",
                    background: isActive ? "rgba(201,161,90,0.08)" : "transparent",
                    borderLeft: isActive
                      ? `2px solid ${C.gold}`
                      : "2px solid transparent",
                    transition: "background 0.15s, color 0.15s",
                  }}
                >
                  <span style={{ fontSize: 14, width: 20, textAlign: "center" }}>
                    {item.icon}
                  </span>
                  <span>{item.label}</span>
                </a>
              );
            })}
          </div>
        ))}
      </div>
    </nav>
  );
}

/* ---------- Shell ---------- */

export default function Shell({ children, executionMode = "PAPER", marketStatus = "unknown" }) {
  const pathname = usePathname();
  const isMobile = useIsMobile(900);
  const [sidebarOpen, setSidebarOpen] = useState(!isMobile);
  const [authUser, setAuthUser] = useState(null);

  // Lightweight auth check — reads session from localStorage and checks status
  useEffect(() => {
    (async () => {
      try {
        const { getSessionId } = await import("@/lib/session");
        const { getStatus, getMe } = await import("@/lib/api");
        const session = getSessionId();
        if (!session) return;
        const status = await getStatus();
        if (status.logged_in) {
          const me = await getMe();
          setAuthUser(me);
        }
      } catch {
        // Not logged in or session expired — silently ignore
      }
    })();
  }, []);

  const handleLogout = useCallback(async () => {
    try {
      const { logoutUser } = await import("@/lib/api");
      const { clearSessionId } = await import("@/lib/session");
      await logoutUser();
      clearSessionId();
    } catch {
      // Ignore
    }
    setAuthUser(null);
  }, []);

  const activeKey = getActiveKey(pathname);

  // Close sidebar on mobile by default
  useEffect(() => {
    if (isMobile) setSidebarOpen(false);
    else setSidebarOpen(true);
  }, [isMobile]);

  // Close sidebar on navigation on mobile
  useEffect(() => {
    if (isMobile) setSidebarOpen(false);
  }, [pathname, isMobile]);

  const contentMarginLeft = isMobile ? 0 : sidebarOpen ? 220 : 0;

  return (
    <>
      <style>{`
        @media (max-width: 900px) {
          .shell-hamburger { display: block !important; }
          .shell-sidebar { width: 0 !important; min-width: 0 !important; }
          .shell-sidebar.shell-open { width: 220px !important; min-width: 220px !important; }
        }
      `}</style>

      <TopBar
        executionMode={executionMode}
        marketStatus={marketStatus}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
        authUser={authUser}
        onLogout={handleLogout}
      />

      <Sidebar
        activeKey={activeKey}
        isMobile={isMobile}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Mobile overlay */}
      {isMobile && sidebarOpen && (
        <div
          style={{
            position: "fixed",
            top: 48,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: 80,
          }}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Main content */}
      <main
        style={{
          marginTop: 48,
          marginLeft: contentMarginLeft,
          minHeight: "calc(100vh - 48px)",
          transition: "margin-left 0.2s ease",
          padding: 16,
        }}
      >
        {children}
      </main>
    </>
  );
}
