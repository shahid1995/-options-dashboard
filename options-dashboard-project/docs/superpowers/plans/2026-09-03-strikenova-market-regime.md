# StrikeNova Day 23 — Market Regime Engine

Deterministic, broker-neutral **market regime classification** on the Day-19
Intelligence Contract, consuming the evidence surfaces of Days 20–22.

Pipeline (as approved):

```text
Canonical Market Data → Day-12 Quality → Day-14 Quant
  → Day-20 Positioning/Flow → Day-21 Dynamic Levels → Day-22 Institutional-Like
  → Day-23 Market Regime Engine   (app/intelligence/regime.py)
  → Day-19 IntelligenceResult (regime attached via MarketRegime)
```

The regime classification travels in the Day-19 typed channel:
`result.regime` is a `MarketRegime(label, source, model_version,
reference_timestamp)` — the label is the `RegimeLabel` vocabulary
(`TRENDING | RANGING | HIGH_VOLATILITY | LOW_VOLATILITY | RISK_ON | RISK_OFF |
UNKNOWN`).  No participant-identification claims; no wall clock / randomness /
DB / network / filesystem / broker access; no history is ever fabricated.

## Evidence model (explicit, optional, caller-supplied)

`RegimeInput` carries canonical evidence only (mirrors the Day-20/22 input
convention; missing stays `None`, a measured 0.0 stays zero):

| Field | Source | Meaning / unit |
|-------|--------|----------------|
| `price_moves` | caller-supplied ordered window (from canonical price observations) | tuple of signed price changes, points |
| `spot` / `spot_change` | latest price context | points / signed points |
| `volatility` | explicit annualized volatility fraction from the Day-15/16 quant surface (`implied_volatility`, e.g. ATMF IV reference) | fraction, 0.05 = 5% |
| `positioning` | Day-20 `PositioningClassification` label | typed change-based chain label |
| `institutional_direction` / `institutional_strength` | Day-22 result direction + signal_strength | `IntelligenceDirection` / 0..1 |
| `level_classifications` | Day-21 typed `LevelClassification` rows | kind/state/strength per strike |

## Derived context (deterministic)

- `price_dir` — usable directional price evidence: the signed net of
  `price_moves` when the window is non-empty, else `spot_change`; requires a
  non-zero sign (a measured flat price is never a directional signal).
- `nonzero = [m for m in price_moves if m != 0]`;
  `net = sum(nonzero)`; `gross = sum(abs(m) for m in nonzero)`;
  `net_fraction = |net| / gross` when `gross > 0` (bounded in [0, 1]).
- `positioning_dir` — Day-20 label → direction via the public
  `classification_direction()` mapping (UNCLASSIFIED ⇒ None).
- Proximate levels (same documented rule as Day-22:
  `abs(strike − spot)/spot <= LEVEL_PROXIMITY_FRACTION = 0.10`):
  constructive corroboration when the level kind/state supports `price_dir`
  (rising price with a proximate constructive SUPPORT below or RESISTANCE
  above; falling price mirrored); a proximate Day-21 `CONFLICTED_INTERACTION`
  level is opposing evidence.
- A Day-22 `MIXED` institutional direction is opposing evidence.

## Classification (deterministic priority — one regime label per evaluation)

1. **Conflicting evidence** — `price_dir` present and any opposing
   source (positioning, institutional, level) ⇒ `PARTIAL` + `direction=MIXED`
   + `regime=UNKNOWN` + structured `CONFLICTING_DIRECTION` issue.  Opposing
   evidence is never hidden inside a clean regime read.
2. **TRENDING** — requires actual directional price-window evidence:
   `len(nonzero) >= TREND_MIN_MOVES (3)` and every nonzero move the same sign
   (zeros are measured flats, allowed).  Flat/insufficient price evidence
   never becomes TRENDING.  `direction` = BULLISH/BEARISH by sign;
   strength = `net_fraction` (perfect one-directional window ⇒ 1.0);
   confidence 0.90.
3. **RANGING** — requires bounded, non-directional price-window evidence:
   `len(price_moves) >= RANGE_MIN_MOVES (3)`, at least one positive and one
   negative move, and `net_fraction <= RANGING_MAX_NET_FRACTION (0.25)`.
   "No trend evidence" alone never becomes RANGING.  `direction = NEUTRAL`;
   strength = `1 − net_fraction`; confidence 0.90.
4. **HIGH_VOLATILITY** — explicit `volatility > HIGH_VOLATILITY_THRESHOLD`
   (0.30 annualized fraction).  Never manufactured from a single price
   observation; if `volatility` is None the vol regimes are unreachable.
   `direction = UNKNOWN`; strength = `min(volatility, 1.0)`; confidence 0.85.
5. **LOW_VOLATILITY** — explicit `volatility < LOW_VOLATILITY_THRESHOLD`
   (0.15).  `direction = UNKNOWN`; strength = `1 − volatility / 0.15`
   (bounded ≥ 0); confidence 0.85.  Boundaries are exclusive: a measured
   0.30 / 0.15 falls through (documented and boundary-tested).
6. **RISK_ON / RISK_OFF** — `price_dir` present, no opposing source, and at
   least one corroborating directional source (positioning,
   institutional, level).  Day-20/22 bullish/bearish evidence alone is never
   a regime claim — price evidence is mandatory.  RISK_ON ⇒ BULLISH,
   RISK_OFF ⇒ BEARISH.  Strength = `agreeing_sources / 3` (deterministic
   count over the three corroborator types); confidence 0.90 with ≥2
   corroborators, 0.75 with exactly one.
7. **UNKNOWN** — evidence present but nothing above classified (e.g. a single
   price move with no corroborators, mid-band volatility, no price window and
   no vol).  `SUCCESS` + `direction = UNKNOWN` + `regime = UNKNOWN` +
   strength 0.0 — an honest measured "cannot classify", never a fabricated
   regime.  Confidence 0.40 (limited evidence).

Non-pattern statuses mirror Days 20–22: no usable evidence at all ⇒
`UNAVAILABLE` + `MISSING_EVIDENCE` (+ `MISSING_QUALITY`); `quality = None` ⇒
`PARTIAL` + `MISSING_QUALITY`; Day-12 INSUFFICIENT quality state ⇒ `PARTIAL`
+ `INSUFFICIENT_QUALITY` (the Day-21 gating precedent).  Timestamps are
explicit and genuinely timezone-aware; provenance and quality are preserved
verbatim (`is` for the Day-12 instance), never recomputed.

## Documented constants

`TREND_MIN_MOVES = 3`, `RANGE_MIN_MOVES = 3`,
`RANGING_MAX_NET_FRACTION = 0.25`, `HIGH_VOLATILITY_THRESHOLD = 0.30`,
`LOW_VOLATILITY_THRESHOLD = 0.15`, `LEVEL_PROXIMITY_FRACTION = 0.10`,
confidence table 0.90 / 0.90 / 0.85 / 0.85 / 0.90 / 0.75 / 0.50 / 0.40;
`CALCULATION_ID = "intelligence.regime.v1"`, model/calculation version 1.0.0.
All thresholds are documented deterministic references, not hidden weights.

## Quality / provenance / determinism

`signal_strength != confidence != quality` (separate fields); exact Day-12
`QualityResult` and Day-9 `Provenance` preserved; pure module (AST-guarded);
stable serialization via the Day-19 round-trip.

## Scope

Allowed: `app/intelligence/regime.py`, `tests/test_day23_market_regime.py`,
plan + tracker evidence.  Forbidden: Day-24+, event/trap/expiry intelligence,
opportunity/strategy engines, DB/schema, API/frontend, broker/execution/risk,
GEX changes, Day-19/20/21/22 contract changes, historical persistence, AI/ML,
backtesting, deployment, production DB, live trading, merge.

## Known limitations (documented, not blockers)

- Single-snapshot-plus-window classification: "continuously updated",
  transition indicators and the gamma/liquidity dimensions of the master plan
  require persistence and are deferred (never fabricated).
- Trend/ranging require a caller-supplied price window (≥3 moves); with only a
  single price observation the honest answer is UNKNOWN.
- Volatility regimes use documented annualized thresholds; no vol surface ⇒
  no vol regime.