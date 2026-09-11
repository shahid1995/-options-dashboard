# StrikeNova Public Website V1.2 — P6 Navigation, Footer, Metadata & Cross-Page Cohesion

> Status: AUTHORIZED — implementation handoff
> Date: 2026-09-11
> Scope: Global public navigation/footer/metadata and cross-page public cohesion only.
> Predecessors: P5 accepted at `4a2eda84589609da54f151f80ae87289acda3f1e`.

## Authority

Design specification:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md

Master implementation plan:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-10-strikenova-public-website-v1-2.md

P0 audit:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/audits/2026-09-10-strikenova-public-website-v1-2-p0-baseline.md

Current project status:
https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/PROJECT_STATUS_CURRENT.md

## Objective

Make every public route feel like one coherent StrikeNova product after P3–P5 page redesigns.

Focus only on:

- PublicHeader
- PublicFooter
- global/public metadata
- page titles/descriptions where needed
- legacy visible branding sweep
- navigation grouping and active states
- cross-page CTA/link accuracy
- cross-page truth/research consistency

Do not redesign page bodies in P6.

## Expected public routes

- `/`
- `/features`
- `/market-intelligence`
- `/strategy-lab`
- `/paper-trading`
- `/how-it-works`
- `/about`

Authenticated `(app)` routes remain unchanged.

## P6.1 — PublicHeader

File:
`frontend/components/public/PublicHeader.js`

### Requirements

Replace legacy visible identity with:

**StrikeNova**

Use a clear compact product mark; do not present `Options Dashboard` as public brand identity.

Navigation must reflect actual routes and content:

Product:
- Features
- Market Intelligence
- Strategy Lab
- Paper Trading

Learn:
- How It Works
- About

Primary CTA should be unmistakable.

Login/auth behavior must remain intact.

Preserve:

- click-outside behavior
- Escape-to-close
- keyboard navigation
- focus-visible behavior
- mobile menu semantics

Improve:

- active route state
- desktop hierarchy
- mobile grouping
- touch targets
- visual consistency with P1/P2/P3 language

Do not create a mega-menu unless justified.

## P6.2 — PublicFooter

File:
`frontend/components/public/PublicFooter.js`

Update visible brand and labels to StrikeNova.

Ensure every link resolves to a real public route.

Organize product/learning links consistently with the header.

Do not invent legal entities, social profiles, addresses, certifications, or company claims.

## P6.3 — Metadata

Files:
- `frontend/app/layout.js`
- public route metadata files as needed

Replace public default metadata branding with StrikeNova.

Requirements:

- title templates consistently use StrikeNova;
- descriptions accurately describe the product;
- no unsupported live-data claims;
- no unsupported execution claims;
- no performance or prediction claims;
- unique metadata for each public route where appropriate.

Authenticated metadata should not be changed unless required to prevent accidental public branding leakage.

## P6.4 — Legacy branding sweep

Search the full public surface for visible or semantic references to:

- `Options Dashboard`
- `OPTIONS DASHBOARD`
- `OD` where it represents the obsolete public brand

Classify every hit:

`REMOVE / MIGRATE / KEEP-INTERNAL`

Do not blindly replace internal technical identifiers.

The target is public user-facing branding.

## P6.5 — Cross-page truth audit

Search all public pages for:

- `LIVE`
- `REAL-TIME`
- performance claims
- prediction accuracy
- guarantees
- fabricated customers/users
- partnerships/certifications
- research features represented as shipped

Correct only public presentation/wording within P6 scope.

Do not add data integrations.

## P6.6 — Cross-page CTA/link audit

Verify that:

- product links point to existing product pages;
- workflow CTAs point to the canonical pages;
- research links do not imply current availability;
- no CTA points to an unimplemented route;
- auth CTA still opens the existing auth flow.

## P6.7 — Cohesion rules

The public system should now communicate:

```text
StrikeNova
  ↓
Options intelligence for structured decisions
  ↓
Market Intelligence
  ↓
Strategy Lab
  ↓
Risk
  ↓
Paper Trading
  ↓
Review
```

Header/footer should be quieter than hero content.

Do not add flashy global motion.

## Accessibility

P6 must preserve and improve:

- keyboard access;
- visible focus;
- semantic nav landmarks;
- mobile-menu labeling;
- Escape behavior;
- touch target sizes;
- current reduced-motion support.

P7 remains the comprehensive whole-site accessibility gate.

## Responsive

Verify effective browser sizes:

- 1440×900
- 1280×800
- 390×844
- 360×800

No header/footer overflow.

Mobile menu must be usable and contain the expected public links after opening.

## Tests

Add/update focused tests for:

### Header
- StrikeNova visible branding
- route links
- active state
- mobile menu open/close
- Escape
- focus behavior
- primary CTA

### Footer
- StrikeNova branding
- accurate links
- no obsolete public branding

### Metadata
- title template
- route descriptions
- absence of unsupported claims

### Cohesion
- no stale public `Options Dashboard` branding
- no dead public CTA routes
- research/future labels remain explicit

## Browser verification

Use a real browser against the local app.

Verify every public route with the updated header/footer.

Specifically test:

- desktop navigation
- mobile menu interaction
- click-outside
- Escape
- keyboard focus
- CTA navigation
- no console errors
- no horizontal overflow from global chrome

## Strict no-touch boundary

Do NOT modify:

- backend/FastAPI
- database/schema/migrations
- broker integrations
- OAuth/session implementation
- execution/trading engine
- market-data architecture
- financial calculation engines
- authenticated `(app)` route behavior

Do not redesign page bodies in P6.

Do not deploy.

## Git

Recommended commit:

`feat(public): unify StrikeNova navigation metadata and cohesion`

## Required final report

Return:

### P6 RESULT
`PASS` or `BLOCKED`

### FILES CHANGED
Exact paths.

### HEADER
Actual branding/navigation/mobile behavior delivered.

### FOOTER
Actual branding/link behavior delivered.

### METADATA
Actual title/description changes.

### TRUTH/BRANDING AUDIT
Counts before/after for legacy branding and risky claims.

### VERIFICATION

```text
Tests:
Build:
Routes:
Browser:
Console errors:
Responsive overflow:
Mobile menu links:
```

### PROTECTED SCOPE

```text
Backend: NONE
Database/schema/migrations: NONE
Broker: NONE
OAuth/session: NONE
Execution: NONE
Trading engine: NONE
Market-data architecture: NONE
Financial calculations: NONE
Authenticated app: NONE
Page-body redesign: NONE
Deployment: NOT PERFORMED
```

## STOP

After P6 verification:

STOP.

Do not start P7.
Do not perform whole-site accessibility/performance hardening.
Do not deploy.
