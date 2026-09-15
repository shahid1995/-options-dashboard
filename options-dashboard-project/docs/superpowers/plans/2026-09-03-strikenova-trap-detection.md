# Day 25 — Trap Detection Intelligence

## Objective

Deterministic, broker-neutral **trap-candidate detection** on the Day-19
Intelligence Contract, consuming only typed evidence available through the
existing Days 20–24 engines.  The engine detects **observable conflict
patterns that may represent a trap** — never certainty, manipulation,
institutional intent, or hidden-participant knowledge.

> trap candidate / trap-like condition — never "confirmed manipulation".

## Pipeline

```text
Canonical Market Data
        ↓
Day-20 Positioning / Flow / Divergence
        ↓
Day-21 Dynamic Levels
        ↓
Day-22 Institutional-Like Activity
        ↓
Day-23 Market Regime
        ↓
Day-24 Event / Expiry Context   (context only — never directional)
        ↓
DAY-25 TRAP DETECTION
        ↓
Day-19 IntelligenceResult
```

## Architecture boundary

Market data → quality → quant → intelligence contract → engines.  Day 25
consumes the **derived typed outputs** of Days 20–23; it never reads raw
market data, never recomputes quality, never re-implements Greeks/IV/GEX.

## Evidence-family design (independence first)

Evidence is evaluated at the **family level** — raw fields that derive from
the same measurement are never counted as independent confirmations:

| Family | Source | Directional read |
|--------|--------|------------------|
| PRICE | caller `spot_change` (signed) | attempt sign: +1 bullish / −1 bearish / 0 measured flat |
| POSITIONING | Day-20 `PositioningClassification` via public `classification_direction` | BULLISH / BEARISH / None (UNCLASSIFIED = no read) |
| FLOW | Day-20 derived `PriceFlowRelation` (CONFIRM / DIVERGE / NO_SIGNAL) | relative to price: DIVERGE = opposing, CONFIRM = agreeing, NO_SIGNAL = no read |
| LEVEL | Day-21 `LevelClassification` rows (proximate, classified, with strength) | kind-aware Day-21/23 semantics: conflicted SUPPORT opposes rising price; conflicted RESISTANCE opposes falling price |
| INSTITUTIONAL_LIKE | Day-22 result direction + strength | BULLISH / BEARISH / MIXED (no implication) / None |
| REGIME | Day-23 result direction (+ label for evidence) | BULLISH / BEARISH / MIXED (no implication) / None |

FLOW consumes Day-20's *derived relation* (which already folds net flow,
imbalance and delta shift into one relation) — one family, never
double-counted.  The Day-24 EXPIRY family is **intentionally excluded**:
Day-24 semantics state expiry proximity / gamma / pinning / events carry no
directional implication and must never independently create a trap.

## Vocabulary

```text
BULL_TRAP_CANDIDATE   BEAR_TRAP_CANDIDATE
FAILED_BREAKOUT       FAILED_BREAKDOWN
FLOW_PRICE_TRAP       NO_TRAP
```

Carried as `observation.metric_name` (the Days 20–24 convention).  One
`IntelligenceResult` per evaluation.

## Classification cascade

1. **No evidence at all** (no price, no family inputs) ⇒
   `UNAVAILABLE` + `MISSING_EVIDENCE` (+ `MISSING_QUALITY` when quality
   absent).
2. **Quality gating** — `quality=None` ⇒ `PARTIAL` + `MISSING_QUALITY`;
   Day-12 `INSUFFICIENT` state ⇒ `PARTIAL` + `INSUFFICIENT_QUALITY`.
3. **Price direction missing** (`spot_change is None`) ⇒ `PARTIAL` +
   `MISSING_REQUIRED_INPUT(spot_change)` — a trap cannot be evaluated
   without a directional move (family evidence rows are still emitted).
4. **Measured flat price** (`spot_change == 0.0`, a legitimate zero) ⇒
   `SUCCESS` `NO_TRAP` NEUTRAL strength 0.0 — no directional attempt
   exists; this is a measurement, not missing.
5. **Directional attempt + no directional families** (all reads
   missing/non-directional) ⇒ `PARTIAL` + `MISSING_REQUIRED_INPUT(
   directional_evidence)` — insufficient evidence is never `NO_TRAP` by
   convenience.
6. **Opposing families** (a family whose read opposes the attempt):
   - opposing set == {FLOW} ⇒ `FLOW_PRICE_TRAP`
   - opposing set == {LEVEL} ⇒ `FAILED_BREAKOUT` (bullish attempt) /
     `FAILED_BREAKDOWN` (bearish attempt)
   - otherwise ⇒ `BULL_TRAP_CANDIDATE` / `BEAR_TRAP_CANDIDATE`
   - status `SUCCESS`; direction = the **opposite of the attempted move**
     (bullish attempt + opposing evidence ⇒ `BEARISH` interpretation, and
     vice-versa).
7. **No opposing, ≥1 agreeing** (price + agreeing families) ⇒ `SUCCESS`
   `NO_TRAP` NEUTRAL — valid sufficient evidence with no contradiction.

`MIXED`/`UNKNOWN`/`NO_SIGNAL` family reads never count as either side
(Day-22/23 corrections); `APPROACHING` levels never count as conflict
(Day-21 remediation — APPROACHING ≠ CONFIRMED_INTERACTION); level existence
alone never creates a trap (Day-23 correction).

## Strength

```text
strength = min(Σ opposing family strengths, 1.0)
```

- POSITIONING label-level opposing read: **0.5** (documented constant)
- FLOW `DIVERGE` read: **0.5**
- LEVEL: the opposing conflicted level's own Day-21 `strength` (measured)
- INSTITUTIONAL_LIKE: caller-supplied Day-22 `institutional_strength`
  (measured) when present, else label-level **0.5**
- REGIME label-level opposing read: **0.5**

Reference = 1.0 (one complete independent opposing family).  Strength
reflects the amount of independent contradictory evidence — never the raw
field count.  `NO_TRAP` strength 0.0.

## Confidence

Completeness/consistency table (documented constants; never equal to
strength):

| Case | Confidence |
|------|-----------|
| opposing + agreeing both observed (conflict fully characterized) | 0.80 |
| opposing observed, agreement side missing | 0.70 |
| price + agreeing, no opposing (clean read) | 0.90 |
| measured flat price | 0.90 |

`PARTIAL` / `UNAVAILABLE` results carry `confidence=None` (Days 20–24
convention).

## Missing ≠ zero

- `spot_change=None` = missing; `0.0` = measured flat (both tested).
- Missing family input = no read — never opposing, never agreeing, never a
  `0.0` strength contribution.
- Never use `value or 0` coercion in the engine.

## Day-19 envelope

Standard `IntelligenceResult`: status / direction / signal_strength /
confidence / `time_horizon=EXPIRY` (SUCCESS, chain-scoped) / evidence
(tuple) / issues / observation (metric_name = trap label, value = strength)
/ provenance verbatim / reference_timestamp caller-supplied / exact
Day-12 quality instance preserved.  `signal_strength != confidence !=
quality`.  Quality is never recomputed.

## Determinism / purity

No wall clock, randomness, network, filesystem, database, broker or
services access; no mutable global state; all timestamps caller-supplied
and genuinely timezone-aware.  Repeated evaluation of identical inputs is
identical (tested).  No participant identity, manipulation, intent or
hidden-flow claims anywhere in vocabulary or docstrings.

## Non-goals

No opportunity / strategy / execution / risk / synthesis; no historical
persistence; no expiry/event-direction inference; no Gamma Flip/Walls; no
Day-19–24 contract changes; no DB/migration/API/frontend/broker changes;
no AI/ML/backtesting; no Day-26.

## Gate

Evidence-first verification ladder (focused; Days 19–25 / 14–25 / 9–25;
security/session with clean-baseline reproduction; Days 4–7 + Alembic
infra; py_compile; diff --check; AST purity; unused imports; secret scan;
CI).  Tracker records evidence; Day 25 does not self-declare PASS.