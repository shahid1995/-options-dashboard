// =============================================================================
// StrikeNova Public Home — Evidence & Trust Section
// =============================================================================
// Presentational component for trust clarification and transparency.
// Content sourced from EvidenceTrustContent.js (separated from logic).
// =============================================================================

"use client";

import React from "react";
import { Section, Container, FlexColumn } from "./layout";
import { SectionTitle } from "./truth";
import { LinkButton } from "./buttons";
import { COLOR, TYPE, SPACE, RADIUS } from "./tokens";
import { useIsMobile } from "@/lib/ui";
import { evidenceTrustContent } from "./EvidenceTrustContent";

export default function EvidenceTrustSection() {
  const isMobile = useIsMobile();

  return (
    <Section style={{ borderTop: `1px solid ${COLOR.border}` }}>
      <Container maxWidth={1100}>
        <SectionTitle
          eyebrow={evidenceTrustContent.eyebrow}
          title={evidenceTrustContent.title}
          subtitle={evidenceTrustContent.description}
        />

        <FlexColumn gap={SPACE.cardLg}>
          {/* Points Grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
              gap: SPACE.card,
            }}
          >
            {evidenceTrustContent.points.map((point, index) => (
              <div
                key={index}
                style={{
                  padding: SPACE.cardLg,
                  background: COLOR.surface,
                  borderRadius: RADIUS.lg,
                  border: `1px solid ${COLOR.border}`,
                }}
              >
                <h4
                  style={{
                    margin: `0 0 ${SPACE.small}`,
                    fontSize: TYPE.h4.size,
                    fontWeight: TYPE.h4.weight,
                    color: COLOR.textPrimary,
                    letterSpacing: TYPE.h4.letterSpacing,
                  }}
                >
                  {point.title}
                </h4>
                <p
                  style={{
                    margin: 0,
                    fontSize: TYPE.body.size,
                    lineHeight: TYPE.body.lineHeight,
                    color: COLOR.textSecondary,
                  }}
                >
                  {point.body}
                </p>
              </div>
            ))}
          </div>

          {/* Disclaimer */}
          <p
            style={{
              fontSize: TYPE.bodySmall.size,
              lineHeight: TYPE.bodySmall.lineHeight,
              color: COLOR.textFaint,
              textAlign: "center",
              maxWidth: "60ch",
              margin: "0 auto",
            }}
          >
            {evidenceTrustContent.disclaimer}
          </p>

          {/* CTA */}
          <div style={{ textAlign: "center" }}>
            <LinkButton
              variant="secondary"
              size="md"
              href={evidenceTrustContent.ctaHref}
            >
              {evidenceTrustContent.ctaLabel} <span aria-hidden>→</span>
            </LinkButton>
          </div>
        </FlexColumn>
      </Container>
    </Section>
  );
}
