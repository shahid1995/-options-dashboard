"use client";
import { C, useIsMobile } from "@/lib/ui";
import { PAGE_MAX } from "./styles";

export default function CTASection({ headline, body, primaryLabel, primaryHref, primaryOnClick, secondaryLabel, secondaryHref, secondaryOnClick }) {
  const isMobile = useIsMobile();

  const primaryStyle = {
    fontSize: 15,
    padding: "14px 30px",
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    borderRadius: 8,
    fontWeight: 700,
    textDecoration: "none",
    border: "none",
    cursor: "pointer",
    fontFamily: "inherit",
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
          background:
            "radial-gradient(ellipse 70% 90% at 50% 0%, rgba(201,161,90,0.16), transparent 65%), linear-gradient(180deg, #12161F, #0B0E14)",
          border: "1px solid rgba(201,161,90,0.25)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
        }}
      >
        <h2
          style={{
            margin: "0 0 14px",
            fontSize: isMobile ? 26 : 34,
            letterSpacing: -0.5,
            fontWeight: 800,
            color: C.text,
            lineHeight: 1.15,
          }}
        >
          {headline}
        </h2>
        {body && (
          <p style={{ color: C.muted, fontSize: 15, maxWidth: 520, margin: "0 auto 30px", lineHeight: 1.7 }}>
            {body}
          </p>
        )}
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
          {primaryLabel && primaryOnClick ? (
            <button
              data-testid="cta-primary-button"
              onClick={primaryOnClick}
              className="od-btn-gold"
              style={primaryStyle}
            >
              {primaryLabel} <span aria-hidden>&rarr;</span>
            </button>
          ) : primaryLabel ? (
            <a className="od-btn-gold" href={primaryHref || "/"} style={primaryStyle}>
              {primaryLabel} <span aria-hidden>&rarr;</span>
            </a>
          ) : null}
          {secondaryLabel && secondaryOnClick ? (
            <button
              data-testid="cta-secondary-button"
              onClick={secondaryOnClick}
              className="od-btn-ghost"
              style={{ ...primaryStyle, background: "transparent", color: C.text, border: `1px solid ${C.border}` }}
            >
              {secondaryLabel}
            </button>
          ) : secondaryLabel ? (
            <a className="od-btn-ghost" href={secondaryHref || "/"} style={primaryStyle}>
              {secondaryLabel}
            </a>
          ) : null}
        </div>
      </div>
    </section>
  );
}
