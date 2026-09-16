// Shared style constants and CSS strings for public marketing pages.
import { COLOR, TYPE, RADIUS, SPACE, MOTION } from "./tokens";

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

/* Legacy class names retained for compatibility, but now consume canonical tokens. */
.od-btn-gold {
  display: inline-flex; align-items: center; gap: ${SPACE.small};
  background: ${COLOR.strategy}; color: ${COLOR.baseElevated};
  padding: 12px 24px; border-radius: ${RADIUS.md}; font-weight: ${TYPE.label.weight}; font-size: ${TYPE.label.size};
  line-height: ${TYPE.label.lineHeight}; font-family: ${TYPE.body};
  text-decoration: none; border: 1px solid ${COLOR.strategy};
  transition: transform ${MOTION.fast} ease, box-shadow ${MOTION.fast} ease, background ${MOTION.fast} ease;
}
.od-btn-gold:hover { background: #D9B36A; box-shadow: 0 6px 24px rgba(201, 161, 90, 0.35); transform: translateY(-1px); }
.od-btn-ghost {
  display: inline-flex; align-items: center; gap: ${SPACE.small};
  background: transparent; color: ${COLOR.textPrimary};
  padding: 12px 24px; border-radius: ${RADIUS.md}; font-weight: 600; font-size: ${TYPE.label.size};
  line-height: ${TYPE.label.lineHeight}; font-family: ${TYPE.body};
  text-decoration: none; border: 1px solid ${COLOR.borderStrong};
  transition: border-color ${MOTION.fast} ease, background ${MOTION.fast} ease, transform ${MOTION.fast} ease;
}
.od-btn-ghost:hover { border-color: ${COLOR.strategy}; background: ${COLOR.strategyDim}; transform: translateY(-1px); }
.od-link { color: ${COLOR.textMuted}; text-decoration: none; font-size: ${TYPE.bodySmall.size}; transition: color ${MOTION.fast} ease; }
.od-link:hover { color: ${COLOR.strategy}; }
.od-card { transition: transform 0.18s ease, border-color 0.18s ease; }
.od-card:hover { transform: translateY(-3px); border-color: rgba(201, 161, 90, 0.45) !important; }

a:focus-visible, button:focus-visible, [tabindex]:focus-visible {
  outline: 2px solid ${COLOR.strategy};
  outline-offset: 2px;
  border-radius: ${RADIUS.sm};
}
.od-btn-gold:focus-visible, .od-btn-ghost:focus-visible {
  outline: 2px solid ${COLOR.strategy};
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

export const PAGE_MAX = 1100;

export const sectionPad = (isMobile) => ({
  maxWidth: PAGE_MAX,
  margin: "0 auto",
  padding: isMobile ? "72px 20px" : "96px 20px",
});

export const DEMO_LABEL_STYLE = {
  display: "inline-block",
  fontSize: TYPE.labelSmall.size,
  letterSpacing: TYPE.labelSmall.letterSpacing,
  color: COLOR.textFaint,
  background: "rgba(120, 128, 148, 0.16)",
  border: `1px solid ${COLOR.border}`,
  borderRadius: RADIUS.sm,
  padding: "2px 8px",
  marginBottom: 12,
};
