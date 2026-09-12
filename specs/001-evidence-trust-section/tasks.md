# Tasks: StrikeNova Public Home — Evidence & Trust Section

**Input**: Design documents from `/specs/001-evidence-trust-section/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: TDD-first approach required per StrikeNova engineering protocol.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Frontend**: `frontend/components/public/`, `frontend/app/(public)/`
- **Tests**: `frontend/components/public/`
- **Specs**: `specs/001-evidence-trust-section/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify existing infrastructure and conventions

- [ ] T001 Verify existing public design system tokens are available: `COLOR`, `TYPE`, `SPACE`, `RADIUS` in `frontend/components/public/tokens.js`
- [ ] T002 Verify existing layout primitives are available: `Section`, `Container`, `FlexRow`, `FlexColumn` in `frontend/components/public/layout.js`
- [ ] T003 Verify existing public component conventions by inspecting `CTASection.js` and `WorkflowTabs.js` in `frontend/components/public/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 Define content contract data file at `frontend/components/public/EvidenceTrustContent.js` with all required fields: `eyebrow`, `title`, `description`, `points` (array of `{title, body}`), `disclaimer`, `ctaLabel`, `ctaHref`. Content MUST NOT claim guaranteed accuracy, live trading, or prediction capability. CTA MUST link to `/about`. Per `specs/001-evidence-trust-section/contracts/content.md`.
- [ ] T005 Create component test file at `frontend/components/public/EvidenceTrustSection.test.js` with initial test stubs that will fail before implementation (TDD RED phase readiness).

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 — First-Time Visitor Understands StrikeNova's Purpose (Priority: P1) — MVP

**Goal**: A visitor lands on the public Home page and understands StrikeNova is an options-intelligence platform for structured decisions. The Evidence & Trust section communicates paper-trading boundary, decision-support framing, and uncertainty awareness.

**Independent Test**: View the Home page, scroll past Section 04 (Market Intelligence), verify "EVIDENCE & TRUST" eyebrow is visible, verify paper-trading boundary is stated, verify uncertainty disclaimer is present, verify no claims of guaranteed accuracy.

### Tests for User Story 1 (TDD RED Phase)

> **NOTE**: Write these tests FIRST, ensure they FAIL before implementation. All tests go into the same file and must be written sequentially.

- [ ] T006 [US1] Add component test: renders "EVIDENCE & TRUST" eyebrow text in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T007 [US1] Add component test: renders paper-trading boundary statement in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T008 [US1] Add component test: renders uncertainty/risk disclaimer in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T009 [US1] Add component test: renders CTA link to `/about` in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T010 [US1] Add component test: does NOT render claims of guaranteed accuracy or live trading in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T011 [US1] Add component test: renders without errors at mobile (320px) viewport in `frontend/components/public/EvidenceTrustSection.test.js`

### Implementation for User Story 1

- [ ] T012 [US1] Create `EvidenceTrustSection` component in `frontend/components/public/EvidenceTrustSection.js` that imports content from `EvidenceTrustContent.js` and renders using `Section`, `Container`, `SectionTitle` from layout primitives and design tokens. Uses responsive `isMobile` hook for grid layout. Per `specs/001-evidence-trust-section/plan.md`.
- [ ] T013 [US1] Integrate `EvidenceTrustSection` into `frontend/app/(public)/page.js` after `MarketIntelligenceGrid` (Section 04) and before `WorkflowTabs` (Section 05). Per `specs/001-evidence-trust-section/plan.md` Phase 0 decision.

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently. Run `npm test -- EvidenceTrustSection.test.js` from `frontend/` directory — tests should pass (GREEN). Then run `npm run dev` and verify in browser.

---

## Phase 4: User Story 2 — Visitor Understands Evidence and Uncertainty (Priority: P2)

**Goal**: A visitor evaluating trustworthiness finds transparent language about evidence/decision-support orientation, inherent uncertainty in options markets, and that past outputs do not guarantee future outcomes.

**Independent Test**: Inspect section content for evidence-orientation language and explicit uncertainty/risk awareness statements. Verify content contract constraints are enforced.

### Tests for User Story 2 (TDD RED Phase)

- [ ] T014 [US2] Add component test: renders "Decision-Support, Not Decision-Making" point in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T015 [US2] Add component test: renders "Uncertainty Is Inherent" point in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T016 [US2] Add component test: renders "Transparency Over Hype" point in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T017 [US2] Add component test: disclaimer explicitly states uncertainty/risk in `frontend/components/public/EvidenceTrustSection.test.js`

### Implementation for User Story 2

- [ ] T018 [US2] Verify content contract in `EvidenceTrustContent.js` includes all 4 points with exact titles and bodies per `specs/001-evidence-trust-section/contracts/content.md`. Verify disclaimer explicitly states uncertainty/risk.

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently. All tests pass. Section content matches content contract exactly.

---

## Phase 5: User Story 3 — Visitor Finds a Path to Learn More (Priority: P3)

**Goal**: A visitor who wants to understand StrikeNova's philosophy and principles more deeply can navigate to `/about` for expanded context.

**Independent Test**: Confirm a visible link or CTA to `/about` from the evidence/trust section. Verify `/about` route exists.

### Tests for User Story 3 (TDD RED Phase)

- [ ] T019 [US3] Add component test: renders CTA with label "Learn More About StrikeNova" in `frontend/components/public/EvidenceTrustSection.test.js`
- [ ] T020 [US3] Add component test: CTA links to `/about` in `frontend/components/public/EvidenceTrustSection.test.js`

### Implementation for User Story 3

- [ ] T021 [US3] Verify `EvidenceTrustContent.js` has `ctaLabel: "Learn More About StrikeNova"` and `ctaHref: "/about"` per content contract.
- [ ] T022 [US3] Verify `/about` route exists in `frontend/app/(public)/about/page.js`.

**Checkpoint**: All user stories should now be independently functional. CTA is visible and links to existing `/about` page.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories and final verification

- [ ] T023 Run `npm test -- EvidenceTrustSection.test.js` from `frontend/` directory — verify all tests pass (GREEN phase)
- [ ] T024 Run `npm run dev` and verify in browser at 320px, 768px, 1280px viewports — verify no layout breakage
- [ ] T025 Verify no claims of guaranteed accuracy or live trading in rendered output
- [ ] T026 Verify section provides trust clarification rather than duplicating existing homepage messaging
- [ ] T027 Run existing public page tests to verify no regression: `npm test -- public` from `frontend/` directory
- [ ] T028 Run quickstart.md validation steps from `specs/001-evidence-trust-section/quickstart.md`. Verify homepage opens, Hero is visible and communicates options-intelligence / structured-decisions identity, Evidence & Trust is a later trust-clarification section, and no requirement exists for the new section to appear within the first 10 seconds.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User story phases proceed sequentially (US1 → US2 → US3) because tests for each story are additive and build on the same test file
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) — No dependencies on other stories
- **User Story 2 (P2)**: Should follow User Story 1 — depends on component structure from US1
- **User Story 3 (P3)**: Should follow User Story 2 — depends on CTA and content from US1/US2

### Within Each User Story

- Tests (TDD RED) MUST be written and FAIL before implementation
- Content definition before component
- Component before page integration
- Core implementation before responsive verification
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks (T001–T003) can run in parallel (different read-only files)
- T004 (content file) and T005 (test file) can run in parallel (different files)
- Within each story, tests go into the same file and must be written sequentially (NOT parallel)
- T021 (content verification) and T022 (route verification) can run in parallel (different files)

---

## Parallel Example: User Story 1

```bash
# Tests go into the same file sequentially (NOT parallel):
Task T006: "Add test for eyebrow text"
Task T007: "Add test for paper-trading boundary"
Task T008: "Add test for uncertainty disclaimer"
Task T009: "Add test for CTA link"
Task T010: "Add test for no guaranteed claims"
Task T011: "Add test for mobile viewport"

# Then implement:
Task T012: "Create EvidenceTrustSection component"
Task T013: "Integrate into page.js"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test User Story 1 independently
5. Validate locally / browser verification

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Validate locally / browser verification (MVP!)
3. Add User Story 2 → Test independently → Validate locally / browser verification
4. Add User Story 3 → Test independently → Validate locally / browser verification
5. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD RED-GREEN-REFACTOR)
- Commit after each task or logical group per StrikeNova execution protocol
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence

---

## Requirement Traceability

| Requirement | Task IDs |
|-------------|----------|
| FR-001 | T006, T012, T013 |
| FR-002 | T007, T012, T014, T018 |
| FR-003 | T007, T012 |
| FR-004 | T008, T012, T015, T017 |
| FR-005 | T009, T019, T020, T021, T022 |
| FR-006 | T004, T012 |
| FR-007 | T011, T024 |
| FR-008 | T010, T025 |
| FR-009 | T004, T018 |

| Success Criteria | Task IDs |
|------------------|----------|
| SC-001 | T028 |
| SC-002 | T007, T012 |
| SC-003 | T010, T025 |
| SC-004 | T011, T024 |
| SC-005 | T009, T019, T020 |
