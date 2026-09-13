"use client";
import { useState, useEffect, useCallback } from "react";
import { usePathname, useRouter } from "next/navigation";
import { C, useIsMobile } from "@/lib/ui";
import { COLOR, SPACE, RADIUS, LAYER } from "@/components/public/tokens";

/**
 * Phase C — Application shell
 * 4 workflow-aligned sections, canonical token surfaces, improved navigation hierarchy.
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

const ROUTE_KEY_MAP = {
  "/dashboard": "dashboard",
  "/gex": "gex",
  "/paper": "paper",
  "/positions": "positions",
  "/portfolio": "portfolio",
  "/orders": "orders",
  "/brokers": "brokers",
  "/settings": "settings",
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

const SIDEBAR_WIDTH = 220;
const TOP_BAR_HEIGHT = 52;

/* ---------- Top Bar ---------- */

function TopBar({ executionMode, marketStatus, sidebarOpen, onToggleSidebar, authUser, onLogout }) {
  return (
    <header
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        height: TOP_BAR_HEIGHT,
        background: COLOR.surface,
        borderBottom: `1px solid ${COLOR.border}`,
        display: "flex",
        alignItems: "center",
        padding: `0 ${SPACE.comp}`,
        zIndex: LAYER.sticky,
        gap: SPACE.comp,
      }}
    >
      <button
        onClick={onToggleSidebar}
        style={{
          display: "none",
          background: "none",
          border: "none",
          color: COLOR.textMuted,
          fontSize: 18,
          cursor: "pointer",
          padding: SPACE.xs,
        }}
        className="shell-hamburger"
        aria-label="Toggle navigation"
      >
        {sidebarOpen ? "✕" : "☰"}
      </button>

      <div
        style={{
          fontSize: 14,
          fontWeight: 800,
          color: COLOR.strategy,
          letterSpacing: 0.8,
          whiteSpace: "nowrap",
        }}
      >
        STRIKENOVA
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: SPACE.small, marginLeft: SPACE.small }}>
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1,
            padding: `${SPACE.xs} ${SPACE.small}`,
            borderRadius: RADIUS.sm,
            background: executionMode === "PAPER" ? "rgba(201,161,90,0.15)" : "rgba(76,175,125,0.15)",
            color: executionMode === "PAPER" ? COLOR.strategy : COLOR.positive,
            border: `1px solid ${executionMode === "PAPER" ? "rgba(201,161,90,0.3)" : "rgba(76,175,125,0.3)"}`,
          }}
        >
          {executionMode}
        </span>
        <span style={{ fontSize: 10, color: COLOR.textFaint }}>
          {executionMode === "PAPER"
            ? "Simulated — no broker orders"
            : executionMode === "LIVE"
              ? "Live — orders sent to broker"
              : "Simulated — no broker orders"}
        </span>
      </div>

      <div style={{ flex: 1 }} />

      <div style={{ display: "flex", alignItems: "center", gap: SPACE.small }}>
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            background:
              marketStatus === "open"
                ? COLOR.positive
                : marketStatus === "closed"
                  ? COLOR.negative
                  : COLOR.textFaint,
          }}
        />
        <span style={{ fontSize: 11, color: COLOR.textMuted, letterSpacing: 0.5 }}>
          {marketStatus === "open"
            ? "MARKET OPEN"
            : marketStatus === "closed"
              ? "MARKET CLOSED"
              : "MARKET UNKNOWN"}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: SPACE.small }}>
        {authUser ? (
          <>
            <a
              href="/settings"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: SPACE.small,
                fontSize: 11,
                fontWeight: 600,
                color: COLOR.textMuted,
                textDecoration: "none",
                padding: `${SPACE.xs} ${SPACE.small}`,
                borderRadius: RADIUS.md,
                border: `1px solid ${COLOR.border}`,
                background: "rgba(76,175,125,0.06)",
                transition: "border-color 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = COLOR.positive; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = COLOR.border; }}
            >
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: COLOR.positive, flexShrink: 0 }} />
              {authUser.display_name || authUser.email || "Account"}
            </a>
            <button
              onClick={onLogout}
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: COLOR.textMuted,
                background: "none",
                border: `1px solid ${COLOR.border}`,
                borderRadius: RADIUS.md,
                padding: `${SPACE.xs} ${SPACE.small}`,
                cursor: "pointer",
                fontFamily: "inherit",
                transition: "color 0.15s, border-color 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = COLOR.negative; e.currentTarget.style.borderColor = COLOR.negative; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = COLOR.textMuted; e.currentTarget.style.borderColor = COLOR.border; }}
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
              color: COLOR.strategy,
              textDecoration: "none",
              padding: `${SPACE.xs} ${SPACE.small}`,
              borderRadius: RADIUS.md,
              border: `1px solid ${COLOR.strategy}44`,
              transition: "border-color 0.15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = COLOR.strategy; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = `${COLOR.strategy}44`; }}
          >
            Sign In
          </a>
        )}
      </div>
    </header>
  );
}

/* ---------- Sidebar ---------- */

function Sidebar({ activeKey, isMobile, isOpen, onClose }) {
  return (
    <nav
      className={`shell-sidebar${isOpen ? " shell-open" : ""}`}
      style={{
        position: "fixed",
        top: TOP_BAR_HEIGHT,
        left: 0,
        bottom: 0,
        width: isOpen ? SIDEBAR_WIDTH : 0,
        minWidth: isOpen ? SIDEBAR_WIDTH : 0,
        background: COLOR.surface,
        borderRight: isOpen ? `1px solid ${COLOR.border}` : "none",
        overflow: "hidden",
        transition: "width 0.2s ease, min-width 0.2s ease",
        zIndex: LAYER.overlay - 10,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: isOpen ? `${SPACE.comp} 0` : 0,
          display: "flex",
          flexDirection: "column",
          gap: SPACE.xs,
          minWidth: SIDEBAR_WIDTH,
          overflowY: "auto",
        }}
      >
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1.5,
                color: COLOR.textFaint,
                padding: `${SPACE.comp} ${SPACE.comp} ${SPACE.xs}`,
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
                  className={isActive ? "shell-nav-active" : undefined}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: SPACE.small,
                    padding: `${SPACE.small} ${SPACE.comp}`,
                    fontSize: 13,
                    fontWeight: isActive ? 600 : 400,
                    color: isActive ? COLOR.strategy : COLOR.textMuted,
                    textDecoration: "none",
                    background: isActive ? "rgba(201,161,90,0.08)" : "transparent",
                    borderLeft: isActive
                      ? `2px solid ${COLOR.strategy}`
                      : "2px solid transparent",
                    transition: "background 0.15s, color 0.15s",
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.background = COLOR.surfaceElevated;
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.background = "transparent";
                    }
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
      } catch {}
    })();
  }, []);

  const router = useRouter();

  const handleLogout = useCallback(async () => {
    try {
      const { logoutUser } = await import("@/lib/api");
      const { clearSessionId } = await import("@/lib/session");
      await logoutUser();
      clearSessionId();
    } catch {}
    setAuthUser(null);
    router.replace("/");
  }, [router]);

  const activeKey = getActiveKey(pathname);

  useEffect(() => {
    if (isMobile) setSidebarOpen(false);
    else setSidebarOpen(true);
  }, [isMobile]);

  useEffect(() => {
    if (isMobile) setSidebarOpen(false);
  }, [pathname, isMobile]);

  const contentMarginLeft = isMobile ? 0 : sidebarOpen ? SIDEBAR_WIDTH : 0;

  return (
    <>
      <style>{`
        @media (max-width: 900px) {
          .shell-hamburger { display: block !important; }
          .shell-sidebar { width: 0 !important; min-width: 0 !important; }
          .shell-sidebar.shell-open { width: ${SIDEBAR_WIDTH}px !important; min-width: ${SIDEBAR_WIDTH}px !important; }
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

      {isMobile && sidebarOpen && (
        <div
          style={{
            position: "fixed",
            top: TOP_BAR_HEIGHT,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: LAYER.overlay - 20,
          }}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <main
        style={{
          marginTop: TOP_BAR_HEIGHT,
          marginLeft: contentMarginLeft,
          minHeight: `calc(100vh - ${TOP_BAR_HEIGHT}px)`,
          transition: "margin-left 0.2s ease",
        }}
      >
        {children}
      </main>
    </>
  );
}
