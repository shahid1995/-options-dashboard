# StrikeNova Day 26 — Intelligence Synthesis & Conflict Resolution

**Status:** Implementation plan (TDD: RED → GREEN → REFACTOR)
**Date:** 2026-09-03
**Branch:** `feat/strikenova-day1-security`
**Baseline:** `8d75fa8` (Day-25 tracker state)

## Objective

Build the deterministic **Intelligence Synthesis** engine that combines the
per-family directional reads of Days 20–25 into one transparent,
evidence-linked Day-19 `IntelligenceResult`, without pretending that more
signals equal more certainty.

```
Day20 Positioning + Flow
  → Day21 Dynamic Levels
  → Day22 Institutional-Like Activity
  → Day23 Market Regime
  → Day24 Event / Expiry context
  → Day25 Trap Detection
  → DAY-26 INTELLIGENCE SYNTHESIS
  → Day-19 IntelligenceResult
```

## Architecture boundary

New module `backend/app/intelligence/synthesis.py` + tests + this plan.
Consumes only typed public outputs of Days 20–25 (the same caller-supplied
typed inputs Days 23–25 consume). Produces the Day-19 `IntelligenceResult`.

Nothing below this boundary changes. No Day-19 contract modification; no
database, migration, API, frontend, broker/execution, risk, ML/AI,
backtesting, or historical persistence.

## Core principles locked by tests

1. **No majority vote.** Each evidence *family* contributes at most one
   directional read. Different families are different engines with different
   meanings; correlated fields derived from one measurement are never
   counted repeatedly.
2. **Only BULLISH / BEARISH vote.** NEUTRAL, MIXED, UNKNOWN, NO_SIGNAL and
   unsupported evidence never become a directional vote (Days 22–23
   corrections preserved).
3. **Missing ≠ zero ≠ neutral ≠ evidence.** A missing family input is
   absent. A measured zero is a measurement. Absence never raises
   strength, never lowers status, never fabricates an opposing vote.
4. **signal_strength ≠ confidence ≠ quality.** Preserve the supplied Day-12
   `QualityResult` by identity; never recompute it.
5. **Candidate language.** Trap results are one *pattern* family: candidate
   context, never certainty, never an automatic override.

## SynthesisInput (typed, all optional except identity)

Mirrors the Day-25 `TrapInput` caller-supplied surface (single underlying /
chain evaluation):

| Field | Source | Directional read |
|---|---|---|
| `positioning` | Day-20 `PositioningClassification` | via Day-20 `classification_direction`; label strength 0.5 |
| `price_flow_relation` | Day-20 `PriceFlowRelation` | needs `spot_change` direction; CONFIRM agrees with price, DIVERGE opposes; NO_SIGNAL none; strength 0.5 |
| `level_classifications` | Day-21 typed rows | proximate (≤10% of spot) CONFLICTED_INTERACTION rows only: conflicted SUPPORT ⇒ BEARISH (broken down), conflicted RESISTANCE ⇒ BULLISH (broken up); strength = measured row strength. APPROACHING / STATIC / constructive rows never vote (Day-21 remediation) |
| `institutional_direction` / `institutional_strength` | Day-22 result | BULLISH/BEARISH only (MIXED none); strength = caller strength else 0.5 |
| `regime_label` / `regime_direction` | Day-23 result | regime_direction BULLISH/BEARISH only; label alone never votes; strength 0.5 |
| `trap_direction` / `trap_strength` | Day-25 result | BULL_TRAP_CANDIDATE direction etc. (BEARISH/BULLISH); NO_TRAP (NEUTRAL) → present, never votes; strength = caller strength else 0.5 |
| `spot` / `spot_change` | price context | converts flow relation and level geometry into reads; missing ⇒ those families are present-but-uninterpretable |
| `expiry` | chain scope | context only, never a vote |
| `time_horizon` | caller (authoritative) | preserved verbatim into SUCCESS results; missing ⇒ PARTIAL + MISSING_HORIZON, never invented |
| `regime` | Day-23 `MarketRegime` | propagated verbatim into `IntelligenceResult.regime`; label mismatch with `regime_label` rejected; no channel fabricated when absent |
| `quality` / `provenance` / `reference_timestamp` | Days 12 / 9 / caller | preserved verbatim; quality gates status |

## Evidence-family independence (explicit, testable)

Each engine family is one unit: POSITIONING, FLOW, LEVEL,
INSTITUTIONAL_LIKE, REGIME, TRAP. Two documented correlation rules prevent
double counting of derived reads:

1. **Same-OI alignment (POSITIONING ↔ INSTITUTIONAL_LIKE).** Day-22
   institutional-like activity is derived from Day-20 OI-based positioning.
   When both are present and directionally **aligned**, they form **one**
   vote at `max(positioning_strength, institutional_strength)` — never the
   sum (no fabricated 100% share of the evidence). When they oppose each
   other the divergence is material and each votes (visible conflict).
2. **Derived-pattern duplication (TRAP).** The trap classification is a
   synthesized pattern over the family reads plus price context. When its
   directional read **duplicates** any other independent vote of the same
   direction, the trap contributes **no strength** to the totals (recorded
   as pattern corroboration evidence only). When its read is unique among
   the votes (families absent or non-directional), it votes at its own
   strength. Trap never overrides anything.

## Directional synthesis (deterministic, documented)

After correlation the module holds `bull_total` and `bear_total`
(each = `min(Σ independent vote strengths, 1.0)`).

| Case | Outcome (`SynthesisOutcome`) | Day-19 direction | strength |
|---|---|---|---|
| only bullish votes | `BULLISH_AGREEMENT` | BULLISH | `bull_total` |
| only bearish votes | `BEARISH_AGREEMENT` | BEARISH | `bear_total` |
| both sides have ≥1 vote | `MATERIAL_CONFLICT` | MIXED | `min(bull_total, bear_total)` (contested mass) |
| reads present, none directional | `NO_DIRECTIONAL_EVIDENCE` | UNKNOWN | 0.0 (measured "cannot classify", Day-23 precedent) |

Both-side material evidence is never forced into one direction — the
conflict is exposed (direction MIXED, contested-mass strength, and
`bull_total` / `bear_total` / net evidence rows). Winning-side agreement is
not "certainty": strength stays bounded and conflicts reduce dominance by
construction (a conflicted read cannot inflate a one-sided total).

## Confidence (separate from strength; documented constants)

| Condition | constant |
|---|---|
| one-sided agreement, ≥2 independent winning votes | 0.85 |
| one-sided agreement, 1 winning vote | 0.75 |
| material two-sided conflict (MIXED) | 0.60 |
| reads present, no directional read (UNKNOWN) | 0.70 |

## Status ladder (Day-19 semantics, mirrored from Day-25)

- No usable family input at all → `UNAVAILABLE` (`MISSING_EVIDENCE`,
  plus `MISSING_QUALITY` when quality absent).
- `quality is None` → `PARTIAL` (`MISSING_QUALITY`) with read evidence rows.
- `quality.quality_state == INSUFFICIENT` → `PARTIAL`
  (`INSUFFICIENT_QUALITY`) with read evidence rows.
- **Time-horizon gate:** the synthesis layer never invents a horizon. A
  Day-19 `SUCCESS` requires a `time_horizon`, so without a caller-supplied
  `SynthesisInput.time_horizon` the interpretation is `PARTIAL`
  (`MISSING_HORIZON`) with the read evidence rows — never a fabricated
  `EXPIRY` SUCCESS.
- Otherwise → `SUCCESS` per the outcome table, carrying the caller-supplied
  `time_horizon` verbatim (never defaulted, never overwritten).
- Structural input violations raise `ValueError` (INVALID semantics are
  enforced at construction like every intelligence module).

## Evidence / observation

- One evidence row per present family read (`bull:` / `bear:` directional,
  `read:` presence-only), each with provenance + versions + aware timestamp.
- Aggregation rows: `synthesis:bull_total`, `synthesis:bear_total`,
  `synthesis:net` (bull − bear), only when ≥1 directional vote exists.
- Observation: `metric_name` = outcome value, `value` = strength
  (`score_0_1`); never fabricated for non-SUCCESS paths.
- Day-9 provenance preserved verbatim on every row and the result; Day-12
  quality preserved by identity; the authoritative Day-23 `MarketRegime`
  (label / source / model version / reference timestamp) supplied in
  `SynthesisInput.regime` propagates verbatim into `IntelligenceResult.regime`
  on every status — never recomputed, never fabricated (a bare
  `regime_label` without the Day-23 channel fabricates no channel; a label
  alone never votes).

## Purity

No wall clock, random, network, filesystem, database, broker, services, or
environment-dependent behavior. All timestamps caller-supplied and genuinely
aware. No hidden global mutable state.

## Day-26 tests (RED first)

Contract, validation, one-family reads (each of the six families, both
directions), multi-family agreement, balanced conflict, weak-vs-strong
conflict, MIXED/UNKNOWN/NEUTRAL never opposing, correlation rules
(positioning+institutional aligned single vote; institutional alone full
vote; opposing pair material), trap duplication (same-direction duplicate
adds no strength; unique trap votes), missing ≠ zero, insufficient/missing
quality, provenance/quality preservation, trap/regime non-directional
labels, expiry context never directional, determinism, serialization
round-trip, AST purity. Independent golden arithmetic (documented in the
test module docstring), never derived from the implementation.

## Verification ladder

Day-26 focused → Days 19–26 → Days 14–26 → Days 9–26 → security/session →
infrastructure/Alembic → `py_compile` → `git diff --check` → AST purity →
unused imports → secret scan → CI. The two known pre-existing security
failures reproduced against the clean Day-25 baseline `8d75fa8`.

## Explicit non-goals (Day 27+)

No event/expiry detection beyond the supplied Day-24 context, no
opportunity/strategy/ranking, no execution, no persistence, no ML/AI, no
backtesting, no frontend/API work, no database/schema changes, no merge,
no deployment, no production cutover, no live trading.
