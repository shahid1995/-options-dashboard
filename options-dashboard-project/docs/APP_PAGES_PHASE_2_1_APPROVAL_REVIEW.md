# Phase 2.1 Approval Review — Decision-by-Decision Analysis

_Last updated: 2026-08-22_

---

This document reviews every decision in the Phase 2.1 Blueprint before implementation begins.

---

## Decision #1: Sidebar Item Count (9 → 7)

### Current Architecture
9 flat navigation items in `Shell.js`:
```
📊 Dashboard
📈 Market
📋 Orders
📐 Positions
⚡ Strategies
💼 Portfolio
🕐 Activity
🔗 Brokers
⚙️ Settings
```

### Proposed Architecture
7 items in 4 workflow-aligned sections:
```
── MARKET ──────────
📊 Dashboard

── BUILD ───────────
⚡ Strategy Builder

── MANAGE ──────────
📐 Positions
💼 Portfolio
📋 Orders

── SYSTEM ──────────
🔗 Brokers
⚙️ Settings
```

### Why Change Is Needed
5 of 9 items are stubs ("coming soon"). The sidebar overpromises and erodes user trust. The remaining items don't follow the natural trading workflow.

### Benefits
- Navigation reflects actual functionality
- Workflow-aligned structure helps new users
- Section labels provide visual hierarchy
- Reduces cognitive load (7 vs 9 items)

### Risks
- Users accustomed to the old layout may be confused temporarily
- Market/Strategies/Activity routes still exist but are hidden

### Files/Components Affected
- `frontend/components/Shell.js` — NAV_ITEMS array, ROUTE_KEY_MAP

### Backend/API Impact
- None

### Database Impact
- None

### Authentication/Broker Impact
- None

### Existing Routes Change?
- Routes remain unchanged. Only sidebar visibility changes. All 10 routes still work if accessed directly by URL.

### Existing Functionality Could Break?
- No. Sidebar is purely navigational. All routes remain functional.

### Reversible?
- Yes. Adding items back to NAV_ITEMS is trivial.

### Recommendation
Reduce to 7 items. The 3 removed items (Market, Strategies, Activity) are stubs that redirect elsewhere anyway. No functionality is lost.

### Approval Status: ✅ SAFE TO APPROVE

---

## Decision #2: Sidebar Sections (4 sections)

### Current Architecture
No sections. All 9 items are flat in a single list.

### Proposed Architecture
4 sections with uppercase labels:
- **MARKET** — Dashboard
- **BUILD** — Strategy Builder
- **MANAGE** — Positions, Portfolio, Orders
- **SYSTEM** — Brokers, Settings

### Why Change Is Needed
Sections provide visual grouping that helps users find what they need. The trading workflow naturally groups into these categories.

### Benefits
- Visual hierarchy in navigation
- Easier to locate functionality
- Clear mental model of the app structure

### Risks
- Section labels add vertical space (approximately 4 × 24px = 96px total)
- At very short viewports, items may need scrolling

### Files/Components Affected
- `frontend/components/Shell.js` — sidebar rendering logic

### Backend/API Impact
- None

### Database Impact
- None

### Authentication/Broker Impact
- None

### Existing Routes Change?
- No

### Existing Functionality Could Break?
- No

### Reversible?
- Yes. Removing section labels is trivial.

### Recommendation
Approve. The spacing cost is minimal and the organizational benefit is significant.

### Approval Status: ✅ SAFE TO APPROVE

---

## Decision #3: Remove `/market` from Sidebar

### Current Architecture
`/market` is in the sidebar as "📈 Market". The page is a 58-line stub that renders a single redirect card linking to `/dashboard`.

### Proposed Architecture
`/market` is removed from the sidebar. The route still exists and works if accessed directly.

### Why Change Is Needed
The page is a stub. Showing it in the sidebar creates confusion — users click it and get a redirect card. The market overview functionality should either be built properly or not shown.

### Benefits
- No more confusing redirect cards
- Cleaner sidebar with only functional items
- Market intelligence can be added to Dashboard instead

### Risks
- If someone has bookmarked `/market`, it still works but has no sidebar link
- Future market overview page will need to be added back to sidebar

### Files/Components Affected
- `frontend/components/Shell.js` — remove from NAV_ITEMS

### Backend/API Impact
- None

### Database Impact
- None

### Authentication/Broker Impact
- None

### Existing Routes Change?
- `/market` route remains functional. Only sidebar link is removed.

### Existing Functionality Could Break?
- No

### Reversible?
- Yes. Adding back to NAV_ITEMS is trivial.

### Recommendation
Approve. The page is a stub. Remove from sidebar until it becomes real.

### Approval Status: ✅ SAFE TO APPROVE

---

## Decision #4: Remove `/strategies` from Sidebar

### Current Architecture
`/strategies` is in the sidebar as "⚡ Strategies". The page is a 62-line stub that renders a redirect card linking to `/paper`.

### Proposed Architecture
`/strategies` is removed from the sidebar. The Strategy Builder functionality lives at `/paper` (which will eventually be renamed).

### Why Change Is Needed
The page is a stub redirecting to `/paper`. The sidebar already has "Strategy Builder" pointing to `/paper`. Having both is redundant.

### Benefits
- Eliminates redundant navigation entry
- Clear single entry point for strategy building
- Cleaner sidebar

### Risks
- Future strategy management page (template list, strategy history) may want its own route
- The route still exists but has no sidebar link

### Files/Components Affected
- `frontend/components/Shell.js` — remove from NAV_ITEMS

### Backend/API Impact
- None

### Database Impact
- None

### Authentication/Broker Impact
- None

### Existing Routes Change?
- `/strategies` route remains functional. Only sidebar link is removed.

### Existing Functionality Could Break?
- No

### Reversible?
- Yes

### Recommendation
Approve. The redirect card is unnecessary when the sidebar already points to the correct destination.

### Approval Status: ✅ SAFE TO APPROVE

---

## Decision #5: Remove `/activity` from Sidebar

### Current Architecture
`/activity` is in the sidebar as "🕐 Activity". The page is a 36-line stub ("Activity feed coming soon").

### Proposed Architecture
`/activity` is removed from the sidebar. Activity timeline may be merged into Orders in the future.

### Why Change Is Needed
The page is a stub. Showing it creates confusion.

### Benefits
- Cleaner sidebar
- Activity data is already partially available in Orders and Paper Journal

### Risks
- Future activity/timeline feature will need a route and sidebar entry

### Files/Components Affected
- `frontend/components/Shell.js` — remove from NAV_ITEMS

### Backend/API Impact
- None

### Database Impact
- None

### Authentication/Broker Impact
- None

### Existing Routes Change?
- `/activity` route remains functional. Only sidebar link is removed.

### Existing Functionality Could Break?
- No

### Reversible?
- Yes

### Recommendation
Approve. Stub page, no functionality to lose.

### Approval Status: ✅ SAFE TO APPROVE

---

## Decision #6: TopBar Height (44px → 48px)

### Current Architecture
TopBar is 44px tall with `height: 44`. Contains: hamburger, title, execution badge, market status.

### Proposed Architecture
TopBar is 48px tall. Content remains the same with slightly more vertical breathing room.

### Why Change Is Needed
44px is tight for the content (title + badge + market status + spacer). 48px provides better vertical alignment and reduces visual cramping.

### Benefits
- Better visual balance
- Easier touch targets on mobile (48px is the minimum recommended by Apple/Google)
- More room for text at 12px

### Risks
- 4px height increase reduces main content area by 4px
- Main content `margin-top` must be updated from 44 to 48

### Files/Components Affected
- `frontend/components/Shell.js` — TopBar height, main content margin-top

### Backend/API Impact
- None

### Database Impact
- None

### Authentication/Broker Impact
- None

### Existing Routes Change?
- No

### Existing Functionality Could Break?
- No. Layout change only.

### Reversible?
- Yes. Changing one number reverts it.

### Desktop Behavior
48px is appropriate. On 1440px+ screens, 4px is negligible.

### Tablet Behavior
48px works well. Hamburger appears at 900px.

### Mobile Behavior
48px is th
