# StrikeNova Visual Design System V1

**Date:** 2026-09-13  
**Status:** Design specification — review required before implementation  
**Scope:** StrikeNova public website and authenticated application UI  
**Primary principle:** *From Market Data to Structured Decisions.*

---

## 1. Purpose

This document defines the visual and interaction contract for StrikeNova. It is intended to prevent ad-hoc visual decisions by coding agents, designers, or future contributors.

StrikeNova is not positioned as a generic trading terminal, an options calculator, a crypto-style analytics dashboard, or an "AI trading" product. It is a market-intelligence and structured-decision platform for options traders.

The design must therefore communicate:

- analytical depth without visual intimidation;
- financial credibility without looking institutional or dated;
- high information density without clutter;
- premium product quality without decorative excess;
- actionable interpretation rather than raw-data accumulation;
- clear separation between market observation, analysis, decision support, and execution.

### Governing rule

> Every important visualization or metric should answer a meaningful market question.

Examples:

- **GEX** → Where could dealer positioning influence volatility and price behavior?
- **Gamma Flip** → Where does the modeled gamma regime change?
- **OI** → Where is options positioning concentrated?
- **IV/Vega** → Is volatility expansion or compression relevant to the current setup?
- **Strategy Builder** → Which structure expresses the current market thesis and risk profile?

---

## 2. Research Foundation

The system is informed by research across current financial products and modern software products. No external product is treated as a template or design dependency.

| Reference | Borrow | Do not copy |
|---|---|---|
| TradingView | Options information architecture, progressive disclosure, configurable tables | Brand styling or entire terminal layout |
| Zerodha Kite/Terminal | Indian trader workflow, workspace concept, execution proximity | Broker-specific interaction model |
| SpotGamma | Market-structure storytelling, GEX levels, regime framing | Proprietary terminology or claims beyond StrikeNova's methodology |
| ORATS | Quant workflow from analytics to strategy evaluation | Institutional complexity for its own sake |
| Unusual Whales | Custom intelligence views and filtering | Activity-first dashboard overload |
| Sensibull | Indian options strategy UX and payoff presentation | Strategy builder as the sole differentiator |
| Dhan | Strategy visualization and multi-leg analysis | Generic broker-dashboard styling |
| Linear | Information hierarchy, density, navigation discipline | Product branding |
| Vercel / Geist | Typography, precision, restraint, technical polish | Vercel identity |
| Stripe | Complex financial workflow clarity | Stripe-specific components or branding |
| Ramp | Decision-oriented analytics and reporting | Enterprise-finance visual clichés |
| HorizonX | Premium visual composition, motion, dashboard references | Template dependency or visual imitation |
| shadcn/ui ecosystem | Practical component primitives and accessible patterns | Treating defaults as the final StrikeNova identity |
| Landing-page galleries | Public-site storytelling and composition | Trend-chasing |

### Quantitative reference principle

GEX must be presented as market-structure/volatility context, not as a standalone directional predictor. Current public explanations from SpotGamma explicitly distinguish GEX from directional forecasting and describe Gamma Flip/Zero Gamma as a modeled regime transition. StrikeNova UI must preserve this distinction in labels and explanatory copy.

---

## 3. Product Personality

StrikeNova should feel:

- **Technical** — built for serious analytical work.
- **Premium** — polished enough to justify paid software.
- **Quietly powerful** — capability is demonstrated through clarity, not visual noise.
- **Quantitative** — numbers, relationships, and evidence are first-class.
- **Fast** — interfaces should feel responsive and purposeful.
- **Trustworthy** — financial claims and system states must never be visually ambiguous.
- **Structured** — users should understand where they are and why a metric matters.

It should not feel:

- crypto/Web3;
- gaming;
- casino-like;
- neon/cyberpunk;
- generic AI SaaS;
- overloaded Bloomberg imitation;
- template-generated;
- excessively glassmorphic;
- animation-first.

---

## 4. Core UX Model

The product architecture should visually reinforce this flow:

```text
MARKET DATA
    ↓
MARKET STATE
    ↓
MARKET STRUCTURE
    ↓
ANALYTICS
    ↓
SCENARIO / INTERPRETATION
    ↓
STRATEGY
    ↓
RISK
    ↓
PAPER EXECUTION
    ↓
JOURNAL / REVIEW
```

The application must not make execution the first or most visually dominant concept. Intelligence comes before action.

### Primary navigation concept

```text
Overview
Market Intelligence
Strategy Lab
Paper Trading
Trading Journal
```

Additional modules may be introduced later, but navigation must remain organized around user goals rather than backend subsystems.

---

## 5. Two Visual Contexts

StrikeNova has two related but distinct visual contexts.

### 5.1 Public website

Purpose: communicate product value, credibility, differentiation, and workflow.

Visual character:

- spacious;
- editorial;
- high-impact but restrained;
- strong typography;
- selective quantitative visualizations;
- subtle motion;
- product screenshots that show real analytical value.

### 5.2 Authenticated application

Purpose: high-frequency analytical work.

Visual character:

- denser;
- persistent navigation/context;
- compact controls;
- configurable data views;
- strong state indication;
- fast scanning;
- minimal decorative content.

The public site may be cinematic in selected sections. The application must prioritize operational clarity.

---

## 6. Color System

The color system must be semantic, not component-specific.

### Base surfaces

Use a restrained neutral foundation with separate tokens for:

- page background;
- elevated surface;
- secondary surface;
- input/control surface;
- border/subtle border;
- primary text;
- secondary text;
- muted text.

Both dark and light themes should remain possible, but **dark is the primary analytical environment** unless an existing product requirement says otherwise.

### Semantic states

Use semantic tokens for:

- positive / bullish;
- negative / bearish;
- warning / elevated risk;
- neutral;
- informational;
- active/focus;
- disabled.

Do not use green/red merely as decoration. A state color must carry semantic meaning.

### Quant visualization colors

Charts may use additional distinguishable series colors, but they must remain subordinate to semantic market-state colors.

Avoid a permanent "green vs red everywhere" aesthetic. Use neutral chart scaffolding and reserve strong semantic colors for meaningful states.

### Prohibited patterns

- neon gradients as primary identity;
- glowing borders around ordinary cards;
- rainbow charts without semantic reason;
- colored text for every numeric value;
- low-contrast grey-on-grey financial data;
- color-only state communication.

---

## 7. Typography

Typography must prioritize numerical legibility and hierarchy.

### Rules

1. Use one primary UI type family unless a specific brand treatment is justified.
2. Use tabular/monospaced numerals where aligned numeric comparison benefits from it.
3. Headlines may be expressive on the public site but must remain restrained in the app.
4. Labels should be compact and unambiguous.
5. Avoid excessive font-weight changes.
6. Never rely on typography alone to distinguish market states.

### Hierarchy

```text
Display / Hero
Page title
Section title
Metric value
Metric label
Body
Secondary metadata
Micro label
```

Numbers must remain readable at normal dashboard zoom and on smaller screens.

---

## 8. Layout and Grid

### Application

The application should use a stable shell:

```text
┌────────────────────────────────────────────────────────────┐
│ Global context / symbol / market state                    │
├─────────────┬──────────────────────────────────────────────┤
│ Navigation  │ Page header / controls                      │
│             ├──────────────────────────────────────────────┤
│             │ Primary analytical workspace                 │
│             │                                              │
│             │ Secondary supporting panels                  │
└─────────────┴──────────────────────────────────────────────┘
```

### Principles

- alignment is more important than decoration;
- related metrics should share visual boundaries;
- avoid arbitrary card sizes;
- use consistent vertical rhythm;
- allow dense tables to use the available width;
- do not make every element a card;
- whitespace separates concepts, not individual numbers.

### Public site

Use an editorial grid with deliberate asymmetry where it improves storytelling. Do not turn every section into a uniform three- or four-card grid.

---

## 9. Cards and Panels

Cards are for grouping a coherent concept, not for decorating every metric.

### Preferred card anatomy

```text
Label / context
Primary metric or visualization
Short interpretation
Optional action / drill-down
```

Example:

```text
GAMMA REGIME
Positive

Dealer positioning is modeled as stabilizing
above the current Gamma Flip.

[View Structure →]
```

### Avoid

```text
┌──────────┐ ┌──────────┐ ┌──────────┐
│  GEX     │ │  IV      │ │  VIX     │
│  +4.2B   │ │  18.2%   │ │  14.2    │
└──────────┘ └──────────┘ └──────────┘
```

when there is no interpretation or relationship between those numbers.

---

## 10. Data Tables

Options chains are inherently data-dense. StrikeNova should use progressive disclosure rather than hiding important data permanently.

TradingView demonstrates a useful model: configurable option-chain columns, multiple views, and expandable row detail. StrikeNova should apply the same principle while emphasizing its own intelligence layer.

### Default table

Show only the highest-value fields for the user's current workflow.

### Advanced mode

Allow additional Greeks, IV, theoretical values, and market fields.

### Row expansion

A row may expose:

- contract details;
- payoff preview;
- relevant Greeks;
- scenario values;
- strategy actions;
- market context.

### Table rules

- sticky strike/context columns where useful;
- clear call/put grouping;
- right-align numerical data;
- consistent decimal precision;
- no unexplained abbreviations;
- preserve keyboard and screen-reader usability;
- avoid excessive zebra striping;
- use subtle hover/focus states.

---

## 11. Market Intelligence Dashboard

This is the visual center of the StrikeNova application.

### Recommended hierarchy

```text
MARKET STATE
    ↓
KEY STRUCTURAL LEVELS
    ↓
GEX / OI / IV / GREEKS
    ↓
SIGNALS / DIVERGENCES
    ↓
SCENARIOS
    ↓
STRATEGY IMPLICATION
```

### Example

```text
NIFTY 50                         25,xxx
Market Regime                    BULLISH
Confidence                       78%

Gamma Flip                       25,180
Call Wall                        25,400
Put Wall                         25,050

Net GEX                          Positive
IV Regime                        Stable
VIX                              14.2

────────────────────────────────────────

WHAT MATTERS NOW
Positive gamma suggests movement may be
absorbed around current structure.

[Inspect GEX] [Run Scenario]
```

The interpretation layer is the differentiator. Raw charts remain available for advanced users.

---

## 12. GEX and Gamma Visualization

GEX must be visually legible at both overview and analytical levels.

### Required concepts

- Net GEX;
- GEX by strike;
- Call Wall;
- Put Wall;
- Gamma Flip / Zero Gamma;
- optional expiration breakdown;
- spot price;
- regime indication.

SpotGamma's current documentation emphasizes that GEX describes market structure and volatility sensitivity rather than direction, and identifies Call Wall, Put Wall, and Gamma Flip as key structural levels. StrikeNova should preserve this conceptual distinction.

### Preferred visualization hierarchy

**Overview:**

```text
Current Price ────────●────────
                      │
              Gamma Flip
                      │
         Positive / Negative regime
```

**Detailed:**

- strike-based histogram/curve;
- spot marker;
- structural level annotations;
- optional expiry layers;
- tooltip with methodology/context.

### Do not

- imply GEX predicts direction;
- use a single green/red gauge as the entire GEX product;
- hide assumptions/methodology;
- use proprietary competitor terminology as if it were StrikeNova's own model.

---

## 13. Greeks, IV, OI, and Signal Visualization

### Greeks

Prefer compact comparative displays and contextual tooltips over giant individual cards.

Examples:

- Delta exposure by strike;
- Gamma concentration;
- Vega sensitivity;
- Theta pressure;
- ATM vs OTM comparisons.

### IV

Visualize:

- current IV;
- IV regime;
- relative change;
- call/put comparison;
- relationship to VIX where appropriate.

### OI

Prioritize:

- concentration;
- change in OI;
- price/OI relationship;
- structural support/resistance context.

### Signals

Signals must have:

- name;
- state;
- confidence/strength where scientifically justified;
- supporting evidence;
- timestamp/data freshness;
- explanation or drill-down.

Never show an unexplained "BUY 92%" style badge.

---

## 14. Strategy Lab

Strategy Lab should visually follow the chain:

```text
Market thesis
    ↓
Candidate structure
    ↓
Payoff
    ↓
Greeks / risk
    ↓
Scenario
    ↓
Evaluation
```

The payoff chart is the visual anchor, but the market context must remain visible.

### Strategy builder rules

- legs are visually distinct;
- buy/sell and call/put are unambiguous;
- quantities and prices remain readable;
- payoff and risk update immediately;
- scenario assumptions are explicit;
- no visual suggestion that a strategy is guaranteed to work.

---

## 15. Paper Trading

Paper Trading should feel like a controlled execution environment, not like a game.

### Visual priorities

1. Instrument/position context
2. Order state
3. Price/quantity
4. Risk/margin impact
5. Confirmation
6. Lifecycle state

### Lifecycle states

Use explicit states such as:

```text
Draft → Submitted → Accepted → Filled → Open → Exit Requested → Closed
```

Animations may communicate state transitions but must never obscure the actual state.

---

## 16. Trading Journal

The Journal should feel analytical rather than diary-like.

Primary dimensions:

- realized P&L;
- strategy;
- market regime;
- setup quality;
- execution quality;
- risk outcome;
- lesson/review.

The visual language should encourage comparison over time:

```text
Trade → Outcome → Context → Review → Pattern
```

---

## 17. Public Website

The public site should sell the **workflow**, not a list of features.

### Recommended narrative

```text
Hero
 ↓
The problem: too much market data, too little structure
 ↓
StrikeNova workflow
 ↓
Market Intelligence
 ↓
Strategy Intelligence
 ↓
Risk / Scenario
 ↓
Paper Trading
 ↓
Journal / feedback loop
 ↓
Product proof
 ↓
CTA
```

### Hero direction

Primary message:

> **From Market Data to Structured Decisions.**

Supporting copy should explain the transformation rather than claim prediction.

### Visual language

Use real analytical artifacts:

- GEX structures;
- option-chain snippets;
- payoff curves;
- market-state panels;
- scenario comparisons.

Avoid generic stock photos, generic AI illustrations, floating 3D blobs, and decorative dashboards with fake numbers.

---

## 18. Motion System

Motion is functional, not ornamental.

### Appropriate uses

- page/section transitions;
- progressive disclosure;
- chart state changes;
- strategy-leg updates;
- order lifecycle transitions;
- hover/focus feedback;
- subtle public-site storytelling.

### Motion rule

> If removing the animation does not reduce comprehension, it is probably optional.

### Required safeguards

- reduced-motion support;
- no animation that blocks interaction;
- no rapidly pulsing market-state indicators;
- no constant decorative movement in analytical workspaces.

---

## 19. Responsive Design

Responsive behavior is a product requirement, not a final polish step.

### Desktop

Primary analytical workstation.

### Tablet

Collapse secondary panels while preserving market context and key controls.

### Mobile

Do not attempt to reproduce the desktop dashboard literally.

Prioritize:

1. market state;
2. key levels;
3. critical alerts/signals;
4. compact charts;
5. drill-down pages.

Dense option-chain workflows may intentionally remain desktop-first where usability would otherwise degrade.

---

## 20. Accessibility

Financial state must never be communicated through color alone.

Every semantic state should have at least one additional cue:

- label;
- icon;
- symbol;
- text;
- position/context.

Requirements:

- keyboard navigation;
- visible focus;
- sufficient contrast;
- screen-reader labels for charts and controls;
- reduced-motion support;
- accessible tables;
- error states with actionable text.

---

## 21. Component Governance

The design system must be implemented through reusable semantic primitives rather than page-specific CSS improvisation.

Suggested conceptual layers:

```text
Design tokens
    ↓
Primitive components
    ↓
Financial primitives
    ↓
Analytical modules
    ↓
Page compositions
```

### Financial primitives

Examples:

- MarketStateBadge
- MetricValue
- PriceChange
- SignalStrength
- RiskIndicator
- StructuralLevel
- GreekValue
- IVValue
- PositionState
- OrderState

### Analytical modules

Examples:

- MarketStatePanel
- GEXPanel
- GammaLevelsPanel
- OptionsChain
- GreeksMatrix
- ScenarioPanel
- StrategyPayoff
- PositionRisk

Page components should compose these modules rather than recreate their visual logic.

---

## 22. AI-Agent Guardrails

This section is mandatory for all AI-assisted implementation.

### Agents may

- implement components using the approved system;
- improve accessibility;
- improve responsive behavior;
- simplify visual clutter;
- fix spacing/typography inconsistencies;
- create reusable primitives where duplication is proven;
- propose changes through documented review.

### Agents may not independently

- introduce a new visual style;
- replace the design system with a purchased template;
- introduce neon/glow aesthetics;
- turn every metric into a card;
- add decorative animation without a UX reason;
- change semantic colors arbitrarily;
- copy another product's brand identity;
- make financial claims visually stronger than the underlying evidence;
- redesign navigation without an approved design change;
- remove explanatory context from quantitative signals merely to make the UI look cleaner.

### Escalation rule

If implementation requires a decision not covered by this document, the agent must:

1. identify the missing rule;
2. present the smallest reasonable proposal;
3. avoid silently inventing a new system;
4. wait for approval when the decision affects shared design language.

---

## 23. Do / Don't Matrix

| Do | Don't |
|---|---|
| Use restrained dark analytical surfaces | Build a neon crypto aesthetic |
| Prioritize information hierarchy | Make every element a card |
| Explain quantitative metrics | Show unexplained scores |
| Use progressive disclosure | Dump every Greek into the default view |
| Use motion to explain state | Animate everything |
| Use semantic colors | Color every number |
| Show methodology/context | Imply certainty from modeled metrics |
| Build reusable primitives | Duplicate page-specific styling |
| Use real product data in marketing examples | Use fake decorative charts without context |
| Keep the app dense but calm | Make it visually noisy |
| Make desktop the primary analytical workspace | Force the entire terminal onto mobile |
| Borrow patterns | Copy competitors' branding |

---

## 24. Design Acceptance Criteria

A page or component is not design-system compliant unless:

- its purpose is clear without visual guesswork;
- hierarchy is obvious;
- semantic states are consistent;
- quantitative values are legible;
- color is not the only state indicator;
- spacing follows shared tokens;
- responsive behavior is intentional;
- motion is purposeful and reduced-motion safe;
- the component does not introduce an unrelated visual language;
- financial interpretation is not overstated;
- accessibility is considered;
- repeated patterns use shared primitives.

### Product-level acceptance

A user should be able to answer:

1. **What is happening in the market?**
2. **Why does StrikeNova think that?**
3. **What structural levels matter?**
4. **What scenarios should I consider?**
5. **What strategy expresses my thesis?**
6. **What is the risk?**
7. **What happened after execution?**

without navigating through a maze of unrelated dashboards.

---

## 25. Implementation Boundary

This document defines design intent and governance. It does **not** authorize immediate broad UI refactoring.

Implementation should be incremental and evidence-driven:

1. inventory existing design tokens/components;
2. identify gaps against this document;
3. establish the shared primitives;
4. migrate one representative public page;
5. migrate one representative analytical page;
6. independently audit visual consistency;
7. expand only after the system proves reusable.

No wholesale rewrite is implied by this specification.

---

## 26. Reference Links

- TradingView Options Chain: https://www.tradingview.com/support/solutions/43000760837-options-chain-overview/
- SpotGamma GEX: https://spotgamma.com/gamma-exposure-gex/
- SpotGamma Gamma Flip: https://support.spotgamma.com/hc/en-us/articles/15413261162387-Gamma-Flip
- Vercel Geist: https://vercel.com/geist/introduction
- shadcn/ui: https://ui.shadcn.com/
- HorizonX: https://horizonx.so/

These links are research references, not implementation dependencies.

---

## 27. Final Design Contract

> **StrikeNova is a market-intelligence product first and a trading interface second.**
>
> The interface should make complex options information easier to understand, compare, validate, and act upon — without pretending that modeled analytics are certainty.
>
> The visual system should therefore combine the information discipline of professional trading software, the clarity of modern product design, and the polish of premium SaaS — while developing a distinctly StrikeNova-native identity.
