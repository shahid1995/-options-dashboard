# StrikeNova — Day 29: Scalping Opportunity Engine

**Status:** Planned (implementation follows the repository TDD convention: RED → GREEN → REFACTOR).
**Baseline:** `a79ba9b` (Day-28 Opportunity Domain, approved/frozen).
**Scope:** Day 29 ONLY. No Day-30+ (strike ranking / strategy / risk / execution).

## 1. Objective (Master Plan Day 29)

Build a deterministic **scalping opportunity engine** on the Day-28 pipeline
`Observation → Signal → Setup → Opportunity` with strict freshness
requirements:

1. Define a short-horizon input window and explicit, deterministic freshness thresholds.
2. Combine price / flow / positioning / GEX-gamma / regime / event-expiry state.
3. Rank opportunities deterministically by evidence and quality.
4. Suppress stale / insufficient / conflicted candidates.
5. **Gate:** scalping signals degrade or suppress safely under stale data.

Day 29 is an intelligence/discovery layer. It stops at `Opportunity`
(Day-28 contract) — no orders, no execution intents, no broker access.

## 2. Inputs

All inputs are typed, caller-supplied and explicit (the engine is pure:
no wall clock, no randomness, no IO).

- `ScalpingInput`:
  - `candidates: tuple[ScalpingCandidateInput, ...]`
  - `as_of: datetime | None` — explicit deterministic freshness reference
    (must be genuinely timezone-aware when present). `None` ⇒ freshness
    cannot be established: every candidate is suppressed
    (`NO_REFERENCE_TIME`) — freshness is never guessed, never invented.
  - `policy: ScalpingFreshnessPolicy` — explicit thresholds.
- `ScalpingCandidateInput` (pure data):
  - `candidate_id`, `underlying`, `expiry`
  - `interpretation: IntelligenceResult` — the directional read
    (typically a Day-26 synthesis or Day-25 trap result)
  - `context: tuple[ContextEvidence, ...]` — supporting channel reads
    (positioning / flow / gamma-GEX / regime / event-expiry / price),
    each `ContextEvidence{role, result}` where `role` is caller-supplied
    explanation metadata (`EvidenceRole`) — direction is never derived
    from a role label.
- `ScalpingFreshnessPolicy`: `fresh_seconds: float = 60.0`,
  `stale_seconds: float = 300.0` — the **same documented freshness
  semantics already used by Day 12** (`market_data/quality.py`
  `MarketDataQualityConfig`), applied as eligibility gates, not quality
  scoring. Validated: `0 < fresh_seconds < stale_seconds`, finite.

Channel kinds do not exist as separate required slots: missing context
roles are missing (never zero, never opposing, never a suppression by
themselves). Day-17 GEX is consumed **only** through its Day-24 gamma
context representation (sign conventions preserved upstream; Day 29 never
recalculates GEX).

## 3. Freshness semantics (deterministic)

`age_seconds = (as_of - reference_timestamp).total_seconds()` for every
supplied evidence item (interpretation + each context result):

| State | Condition |
|---|---|
| `FRESH` | `0 <= age <= fresh_seconds` |
| `DECAYING` | `fresh_seconds < age <= stale_seconds` |
| `STALE` | `age > stale_seconds` |
| `NO_TIMESTAMP` | reference timestamp is `None` |
| `INVALID_TIMESTAMP` | `age < 0` (future — never fresh) |

- Boundary `age == fresh_seconds` is FRESH; `age == stale_seconds` is
  DECAYING (STALE is strict). Explicit boundary tests.
- The **interpretation** may be FRESH or DECAYING (degrade) but never
  STALE (suppress). **Context** evidence: STALE, NO_TIMESTAMP or
  INVALID_TIMESTAMP suppresses the candidate; DECAYING degrades its rank.
- Missing timestamps are never treated as fresh.
- The engine never reads the current time; `as_of` is the caller's
  explicit reference.

## 4. Eligibility / suppression cascade (first matching reason wins)

Per candidate, in order:

1. `NO_REFERENCE_TIME` — result-level when `as_of is None`.
2. `UNINTERPRETABLE` — interpretation status is not SUCCESS.
3. `INSUFFICIENT_QUALITY` — interpretation quality missing or state
   `INSUFFICIENT` (DEGRADED is usable and visible — the Days 20–26/28
   rule).
4. `NON_DIRECTIONAL` — direction not BULLISH/BEARISH (NEUTRAL / MIXED /
   UNKNOWN never become a scalp direction).
5. `NO_TIMESTAMP` — interpretation reference timestamp missing.
6. `INVALID_TIMESTAMP` — interpretation timestamp in the future.
7. `NO_TIMESTAMP` / `INVALID_TIMESTAMP` / `STALE_EVIDENCE` — any context
   evidence failing the freshness check (detail names the role).
8. `STALE_EVIDENCE` — interpretation age `> stale_seconds`.
9. `CONFLICTED_CONTEXT` — any context SUCCESS read with direction
   BULLISH/BEARISH **opposite** to the interpretation direction. A
   context direction that agrees is corroboration; NEUTRAL / MIXED /
   UNKNOWN / PARTIAL / UNAVAILABLE context is non-directional and never
   opposes (missing ≠ zero ≠ opposing).
10. Else: **eligible** → Day-28 chain
    (`Observation → Signal → Setup → Opportunity`) with deterministic
    derived ids; the interpretation object is preserved by identity
    through the whole chain.

Suppression is deterministic and observable: `SuppressedCandidate`
records `candidate_id`, `underlying`, `reason`, and a deterministic
`detail`.

## 5. Deterministic ranking

Eligible candidates are ranked with an explicit, documented additive
formula (module-level constants; no ML, no randomness, no hidden state):

```
fresh_component  = mean over supplied evidence items of
                   (1.0 if FRESH else 0.75 if DECAYING)      # STALE/NO_TS/INVALID already suppressed
quality_component = interpretation.quality.quality_score / 100   # Day-12 index, 0-100
rank = clamp(0.30*fresh_component
           + 0.25*quality_component
           + 0.25*interpretation.signal_strength
           + 0.20*interpretation.confidence, 0.0, 1.0)
```

- Weights sum to 1.0; every input is bounded [0,1]; rank ∈ [0,1].
- signal_strength, confidence and Day-12 quality remain **separate
  fields**, preserved verbatim on the Day-28 Opportunity.
- Decaying evidence degrades only the freshness component — a decaying
  candidate can rank below an otherwise-identical fresh candidate but is
  not silently dropped.
- Ordering: descending rank, then ascending `(underlying, candidate_id)`
  — fully deterministic.
- Each ranked item carries a deterministic `explanation` string naming
  every factor value and the freshness states (why it ranked where it
  did); stale candidates can never appear in the ranked list.

## 6. Output

`ScalpingResult` (frozen, JSON-safe `to_dict`/`from_dict`):

- `status`: `SUCCESS` (≥1 ranked) / `NOTHING_ELIGIBLE` (≥1 candidate,
  0 ranked — with the suppressed list and reasons) / `EMPTY` (0 candidates).
- `ranked: tuple[RankedScalpingOpportunity, ...]` — each wraps the
  **Day-28 `Opportunity`** (unchanged contract: thesis, evidence chain,
  regime, horizon, expected behavior, invalidation conditions,
  provenance, quality, CANDIDATE status) plus `candidate_id`, `rank`,
  `explanation`, and per-evidence freshness rows.
- `suppressed: tuple[SuppressedCandidate, ...]`
- `policy` and `as_of` echoed for provenance.

Identity/quality/regime/horizon/provenance all flow from the
interpretation verbatim through the Day-28 chain (upstream object
identity preserved).

## 7. Non-goals (strict)

No strike selection, no strategy construction/evaluation, no risk checks,
no allocation, no order/execution generation, no broker adapters, no live
trading, no DB/migrations, no API/frontend, no persistence, no AI/ML, no
Day-30+ behavior. Day-28 files are not modified — Day 29 is additive
(`app/opportunity/scalping.py` + tests + docs).

## 8. Verification plan

1. Day-29 focused tests (freshness matrix incl. exact boundaries, quality
   gates, non-directional suppression, conflict agreement/opposition,
   ranking golden arithmetic, deterministic ordering/repeatability,
   stale-cannot-outrank, provenance/quality/horizon/regime preservation,
   missing≠zero, serialization round-trip, purity AST + vocabulary).
2. Days 19–29, Days 14–29, Days 9–29 regression.
3. Security/session regression + clean-baseline reproduction of the two
   documented pre-existing failures.
4. Infra (Days 4–7 + Alembic) regression.
5. `py_compile`, `git diff --check`, AST purity/unused-import checks,
   secret scan.
6. Two commits: implementation + tests + plan; tracker update. Push and
   verify CI. No self-declared PASS.
