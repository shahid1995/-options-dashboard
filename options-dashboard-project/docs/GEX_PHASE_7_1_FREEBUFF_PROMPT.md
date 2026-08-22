# Phase 7.1 — GEX Calculation & Gamma Profile Foundation

## Purpose

Implement the first production-safe GEX analytics layer using the existing canonical option-chain and Greek pipeline. This phase is calculation and data-foundation only. Do not implement Gamma Flip, Gamma Walls, historical GEX snapshots, GEX percentile/anomaly, GEX migration, Strategy Builder integration, or trading signals in this phase.

## Non-negotiable constraints

1. **Do not deploy anything.**
2. **Do not modify unrelated production behavior.**
3. Preserve the existing broker adapter, canonical option-chain contract, live-vs-model Greek separation, and existing Greek units.
4. Do not create a second option-chain or Greek data pipeline.
5. Do not hard-code NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY lot sizes in production logic.
6. Use the contract-specific `lot_size` supplied by the broker/instrument metadata. Upstox officially exposes `lot_size` on option-contract and instrument records.
7. Never represent GEX as an observed dealer position. It is an inferred exposure model whose sign convention and assumptions must be explicit.
8. Missing/invalid required inputs must not silently become zero.
9. Keep the implementation deterministic and independently testable.

## Step 1 — Audit before editing

Inspect the current repository and identify:

- the canonical option-contract schema;
- where `instrument_key`, `strike`, `expiry`, `CE/PE`, and `lot_size` enter the system;
- whether `lot_size` is already preserved into the canonical model;
- the exact unit/meaning of OI in the current option-chain data;
- the existing live gamma field and its unit;
- the existing underlying spot field;
- the existing tests for chain normalization and Greek analytics.

If canonical `lot_size` already exists, reuse it. If it does not, add the smallest possible mapping change needed to preserve the broker value. Do not introduce a new broker API request if the current instrument metadata already contains the value.

## Step 2 — Lot-size handling

The GEX engine must consume the lot size belonging to the actual option contract. The resolver must:

- accept the canonical contract's lot size;
- reject null, zero, negative, or non-finite values;
- never guess a lot size;
- preserve enough metadata to identify the source as broker/instrument metadata;
- ensure the lot multiplier is applied exactly once.

Do not use today's NIFTY lot size for historical contracts. Contract-specific metadata must remain authoritative.

## Step 3 — GEX calculation

Implement a pure calculation function/service with no network or broker dependency.

Inputs per option contract:

- underlying spot `S`;
- option gamma `Gamma`;
- open interest `OI`;
- contract `lot_size`;
- option type `CE` or `PE`;
- strike and expiry for aggregation keys.

Use the project-approved dollar/rupee GEX convention:

`contract_gex = gamma × OI × lot_size × S² × 0.01`

The implementation must first establish whether the current OI is expressed in contracts/lots and document the conversion. The lot multiplier must not be applied twice.

For the Phase 7.1 positioning convention:

- CE GEX is positive;
- PE GEX is negative;
- Net GEX = sum(CE GEX + PE GEX).

This is a modelling convention, not proof of actual dealer inventory.

## Step 4 — Required outputs

At minimum expose a typed/validated result containing:

- `call_gex`;
- `put_gex`;
- `net_gex`;
- GEX by strike;
- GEX by expiry;
- calculation methodology/sign convention;
- lot-size source metadata;
- data-availability/status information;
- warnings for skipped/invalid contracts.

Keep numeric precision appropriate for the application's analytics layer. Do not round intermediate values; round only at presentation boundaries.

## Step 5 — Aggregation

Provide deterministic aggregation:

### By strike

For every strike:

- CE GEX;
- PE GEX;
- Net GEX.

### By expiry

For every expiry:

- CE GEX;
- PE GEX;
- Net GEX.

### Overall

For the requested option-chain scope:

- total CE GEX;
- total PE GEX;
- total Net GEX.

Do not calculate Gamma Flip or Gamma Walls yet.

## Step 6 — Missing-data behavior

Do not convert missing gamma, missing OI, missing lot size, invalid spot, or malformed contract identity to zero.

Use an explicit status such as `UNAVAILABLE`, `PARTIAL`, or an equivalent existing project convention.

A contract that cannot be safely calculated may be skipped from numeric aggregation, but the result must report that it was skipped and why.

## Step 7 — Tests

Add focused numerical tests covering at least:

1. One CE contract with hand-calculated expected GEX.
2. One PE contract with hand-calculated expected signed GEX.
3. CE + PE netting.
4. Multiple contracts at the same strike.
5. Multiple expiries.
6. Zero OI.
7. Missing gamma.
8. Missing/zero/negative lot size.
9. Invalid/non-finite spot.
10. Confirmation that lot size is applied exactly once.
11. Confirmation that intermediate calculations are not prematurely rounded.
12. Deterministic repeated calculation with identical inputs.

Use independent fixtures where expected values are calculated manually rather than by reusing the production function in the test oracle.

## Step 8 — Regression validation

Run:

- all focused GEX tests;
- existing backend tests relevant to option-chain normalization and Greek analytics;
- the existing frontend tests/build if the implementation exposes a shared contract consumed by frontend code;
- production build checks already required by the repository.

Do not weaken, delete, or rewrite unrelated tests merely to make the suite pass.

## Step 9 — Scope control

Do NOT implement in this phase:

- Gamma Flip / Zero Gamma;
- Call Gamma Wall;
- Put Gamma Wall;
- Net Gamma Wall;
- historical GEX snapshots;
- Delta-GEX / ΔGEX;
- GEX velocity or acceleration;
- gamma migration;
- gamma concentration;
- GEX percentile/anomaly;
- GEX regime classification;
- Vanna/Charm/DEX;
- Strategy Builder conditions;
- trading BUY/SELL signals;
- probability weights;
- dashboard redesign.

Those belong to later phases after the base calculation has been validated.

## Step 10 — Change report

When finished, report:

1. Exact files changed.
2. What changed in each file.
3. Whether `lot_size` already existed or required mapping.
4. Exact OI unit discovered.
5. Exact gamma unit consumed.
6. GEX formula and sign convention implemented.
7. Test commands run and results.
8. Build result.
9. Any limitations or unresolved questions.
10. Confirmation that no deployment occurred.

Stop after Phase 7.1. Do not proceed automatically to Phase 7.2.

## Definition of Done

Phase 7.1 is complete only when the repository has a pure, tested GEX foundation that consumes the existing canonical option-chain data, uses contract-specific broker lot size, produces CE/PE/Net GEX plus strike/expiry aggregates, handles invalid data explicitly, passes regression/build checks, and leaves all advanced GEX features for later phases.
