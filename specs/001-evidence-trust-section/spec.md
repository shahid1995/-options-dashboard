# Feature Specification: StrikeNova Public Home — Evidence & Trust Section

**Feature Branch**: `feat/strikenova-day35-portfolio-intelligence`

**Created**: 2026-09-12

**Status**: Draft

**Input**: User description: "StrikeNova Public Home — Evidence & Trust Section"

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — First-Time Visitor Understands StrikeNova's Purpose (Priority: P1)

A visitor lands on the public Home page. Within seconds, they understand:
- StrikeNova is an options intelligence and paper-trading platform
- It is designed for Indian index options (NIFTY)
- Its outputs are decision-support, not guaranteed trading outcomes
- The current product mode is paper trading only

**Why this priority**: First impressions shape trust. A visitor who misunderstands the product as a guaranteed-profit tool will make bad decisions. Clear product positioning is foundational. The existing Hero section is the primary first-impression mechanism.

**Independent Test**: Can be fully tested by viewing the Home page and verifying the presence of concise, accurate product-positioning text that communicates purpose, evidence-orientation, and paper-trading boundary.

**Acceptance Scenarios**:

1. **Given** a first-time visitor on the Home page, **When** they scan the hero or primary content area, **Then** they see a concise statement that StrikeNova is an options intelligence and paper-trading platform for Indian index options.
2. **Given** a first-time visitor, **When** they look for product-mode clarity, **Then** they can identify within one section that the platform is paper-trading only (no live execution inferred unless explicitly authorized).
3. **Given** a first-time visitor, **When** they seek evidence/decision context, **Then** they see language indicating the platform supports structured decision-making rather than guaranteed prediction accuracy.

---

### User Story 2 — Visitor Understands Evidence and Uncertainty (Priority: P2)

A visitor evaluates whether to trust the platform. They find transparent language about:
- The evidence/decision-support orientation of outputs
- The inherent uncertainty in options markets
- That past analytical outputs do not guarantee future outcomes

**Why this priority**: Trust is built through transparency. Misleading claims about prediction accuracy create legal and ethical risk. The Evidence & Trust section provides explicit trust clarification beyond the existing page copy.

**Independent Test**: Verifiable by inspecting the section content for evidence-orientation language and explicit uncertainty/risk awareness statements.

**Acceptance Scenarios**:

1. **Given** a visitor evaluating trustworthiness, **When** they read the evidence/trust section, **Then** they encounter language that StrikeNova outputs are decision-support, not guaranteed trading outcomes.
2. **Given** a visitor evaluating trustworthiness, **When** they read the section, **Then** they see explicit acknowledgment that options trading involves uncertainty and risk.

---

### User Story 3 — Visitor Finds a Path to Learn More (Priority: P3)

A visitor who wants to understand StrikeNova's philosophy and principles more deeply can navigate to `/about` for expanded context on product philosophy, principles, and boundaries.

**Why this priority**: Some visitors want depth. A clear next-step path reduces bounce and supports informed engagement. The `/about` page already contains product philosophy, principles, and explicit "NOT A GUARANTEED-PROFIT SYSTEM" positioning.

**Independent Test**: Verifiable by confirming a visible link or CTA to `/about` from the evidence/trust section.

**Acceptance Scenarios**:

1. **Given** a visitor who wants deeper context on StrikeNova's philosophy, **When** they finish reading the evidence/trust section, **Then** they see a clear path to "Learn More" linking to `/about`.

---

### Edge Cases

- What happens when the Home page is viewed on mobile? The section must remain readable and the trust messaging must not be truncated or hidden.
- How does the section behave for returning visitors? The messaging should remain visible (not dismissible-to-invisible unless a clear affordance exists).
- What if the product mode changes (live execution enabled in the future)? The section must be updatable without rewriting the entire Home page. It must not hardcode claims that could become false.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST display a concise, public-facing section on the Home page providing explicit trust clarification and transparency about StrikeNova's evidence-orientation and limitations.
- **FR-002**: System MUST communicate that StrikeNova outputs are decision-support oriented, not guaranteed trading outcomes.
- **FR-003**: System MUST communicate the paper-trading boundary of the current product mode.
- **FR-004**: System MUST include explicit language about uncertainty/risk in options markets.
- **FR-005**: System MUST provide a visible path to `/about` from the evidence/trust section.
- **FR-006**: Evidence & Trust section content MUST be separated from presentation logic so the copy can be updated without modifying the component's structural/rendering logic.
- **FR-007**: Section MUST render correctly at mobile, tablet, and desktop breakpoints.
- **FR-008**: Section MUST NOT claim live trading capability, guaranteed returns, or prediction accuracy.
- **FR-009**: Section MUST NOT use technical jargon that obscures the trust message (e.g., avoid "BSM Greeks engine" in the trust section).

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Within the first 10 seconds of viewing the public Home page, a first-time visitor can identify what StrikeNova is and that the current product mode is paper trading.
- **SC-002**: A reviewer confirms the paper-trading boundary is explicitly stated in the evidence/trust section.
- **SC-003**: A reviewer confirms no claims of guaranteed accuracy or live-trading capability exist in the section.
- **SC-004**: The section renders without layout breakage at 320px, 768px, and 1280px viewport widths using the existing responsive design system.
- **SC-005**: A "Learn More About StrikeNova" link or CTA is visible from the evidence/trust section and links to `/about`.

---

## Assumptions

- Target visitors are prospective users evaluating whether to engage with StrikeNova.
- The section is a new addition to the existing Home page (`frontend/app/(public)/page.js`), not a standalone page.
- Content will initially live in a JavaScript/JSON data structure as a separate content file (no backend CMS dependency for v1).
- The existing public design system tokens (`@/components/public/tokens`) are used for styling.
- No new backend API endpoints are required for this feature.
- The existing public layout (`PublicLayout`) and component conventions are followed.
- The Evidence & Trust section provides trust clarification and transparency rather than duplicating the existing homepage's workflow messaging.
