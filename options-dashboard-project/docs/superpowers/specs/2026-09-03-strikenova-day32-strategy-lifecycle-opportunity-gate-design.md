# StrikeNova Day 32 — Strategy Lifecycle and Opportunity Gate Design

**Status:** APPROVED FOR IMPLEMENTATION

## 1. Objective

Day 32 connects the existing Day-28 Opportunity, Day-30 Best-Strike Ranking, and Day-31 Strategy Evaluation domains into the next deterministic lifecycle boundary:

`Observation → Signal → Setup → Opportunity → Strategy Candidate → Strategy Evaluation → Risk Check → User Decision → Execution`

The Day-32 boundary answers:

> **Has this Opportunity produced a sufficiently defined and evaluated Strategy Candidate that is structurally eligible to proceed to the Day-33 Risk Check?**

It does **not** answer whether the trade is safe, approved by the user, permitted by risk policy, or executable.

## 2. Architectural Boundary

Day 28 owns Opportunity discovery and the directional thesis.

Day 30 owns multi-factor strike ranking. It selects/ranks candidate strikes but does not authorize a trade.

Day 31 owns deterministic strategy evaluation across payoff, Greeks, scenarios, regime, liquidity, risk characteristics, and historical evidence. Its context (`OPPORTUNITY`, `PAPER`, `BACKTEST`, `RESEARCH`) is metadata only and cannot change the mathematics.

Day 32 owns lifecycle composition and the Opportunity Gate. It composes the upstream objects and verifies structural/evidence completeness. It does not duplicate any Day-28/30/31 calculation.

Day 33 owns centralized risk decisions.

The Day-32 package must remain a pure domain boundary: no database, network, filesystem, wall clock, randomness, broker adapter, order service, execution service, or central risk authorization.

## 3. Strategy Candidate

A Strategy Candidate is the immutable domain object representing a defined strategy that originated from an Opportunity and has been evaluated.

It carries:

- deterministic caller-supplied candidate identity;
- originating Opportunity identity;
- strategy identity/template identity;
- concrete strategy legs;
- selected/ranked strike identities;
- expected behavior;
- invalidation condition;
- authoritative Day-31 evaluation result;
- lifecycle state;
- confidence as a separate channel;
- quality as a separate channel;
- reference timestamp;
- provenance.

The candidate contains no broker order ID, order side/type, execution state, user approval, or risk authorization decision.

## 4. Lifecycle

The lifecycle vocabulary is:

- `CANDIDATE` — strategy candidate is structurally defined but not yet evaluated;
- `EVALUATED` — Day-31 evaluation exists and is structurally usable, but the Opportunity Gate has not yet declared eligibility;
- `ELIGIBLE` — the candidate satisfies the Day-32 structural/evidence gate and may proceed to Day 33;
- `BLOCKED` — the candidate cannot proceed because a required input is missing, incomplete, invalid, stale, or otherwise fails the Day-32 gate;
- `EXPIRED` — the candidate is no longer temporally valid; Day 32 does not itself consult wall clock, so expiry must be represented by explicit caller-supplied evidence/state;
- `INVALID` — the candidate violates a domain invariant or contains invalid authoritative input.

Terminal states are `EXPIRED` and `INVALID`. Eligibility never means execution approval.

If an existing canonical lifecycle vocabulary is discovered in the repository during implementation, it must be reused rather than duplicated, provided it preserves these boundaries.

## 5. Opportunity Gate

The gate verifies, in deterministic order:

1. Opportunity exists and is structurally valid.
2. Strategy identity exists.
3. Strategy legs are present and structurally valid.
4. Ranked strike selection is present when the strategy requires concrete strike selection.
5. Day-31 Strategy Evaluation exists.
6. Day-31 evaluation status is sufficient for eligibility. `SUCCESS` is eligible; `PARTIAL`, `UNAVAILABLE`, or `INVALID` cannot silently become eligible.
7. Required reference timestamp is explicit and genuinely timezone-aware.
8. Quality is explicit where required. Missing quality remains missing; `INSUFFICIENT` quality blocks eligibility.
9. Blocking reasons are explicit and deterministic.

The gate may preserve a `DEGRADED` quality state as visible evidence, but it must not silently reinterpret it as `SUCCESS` or as a risk authorization. Exact quality policy must follow the established Day-12/28 conventions and the approved tests.

## 6. Provenance and Evidence

Day 32 preserves provenance rather than synthesizing it.

- Opportunity provenance remains the provenance of the originating Opportunity.
- Day-31 evaluation provenance remains the provenance of evaluation inputs/dimensions.
- Day-30 factor provenance remains inside the ranking result/contributions.
- The Strategy Candidate must not flatten these into one fabricated source.

Blocking/evidence records identify the reason and relevant upstream state. Missing evidence is not converted to zero, neutral, or favorable evidence.

## 7. Determinism

Given identical canonical inputs, the same Strategy Candidate and gate result must be produced regardless of evaluation context.

Candidate IDs are derived only from explicit caller-supplied identifiers or supplied directly; no UUID, randomness, or current time is allowed.

Serialization is deterministic and JSON-safe. Tuple ordering and enum declaration ordering are stable.

## 8. Context Equivalence

The Day-31 evaluation result may originate from `OPPORTUNITY`, `PAPER`, `BACKTEST`, or `RESEARCH`. Day 32 treats that context as descriptive metadata only. It must not alter payoff, Greek, scenario, regime, liquidity, risk-characteristic, or historical semantics.

The same canonical strategy/evaluation inputs must therefore produce equivalent gate eligibility and lifecycle outcome independent of context.

## 9. Negative Scope

Day 32 explicitly excludes:

- broker API calls;
- broker credentials;
- order creation or submission;
- execution intents;
- fill/position mutation;
- central portfolio risk authorization;
- margin authorization;
- user approval workflow;
- database persistence or migrations;
- API endpoints;
- frontend changes;
- historical-data ingestion;
- backtesting engine;
- walk-forward analysis;
- ML;
- AI agent behavior;
- duplicate payoff, Greek, scenario, regime, or strike-ranking mathematics.

## 10. Test Strategy

TDD is mandatory.

Focused tests must cover:

- valid Opportunity → Strategy Candidate;
- missing/invalid Opportunity;
- required strategy identity and legs;
- ranked strike selection preservation;
- evaluation required and incomplete evaluation blocking;
- lifecycle transition legality and terminal states;
- explicit blocking reasons;
- missing-versus-zero behavior;
- quality handling and `INSUFFICIENT` blocking;
- Opportunity/evaluation/factor provenance separation;
- deterministic serialization and repeated evaluation;
- context equivalence;
- no risk-authorization vocabulary;
- no execution/broker objects;
- pure-domain/no-I/O constraints.

## 11. Success Gate

Day 32 is PASS only when a valid Opportunity can deterministically produce a fully defined Strategy Candidate, ranked strikes and Day-31 evaluation are preserved without duplicated mathematics, incomplete evidence cannot silently pass the gate, provenance/quality/confidence remain distinct, lifecycle state is explicit, and no Day-33 risk or later execution capability enters the implementation.

A PASS unlocks Day 33 — Central Risk Engine Contract.
