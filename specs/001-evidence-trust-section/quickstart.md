# Quickstart Validation: Evidence & Trust Section

## Prerequisites

- Development server running (`npm run dev` in `frontend/`)
- Browser access to `http://localhost:3000/`

## Validation Steps

### Automated (TDD)

Tests to be created during implementation:

1. Component renders without errors
2. Section contains "EVIDENCE & TRUST" eyebrow text
3. Section contains paper-trading boundary statement
4. Section contains uncertainty/risk disclaimer
5. CTA link points to `/about`
6. No claims of guaranteed accuracy or live trading in rendered output

### Visual/Manual

7. Navigate to `http://localhost:3000/` in browser
8. Scroll past Section 04 (Market Intelligence)
9. Verify "EVIDENCE & TRUST" eyebrow is visible
10. Verify headline communicates evidence/decision-support orientation
11. Verify paper-trading boundary is stated
12. Verify risk/uncertainty disclaimer is present
13. Verify "Learn More About StrikeNova" link is visible and links to `/about`
14. Resize browser to 320px width — verify no horizontal overflow
15. Resize browser to 768px width — verify 2-column grid for points
16. Resize browser to 1280px width — verify section layout is centered within 1100px container
17. Verify section provides trust clarification rather than duplicating existing homepage messaging

## Expected Outcomes

- Section renders without console errors
- All text is readable at mobile, tablet, and desktop widths
- No layout breakage or overflow at any tested viewport
- Link to `/about` is functional
- No claims of guaranteed accuracy or live trading are present
- Section adds explicit trust framing beyond existing homepage copy
