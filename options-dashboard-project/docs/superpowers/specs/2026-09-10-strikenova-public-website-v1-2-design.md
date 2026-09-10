# StrikeNova Public Website V1.2 — Signal Field Design Specification

> **Status:** Approved direction — planning baseline; implementation not started
> **Date:** 2026-09-10
> **Scope:** Public marketing experience only. No backend, database, broker, execution, authentication, or authenticated-app behavior changes are authorized by this specification.
> **Supersedes visually:** Public Website V1.1 as the design direction for future public-site work; V1.1 remains the historical implementation baseline.

---

## 1. Purpose

StrikeNova has outgrown the visual identity of a generic "options dashboard." The current public site has a sound dark trading foundation, shared components, responsive behavior, accessibility foundations, explicit demo-data labeling, and responsible product messaging. The next iteration must preserve those strengths while making the public experience futuristic, distinctive, memorable, and clearly differentiated.

The target is not "more neon" or "more animation." The target is a **computational market-instrument aesthetic** in which the structure of an options market becomes the source of the site's visual language.

### Core idea

**StrikeNova Signal Field**

The public website should visually communicate:

```text
MARKET DATA
     ↓
POSITIONING + VOLATILITY + GREEKS
     ↓
MARKET STATE
     ↓
STRATEGY
     ↓
RISK
     ↓
PAPER TRADE
     ↓
REVIEW
```

The site should make a visitor feel that StrikeNova is a market-research instrument built for structured decisions—not a collection of dashboard widgets.

---

## 2. Product/brand direction

### 2.1 Brand name

The public brand is **StrikeNova**.

The public header, metadata, primary messaging, visual language, and future public-page copy must no longer present "Options Dashboard" as the product brand.

"Options Dashboard" may remain only where needed for legacy technical naming or historical references.

### 2.2 Positioning

Primary positioning:

> **Options intelligence for structured decisions.**

Supporting idea:

> See the forces behind the option chain. Understand positioning, volatility and risk. Build, test and review decisions in one workflow.

The site must avoid unsupported claims of prediction, guaranteed returns, accuracy, institutional adoption, or performance.

### 2.3 Design personality

The experience should feel:

- Futuristic
- Technical
- Premium
- Intelligent
- Calm under pressure
- Data-native
- Precise

It should not feel:

- Crypto-hype driven
- Gamer-like
- Generic AI SaaS
- Overly glossy
- Corporate/boring
- Stock-photo dependent

---

## 3. Visual system

### 3.1 Color semantics

The existing dark foundation is retained and expanded.

| Semantic role | Direction |
|---|---|
| Base | Deep obsidian / near-black |
| Surface | Existing dark slate surfaces |
| Border | Existing restrained dark borders |
| Live market / information | Electric cyan family |
| Intelligence / analysis | Ultraviolet / violet family |
| Strategy / decision | Existing premium gold family |
| Positive result | Existing green |
| Risk / negative result | Existing red |

Existing gold remains important. It is no longer the only visual accent.

Gold should communicate **strategy, decision, premium emphasis** rather than every decorative element.

Cyan/violet should be used selectively for information layers and signal-field visualizations.

### 3.2 Typography

Create an explicit three-voice hierarchy:

1. **Brand/display voice** — distinctive contemporary sans or technical grotesk with strong geometry and excellent rendering.
2. **Body voice** — highly readable sans-serif for explanations and long-form content.
3. **Data voice** — tabular/monospace treatment for strikes, prices, Greeks, P&L and market metrics where useful.

Do not select a font solely because it looks futuristic. Readability, performance, weight coverage, numeral quality, and browser rendering are mandatory.

Target hierarchy:

| Element | Desktop | Mobile |
|---|---:|---:|
| Display H1 | 56–76px | 38–48px |
| H2 | 34–48px | 28–34px |
| H3 | 20–26px | 19–23px |
| Body | 16–18px | 16–17px |
| Labels | 11–13px | 11–13px |
| Data | 13–16px | 12–15px |

These are target ranges, not absolute values. Visual balance wins over arbitrary numbers.

### 3.3 Shape language

Move from a uniform "rounded card grid" toward a combination of:

- sharp/asymmetric data panels
- restrained corner radii
- large visual canvases
- layered surfaces
- thin technical lines
- signal nodes
- strike rails
- data traces
- focused glass/blur only where it materially improves depth

Do not apply rounded rectangles to every element.

### 3.4 Graphic language

StrikeNova's signature graphics should derive from:

- strike ladders
- option-chain columns
- OI clusters
- IV bands
- Greek vectors
- market-state nodes
- payoff curves
- support/resistance rails
- signal paths
- scenario axes

Decorative graphics that do not reinforce the product concept should be minimized.

---

## 4. Motion system

Motion should explain the product rather than decorate it.

### Approved motion categories

**Signal motion**

A visible signal/node progresses through a market workflow.

**Market motion**

Strike/OI/IV visual elements shift subtly to imply an active market state.

**Transformation motion**

Raw market observations morph into analysis, then strategy, then risk.

**Micro-interaction motion**

Buttons, links, tabs and panels respond quickly and subtly.

### Motion rules

- No continuous large-scale motion that distracts from content.
- No unnecessary parallax.
- No expensive particle fields covering the viewport.
- Animations must have a reduced-motion path.
- Animation must not be the only way important information becomes understandable.

---

## 5. Signature visual: Signal Field

The **Signal Field** is the defining reusable public visual.

Conceptually:

```text
             IV
              ◌
              │
   OI ●───────●───────● Greeks
              │
              │
        ───── SPOT ─────
              │
         STRIKE RAIL
      25,300 25,500 25,700
              │
              ↓
          MARKET STATE
```

Implementation characteristics:

- SVG and/or CSS-first where possible.
- Real semantic labels around visual nodes.
- No dependency on live broker data.
- Demo values explicitly labeled as illustrative.
- Can be static at first, then progressively enhanced.
- Must render responsively without horizontal overflow.
- Must support reduced motion.

This component should be reusable across Home, Market Intelligence, How It Works, and potentially Strategy Lab.

---

## 6. Public information architecture

The seven existing public routes remain:

```text
/
/features
/market-intelligence
/strategy-lab
/paper-trading
/how-it-works
/about
```

The authenticated route group remains separate and unchanged:

```text
(app)/
```

The public route group remains:

```text
(public)/
```

No route migration is part of V1.2.

---

## 7. Navigation redesign

### Desktop

Replace the current product identity presentation with StrikeNova branding.

Recommended structure:

```text
STRIKENOVA

Product        Intelligence        Learn
              
Features       Market Intelligence   How It Works
Strategy Lab   Signal Field          About
Paper Trading

                              Log in   Enter StrikeNova →
```

The exact number of top-level groups may be reduced during implementation if usability testing shows a simpler model is better.

Requirements:

- Sticky header.
- Strong active-state indicator.
- Dropdown transitions should be quick and controlled.
- Header should remain visually lighter than hero content.
- Primary CTA should be unmistakable.
- No overloaded mega-menu unless justified by content volume.

### Mobile

- Full-screen or near-full-screen menu.
- Clear Product/Learn grouping.
- Large touch targets.
- Clear primary CTA.
- Escape key closes menu.
- Focus behavior must remain accessible.

---

## 8. Homepage V1.2 blueprint

The homepage becomes the flagship expression of the brand.

### Section 01 — Signal Field Hero

Objective: communicate category, intelligence, and distinctiveness within the first viewport.

Recommended composition:

```text
STRIKENOVA

OPTIONS INTELLIGENCE
FOR STRUCTURED DECISIONS

See the forces behind the option chain.
Understand positioning, volatility and risk.
Build. Test. Review.

[ Explore StrikeNova ]   [ Strategy Lab ]

                 SIGNAL FIELD
        ┌────────────────────────────┐
        │  live-style illustrative   │
        │  market-state visualization │
        └────────────────────────────┘
```

Requirements:

- One dominant visual, not a generic screenshot.
- Strong first-screen contrast.
- Brand name is unambiguous.
- Demo visualization clearly indicates its illustrative nature where numerical values are shown.
- Keep the existing MockChain only if it can be reframed as part of the Signal Field; do not preserve it merely for historical continuity.

### Section 02 — The market is more than price

Visualize multiple layers converging:

```text
PRICE
OI
ΔOI
VOLUME
IV
GREEKS
STRUCTURE
        ↓
    MARKET STATE
```

The section should be predominantly visual, with concise explanatory copy.

### Section 03 — Market Intelligence

Large visualization-driven section featuring positioning, volatility, Greeks and market structure.

This should visually establish Market Intelligence as a core product category.

CTA: **Explore Market Intelligence**.

### Section 04 — Strategy Lab

Show how a market view becomes an executable strategy concept.

Sequence:

```text
MARKET VIEW → STRATEGY → PAYOFF → RISK
```

Use the existing Iron Condor demonstration only as supporting evidence, not as the entire visual identity.

CTA: **Open Strategy Lab**.

### Section 05 — Risk before capital

Large payoff/risk visualization.

Show:

- payoff
- max profit
- max loss
- breakevens
- Greeks
- scenario concept

The visitor should understand the product philosophy: risk is visible before capital is committed.

### Section 06 — Paper trading

Position StrikeNova paper trading as an experiment/rehearsal loop:

```text
DECISION
   ↓
SIMULATION
   ↓
POSITION
   ↓
P&L
   ↓
REVIEW
```

### Section 07 — Workflow rail

Canonical public narrative:

```text
01 OBSERVE → 02 ANALYZE → 03 BUILD → 04 TEST → 05 PAPER TRADE → 06 REVIEW
```

The homepage can show a condensed version, but it must not contradict the dedicated How It Works page.

### Section 08 — Final CTA

Recommended direction:

> **Enter the StrikeNova workflow.**

Primary CTA: **Get Started**
Secondary CTA: **Explore the Platform**

---

## 9. Features page V1.2

Current problem: too much information is presented through repeated feature cards.

New direction: **Capability Atlas**.

Primary composition:

```text
┌──────────────────────────────┬─────────────┐
│                              │             │
│       MARKET INTELLIGENCE    │     GEX     │
│       large visual module    │  research   │
│                              │             │
├──────────────┬───────────────┴─────────────┤
│ STRATEGY LAB │        PAPER TRADING        │
└──────────────┴─────────────────────────────┘
```

Each capability module should include:

- clear purpose
- representative visualization
- concise feature list
- link to dedicated page where applicable

Research features remain visually distinct and clearly labeled.

No future capability may be described as production-ready until implemented and verified.

---

## 10. Market Intelligence page V1.2

### Hero

> **Read the market as a system.**

Supporting idea:

> Price is one layer. StrikeNova connects positioning, volatility, Greeks and structure into one market view.

### Signature visualization

A large Market State / Signal Field module with four surrounding analytical dimensions:

```text
              VOLATILITY
                   │
POSITIONING ─ MARKET STATE ─ GREEKS
                   │
              STRUCTURE
```

### Interactive progression

Later enhancement may allow visitors to toggle layers:

- Price
- OI
- OI Change
- Volume
- IV
- Greeks
- Structure

The first implementation may use illustrative static/deterministic state.

### Research direction

Present GEX, OI migration, unusual activity, statistical signals, and related research as forward-looking work only.

---

## 11. Strategy Lab page V1.2

### Hero

> **Build the strategy. See the risk. Test the outcome.**

### Signature composition

Move from the current vertically stacked table/cards into a strategy workspace feel:

```text
┌──────────────────────┬─────────────────────────┐
│ STRATEGY LEGS        │ PAYOFF / RISK FIELD     │
│                      │                         │
│ SELL 25500 CE        │      payoff curve       │
│ BUY 25700 CE         │                         │
│ SELL 25500 PE        │      BE ───── BE        │
│ BUY 25300 PE         │                         │
├──────────────────────┼─────────────────────────┤
│ GREEKS               │ SCENARIO CONCEPT        │
└──────────────────────┴─────────────────────────┘
```

The existing demo Iron Condor can remain, but the layout should emphasize the relationship between legs, payoff and risk.

Future enhancement: scenario controls that alter the illustrative graph without suggesting that the public page is an authenticated trading environment.

---

## 12. Paper Trading page V1.2

Position the page as a **rehearsal environment**.

Hero idea:

> **Practice the decision. Measure the result.**

Visual centerpiece:

```text
CAPITAL
   │
ORDERS → POSITIONS → P&L
   │             │
   └──── REVIEW ─┘
```

The demo portfolio remains clearly labeled as illustrative.

Mobile position data should be presented as cards or a responsive structure rather than a squeezed desktop table.

The simulated-trading disclaimer remains mandatory.

---

## 13. How It Works page V1.2

This is the canonical workflow story.

Use a **vertical signal rail** on desktop and mobile, with a persistent path connecting six stages.

```text
01 OBSERVE
      │
02 ANALYZE
      │
03 BUILD
      │
04 TEST
      │
05 PAPER TRADE
      │
06 REVIEW
```

Each stage gets:

- stage number
- short purpose
- representative product visual
- concise supporting explanation

The rail becomes a visual product narrative rather than a text-only list.

---

## 14. About page V1.2

The current page repeats philosophy ideas in multiple forms. Replace repetition with an authentic company narrative.

### Proposed structure

1. **Why StrikeNova exists**
2. **What we believe**
3. **What StrikeNova is not**
4. **What we are building**
5. **The long-term direction**
6. CTA

### "What StrikeNova is not"

Possible truthful framing:

```text
Not a signal-selling service.
Not a prediction machine.
Not a guaranteed-profit system.
Not a black box.
```

Do not invent founder biographies, customers, testimonials, partnerships, certifications, institutional usage, or performance statistics.

---

## 15. Shared public components

Existing shared public components should be evolved rather than duplicated.

Current shared area includes:

```text
components/public/
  AuthModal
  CTASection
  DemoMetric
  FeatureCard
  PublicFooter
  PublicHeader
  PublicLayout
  SectionHeading
  styles
```

V1.2 should introduce focused primitives such as:

```text
SignalField
SignalNode
MarketStateField
DataTrace
StrikeRail
CapabilityModule
WorkflowRail
VisualMetric
SectionEyebrow
```

Exact component names may be adjusted by the implementation plan, but responsibilities must remain small and reusable.

Avoid a single giant "FuturisticHero" component that owns unrelated behavior.

---

## 16. Styling architecture

The current public site relies heavily on inline styles. V1.2 should move repeated visual behavior into a maintainable public design layer.

Target structure:

```text
public design system
├── tokens
├── typography
├── surfaces
├── buttons
├── layout primitives
├── visual modules
├── data visualization primitives
├── workflow primitives
├── motion
└── responsive rules
```

The redesign should not require rewriting authenticated-app styling unless a truly shared dependency forces it. Prefer public-only styling boundaries.

---

## 17. Content rules

All claims must reflect the verified product state.

### Production capabilities may be presented when:

- the feature is actually implemented;
- the behavior is verified;
- the page does not overstate it.

### Future/research capabilities must be explicitly labeled:

- **Research Direction**
- **In Development**
- **Coming Later**

### Prohibited claims

- guaranteed returns
- prediction guarantees
- fabricated accuracy rates
- fabricated customer counts
- fabricated testimonials
- fabricated partnerships
- fabricated certifications
- fabricated institutional adoption
- unsupported "AI predicts" language

---

## 18. Demo-data policy

Public visualizations may use deterministic illustrative data.

Where numerical market or portfolio values are shown, the UI must clearly distinguish them from live data.

Allowed wording:

- `DEMO DATA · ILLUSTRATIVE VALUES ONLY`
- `ILLUSTRATIVE EXAMPLE`

Do not use a "LIVE" badge next to fictional values unless the interface clearly communicates that the visualization is a simulation/decorative representation.

The current homepage MockChain's animated "LIVE" treatment must therefore be reviewed as part of P2; the redesign must not imply that the page is receiving real broker data if it is not.

---

## 19. Accessibility requirements

Target WCAG AA quality where practical.

Required checks:

- single logical H1 per public page
- keyboard navigation
- visible focus states
- accessible dropdowns/menu states
- reduced-motion support
- text contrast
- meaningful alternative text/labels for visualizations
- charts with programmatic labels where possible
- no color-only encoding for critical information
- touch targets of approximately 44px or greater
- no keyboard traps

Interactive visualizations must have a text-equivalent interpretation.

---

## 20. Responsive requirements

Required verification:

- 1440 × 900 desktop
- 1280 × 800 desktop/laptop
- 390 × 844 mobile
- 360 × 800 mobile

Acceptance:

- no horizontal overflow
- no compressed/unreadable data panels
- visual hierarchy preserved
- navigation usable
- hero remains compelling on mobile
- charts and Signal Field remain understandable
- CTA remains reachable
- reduced-motion behavior remains correct

---

## 21. Performance requirements

The visual redesign must remain a web product, not a visual-effects demo.

Rules:

- Prefer CSS/SVG over large raster assets for decorative data graphics.
- Avoid unnecessary client-side libraries.
- Avoid large animation packages when CSS/SVG is sufficient.
- Lazy-load non-critical below-the-fold heavy visuals if needed.
- Avoid hydration-heavy animated components unless interaction requires client state.
- Keep public pages as statically/renderably efficient as the architecture permits.

Any new dependency must be justified in the implementation plan and verified after installation.

---

## 22. SEO and metadata

Each page must have:

- unique title
- unique description
- canonical route semantics consistent with current app architecture
- meaningful heading hierarchy
- descriptive link labels

Brand should transition from "Options Dashboard" to "StrikeNova" in public metadata.

Do not use misleading keyword stuffing.

---

## 23. Engineering boundaries

The public-site redesign must not modify, unless separately approved:

- backend Python/FastAPI code
- database schema or migrations
- trading engine
- paper execution engine
- broker adapters
- OAuth/session implementation
- WebSocket/market-data architecture
- authenticated application routes
- execution semantics
- financial formulas

The public website is a presentation layer consuming verified product truth.

---

## 24. Parallel-work rule

Public V1.2 work may proceed in parallel with core architecture work.

Public work must stay isolated by:

- route group boundaries
- public component directories
- public style tokens/primitives
- explicit no-touch file boundaries

A public task must not alter backend behavior just because a visual mock would be easier to build by doing so.

---

## 25. Delivery phases

### P0 — Baseline & visual audit

- capture/verify current public pages
- confirm route/component inventory
- identify reusable components
- record current screenshots as baseline
- establish exact no-touch boundaries

### P1 — Brand & public design system

- StrikeNova public branding
- typography
- color semantics
- layout primitives
- surfaces
- motion
- visualization primitives

### P2 — Signal Field foundation

- build reusable Signal Field
- accessible SVG/CSS rendering
- responsive behavior
- reduced-motion path
- deterministic demo state

### P3 — Homepage

- full hero redesign
- market layers section
- intelligence visual
- strategy visual
- risk section
- paper trading section
- workflow rail
- final CTA

### P4 — Product pages

- Features / Capability Atlas
- Market Intelligence
- Strategy Lab
- Paper Trading

### P5 — Story pages

- How It Works
- About

### P6 — Navigation, metadata, content and polish

- public header
- footer
- metadata
- cross-page CTA consistency
- content truth audit

### P7 — Accessibility, responsive and performance hardening

- keyboard
- contrast
- reduced motion
- mobile layouts
- performance review
- visual regression baseline updates

### P8 — Final public acceptance

- desktop verification
- mobile verification
- route smoke tests
- console/error review
- production-readiness review

---

## 26. Phase gates

No later phase should start until the preceding phase has:

1. implementation complete for its defined scope;
2. focused tests/checks passing;
3. visual verification complete;
4. no unresolved P0/P1 findings within scope;
5. explicit Project Control Center approval to proceed.

This allows the public site to be completed part-by-part without destabilizing core platform work.

---

## 27. Definition of done

V1.2 is complete when:

- StrikeNova is the public brand.
- Signal Field is recognizable as the signature visual system.
- All seven public routes use a coherent visual language.
- Homepage feels materially different from V1.1 without becoming gimmicky.
- Product pages explain capability through visual storytelling rather than repeated card grids.
- Demo data is never misleading.
- Research capabilities are clearly separated from shipped features.
- Mobile and desktop are both first-class experiences.
- Accessibility checks pass.
- Public-site tests/build pass.
- Authenticated routes and backend remain behaviorally unchanged.
- Production visual verification confirms the intended site is actually served.

---

## 28. Explicit non-goals

V1.2 does not include:

- live market-data integration into marketing pages
- a new trading engine
- live order execution
- a new broker integration
- a new data vendor
- historical data storage solely for marketing visuals
- a new analytics backend just to support public-page animations
- a full authenticated-app redesign

---

## 29. Decision summary

The approved design direction is:

> **StrikeNova Signal Field — a futuristic, computational, options-native visual identity built around market structure, not generic fintech decoration.**

The site should feel like a **market research instrument from the future** while remaining credible, readable, transparent, performant, and grounded in actual product capabilities.
