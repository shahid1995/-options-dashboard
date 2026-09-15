# StrikeNova — Day 30: Best-Strike Ranking Design

**Date:** 2026-09-03  
**Status:** DESIGN — approved direction; implementation remains gated by written-spec review  
**Baseline:** Day 29 approved/frozen at `803c4bc`  
**Master Plan:** `docs/superpowers/plans/2026-09-02-strikenova-architecture-blueprint-v1-master-implementation-plan.md`

## 1. Objective

Implement a deterministic, broker-neutral **Best-Strike Ranking** boundary for eligible option strikes associated with an Opportunity.

The Day-30 engine evaluates the nine factors explicitly required by the Master Plan:

1. liquidity
2. spread quality
3. IV
4. Greeks
5. positioning
6. GEX
7. distance to spot
8. strategy objective
9. risk

It produces an explainable ordered set of strike candidates. It does **not** create a Strategy Candidate, authorize a trade, submit an order, call a broker, or become the central risk engine.

## 2. Architectural placement

Day 30 sits after Opportunity discovery and before the Day-31 Strategy Evaluation Engine:

`Opportunity → Strike Candidate Set → Factor Evaluation → Deterministic Ranking → Ranked Strike Candidates`

Day 30 consumes the Day-28 Opportunity contract and caller-supplied strike-domain observations. It does not mutate the Opportunity or recalculate upstream intelligence such as GEX, Greeks, IV, positioning, or risk.

The ranking engine is a pure deterministic function. It has no database, network, wall-clock, randomness, broker access, or hidden state.

## 3. Boundary and contracts

### 3.1 Strike identity

Every candidate has a caller-supplied stable identity:

- `candidate_id`
- `underlying`
- `option_type` (`CE` or `PE`)
- `strike`
- optional `expiry`

The engine never generates IDs with UUIDs, timestamps, or randomness.

### 3.2 Strategy objective

The engine accepts a typed, explicit strategy-objective context rather than inferring an objective from a strike, option type, direction label, or ranking outcome.

The objective context supplies a deterministic `objective_alignment` score in `[0,1]`. The engine records the objective name/identifier and score in the factor explanation. Day 30 does not construct a strategy template; that belongs to Day 32.

### 3.3 Risk

Day 30 accepts a caller-supplied normalized `risk_score` in `[0,1]`, where higher means more suitable under the caller's stated risk objective. It does not implement the authoritative central risk engine scheduled for Day 33.

A missing risk input is **missing**, not zero. The ranking policy must explicitly decide eligibility when a required factor is absent; it may not silently reward or punish the candidate through a fabricated numeric value.

### 3.4 Factor observations

Each factor is represented as an explicit normalized score in `[0,1]`, together with source/provenance metadata and a presence/quality state. Raw market values may be carried for explanation, but ranking operates on the normalized value supplied by the relevant upstream calculation boundary.

The nine factor records are:

- `liquidity`
- `spread_quality`
- `iv`
- `greeks`
- `positioning`
- `gex`
- `distance_to_spot`
- `strategy_objective`
- `risk`

No factor may be synthesized from a missing value. The engine validates finite bounds and rejects invalid scores.

## 4. Ranking semantics

### 4.1 Separation of concepts

The following are independent fields and must never be conflated:

- **ranking score:** deterministic suitability ordering across strikes
- **confidence:** confidence supplied by the opportunity/intelligence context; not used as a substitute for factor quality
- **quality:** data-quality state/score; not a directional or ranking-confidence claim

A high ranking score does not imply high confidence. High data quality does not imply a high ranking score.

### 4.2 Default deterministic weights

Day 30 uses an explicit fixed weighted score. The nine factor weights are configuration values captured in the ranking request/result and must sum exactly to `1.0`:

| Factor | Default weight |
|---|---:|
| Liquidity | 0.15 |
| Spread quality | 0.15 |
| IV | 0.10 |
| Greeks | 0.10 |
| Positioning | 0.10 |
| GEX | 0.10 |
| Distance to spot | 0.10 |
| Strategy objective | 0.10 |
| Risk | 0.10 |

`rank_score = Σ(weight_i × factor_score_i)`.

Because all factor scores are bounded to `[0,1]`, the resulting rank is bounded to `[0,1]`.

The default weights are deliberately explicit and deterministic. They are not claimed to be statistically optimal; future calibration/model-governance work may evaluate them without changing the Day-30 contract.

### 4.3 Missing/insufficient factor handling

The engine must not use `or 0`, null coercion, NaN-to-zero, or equivalent behavior for absent inputs.

Default policy: **all nine factors are required for a fully ranked candidate**. If any factor is missing or unusable, that candidate is excluded from the ranked output and appears in a deterministic `suppressed` collection with a specific reason and factor name.

This conservative policy prevents a strike from winning because one or more material dimensions were unavailable. It also makes the result honest about data completeness.

A future policy can explicitly permit partial-factor ranking, but that is outside Day 30 and cannot be introduced implicitly.

## 5. Factor interpretation rules

Day 30 does not invent market meaning from labels. Each upstream factor provider owns the domain-specific transformation into `[0,1]`.

- **Liquidity:** higher normalized liquidity suitability ranks higher.
- **Spread quality:** higher normalized execution-quality suitability ranks higher; narrower/better spreads must already map to higher score.
- **IV:** score represents suitability for the explicit objective, not a universal claim that high or low IV is always better.
- **Greeks:** composite score represents suitability for the explicit objective and must be supplied explicitly; Day 30 does not reinterpret delta/gamma/theta/vega signs.
- **Positioning:** score represents suitability derived from approved positioning intelligence; static OI concentration alone must not be silently treated as support/resistance.
- **GEX:** score represents suitability from the approved GEX/gamma context; Day 30 does not recalculate GEX or alter Day-17 sign conventions.
- **Distance to spot:** score represents objective-specific strike-distance suitability; raw distance may be preserved for explanation.
- **Strategy objective:** explicit alignment score; never inferred from rank.
- **Risk:** explicit suitability score from the caller; Day 30 does not bypass or replace Day-33 central risk authority.

## 6. Deterministic ordering

Candidates are sorted by:

1. descending `rank_score`
2. ascending `underlying`
3. ascending `expiry` using canonical serialized expiry value when present
4. ascending `option_type` using the contract's fixed enum order
5. ascending numeric `strike`
6. ascending `candidate_id`

The final ordering is therefore stable even when two candidates have identical scores.

The engine must produce identical score, factor contribution, explanation, suppression reason, and ordering for identical inputs.

## 7. Explainability

Every ranked candidate must expose:

- total ranking score
- every factor's normalized score
- every factor's configured weight
- every factor's weighted contribution
- objective identifier/alignment
- risk suitability score
- candidate identity
- ranking position

The explanation must answer the required gate question: **why did this strike rank higher?**

The explanation is deterministic and generated from structured factor data. No LLM-generated explanation is used.

Example structure (not a required literal string):

`rank 1; score 0.82; liquidity +0.135; spread +0.120; IV +0.080; ...; objective alignment 0.90; risk 0.85`

## 8. Opportunity/provenance preservation

A ranked candidate must retain a reference or immutable projection of its originating Opportunity identity and upstream provenance. Day 30 must not manufacture a new market-data provenance chain.

The originating Opportunity remains the discovery boundary. Ranking is an evaluation/selection result over that Opportunity's candidate strikes.

## 9. Output states

The result contract should distinguish:

- `SUCCESS` — at least one candidate ranked.
- `EMPTY` — no candidates were supplied.
- `NOTHING_ELIGIBLE` — candidates were supplied but all were suppressed.

Suppression records include:

- `candidate_id`
- instrument identity
- deterministic reason
- factor(s) responsible

Invalid input such as out-of-range/non-finite factor values should fail validation rather than being silently converted.

## 10. Non-goals

Day 30 explicitly does **not** implement:

- Strategy Candidate lifecycle
- Day-31 payoff/Greek/scenario strategy evaluation
- Day-32 strategy templates or user decision gate
- central risk engine or authorization
- order generation
- execution intents
- broker calls/adapters
- live trading
- database schema/migrations/persistence
- API/frontend changes
- AI/ML
- backtesting
- statistical optimization of weights

## 11. Testing and verification requirements

TDD is mandatory: RED → GREEN → REFACTOR.

Tests must include:

1. construction/validation of every factor and candidate contract
2. exact golden arithmetic for the default nine-factor weighted score
3. weight-sum validation
4. bounds and non-finite input rejection
5. missing-factor suppression for each factor
6. distinction between ranking score, confidence and quality
7. deterministic tie-breaking across every ordering key
8. repeatability with identical inputs
9. explanation completeness and factor contribution arithmetic
10. provenance/opportunity identity preservation
11. serialization round-trip where serialization is provided
12. purity/no IO/no wall-clock/randomness
13. missing ≠ zero invariant
14. regression against approved Days 19–29 suites

## 12. Day-30 acceptance gate

Day 30 is approved only if:

> **Same inputs produce stable ranking and explanations identify why a strike ranked higher.**

Additionally, the independent review must confirm that the implementation remains below the Day-31 Strategy Evaluation and Day-33 Central Risk boundaries, does not modify Day-28/29 semantics, and contains no execution/broker behavior.
