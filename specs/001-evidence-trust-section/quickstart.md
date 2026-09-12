# Quickstart Validation: Evidence & Trust Section

## Prerequisites

- Development server running (`npm run dev` in `frontend/`)
- Browser access to `http://localhost:3000/`

## Validation Steps

1. Open `http://localhost:3000/` in browser
2. Scroll past Section 04 (Market Intelligence)
3. Verify "EVIDENCE & TRUST" eyebrow label is visible
4. Verify headline "Built on evidence. Not guarantees." is displayed
5. Verify description paragraph is readable
6. Verify 4 trust points are displayed with correct titles and bodies
7. Verify paper-trading boundary is explicitly stated in at least one point
8. Verify uncertainty/risk disclaimer is visible
9. Verify "Learn More About StrikeNova" link is visible and links to `/about`
10. Resize browser to 320px width — verify no horizontal overflow
11. Resize browser to 768px width — verify 2-column grid for points
12. Resize browser to 1280px width — verify section layout is centered within 1100px container

## Expected Outcomes

- Section renders without console errors
- All text is readable at mobile, tablet, and desktop widths
- No layout breakage or overflow at any tested viewport
- Link to `/about` is functional
- No claims of guaranteed accuracy or live trading are present

## Test Command

```bash
npm test -- --testPathPattern="EvidenceTrust"
```

(Tests will be created during implementation phase per TDD discipline.)
