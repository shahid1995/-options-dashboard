# Phase 0: Research Decisions

**Feature**: StrikeNova Public Home — Evidence & Trust Section

## Decision Log

| Question | Decision | Rationale |
|----------|----------|-----------|
| Where should section content live? | Co-located content data file in `frontend/components/public/` | Content separated from presentation logic; copy can be updated without modifying component's structural/rendering logic; matches existing public component conventions |
| What component name? | `EvidenceTrustSection` | Matches existing `Section`, `Container`, `CTASection` naming convention |
| Where to place in Home page? | After Market Intelligence Grid (Section 04), before Strategy Lab (Section 05) | Logical flow: market context → evidence/trust → strategy lab |
| Mobile rendering approach? | Use existing `isMobile` hook + responsive `Section`/`Container` primitives | Consistent with all other sections on the page |
| CTA destination | `/about` | About page contains product philosophy, principles, and explicit "NOT A GUARANTEED-PROFIT SYSTEM" positioning. Better supports trust clarification and transparency goals than `/how-it-works` which focuses on workflow steps |
| SC-001 placement clarification | SC-001 applies to the overall homepage first-impression experience (product identity only). The Evidence & Trust section is not required to appear within 10 seconds. | The Evidence & Trust section is placed after Section 04; it cannot be the primary 10-second mechanism. The Hero already provides product identity. The trust section handles paper-trading boundary and trust clarification (SC-002). |
| FR-006 semantic correction | Changed from "editable without requiring code changes" to "separated from presentation logic so the copy can be updated without modifying the component's structural/rendering logic" | The original wording was misleading. A JavaScript content data file is still code; the separation is about maintainability, not about eliminating code changes. |
| Homepage duplication check | Evidence & Trust section provides trust clarification and transparency rather than duplicating existing workflow messaging | Existing homepage communicates workflow, market intelligence, risk awareness, and paper trading. The new section adds explicit trust framing, decision-support boundary, uncertainty, and transparent limitations. |
| Content claim verification | All proposed content claims verified against existing product context | No guaranteed returns, no guaranteed prediction accuracy, no live-trading capability, no claims that StrikeNova predicts the future. The "educational and research tool" characterization is supported by the existing product context (paper trading, analytics, no live execution). |

All NEEDS CLARIFICATION resolved. Proceed to Phase 1.
