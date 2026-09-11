# StrikeNova Public Website V1.2 — P2 Signal Field Foundation

> **Status:** Authorized — implementation handoff
> **Date:** 2026-09-11
> **Scope:** Public presentation layer only. Build the reusable StrikeNova Signal Field foundation. Do not redesign public pages.
> **Predecessor:** P1 accepted at corrective commit `17492609dfb031f2b23e6566798e4c787caba669`

## Authority documents

Design specification:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/specs/2026-09-10-strikenova-public-website-v1-2-design.md

Master implementation plan:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/plans/2026-09-10-strikenova-public-website-v1-2.md

P0 audit:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/superpowers/audits/2026-09-10-strikenova-public-website-v1-2-p0-baseline.md

Current project status:

https://github.com/shahid1995/-options-dashboard/blob/main/options-dashboard-project/docs/PROJECT_STATUS_CURRENT.md

## P2 objective

Create StrikeNova's reusable signature visualization: **Signal Field**.

The Signal Field is a market-native visualization of:

```text
Price
OI
OI Change
IV
Greeks
Structure
        ↓
   Market State
```

It should feel like a computational market instrument rather than a generic chart, dashboard screenshot, or decorative neon graphic.

P2 is the first phase that creates the actual signature visual language. It still does **not** redesign the seven public pages.

## Mandatory boundaries

### Do not change

- `frontend/app/(public)/page.js`
- `frontend/app/(public)/features/**`
- `frontend/app/(public)/market-intelligence/**`
- `frontend/app/(public)/strategy-lab/**`
- `frontend/app/(public)/paper-trading/**`
- `frontend/app/(public)/how-it-works/**`
- `frontend/app/(public)/about/**`
- `frontend/app/(app)/**`
- `backend/**`
- database/schema/migrations
- broker integrations
- OAuth/session logic
- execution/trading logic
- market-data architecture
- financial calculation engines

Do not add live broker/data-provider calls.
Do not add new backend endpoints.
Do not deploy.

## Important P1 context

P1 already created generic signal primitives in:

`frontend/components/public/signals.js`

Current primitives include:

- `SignalLine`
- `SignalNode`
- `StrikeRail`
- `DataTrace`
- `TechnicalDivider`
- `GridOverlay`

Do **not** create duplicate `SignalNode.js` or `StrikeRail.js` files merely because the original master plan listed those proposed filenames.

First inspect and reuse/evolve the P1 primitives. Keep one coherent source of truth.

Similarly, P1 already provides:

- semantic tokens in `tokens.js`
- motion in `motion.js`
- reusable surfaces
- metrics
- visualization frame
- responsive layout primitives
- truth/data-state primitives

P2 should compose these.

---

# P2.1 — Signal Field contract

Before coding, define the concrete component contract.

Create a short internal implementation note or code comments covering:

### Inputs

Signal Field should accept a deterministic illustrative state rather than fetching data.

Suggested conceptual state:

```js
{
  spot,
  strikes,
  oi,
  oiChange,
  iv,
  greeks,
  structure,
  marketState
}
```

Exact schema may differ if a cleaner API is justified.

Requirements:

- deterministic
- serializable
- no `Math.random()`
- no network
- no broker dependency
- no authentication dependency
- no current-market claim

### Semantic layers

The component must be able to visually represent:

```text
PRICE
POSITIONING / OI
OI CHANGE
VOLATILITY / IV
GREEKS
STRUCTURE
MARKET STATE
```

Not every layer must occupy equal visual weight.

The design should establish hierarchy rather than a flat seven-item chart.

---

# P2.2 — Evolve P1 SignalNode

Use the existing `SignalNode` from `signals.js` as the starting point.

Inspect its current API and implementation before changing it.

Required outcome:

- semantic label
- optional value
- semantic role/state
- position support
- optional visual state such as active/focus/positive/risk/info
- accessible text representation
- reduced-motion compatibility

Avoid breaking existing consumers. Since current P1 consumers may be limited, determine the safest backward-compatible extension.

Do not make the node itself overly elaborate.

The node should be useful as a basic primitive, while SignalField owns the higher-level composition.

---

# P2.3 — Evolve P1 StrikeRail

Use the existing `StrikeRail` from `signals.js`.

Required outcome:

- central/spot reference
- illustrative strike levels
- readable labels
- active/reference state
- desktop vertical orientation
- mobile horizontal orientation where appropriate
- no forced minimum width that causes viewport overflow

Do not create a second StrikeRail component.

Keep the API small.

---

# P2.4 — Implement SignalField

Create:

`frontend/components/public/SignalField.js`

This is the primary P2 deliverable.

## Visual composition

Build around the conceptual system:

```text
                    VOLATILITY / IV
                           │
                           ●
                           │
          OI ●────────────●────────────● GREEKS
                           │
                           │
                      ── SPOT ──
                           │
                     STRIKE RAIL
                           │
              ─────────────────────
                 MARKET STRUCTURE
                           │
                           ↓
                     MARKET STATE
```

This is a conceptual guide, not a requirement for literal geometry.

The final composition should be visually sophisticated, asymmetric where useful, and clearly market-native.

## Design requirements

### Market-native

Visual elements should derive from:

- strikes
- OI concentrations
- OI change
- volatility bands
- Greek signals
- support/resistance structure
- spot/reference price

Avoid generic circles-and-lines decoration with no analytical meaning.

### Futuristic but credible

Use:

- thin technical lines
- signal nodes
- subtle glows
- controlled cyan/violet/gold semantics
- layered dark surfaces
- restrained grid structure

Avoid:

- crypto/gaming neon
- giant particle fields
- rainbow gradients
- excessive blur
- fake holographic gimmicks
- continuous viewport-heavy animation

### Visual hierarchy

The eye should understand this order:

```text
1. Market State
2. Spot/reference
3. major market forces
4. strike structure
5. supporting metrics
```

Do not make every node equally bright.

---

# P2.5 — Illustrative state

Create a small deterministic demo state for Signal Field.

Example concept only:

```text
Spot: 25,500
Reference strikes: 25,300 / 25,400 / 25,500 / 25,600 / 25,700
OI concentration: illustrative
OI change: illustrative
IV: illustrative
Greeks: illustrative
Structure: illustrative
```

All numerical values must be clearly treated as demo/illustrative.

Do not label invented values as `LIVE`.

Do not imply that the display is connected to NSE, BSE, Upstox, or any broker.

Prefer the P1 truth primitives for labeling.

---

# P2.6 — Market State treatment

Create a clear semantic presentation for the final state.

Examples of conceptual states:

- bullish pressure
- bearish pressure
- balanced / range-bound
- mixed / conflicting

The implementation should not present these as prediction certainty.

Use wording such as:

- illustrative market state
- structure indicates
- observed in the example

Avoid:

- guaranteed direction
- prediction certainty
- expected profit
- accuracy percentage

If a state label is included, make clear that it is part of the illustrative demo state.

---

# P2.7 — Accessibility model

The Signal Field must have a text-equivalent interpretation.

A screen-reader user must not receive only an unexplained decorative SVG/canvas.

Provide an accessible representation such as:

```text
Signal Field, illustrative data.
Spot 25,500.
Primary positioning signal: ...
Volatility signal: ...
Greek signal: ...
Structure reference: ...
Illustrative market state: ...
```

The exact wording may be adapted to the actual state.

Requirements:

- meaningful overall accessible name
- useful text alternative
- no color-only semantic dependency
- decorative lines remain `aria-hidden`
- important nodes/labels are represented textually

Do not expose duplicate noisy content to assistive technology.

---

# P2.8 — Reduced motion

Signal Field animation must be optional/subtle.

Preferred motion:

- node appearance
- soft pulse
- trace drawing
- restrained state emphasis

Do not use continuous animation to communicate essential meaning.

The existing P1 reduced-motion CSS must work.

Verify that:

```text
prefers-reduced-motion: reduce
```

results in no distracting continuous Signal Field animation.

---

# P2.9 — Responsive behavior

The component must work at:

- 1440×900
- 1280×800
- 390×844
- 360×800

Minimum requirements:

- no horizontal page overflow caused by SignalField
- no clipped strike labels
- no overlapping nodes that make labels unreadable
- no hard-coded desktop width that breaks mobile
- mobile composition remains understandable

Important P0 caveat:

The earlier CDP audit had a viewport-measurement discrepancy on narrow devices. Use confirmed effective viewport dimensions when verifying P2.

Do not claim that a width test is valid merely because a headless tool reports a nominal viewport setting.

---

# P2.10 — Performance

SignalField must remain lightweight.

Prefer:

- SVG
- CSS
- simple React composition

Avoid introducing a charting/graphics dependency unless there is a compelling, documented reason.

No WebGL dependency for P2.

No canvas animation loop unless absolutely necessary.

No requestAnimationFrame loop for purely decorative effects.

Keep DOM complexity reasonable.

---

# P2.11 — Visualization frame integration

SignalField should be compatible with the P1 `VisualizationFrame`.

Do not require callers to duplicate:

- eyebrow
- title
- caption
- legend
- demo label

The final component may be used as:

```jsx
<VisualizationFrame
  eyebrow="SIGNAL FIELD"
  title="Illustrative market state"
  demoLabel
>
  <SignalField ... />
</VisualizationFrame>
```

The component itself should remain concerned with the visual model, not page-level marketing copy.

---

# P2.12 — Testing

Add focused tests for Signal Field.

At minimum:

### Rendering

- default render succeeds
- required structure exists
- deterministic demo state renders
- no random state generation

### Data semantics

- null/unavailable values do not become fake zeros
- demo/illustrative state remains visibly labeled when used through the intended wrapper
- market-state value is deterministic

### Accessibility

- overall visualization has an accessible name
- text-equivalent interpretation exists
- important labels are present
- decorative primitives remain hidden where appropriate
- no required meaning depends solely on color

### Responsive contract

Test the component-level assumptions that are practical to validate in the current test environment.
Do not pretend component tests prove actual browser geometry.

### Motion

- signal primitives use the P1 motion system
- no direct hard-coded animation that bypasses reduced-motion behavior unless justified

---

# P2.13 — Browser verification

A browser verification pass is required.

Inspect the SignalField on a running local public page or a minimal test harness.

Check:

- no console errors
- no runtime exceptions
- no horizontal overflow caused by SignalField
- labels readable
- nodes/rails align correctly
- motion is subtle
- reduced-motion behavior works
- mobile layout remains coherent

Because P3 is not authorized, use a minimal isolated test harness/page if necessary rather than modifying a production public page.

Do not leave a temporary production route behind.

---

# P2.14 — Files

Expected primary file:

`frontend/components/public/SignalField.js`

Likely supporting changes:

`frontend/components/public/signals.js`

`frontend/components/public/index.js`

`frontend/components/public/design-system.test.js`

Additional public-only helper/data files are allowed only where they materially improve clarity.

Do not duplicate P1 primitives.

---

# P2.15 — Engineering quality

Prefer clear, composable APIs over a large component with dozens of props.

The SignalField API should describe the market concept, not low-level pixel coordinates everywhere.

Avoid embedding page-specific copy.

Avoid coupling to pathname, router state, authentication context, or broker state.

Do not hard-code live market assumptions into the component.

Do not import backend modules.

---

# P2.16 — Regression verification

Run fresh:

- full frontend test suite
- production Next.js build
- all seven existing public routes

Verify the existing routes still return HTTP 200.

Verify there are no import/build regressions.

Verify no authenticated-app files changed.

Inspect the final git diff manually.

---

# P2.17 — Git discipline

Commit with a focused message, for example:

`feat(public): build StrikeNova Signal Field foundation`

Do not deploy.

Do not merge unrelated changes into the commit.

---

# STOP CONDITION

P2 ends after the Signal Field component and its verification are complete.

Do NOT implement:

- homepage redesign
- Features redesign
- Market Intelligence page redesign
- Strategy Lab redesign
- Paper Trading redesign
- How It Works redesign
- About redesign
- WorkflowRail for P3
- CapabilityModule page compositions
- final public navigation redesign
- P6/P7 hardening

Those are separately gated.

## Required final report

Return:

### P2 result

`PASS` or `BLOCKED`

### Files changed

Exact list.

### Signal Field inventory

- component(s)
- reused/evolved P1 primitives
- demo-state source
- accessibility mechanism
- motion mechanism
- responsive strategy

### Verification

Report actual fresh evidence:

```text
Tests:
Build:
Public routes:
Browser verification:
Console errors:
```

### Protected scope

Confirm whether any of these changed:

```text
backend
DB/schema/migrations
broker
OAuth/session
execution
trading engine
market-data architecture
financial calculation engines
authenticated app
```

Expected: `NONE`

### Boundary confirmation

Explicitly state:

- P3 homepage redesign was NOT implemented.
- No public page redesign was implemented.
- No live data was added.
- No deployment was performed.

Then STOP.
