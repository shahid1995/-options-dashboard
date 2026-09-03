# StrikeNova Day 24 — Expiry Intelligence + Market Event Detection

Deterministic, broker-neutral **expiry context intelligence** and
**observable state-transition event detection** on the Day-19 Intelligence
Contract, consuming only evidence available through the existing contracts.

Pipeline (as approved):

```text
Canonical Market Data → Day-12 Quality → Day-14 Quant → Day-20 Positioning/Flow
  → Day-21 Levels → Day-22 Institutional-Like → Day-23 Market Regime
  → Day-24 Expiry/Event Intelligence   (app/intelligence/expiry.py)
  → Day-19 IntelligenceResult
```

Two public evaluation surfaces in one module:

1. `classify_expiry(inp) -> ExpiryContext` — typed expiry context (typed
   layer, like Day-21's classification layer).
2. `evaluate_expiry(inp) -> IntelligenceResult` — the Day-19 envelope for the
   expiry context assessment (observation metric `expiry_intelligence`).
3. `evaluate_transitions(inp, previous=None) -> tuple[IntelligenceResult, ...]`
   — deterministic event detection; one result per fired transition.

An **event is a transition, never a current state**: it requires explicit
prior AND current observations supplied by the caller.  No previous
observation ⇒ an explicit PARTIAL "initial state — no prior observation"
condition (never a fabricated `UNKNOWN → X` event).  No history is ever
invented; no persistence; no database.

## Evidence model (explicit, caller-supplied; missing stays None)

`ExpiryInput` (identity: underlying, aware `reference_timestamp`,
Day-9 `provenance`; all measurements optional):

| Field | Source | Meaning / unit |
|-------|--------|----------------|
| `expiry_timestamp` | caller (exchange chain expiry) | aware datetime |
| `spot` | price context | points |
| `rows` | Day-20 `StrikePositioning` raw rows | per-strike CE/PE OI for concentration |
| `gex` / `gex_source` | Day-17 `GammaProfile.total_net_gex` + `greeks_source` | signed net GEX / "BROKER"/"MODEL" |
| `theta_reference` | Day-15 annualized model theta (ATMF reference) | per-year |
| `regime_label` | Day-23 result label | `RegimeLabel` |
| `positioning` | Day-20 label | `PositioningClassification` |
| `level_state` | Day-21 proximate level dynamic state | `LevelState` |
| `institutional_pattern` | Day-22 result pattern | `ActivityPattern` |
| `conflict` | Day-23 cross-evidence conflict flag | bool |
| `quality` | preserved Day-12 `QualityResult` | — |

The engine derives chain totals through the **public Day-20
`compute_metrics`** (documented reuse; no duplicate OI mathematics), plus a
local deterministic top-strike measurement (`top_strike`, `top_share`).
GEX is consumed whole (Day-17 convention: signed net, source distinguished,
never reimplemented); theta is consumed whole (Day-15 annualized convention).

## Expiry context rules (deterministic; time convention follows Day-14/18 — calendar days)

- `time_remaining_days = (expiry_timestamp − reference_timestamp) / 86400`
  (both explicit and aware; deterministic — never wall clock).
- Proximity classes (documented thresholds): `EXPIRED` (< 0),
  `AT_EXPIRY` (<= 1 day), `NEAR` (<= 7 days), `FAR` (> 7 days),
  `UNKNOWN` (missing expiry or reference).  Short time-to-expiry alone is
  never an event and never directional.
- Concentration (measurements only — never support/resistance/pinning/direction):
  `ce_share`, `pe_share`, `total_oi`, `top_strike`, `top_share`
  (dominant single-side strike value ÷ total OI), `spot_distance_top`
  (`|top_strike − spot| / spot`).  A high share is a measured fact only.
  **Partial-OI semantics (Day-20 authoritative — missing ≠ zero):**
  `total_oi` is a one-sided measurement when only one side is available;
  CE/PE shares are defined only over a complete two-sided denominator with
  a non-zero total — partial availability never fabricates a 100% share,
  a measured-zero total leaves ratios undefined (never 0.0), and a side
  measured `0.0` remains a legitimate zero (distinct from missing).
- Gamma context: `POSITIVE` (gex > 0) / `NEGATIVE` (gex < 0) / `NEUTRAL`
  (measured 0.0) / `UNSUPPORTED` (missing).
- Time-decay context: `ACCELERATING` (proximity NEAR/AT_EXPIRY AND
  `theta_reference < 0` — annualized model decay present near expiry) /
  `NORMAL` (theta present, far) / `UNSUPPORTED` (theta missing).  Theta
  magnitude is never a directional prediction.

### Pinning pressure (evidence pattern — never certainty)

`PINNING_CANDIDATE` requires ALL of (documented deterministic rule, no
`high OI = pinning`):
1. proximity in (`NEAR`, `AT_EXPIRY`), and
2. `top_share >= PINNING_CONCENTRATION_FLOOR (0.20)`, and
3. `spot_distance_top <= PINNING_SPOT_BAND (0.02)`.

`PINNING_EVIDENCE` — proximity in (NEAR, AT_EXPIRY) but only some of (2)/(3)
hold (partial, evidence-limited).  `PINNING_UNSUPPORTED` otherwise.  GEX
presence corroborates (confidence 0.85 vs 0.70) but is not required.  The
classification is **derived pressure/evidence language only** — never
"the market will pin", never market-maker positioning claims, no direction.

## Event detection rules (transitions only)

Categories evaluated when BOTH `previous` and current supply the field, and
both endpoints are **meaningful** (non-UNKNOWN / non-UNCLASSIFIED /
non-NONE-like — `UNKNOWN → X` is never a fabricated event):

| EventType | Prior vs current | Fires when |
|-----------|------------------|------------|
| `REGIME_TRANSITION` | `regime_label` | both meaningful & different |
| `POSITIONING_TRANSITION` | `positioning` | both meaningful & different |
| `LEVEL_TRANSITION` | `level_state` | both meaningful & different |
| `INSTITUTIONAL_TRANSITION` | `institutional_pattern` | both meaningful & different |
| `EXPIRY_PROXIMITY_TRANSITION` | derived proximity class | both != UNKNOWN & different |
| `GAMMA_CONTEXT_TRANSITION` | derived gamma context | both in (POSITIVE, NEGATIVE, NEUTRAL) & different |
| `DIRECTIONAL_CONFLICT_TRANSITION` | `conflict` flag | changed True↔False |

Identical states ⇒ no event.  Missing previous ⇒ one explicit PARTIAL
"initial state" result (structured `MISSING_REQUIRED_INPUT`).  Multiple
simultaneous transitions emit one result each, ordered deterministically by
`EventType` enum order.  Strength: 1.0 for categorical transitions;
ordinal transitions (`EXPIRY_PROXIMITY`, `GAMMA_CONTEXT`) use
`|index_prior − index_current| / max_index_distance` (documented ordinal
indices — gamma ordinals NEGATIVE=0 / NEUTRAL=1 / POSITIVE=2, max distance
2, so NEGATIVE↔POSITIVE = 1.0 and NEUTRAL↔NEGATIVE/POSITIVE = 0.5).
`UNSUPPORTED` is **absence, never a gamma state**: UNSUPPORTED→X and
X→UNSUPPORTED never fire a transition (no fabricated gamma event when the
observation is unavailable), while measured-zero GEX (`NEUTRAL`) is
legitimate and participates in every meaningful-pair transition.
Confidence: 0.90 when both endpoints and the expiry context are present,
0.70 when the expiry context is incomplete.  `direction = NEUTRAL` always —
transitions are not trade signals and never imply a direction.

## Quality / provenance / determinism

- Day-12 quality preserved (`is`); missing quality ⇒ PARTIAL +
  `MISSING_QUALITY`; Day-12 INSUFFICIENT state ⇒ PARTIAL +
  `INSUFFICIENT_QUALITY` (Days 21/23 precedent).  No usable evidence ⇒
  UNAVAILABLE + `MISSING_EVIDENCE`.  Missing expiry timestamp (with usable
  context) ⇒ PARTIAL + `MISSING_REQUIRED_INPUT`.
- Day-9 provenance preserved verbatim on result and every evidence row.
- `signal_strength != confidence != quality`; horizon EXPIRY (chain/expiry-
  scoped evaluation, mirroring Days 20–23).
- Timestamps: every evidence record carries the caller-supplied aware
  `reference_timestamp`; event evidence rows carry both prior and current
  numeric context (refs `exp:{u}:{scope}:…` and `…:prior:…`).  No wall clock,
  no UUIDs, no filesystem/database timestamps.
- Pure module (AST-guarded): no clock / random / DB / network / filesystem /
  broker / services imports; no persistence.

## Documented constants

`AT_EXPIRY_DAYS = 1.0`, `NEAR_EXPIRY_DAYS = 7.0`,
`PINNING_CONCENTRATION_FLOOR = 0.20`, `PINNING_SPOT_BAND = 0.02`,
confidence table 0.90 / 0.85 / 0.70 / 0.50; proximity strength table
AT_EXPIRY 1.0 / NEAR 0.6 / FAR 0.3 / EXPIRED 0.0 / UNKNOWN 0.0;
`CALCULATION_ID = "intelligence.expiry_event.v1"`, versions 1.0.0.
All thresholds documented — no hidden weights, no opaque composite scores
(the observation value is the documented proximity-strength component only).

## Scope

Allowed: `app/intelligence/expiry.py`, `tests/test_day24_expiry_event.py`,
plan + tracker evidence.  Forbidden: Day-25+ (trap detection etc.),
Day-19/20/21/22/23 contract changes, GEX reimplementation or semantic change,
DB/schema/migrations, API/frontend, broker/execution/risk, backtesting,
AI/ML, historical persistence/event store, deployment, production DB,
live trading, merge.

## Known limitations (documented, not blockers)

- Events require the caller to supply the prior observation — no history is
  stored or inferred; persistence/event-store belongs to later architecture.
- Gamma context is a chain-sign reading of the Day-17 net GEX; per-strike
  gamma-profile transitions and Gamma Flip/Walls remain later scope.
- Pinning is a deterministic evidence-pattern classification with documented
  thresholds, never certainty; no exchange expiry calendars or holidays are
  modeled (proximity uses explicit caller timestamps only).
- Concentration shares use the supplied rows' present values; missing sides
  yield None, never zero; partial (one-sided) availability exposes the
  one-sided measurement only and never fabricates a 100% aggregate share.

## Day 24 gate

Evidence-first verification ladder (focused; Days 19–24 / 14–24 / 9–24;
security/session with clean-baseline reproduction; Days 4–8 infra; py_compile;
diff --check; AST purity; unused imports; secret scan; CI).  Tracker records
evidence; Day 24 does not self-declare PASS.