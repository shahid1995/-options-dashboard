"use client";
import { COLOR, TYPE, RADIUS, SPACE } from "./tokens";
import { useIsMobile } from "@/lib/ui";

export default function CTASection({ headline, body, primaryLabel, primaryHref, primaryOnClick, secondaryLabel, secondaryHref, secondaryOnClick }) {
  const isMobile = useIsMobile();

  const primaryStyle = {
    fontSize: TYPE.label.size,
    lineHeight: TYPE.label.lineHeight,
    padding: "14px 30px",
    display: "inline-flex",
    alignItems: "center",
    gap: SPACE.small,
    borderRadius: RADIUS.md,
    fontWeight: TYPE.label.weight,
    letterSpacing: "normal",
    textDecoration: "none",
    cursor: "pointer",
    fontFamily: TYPE.body,
  };

  const secondaryStyle = {
    ...primaryStyle,
    background: "transparent",
    color: COLOR.textPrimary,
    border: `1px solid ${COLOR.borderStrong}`,
  };

  return (
    <section style={{ padding: isMobile ? "16px 20px 80px" : "24px 20px 100px" }}>
      <div
        style={{
          maxWidth: 900,
          margin: "0 auto",
          textAlign: "center",
          padding: isMobile ? "48px 24px" : "72px 48px",
          borderRadius: 18,
          background: "radial-gradient(ellipse 70% 90% at 50% 0%, rgba(201,161,90,0.16), transparent 65%), linear-gradient(180deg, #12161F, #0B0E14)",
          border: "1px solid rgba(201,161,90,0.25)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
        }}
      >
        <h2
          style={{
            margin: "0 0 14px",
            fontSize: TYPE.h2.size,
            letterSpacing: TYPE.h2.letterSpacing,
            fontWeight: TYPE.h2.weight,
            color: COLOR.textPrimary,
            lineHeight: TYPE.h2.lineHeight,
            fontFamily: TYPE.display,
          }}
        >
          {headline}
        </h2>
        {body && (
          <p
            style={{
              color: COLOR.textMuted,
              fontSize: TYPE.body.size,
              maxWidth: 520,
              margin: "0 auto 30px",
              lineHeight: TYPE.body.lineHeight,
              fontFamily: TYPE.body,
            }}
          >
            {body}
          </p>
        )}
        <div style={{ display: "flex", gap: SPACE.medium, justifyContent: "center", flexWrap: "wrap" }}>
          {primaryLabel && primaryOnClick ? (
            <button data-testid="cta-primary-button" onClick={primaryOnClick} className="od-btn-gold" style={{ ...primaryStyle, background: COLOR.strategy, color: COLOR.baseElevated, border: `1px solid ${COLOR.strategy}` }}>
              {primaryLabel} <span aria-hidden>&rarr;</span>
            </button>
          ) : primaryLabel ? (
            <a className="od-btn-gold" href={primaryHref || "/"} style={{ ...primaryStyle, background: COLOR.strategy, color: COLOR.baseElevated, border: `1px solid ${COLOR.strategy}` }}>
              {primaryLabel} <span aria-hidden>&rarr;</span>
            </a>
          ) : null}
          {secondaryLabel && secondaryOnClick ? (
            <button data-testid="cta-secondary-button" onClick={secondaryOnClick} className="od-btn-ghost" style={secondaryStyle}>
              {secondaryLabel}
            </button>
          ) : secondaryLabel ? (
            <a className="od-btn-ghost" href={secondaryHref || "/"} style={secondaryStyle}>
              {secondaryLabel}
            </a>
          ) : null}
        </div>
      </div>
    </section>
  );
}
