# Implementation Plan: StrikeNova Public Home — Evidence & Trust Section

**Branch**: `feat/strikenova-day35-portfolio-intelligence` | **Date**: 2026-09-12** | **Spec**: [specs/001-evidence-trust-section/spec.md](../specs/001-evidence-trust-section/spec.md)

---

## Summary

Add a concise "Evidence & Trust" section to the existing public Home page (`frontend/app/(public)/page.js`) that provides explicit trust clarification and transparency about StrikeNova's evidence-orientation, decision-support boundaries, paper-trading mode, and inherent uncertainty in options markets. Includes a "Learn More" CTA linking to `/about`.

This is a purely presentational, frontend-only feature using the existing public design system. No backend changes, no new API endpoints, no database schema changes. Content is separated from presentation logic via a dedicated content file.

---

## Technical Context

**Language/Version**: JavaScript (React 18, Next.js 14)

**Primary Dependencies**: React, Next.js 14, existing public design system (`@/components/public/*`)

**Storage**: N/A (content is static, in a separate content data file)

**Testing**: Vitest (existing frontend test framework, `vitest.config.js`)

**Target Platform**: Web browser (public landing page)

**Project Type**: Web application (Next.js App Router)

**Performance Goals**: No measurable performance impact; section renders within existing page budget

**Constraints**:
- Must use existing public design tokens (`COLOR`, `TYPE`, `SPACE`, `RADIUS` from `@/components/public/tokens`)
- Must use existing layout primitives (`Section`, `Container` from `@/components/public/layout`)
- Must not exceed existing Home page render budget
- Must not introduce new npm dependencies for v1
- Content MUST be separated from presentation logic

**Scale/Scope**: One new component, one content data file, one section added to existing Home page. Approximately 3-5 files changed.

---

## Constitution Check

| Gate | Status | Justification |
|------|--------|---------------|
| Evidence Before Assertion | ✅ PASS | Spec does not assert unverified claims |
| Scope Discipline | ✅ PASS | Feature bounded to single section |
| TDD/VDE | ✅ PASS | Implementation will follow existing TDD discipline per `STRIKENOVA_EXECUTION_PROTOCOL.md` |
| Preserve Architecture | ✅ PASS | Uses existing public design system, no architecture changes |
| Security/Credentials | ✅ PASS | No credentials involved |
| Boundary Preservation | ✅ PASS | Public-only, no app/auth boundary crossing |
| Paper-Trading Safety | ✅ PASS | Explicitly reinforces paper-trading boundary |
| Reproducible Changes | ✅ PASS | All changes in Git, spec-driven |
| Founder Authority | ✅ PASS | Spec subordinate to governance hierarchy |
| Spec/Exec Separation | ✅ PASS | Spec Kit defines WHAT, Superpowers governs execution |
| Unknown/Proposed/Accepted | ✅ PASS | Feature is proposed, not claimed as accepted fact |
| Historical Integrity | ✅ PASS | No historical records modified |

**No violations. Proceed to Phase 0.**

---

## Phase 0: Outline & Research

### Decisions

| Unknown | Decision | Rationale | Alternatives Considered |
|---------|----------|-----------|------------------------|
| Where should section content live? | Co-located content data file in `frontend/components/public/` (e.g., `EvidenceTrustContent.js`) | Content separated from presentation logic; copy can be updated without modifying component's structural/rendering logic; matches existing pattern of co-located content in public components | CMS (overkill v1), database (no backend requirement), inline in component (content not separated from logic) |
| What component name? | `EvidenceTrustSection` | Matches existing `Section`, `Container`, `CTASection` naming convention in public components | `TrustBadge`, `EvidenceBanner` (less aligned with layout primitives) |
| Where to place section in Home page? | After `MarketIntelligenceGrid` (Section 04) and before `StrategyLab` (Section 05) | Logical flow: market context → evidence/trust → strategy lab. Visitor understands the market, then understands the platform's relationship to it, then explores strategy | Before hero (too early, no context), after CTA (too late, trust should precede engagement) |
| Mobile rendering approach? | Use existing `isMobile` hook + `Section`/`Container` primitives (already responsive) | Consistent with all other sections on the page | Custom breakpoint logic (duplicates existing infrastructure) |
| CTA destination | `/about` | About page contains product philosophy, principles, and explicit "NOT A GUARANTEED-PROFIT SYSTEM" positioning. Better supports trust clarification and transparency goals than `/how-it-works` which focuses on workflow steps | `/how-it-works` (focuses on workflow steps, not philosophy/boundary clarification) |

### Phase 0 Output

`research.md` consolidated above. No remaining NEEDS CLARIFICATION markers.

---

## Phase 1: Design & Contracts

### Data Model

**Entity: EvidenceTrustSectionContent**

| Field | Type | Purpose |
|-------|------|---------|
| `eyebrow` | string | Short eyebrow label (e.g., "EVIDENCE & TRUST") |
| `title` | string | Section headline |
| `description` | string | Primary explanation paragraph |
| `points` | Array<{ title: string, body: string }>} | 3-4 evidence/trust points |
| `disclaimer` | string | Risk/uncertainty disclaimer text |
| `ctaLabel` | string | "Learn More" button label |
| `ctaHref` | string | Destination path |

**Source of truth**: Static content in `EvidenceTrustContent.js`. No database, no API.

### UI Contract

```
EvidenceTrustSection
  └── Section (layout primitive, borderTop: 1px solid COLOR.border)
       └── Container (maxWidth: 1100)
            ├── SectionTitle
            │    ├── eyebrow: "EVIDENCE & TRUST"
            │    ├── title: "Built on evidence. Not guarantees."
            │    └── description: "StrikeNova turns market data into..."
            ├── Points Grid (responsive, 2-col desktop / 1-col mobile)
            │    └── Point Card × 3-4
            │         ├── title (COLOR.textPrimary)
            │         └── body (COLOR.textSecondary)
            ├── Disclaimer (COLOR.textFaint, smaller type)
            └── CTA (LinkButton → /about)
```

**Styling**: Uses `COLOR`, `TYPE`, `SPACE`, `RADIUS` tokens from `@/components/public/tokens`. No new tokens required.

**No new API contracts.** No new database schemas.

### Quickstart Validation

1. Navigate to `http://localhost:3000/`
2. Scroll past Section 04 (Market Intelligence)
3. Verify "EVIDENCE & TRUST" eyebrow is visible
4. Verify headline communicates evidence/decision-support orientation
5. Verify paper-trading boundary is stated
6. Verify risk/uncertainty disclaimer is present
7. Verify "Learn More About StrikeNova" link is visible and links to `/about`
8. Resize browser to 320px, 768px, 1280px — verify no layout breakage
9. Verify no claims of guaranteed accuracy or live trading

---

## Project Structure

### Documentation (this feature)

```text
specs/001-evidence-trust-section/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (content contract)
│   └── content.md
└── checklists/
    └── requirements.md  # From /speckit-specify
```

### Source Code (repository root)

```text
frontend/
├── app/
│   └── (public)/
│       └── page.js              # MODIFIED: add EvidenceTrustSection import + render
└── components/
    └── public/
        ├── EvidenceTrustSection.js   # NEW: presentational component
        └── EvidenceTrustContent.js   # NEW: static content separated from logic
```

**Files changed**: 1 (`page.js`)
**Files created**: 2 (`EvidenceTrustSection.js`, `EvidenceTrustContent.js`)
**Files unchanged**: All backend, app routes, tests (except new tests per TDD)

---

## Complexity Tracking

No Constitution Check violations. No complexity gates triggered.
