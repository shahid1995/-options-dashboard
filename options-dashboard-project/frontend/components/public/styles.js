// Shared style constants and CSS strings for public marketing pages.
// Uses the same design tokens as the main app (C from lib/ui).

import { C } from "@/lib/ui";

// Global CSS injected once per public page via <style>
export const PUBLIC_CSS = `
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
html { scroll-behavior: smooth; }
@keyframes od-fade-up { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
@keyframes od-ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes od-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@keyframes od-glow { 0%, 100% { box-shadow: 0 0 0 0 rgba(201, 161, 90, 0.28); } 50% { box-shadow: 0 0 0 8px rgba(201, 161, 90, 0); } }
@keyframes od-bar-fill { from { width: 0; } }
.od-fade { animation: od-fade-up 0.6s cubic-bezier(0.22, 1, 0.36, 1) both; }
.od-pulse { animation: od-pulse 1.6s ease-in-out infinite; }
.od-bar-fill { animation: od-bar-fill 1s cubic-bezier(0.22, 1, 0.36, 1) both; }

.od-btn-gold {
  display: inline-flex; align-items: center; gap: 8px;
  background: ${C.gold}; color: #0B0E14;
  padding: 12px 24px; border-radius: 8px; font-weight: 700; font-size: 14.5px;
  text-decoration: none; border: 1px solid ${C.gold};
  transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.od-btn-gold:hover { background: #D9B36A; box-shadow: 0 6px 24px rgba(201, 161, 90, 0.35); transform: translateY(-1px); }
.od-btn-ghost {
  display: inline-flex; align-items: center; gap: 8px;
  background: transparent; color: ${C.text};
  padding: 12px 24px; border-radius: 8px; font-weight: 600; font-size: 14.5px;
  text-decoration: none; border: 1px solid ${C.border};
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}
.od-btn-ghost:hover { border-color: ${C.gold}; background: rgba(201, 161, 90, 0.07); transform: translateY(-1px); }
.od-link { color: ${C.muted}; text-decoration: none; font-size: 14px; transition: color 0.15s ease; }
.od-link:hover { color: ${C.gold}; }
.od-card { transition: transform 0.18s ease, border-color 0.18s ease; }
.od-card:hover { transform: translateY(-3px); border-color: rgba(201, 161, 90, 0.45) !important; }

/* Focus-visible ring for all interactive elements */
a:focus-visible, button:focus-visible, [tabindex]:focus-visible {
  outline: 2px solid ${C.gold};
  outline-offset: 2px;
  border-radius: 4px;
}
.od-btn-gold:focus-visible, .od-btn-ghost:focus-visible {
  outline: 2px solid ${C.gold};
  outline-offset: 2px;
}
.od-ticker-track { display: flex; width: max-content; animation: od-ticker 36s linear infinite; }
.od-ticker-track:hover { animation-play-state: paused; }

@media (max-width: 768px) {
  .pub-nav-links { display: none !important; }
  .pub-nav-mobile-toggle { display: flex !important; }
}
@media (min-width: 769px) {
  .pub-mobile-menu { display: none !important; }
}
`;

// Reusable page container max-width
export const PAGE_MAX = 1100;

// Shared section padding
export const sectionPad = (isMobile) => ({
  maxWidth: PAGE_MAX,
  margin: "0 auto",
  padding: isMobile ? "72px 20px" : "96px 20px",
});

// Common "illustrative data" disclaimer style
export const DEMO_LABEL_STYLE = {
  display: "inline-block",
  fontSize: 11,
  letterSpacing: 1,
  color: C.faint,
  background: "rgba(90, 99, 118, 0.2)",
  border: `1px solid ${C.border}`,
  borderRadius: 4,
  padding: "2px 8px",
  marginBottom: 12,
};
