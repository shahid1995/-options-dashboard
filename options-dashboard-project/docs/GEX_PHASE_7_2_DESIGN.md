# Phase 7.2 — Gamma Flip & Gamma Walls Design

Status: DESIGN ONLY — no implementation approved

## 1. Objective

Phase 7.2 extends the Phase 7.1 GEX foundation with two structural levels:

- **Gamma Flip / Zero Gamma:** the underlying price where modeled aggregate net GEX changes sign.
- **Gamma Walls:** high-concentration strike levels where modeled gamma exposure is unusually large.

These are **market-structure analytics**, not directional trading signals. GEX estimates are model-dependent and must never be presented as direct observation of dealer inventory.

## 2. Research conclusions

Public methodologies broadly agree on the core idea: aggregate gamma exposure by strike/expiry, identify the price where aggregate gamma changes sign, and identify major positive/negative gamma concentrations. SpotGamma describes Gamma Flip as the price at which modeled dealer gamma transitions between positive and negative; Cboe describes market-maker gamma as the change in delta exposure caused by a 1% underlying move and emphasizes both magnitude and sign. These sources also stress that actual dealer positions/hedges are not directly observable from public OI alone.

The project must therefore distinguish:

1. **Observed inputs:** option OI, strike, expiry, spot, IV, and broker/model Greeks.
2. **Model outputs:** GEX, Gamma Flip, Gamma Walls, and regime labels.
3. **Assumptions:** dealer-sign convention and the treatment of IV/dividend/rate inputs during spot sweeps.

## 3. Critical mathematical requirement

A Gamma Flip cannot be found by simply finding the strike whose current GEX is closest to zero.

At the current spot `S0`, Phase 7.1 can calculate current GEX from current gamma. For a flip, we need a function:

`NetGEX(S)`

where gamma is recomputed as the hypothetical underlying price `S` changes.

Therefore Phase 7.2 must use a **spot-sweep model**:

1. Keep the option contracts, OI, strike, expiry and selected IV snapshot fixed for the calculation.
2. Sweep hypothetical underlying prices across a configurable range around current spot.
3. Recalculate option gamma at each hypothetical spot using the same documented option-pricing convention.
4. Apply the Phase 7.1 GEX sign convention.
5. Sum all included contracts.
6. Detect sign changes in `NetGEX(S)`.
7. Interpolate between adjacent grid points to estimate the zero crossing.

Using current gamma as a constant while changing spot is **not acceptable** because it produces no meaningful spot-dependent gamma surface.

## 4. Gamma model for the sweep

For European index options, use Black-Scholes gamma (or the project's already-established equivalent model) with:

- hypothetical spot `S`
- strike `K`
- time to expiry `T`
- implied volatility `sigma` captured from the selected chain snapshot
- risk-free rate `r` from the existing project model/configuration if available
- dividend yield `q` from the existing project model/configuration if available

The implementation must reuse an existing canonical Greek/model implementation where possible rather than create a second incompatible Greek engine.

If required inputs are unavailable, the flip result must be `UNAVAILABLE` or `PARTIAL`; never silently substitute zero gamma.

## 5. Dealer-sign convention

Phase 7.1 uses the project convention:

- Call contribution: positive
- Put contribution: negative

This convention must remain explicit and versioned.

The UI and API must label the result as **modeled GEX / modeled Gamma Flip**, not actual dealer positioning.

## 6. Expiry scope

Phase 7.2 should support configurable expiry scopes:

- `NEAREST`
- `CURRENT_WEEK`
- `NEXT_WEEK`
- `MONTHLY`
- `ALL_ACTIVE`
- explicit expiry list

Default recommendation for the first implementation: **ALL_ACTIVE within a configurable maximum horizon**, while exposing the expiry composition of the result. This avoids making a single-expiry assumption that can be misleading for NIFTY.

For NIFTY, 0DTE/current-expiry gamma can become disproportionately large near expiry. Therefore the result must expose per-expiry GEX contribution and allow the user to inspect/remove an expiry later.

## 7. Spot sweep range and grid

Do not hard-code a universal percentage range.

Recommended initial configuration:

- center: current underlying spot
- range: configurable percentage of spot, default ±5%
- grid: configurable number of points, default 201
- refine around each detected sign change using interpolation/bisection

The algorithm should be deterministic.

If the sweep does not cross zero, return `NO_FLIP` rather than forcing the nearest grid point to be called a Gamma Flip.

If multiple crossings exist, return all valid crossings internally and identify a **primary flip** using documented rules; do not discard secondary crossings silently.

## 8. Gamma Flip selection rules

For each adjacent sweep interval `[S_i, S_{i+1}]`:

- if `NetGEX(S_i) == 0`, that point is an exact grid crossing;
- if `NetGEX(S_i)` and `NetGEX(S_{i+1})` have opposite signs, interpolate the zero crossing;
- if either value is unavailable, do not infer a crossing.

Primary flip ranking should prefer:

1. crossings near current spot;
2. crossings with a strong sign change relative to local GEX magnitude;
3. crossings supported by sufficient data coverage;
4. stable crossings under small grid perturbations.

The implementation must return confidence/quality metadata rather than pretending every zero crossing is equally reliable.

## 9. Flip quality metrics

Return at minimum:

- `flip_price`
- `distance_points`
- `distance_percent`
- `side_of_flip` (above/below/currently near)
- `gex_before`
- `gex_after`
- `crossing_strength`
- `grid_step`
- `expiry_scope`
- `contracts_included`
- `data_quality`
- `method_version`

A useful future stability test is to recompute the flip with a finer grid and compare the price difference.

## 10. Gamma Walls

Do not define walls as simply the largest raw OI strike.

A wall is a **gamma concentration**, so selection must be based on GEX.

Initial definitions:

### Call Wall

Largest positive call-side GEX concentration among strikes above current spot within the configured search window.

### Put Wall

Largest absolute negative put-side GEX concentration among strikes below current spot within the configured search window.

The first implementation should also return the top-N candidate walls so the UI can later display the concentration profile rather than hiding everything behind one level.

## 11. Wall search window

Avoid selecting extremely distant or illiquid strikes solely because of a mathematical artifact.

Initial design:

- configurable percentage distance around spot;
- default ±5% for NIFTY;
- exclude strikes with unavailable/invalid gamma or OI;
- retain the exact strike and expiry composition behind each wall.

Expected-move-based windows can be added later after the project has a validated expected-move/IV framework.

## 12. Wall quality

Each wall should return:

- strike
- side (`CALL` / `PUT`)
- GEX magnitude
- share of total same-side GEX
- distance from spot
- number of expiries contributing
- top contributing expiries
- data-quality status

Do not call a weak isolated strike a "strong wall" merely because it ranks first. The strength metric should be exposed separately from the level itself.

## 13. Important distinction: current GEX vs flip GEX

Phase 7.1 current GEX:

`GEX(S0) = gamma(S0) × OI × S0² × 0.01`

Phase 7.2 flip calculation:

`NetGEX(S) = sum[ modeled_gamma_i(S) × OI_i × S² × 0.01 × sign_i ]`

The spot-dependent gamma must be recomputed for each hypothetical `S`.

Because the same positive scaling constants do not affect a zero crossing, the exact GEX currency scaling does not change the mathematical flip location as long as it is applied consistently. The project must nevertheless preserve one documented unit convention for reporting GEX magnitude.

## 14. Data quality rules

- Missing gamma-model inputs: unavailable.
- Missing IV for a contract: unavailable for sweep unless a documented fallback model is approved.
- Missing OI: exclude that contract and mark the result partial.
- Non-positive spot: invalid.
- Non-positive time to expiry: use the project's explicit expiry convention; do not silently invent time.
- Duplicate option contracts: deduplicate using the canonical instrument identity.
- Sparse chain: return quality warnings.
- No zero-crossing: `NO_FLIP`.
- Multiple crossings: preserve all crossings internally.

## 15. What Phase 7.2 must NOT do

Do not implement:

- buy/sell signals;
- automatic strategy selection;
- Gamma regime trading rules;
- historical ΔGEX;
- gamma migration;
- gamma concentration percentile/anomaly engine;
- backtesting;
- Strategy Builder integration;
- UI redesign.

Those belong to later phases.

## 16. Validation plan

Before implementation is approved, create:

### Level A — hand-calculated cases

Synthetic chains where the sign transition is known exactly or nearly exactly.

### Level B — algebraic properties

- doubling OI doubles GEX;
- consistent scaling preserves flip location;
- symmetric test chains produce expected crossings;
- changing unrelated distant strikes does not alter a localized wall beyond its mathematical contribution.

### Level C — numerical sweep

Compare coarse-grid and refined-grid flip estimates.

### Level D — edge cases

- no crossing;
- exact crossing;
- multiple crossings;
- missing IV;
- missing OI;
- sparse strikes;
- expiry at zero;
- extreme IV;
- duplicate contracts.

### Level E — independent reference

Use a separate reference implementation in tests rather than copying the production helper into the assertion path.

## 17. Proposed outputs

```text
GammaFlipResult
  status
  primaryFlip
  allFlips[]
  netGexAtSpot
  gexCurve[]
  quality
  methodology

GammaWallResult
  callWall
  putWall
  topCallWalls[]
  topPutWalls[]
  quality
  methodology
```

The raw `gexCurve` should be available to analytics/backtesting layers but does not need to be exposed publicly in Phase 7.2.

## 18. Architecture

```text
Canonical Option Chain
        │
        ├── current gamma / OI ──────► Phase 7.1 GEX
        │                                  │
        │                                  ├── GEX by strike
        │                                  └── GEX by expiry
        │
        └── strike / expiry / IV / OI ─► Phase 7.2 Spot Sweep
                                           │
                                           ▼
                                  modeled gamma(S)
                                           │
                                           ▼
                                      NetGEX(S)
                                           │
                            ┌──────────────┴──────────────┐
                            ▼                             ▼
                       Gamma Flip                   Gamma Walls
```

## 19. Recommended implementation boundary

Phase 7.2 should remain a pure calculation module, like Phase 7.1.

No broker imports, no database dependency, no network calls, and no UI dependency.

The module should accept a canonical chain snapshot plus explicit model/configuration inputs and return deterministic results.

## 20. Research references

- SpotGamma, "Gamma Exposure (GEX)" — describes GEX as an estimate of aggregate modeled dealer gamma and stresses that actual hedge timing/positions are not directly observable.
- SpotGamma Support, "GEX Explained" — documents the conventional gamma exposure calculation, Gamma Flip, Call Wall, and Put Wall concepts.
- SpotGamma Support, "Gamma Flip" — defines the flip as the price where modeled dealer gamma changes sign and distinguishes the zero-gamma inflection point from later volatility thresholds.
- Cboe, "Volatility Insights: Evaluating the Market Impact of SPX 0DTE Options" — explains the magnitude/sign interpretation of market-maker gamma and its relationship to hedge rebalancing.
- Cboe research, "Gamma Squeezes" — demonstrates that rigorous market-maker gamma estimation requires position/data inputs and model-based gamma calculations.

External methodologies are references, not specifications. The project's formula, sign convention, expiry scope, sweep parameters, and quality rules must remain explicit and versioned.

## 21. Approval gate

**Do not implement Phase 7.2 until this design is reviewed and approved.**

The next implementation prompt should be generated only after confirming:

1. the spot-sweep gamma model;
2. IV/rate/dividend assumptions;
3. expiry scope;
4. wall search window;
5. primary-flip selection;
6. confidence/quality metrics.
