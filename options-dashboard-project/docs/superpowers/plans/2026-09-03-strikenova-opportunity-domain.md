# StrikeNova Day 28 — Opportunity Domain

**Status:** Implementation plan (TDD: RED → GREEN → REFACTOR)
**Date:** 2026-09-03
**Branch:** `feat/strikenova-day1-security`
**Baseline:** `16d354c` (Day-27 audit state, Intelligence Phase Gate APPROVED)

## Objective

Formalize the deterministic opportunity pipeline as an explicit domain flow:

```text
Observation → Signal → Setup → Opportunity
   → (later days) Strategy Candidate → Risk Check → User Decision → Execution
```

Day 28 builds the **domain foundation only**. An Opportunity is a discovery
object — never an order, never an execution intent, never a broker action.
Days 29+ (scalping engine, strike ranking, strategy, risk) consume it.

## Architecture boundary

New package `backend/app/opportunity/`:

- `app/opportunity/contracts.py` — typed domain vocabulary + the four stage
  contracts (Observation / Signal / Setup / Opportunity) with structural
  validation and deterministic JSON-safe `to_dict`/`from_dict`.
- `app/opportunity/pipeline.py` — deterministic stage transitions
  (`to_signal` → `to_setup` → `to_opportunity`) and the convenience
  `discover_opportunity`.

Consumes the approved Day-19 `IntelligenceResult` (Days 20–26 outputs) as
its observation payload — **no second market-data system**, no re-derivation
of direction/strength/confidence (that is Day-26's job), no regime detection
(Day 23 owns it), no execution vocabulary.

## Domain contracts

**Observation** — a typed envelope over one authoritative upstream
`IntelligenceResult` (typically a Day-26 synthesis result). Carries
`observation_id`, `underlying`, optional `expiry`, `kind`
(`INTELLIGENCE_RESULT`; reserved for future upstreams — never fabricated),
and exposes the upstream projections (status / direction / signal strength /
confidence / quality / regime / horizon / provenance / timestamps / evidence)
through read-only properties. The upstream object is the single source of
truth — no duplicated fields, no drift.

**Signal** — a meaningful interpretation of one observation:
`signal_id` + `observation_id` + the same upstream projections + a
deterministic `explanation`. A Signal is created only from an
interpretable `SUCCESS` upstream observation (missing quality ⇒ the
observation cannot be a Signal at all). Non-directional Signals
(NEUTRAL / UNKNOWN / MIXED) are valid Signals but cannot form a Setup.

**Setup** — a structured directional trading-setup frame derived from one
directional Signal: `expected_behavior` (deterministic mapping; the
`DIRECTIONAL_CONTINUATION_CANDIDATE` family is produced today — the other
expected-behavior values are reserved vocabulary for upstream evidence Day
28 inputs do not carry) and `invalidation_conditions` (non-empty,
deterministic, state/evidence-based, never execution instructions).
Construction enforces: directional upstream read, `SUCCESS` status,
present-and-usable quality, present horizon — never invented.

**Opportunity** — the final discovery object: `opportunity_id`, `setup_id`,
`underlying`, `thesis` (deterministic, explainable "why"), expected
behavior, invalidation conditions, upstream projections, and a
`lifecycle/status` (`CANDIDATE`; reserved members for later strategy days —
nothing beyond `CANDIDATE` is produced). Opportunities are directional and
carry the full upstream evidence chain.

## Evidence chain / traceability

Every stage keeps the upstream `IntelligenceResult` object (`is`-identity
preserved through the whole pipeline) plus the explicit stage ids
(`observation_id` → `signal_id` → `setup_id` → `opportunity_id`). The Day-19
evidence rows (each with provenance + versions + aware timestamps) remain
reachable at every stage. Nothing is re-derived, discarded, or invented.

## Quality / horizon / regime semantics

- **Quality:** the preserved Day-12 `QualityResult` travels verbatim.
  Usable floor mirrors the established Days 20–26 rule: quality present AND
  state != `INSUFFICIENT`. Missing quality ⇒ no Signal (`SUCCESS`
  observations always carry quality); `INSUFFICIENT` ⇒ no Setup.
  `DEGRADED` remains a legitimate usable state (visible on the object).
- **Horizon:** never invented. A Setup/Opportunity requires the upstream
  `SUCCESS` horizon (Day-19 already enforces it) and preserves it; there is
  no `EXPIRY` default anywhere in the domain.
- **Regime:** the authoritative Day-23 `MarketRegime` (label / source /
  model version / reference timestamp) is preserved verbatim through every
  stage. RANGING / UNKNOWN / volatility-only labels never become
  directional evidence (non-directional Signals cannot form Setups).

## Invalidation / expected behavior

`invalidation_conditions` are deterministic, observable, evidence-linked
state descriptions (e.g. the upstream read no longer reports the signalled
direction; upstream quality drops below the usable floor; the supporting
evidence rows disappear). They describe the thesis boundary — they are
**not** stop-losses, cancellations, position management, or broker actions.
`expected_behavior` uses candidate language only
(`*_CANDIDATE`); no probabilities, returns, win rates, or target prices are
invented (none exist upstream).

## Execution boundary (non-negotiable)

The opportunity package imports nothing from `app.brokers`,
`app.services`, `app.routers`, or any execution module; contains no order
creation/submission/modification/cancellation code; performs no network,
DB, filesystem, or broker I/O; no random IDs (identities are
caller-supplied, deterministic); no wall clock. AST purity guards and
boundary tests prove it.

## Day-28 tests (RED first)

`backend/tests/test_day28_opportunity_domain.py` covering: Observation
validation/projections; Signal directional + non-directional + rejection of
non-SUCCESS observations; Setup validity + rejection matrix (non-directional,
INSUFFICIENT quality, no-horizon, malformed conditions); Opportunity
validity + thesis determinism + lifecycle; quality/horizon/regime
propagation; evidence-chain identity; adversarial fixtures (missing
evidence, MIXED/UNKNOWN, INSUFFICIENT quality, trap-type conflicting reads,
regime without direction, duplicate observations); determinism; JSON-safe
serialization round-trips for all four stages; AST purity + execution
boundary. Independent expectations documented in the module docstring.

## Verification ladder

Day-28 focused → Days 19–28 → Days 9–28 → security/session →
infrastructure/Alembic → `py_compile` → `git diff --check` → AST purity →
unused-import scan → secret scan → CI. The two known pre-existing
security failures are reproduced against the clean Day-26 baseline if they
remain.

## Explicit non-goals

No scalping engine / freshness ranking (Day 29), no strike ranking (Day 30),
no strategy evaluation/lifecycle (Days 31–32), no risk (Day 33+), no
persistence/migrations (Blueprint does not require Day-28 persistence —
domain contracts only), no AI/ML, no backtesting, no execution, no
DB/API/frontend/broker changes, no merge, no deployment, no production
cutover, no live trading.
