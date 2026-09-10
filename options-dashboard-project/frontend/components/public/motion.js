// =============================================================================
// StrikeNova Public Design System — Motion & CSS Primitives
// =============================================================================
// Centralized CSS string for the public design system.
// Injected once per public page via <style> tag (same pattern as before).
//
// Contains: keyframes, utility classes, focus-visible rules, reduced-motion.
// =============================================================================

import { COLOR, MOTION } from "./tokens";

export const PUBLIC_DS_CSS = `
/* =============================================================================
   StrikeNova Public Design System — Motion Keyframes
   ============================================================================= */

@keyframes sn-fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes sn-fade-up {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes sn-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.35; }
}

@keyframes sn-signal-glow {
  0%, 100% { box-shadow: 0 0 0 0 ${COLOR.infoGlow}; }
  50%      { box-shadow: 0 0 0 8px rgba(34, 211, 238, 0); }
}

@keyframes sn-trace-draw {
  from { stroke-dashoffset: 100%; }
  to   { stroke-dashoffset: 0%; }
}

@keyframes sn-ticker {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}

@keyframes sn-bar-fill {
  from { width: 0; }
  to   { width: var(--bar-fill-width, 100%); }
}

@keyframes sn-node-appear {
  from { opacity: 0; transform: scale(0.85); }
  to   { opacity: 1; transform: scale(1); }
}

/* =============================================================================
   Utility Classes
   ============================================================================= */

.sn-fade { animation: sn-fade-up 0.6s ${MOTION.easeOut} both; }
.sn-fade-in { animation: sn-fade-in 0.4s ${MOTION.easeOut} both; }
.sn-pulse { animation: sn-pulse 1.6s ease-in-out infinite; }
.sn-bar-fill { animation: sn-bar-fill 1s ${MOTION.easeOut} both; }
.sn-node-appear { animation: sn-node-appear 0.35s ${MOTION.easeOut} both; }

/* Ticker track — pause on hover */
.sn-ticker-track {
  display: flex;
  width: max-content;
  animation: sn-ticker 36s linear infinite;
}
.sn-ticker-track:hover { animation-play-state: paused; }

/* =============================================================================
   Focus-Visible Ring
   ============================================================================= */

.ds-focus-ring:focus-visible,
.ds-btn:focus-visible,
.ds-link:focus-visible,
[tabindex]:focus-visible {
  outline: 2px solid ${COLOR.strategy};
  outline-offset: 2px;
  border-radius: 4px;
}

/* =============================================================================
   Reduced Motion
   ============================================================================= */

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  .sn-ticker-track { animation: none !important; }
}

/* =============================================================================
   Responsive Visibility
   ============================================================================= */

@media (max-width: 768px) {
  .ds-nav-desktop { display: none !important; }
  .ds-nav-mobile-toggle { display: flex !important; }
}
@media (min-width: 769px) {
  .ds-nav-mobile-menu { display: none !important; }
}
`;

// Motion utility: returns inline style object for a fade-up animation
export function fadeUpStyle(delay = 0) {
  return {
    animation: `${MOTION.keyframes.fadeUp} 0.6s ${MOTION.easeOut} both`,
    animationDelay: `${delay}s`,
  };
}

// Motion utility: returns inline style object for signal glow
export function signalGlowStyle(color = COLOR.info) {
  return {
    boxShadow: `0 0 0 1px ${color}26, 0 0 12px ${color}26`,
  };
}

// Motion utility: trace draw style for SVG paths
export function traceDrawStyle(delay = 0, duration = "1.2s") {
  return {
    strokeDasharray: "100%",
    strokeDashoffset: "100%",
    animation: `${MOTION.keyframes.traceDraw} ${duration} ${MOTION.signalTrace} ${delay}s both`,
  };
}
