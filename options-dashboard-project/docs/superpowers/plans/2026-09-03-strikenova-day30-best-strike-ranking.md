# StrikeNova — Day 30 Best-Strike Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, explainable multi-factor strike-ranking engine for eligible option strikes without crossing into Strategy Evaluation, central Risk, or Execution.

**Architecture:** Add a pure backend strike-ranking boundary that consumes an Opportunity plus explicit normalized factor observations. Rank using fixed documented weights, keep ranking score separate from confidence and quality, suppress incomplete candidates explicitly, and preserve provenance/Opportunity identity.

**Tech Stack:** Python, dataclasses/enums, pytest, existing StrikeNova Opportunity/Intelligence/Market Data contracts.

**Spec:** `docs/superpowers/specs/2026-09-03-strikenova-day30-best-strike-ranking-design.md`

## Global Constraints

- Day 30 scope only; do not implement Day 31+ behavior.
- TDD is mandatory: RED → GREEN → REFACTOR.
- PostgreSQL remains the transactional system of record, but Day 30 adds no persistence.
- Alembic remains the sole schema authority; no migrations are required.
- Broker truth remains authoritative for broker facts; Day 30 is broker-neutral.
- Opportunity is not an order; ranking never creates execution intent or submits an order.
- Deterministic intelligence precedes ML; no AI/ML or statistical optimization is introduced.
- Missing ≠ zero; no null/NaN/default-zero coercion for material factor inputs.
- Ranking score, confidence, and data quality are separate concepts.
- No wall-clock, randomness, network IO, database IO, broker calls, API routes, or frontend changes.
- Day-28 and Day-29 contracts remain unchanged unless a separately approved architectural issue is discovered.
- Central risk authority remains Day 33; Day 30 consumes explicit risk suitability input only.

---

## Repository Baseline and File Map

**Implementation baseline:** the repository branch after the Day-30 design commit; Day 29 is approved/frozen at `803c4bc` before the design-only commit.

Expected Day-30 implementation footprint:

- Create: `backend/app/strike_ranking/__init__.py`
- Create: `backend/app/strike_ranking/contracts.py`
- Create: `backend/app/strike_ranking/ranking.py`
- Create: `backend/tests/test_day30_best_strike_ranking.py`
- Create/update: `docs/superpowers/plans/2026-09-03-strikenova-day30-best-strike-ranking.md`
- Update: `docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`

Do not modify Day-28 or Day-29 implementation files unless an explicit contract incompatibility is demonstrated and separately approved.

---

### Task 1: Define strike-ranking contracts

**Files:**
- Create: `backend/app/strike_ranking/__init__.py`
- Create: `backend/app/strike_ranking/contracts.py`
- Test: `backend/tests/test_day30_best_strike_ranking.py`

**Interfaces:**
- Consumes: Day-28 `Opportunity`; explicit caller-supplied factor observations.
- Produces: immutable ranking input/output contracts used by Task 2.

- [ ] **Step 1: Write failing contract tests**

Cover:
- candidate identity validation
- option type validation (`CE`/`PE`)
- finite factor scores in `[0,1]`
- exactly nine required factors
- missing factor remains missing and is not converted to `0.0`
- explicit strategy objective identifier/alignment
- explicit risk score
- weight configuration sums to exactly `1.0`
- invalid/non-finite scores are rejected

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd options-dashboard-project/backend
pytest tests/test_day30_best_strike_ranking.py -q
```

Expected: collection/import failures because the Day-30 contracts do not yet exist.

- [ ] **Step 3: Implement minimal frozen contracts**

Implement typed immutable structures for:

```python
StrikeCandidateInput
FactorObservation
RankingWeights
StrikeRankingInput
SuppressedStrike
RankedStrike
StrikeRankingResult
```

`FactorObservation` must retain factor name, normalized score, quality/presence state, and optional raw/explanation metadata without changing the normalized score.

`StrikeCandidateInput` must carry the originating Opportunity identity/provenance and all nine explicit factor observations.

`RankingWeights` must validate nine non-negative finite weights whose sum is exactly `1.0` within the repository's established deterministic numeric policy.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same pytest command. Expected: all contract tests pass.

- [ ] **Step 5: Commit the contract boundary**

```bash
git add backend/app/strike_ranking backend/tests/test_day30_best_strike_ranking.py
git commit -m "feat: define day30 strike ranking contracts"
```

---

### Task 2: Implement deterministic multi-factor ranking

**Files:**
- Create: `backend/app/strike_ranking/ranking.py`
- Modify: `backend/tests/test_day30_best_strike_ranking.py`

**Interfaces:**
- Consumes: `StrikeRankingInput`, `StrikeCandidateInput`, `RankingWeights`.
- Produces: `StrikeRankingResult` with ranked candidates and deterministic suppression records.

- [ ] **Step 1: Write failing golden-ranking tests**

Add fixtures with explicit values for all nine factors and assert exact arithmetic:

```text
liquidity          0.15
spread_quality     0.15
iv                 0.10
greeks             0.10
positioning        0.10
gex                0.10
distance_to_spot   0.10
strategy_objective 0.10
risk               0.10
```

For a candidate with factor scores `1.0` through `0.2` in the fixture, assert the exact weighted sum from the specification.

- [ ] **Step 2: Add failing deterministic ordering tests**

Create equal-score candidates and assert tie-breaking order:

1. rank score descending
2. underlying ascending
3. expiry ascending using canonical value
4. option type using the fixed enum order
5. strike ascending
6. candidate ID ascending

Also run the same input twice and assert byte-for-byte-equivalent serialized result or equivalent immutable structure.

- [ ] **Step 3: Add failing explanation tests**

Assert every ranked candidate exposes:

- total score
- every factor score
- every configured weight
- every weighted contribution
- objective alignment
- risk score
- rank position

Assert contribution arithmetic reconciles to the total score.

- [ ] **Step 4: Add failing missing-factor suppression tests**

Parameterize each of the nine factors. For each missing/unusable factor:

- candidate must not appear in ranked output
- candidate must appear in `suppressed`
- reason identifies the missing factor
- no fabricated zero is present in the factor record

- [ ] **Step 5: Run focused tests and verify RED**

Run:

```bash
cd options-dashboard-project/backend
pytest tests/test_day30_best_strike_ranking.py -q
```

Expected: new ranking tests fail because the ranking implementation is absent.

- [ ] **Step 6: Implement the minimal deterministic ranking function**

Expose:

```python
def rank_strikes(input: StrikeRankingInput) -> StrikeRankingResult:
    ...
```

The implementation must:

1. validate the input contract
2. reject invalid numeric factor values
3. suppress candidates with missing/unusable required factors
4. calculate `Σ(weight × factor_score)` using the explicit weights
5. preserve confidence and quality as separate fields
6. build structured factor contributions
7. build deterministic explanations from structured data
8. sort using the specified tie-breakers
9. return an immutable result

Do not call any clock, random generator, database, HTTP client, broker gateway, or execution service.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run the same pytest command. Expected: all Day-30 focused tests pass.

- [ ] **Step 8: Commit the ranking engine**

```bash
git add backend/app/strike_ranking/ranking.py backend/tests/test_day30_best_strike_ranking.py
git commit -m "feat: implement deterministic best strike ranking"
```

---

### Task 3: Verify Opportunity/provenance and architectural boundaries

**Files:**
- Modify: `backend/tests/test_day30_best_strike_ranking.py`
- Modify: `docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Consumes: approved Day-28 Opportunity and Day-30 ranked result.
- Produces: regression evidence that the ranking result preserves discovery identity without becoming execution.

- [ ] **Step 1: Write failing provenance/boundary tests**

Assert:
- originating Opportunity identity is preserved
- originating provenance remains available
- ranking does not mutate the Opportunity
- confidence remains distinct from ranking score
- quality remains distinct from ranking score
- no execution intent/order object is produced
- no broker dependency is imported by the strike-ranking module

- [ ] **Step 2: Run tests and verify RED**

```bash
cd options-dashboard-project/backend
pytest tests/test_day30_best_strike_ranking.py -q
```

Expected: newly added assertions fail until the boundary behavior is complete.

- [ ] **Step 3: Implement minimum boundary behavior**

Add only the projections needed to preserve identity/provenance and the separate confidence/quality fields. Do not duplicate upstream intelligence fields unnecessarily.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same command and confirm all Day-30 tests pass.

- [ ] **Step 5: Run static purity checks**

Run:

```bash
python -m py_compile app/strike_ranking/*.py
python -m compileall -q app/strike_ranking
```

Then inspect imports and AST for forbidden dependencies: database/session, HTTP/network clients, broker gateway/adapters, execution/order services, random, and wall-clock APIs.

- [ ] **Step 6: Commit boundary verification**

```bash
git add backend/tests/test_day30_best_strike_ranking.py docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md
git commit -m "test: verify day30 ranking boundaries"
```

---

### Task 4: Full regression and Day-30 gate evidence

**Files:**
- Modify: `docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Consumes: all Day-30 source/tests plus approved prior-day suites.
- Produces: independently verifiable gate evidence; no implementation changes unless a regression failure is diagnosed and repaired through TDD.

- [ ] **Step 1: Run Day-30 focused suite**

```bash
cd options-dashboard-project/backend
pytest tests/test_day30_best_strike_ranking.py -q
```

Record exact test count and failures.

- [ ] **Step 2: Run Days 19–30 regression**

Use the repository's existing Day-19–Day-30 test selection and record exact output.

- [ ] **Step 3: Run Days 14–30 regression**

Use the established quantitative/intelligence regression selection and record exact output.

- [ ] **Step 4: Run Days 9–30 regression**

Use the established market-data/quant/intelligence/opportunity regression selection and record exact output.

- [ ] **Step 5: Run security/session and infrastructure regressions**

Reproduce the repository's documented baseline exceptions rather than hiding or reclassifying them.

- [ ] **Step 6: Run repository hygiene checks**

```bash
git diff --check
```

Run the established secret scan, AST/purity checks, and unused-import checks used by the previous Day gates.

- [ ] **Step 7: Inspect the final diff**

Confirm the Day-30 implementation does not modify Day-28/29 semantics and contains no:

- DB/migration changes
- API/frontend changes
- broker/execution behavior
- Strategy Candidate lifecycle
- Day-31 strategy evaluation
- Day-33 central risk behavior
- AI/ML/backtesting

- [ ] **Step 8: Verify CI status**

Push only the authorized branch commits and inspect the resulting GitHub Actions statuses. Do not deploy or cut over production.

- [ ] **Step 9: Update tracker with evidence, not self-approval**

Record implementation commit(s), test counts, CI statuses, changed-file scope, known non-blocking issues, and the statement that the Day-30 gate awaits independent review.

---

## Final Day-30 Acceptance Gate

Independent review must establish all of the following:

- same inputs produce the same ranking
- rank ordering is deterministic, including ties
- all nine Master Plan factors are represented
- ranking score is separate from confidence and quality
- every ranking difference can be explained through factor values/weights
- missing factors are explicitly suppressed rather than converted to zero
- Opportunity/provenance identity is preserved
- no Day-31, Day-33, or execution behavior leaked into Day 30
- focused and required regression suites have fresh evidence
- repository diff contains only authorized Day-30 scope

**Gate:** **🟢 DAY 30 APPROVED** only after independent verification. Until then, Day 31 remains locked.
