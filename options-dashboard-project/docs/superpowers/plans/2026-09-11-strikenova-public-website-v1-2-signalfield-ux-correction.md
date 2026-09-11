# StrikeNova Public Website V1.2 — Signal Field UX Correction

> **Status:** APPROVED / READY FOR IMPLEMENTATION  
> **Type:** Post-acceptance focused UX correction  
> **Base candidate:** `cb0c2621cf8ded658b611d8e506042e0d4349260`  
> **Related acceptance record:** `4ebbc37ee3247093b5f90eff65ac31c8d1a0892b`

## 1. Purpose

Correct four concrete usability/readability problems discovered in the accepted StrikeNova Signal Field visualization:

1. Greeks text overlap and poor readability;
2. ambiguous floating IV arc;
3. unclear OI bar scale/axis semantics;
4. disconnected support/resistance/pivot reference lines.

This is a focused UX correction, not a new visual redesign and not a new product capability.

## 2. Source of truth

Primary implementation target:

`frontend/components/public/SignalField.js`

Primary test target:

`frontend/components/public/design-system.test.js`

The correction must preserve the accepted P1 design system, P2 Signal Field component contract, P3 homepage, P4 product pages, P5 story pages, P6 global cohesion, P7 hardening, and P8 acceptance architecture.

## 3. Correction A — Greeks readability

### Problem

The current SVG renders Delta/Gamma/Theta/Vega as tightly packed labels using positions only 20px apart. This can visually collide with OI numbers and is not beginner-friendly.

### Required solution

Remove the tightly packed inline Greek label row from the main SVG visualization.

Present Greeks in a dedicated readable breakdown below or alongside the main visualization using a responsive, multi-column layout.

Preferred presentation:

- DELTA
- GAMMA
- THETA
- VEGA

Each item should show:

- full name;
- value;
- concise sensitivity hint where appropriate;
- demo/illustrative status inherited from the truth system.

Example conceptual presentation:

```text
GREEKS
Delta     -0.02
Gamma      0.0003
Theta     +42.15
Vega      -18.40
```

The value source remains the existing deterministic demo state.

Do not change financial calculations.

Do not add live data.

### Accessibility

The full names must be available in the text representation. Do not require knowledge of Greek symbols to understand the component.

## 4. Correction B — replace ambiguous IV arc

### Problem

The current floating semicircular arc labelled `IV 14.2%` does not clearly communicate its meaning.

### Required solution

Replace it with a standard illustrative implied-volatility curve across the displayed strike range.

Extend the deterministic demo state to support IV by strike, for example:

```js
iv: {
  atm: "14.2%",
  vix: "13.8",
  skew: "slight put skew",
  state: "elevated",
  byStrike: [
    { strike: 25300, value: ... },
    { strike: 25400, value: ... },
    { strike: 25500, value: ... },
    { strike: 25600, value: ... },
    { strike: 25700, value: ... },
  ],
}
```

Values must be deterministic and illustrative only.

### Label

Clearly identify the curve as:

**IMPLIED VOLATILITY · DEMO**

or equivalent truthful wording.

Do not represent it as an expected-move curve.
Do not imply live IV.

## 5. Correction C — OI axis and legend

### Problem

The current call/put OI bars have no numerical scale or explicit explanation of what bar height represents.

### Required solution

Make the bars explicitly represent:

**OPEN INTEREST · CONTRACTS**

Add a light, readable Y-axis with sensible illustrative ticks.

Add explicit call/put legend treatment.

Example conceptual legend:

```text
CALL OI    PUT OI
```

Use the existing semantic color tokens, but do not rely on color alone.

Add a clear baseline/axis label.

The scale should be derived from the deterministic demo values rather than hard-coded purely for appearance.

Do not introduce a charting library.

## 6. Correction D — structure guide-line connection

### Problem

Resistance, pivot, and support lines are visually detached from their corresponding strikes.

### Required solution

Connect the structure levels directly to their strike positions.

Required mappings:

```text
25300 → Support
25500 → Pivot / Spot
25700 → Resistance
```

Extend vertical guide lines from those strike positions to the corresponding horizontal structure levels.

The visual relationship should make it immediately clear that the structure level belongs to that strike.

Avoid unnecessary labels in the lower-right quadrant.

## 7. Proposed final composition

The Signal Field should communicate this hierarchy:

```text
                     MARKET STATE
                          ●

        IMPLIED VOLATILITY       GREEKS
          strike curve       Delta / Gamma /
                              Theta / Vega

 CALL OI ███                         █████ PUT OI
        │                                │
────────┼──────── STRIKE RAIL ───────────┼───────
     25,300   25,400   25,500   25,600   25,700
       │                 │                 │
       │                 │                 │
     SUPPORT           PIVOT          RESISTANCE
```

Exact geometry may vary. The semantic relationships may not.

## 8. Responsive requirements

Verify at effective browser dimensions:

- 1440 × 900
- 1280 × 800
- 390 × 844
- 360 × 800

Requirements:

- no Greek overlap;
- no OI label collision;
- no clipped IV curve;
- strike labels remain readable;
- structure guides remain connected;
- mobile layout can stack supporting information cleanly;
- no horizontal overflow.

Do not use global `overflow-x: hidden` to conceal defects.

## 9. Accessibility requirements

Signal Field must retain:

- meaningful `role="img"` or equivalent semantics where appropriate;
- descriptive accessible label;
- text-equivalent interpretation of important values;
- no critical information encoded only by color;
- decorative SVG elements marked appropriately;
- reduced-motion compatibility.

The Greek breakdown must expose full names rather than only `Δ Γ Θ ν`.

The OI legend must distinguish calls and puts with text.

The structure levels must be understandable without relying only on line color.

## 10. Motion requirements

Reuse P1 motion primitives only.

Do not introduce:

- requestAnimationFrame loops;
- particle systems;
- WebGL;
- heavy animation libraries;
- random animation state.

Reduced-motion support must remain intact.

## 11. Data/truth requirements

The component remains a deterministic illustrative visualization.

No:

- network requests;
- broker calls;
- live market data;
- random values;
- new financial calculation engine;
- unsupported market claim.

All demo values must remain clearly illustrative.

## 12. Testing

Update/add focused Signal Field tests in:

`frontend/components/public/design-system.test.js`

Required coverage:

### Greeks

- full names appear;
- values appear;
- no compact symbol-only representation is required;
- deterministic demo state preserved.

### IV curve

- by-strike IV state exists;
- all displayed strikes have a deterministic IV value;
- curve is identified as implied volatility/demo.

### OI axis

- open-interest title/label exists;
- call/put legend exists;
- values remain deterministic.

### Structure

- support maps to 25300;
- pivot maps to 25500;
- resistance maps to 25700;
- corresponding guide-line structure remains represented.

### Regression

- existing Signal Field exports remain unchanged;
- no live/network dependency;
- accessibility semantics remain present.

## 13. Browser verification

Use a real browser against the local development server.

Verify:

- visual composition;
- Greek readability;
- no overlap;
- IV curve interpretation;
- OI scale/legend interpretation;
- structure-line connections;
- responsive behavior;
- console errors;
- reduced-motion behavior where practical.

Capture a screenshot of the Signal Field on desktop and mobile for internal review if the normal workflow supports it.

## 14. Scope

Expected source changes:

- `frontend/components/public/SignalField.js`
- `frontend/components/public/design-system.test.js`

Additional public-only support file changes are allowed only when strictly necessary.

Do not modify:

- backend;
- database/schema/migrations;
- broker integrations;
- OAuth/session internals;
- execution/trading engine;
- market-data architecture;
- financial calculation engines;
- authenticated `(app)` routes;
- global navigation/footer;
- unrelated public page bodies.

## 15. Version/release handling

This is a post-acceptance correction to V1.2.

Do not rewrite the accepted P8 record.

The accepted V1.2 acceptance remains historical evidence.

Deployment should remain on hold until this correction is implemented and independently reviewed.

If the correction is accepted, record it as a subsequent V1.2 maintenance/correction commit rather than modifying the historical P0–P8 chain.

## 16. Git

Work on:

`feat/strikenova-day35-portfolio-intelligence`

Recommended commit:

`fix(public): improve Signal Field readability and market semantics`

Do not force-push.

Do not deploy.

## 17. Final report

Return:

```text
SIGNAL FIELD UX CORRECTION: PASS / BLOCKED

Files changed:

Tests:
Build:
Browser:
Console errors:
Responsive overflow:

Greeks overlap: RESOLVED / NOT RESOLVED
IV curve: CLEAR / NOT CLEAR
OI axis+legend: CLEAR / NOT CLEAR
Structure connections: CLEAR / NOT CLEAR

Backend: NONE
Database: NONE
Broker: NONE
OAuth/session: NONE
Execution: NONE
Trading engine: NONE
Market-data architecture: NONE
Financial calculations: NONE
Authenticated app: NONE

Deployment: NOT PERFORMED
```

## 18. STOP CONDITION

After implementation and verification:

STOP.

Do not redesign other public pages.
Do not change the homepage outside Signal Field consumption.
Do not deploy.
Do not create a new product capability.

Return the exact commit SHA and evidence for Project Control Center review.
