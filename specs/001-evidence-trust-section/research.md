# Phase 0: Research Decisions

**Feature**: StrikeNova Public Home — Evidence & Trust Section

## Decision Log

| Question | Decision | Rationale |
|----------|----------|-----------|
| Where should section content live? | Co-located content data file in `frontend/components/public/` | Editable without component logic changes; matches existing public component conventions |
| What component name? | `EvidenceTrustSection` | Matches existing `Section`, `Container`, `CTASection` naming convention |
| Where to place in Home page? | After Market Intelligence Grid (Section 04), before Strategy Lab (Section 05) | Logical flow: market context → evidence/trust → strategy lab |
| Mobile rendering approach? | Use existing `isMobile` hook + responsive `Section`/`Container` primitives | Consistent with all other sections on the page |

All NEEDS CLARIFICATION resolved. Proceed to Phase 1.
