# StrikeNova Day 22 — Institutional-Like Activity Intelligence

Deterministic, broker-neutral institutional-LIKE activity engine on the
Day-19 Intelligence Contract. Consumes the canonical chain metrics of the
Day-20 positioning/flow engines and the Day-21 typed level-classification
surface; never identifies or claims actual institutions, market makers,
banks, FII/DII or any specific participant.

Pipeline (as approved):

```text
Day-20 Positioning + Flow (chain metrics)
        +
Day-21 Dynamic Levels (typed LevelClassification rows)
        ↓
Day-22 Institutional-Like Activity Engine   (app/intelligence/institutional.py)
        ↓
Day-19 IntelligenceResult  (one deterministic evaluation result per input)
```

Compliant vocabulary: outputs are described with "institutional-LIKE /
large-player-LIKE / evidence-pattern" language only. Observation
``metric_name`` carries the typed ``ActivityPattern`` id
(e.g. ``OI_BUILDUP_CONFIRMED``); direction, signal strength, confidence,
evidence and structured issues travel in the Day-19 envelope. No participant
identity, hidden order flow, market-maker inventory, execution intent or
historical persistence is ever fabricated (see limitations).

## Inputs (canonical, all optional except identity)

``InstitutionalInput`` mirrors the Day-20 ``FlowInput`` shape — canonical
chain metrics, not raw strike rows; callers map Day-20
``PositioningMetrics``/``FlowMetrics`` and Day-21 ``classify_levels`` output
onto it (documented mapping table below):

| Field | Source (Day-20/21 public contract) | Meaning / unit |
|-------|-------------------------------------|----------------|
| ``net_call_oi_change`` (CD) | ``PositioningMetrics.total_call_oi_change`` | chain CE ΔOI, contracts, signed |
| ``net_put_oi_change`` (PD) | ``PositioningMetrics.total_put_oi_change`` | chain PE ΔOI, contracts, signed |
| ``total_call_oi`` (CO) | ``PositioningMetrics.total_call_oi`` | standing CE OI level, contracts |
| ``total_put_oi`` (PO) | ``PositioningMetrics.total_put_oi`` | standing PE OI level, contracts |
| ``call_volume`` (CV) | ``PositioningMetrics.total_call_volume`` | CE volume, contracts |
| ``put_volume`` (PV) | ``PositioningMetrics.total_put_volume`` | PE volume, contracts |
| ``call_delta_shift`` | ``FlowInput.call_delta_shift`` | signed notional delta shift |
| ``put_delta_shift`` | ``FlowInput.put_delta_shift`` | signed notional delta shift |
| ``vega_shift_net`` | ``FlowInput.vega_shift_net`` | signed net vega shift |
| ``level_classifications`` | ``LevelClassification`` rows (Day-21 ``classify_levels``) | typed kind/state/strength per strike |
| ``spot`` / ``spot_change`` | price context (same semantics as Day-20/21) | points / signed points |

Missing stays ``None``; a measured 0.0 stays a legitimate zero. Timestamps
are explicit and genuinely timezone-aware; ``quality`` is the preserved
Day-12 ``QualityResult`` (``None`` ⇒ non-SUCCESS, never a fabricated read).

## Derived context (deterministic; none fabricated)

- ``net = CD + PD`` (only when both legs present)
- ``ce_pe_flow = CD − PD`` (only when both legs present)
- ``delta_shift = call_delta_shift + put_delta_shift`` (only when both present)
- ``total_volume = CV + PV``; ``volume_imbalance = (CV − PV) / (CV + PV)``
  when both volumes present and total > 0 (measured-zero total ⇒ ``None``)
- price direction usable only when ``spot_change`` is present and non-zero
  (a measured flat price is never treated as a directional signal)

Level proximity: a classified level (kind SUPPORT/RESISTANCE with a
non-``None`` strength) is *proximate* when
``abs(strike − spot) / spot <= LEVEL_PROXIMITY_FRACTION (0.10)`` and spot is
present/positive. Day-21 states are used as supplied — Day-22 never
recomputes levels or quality.

## Documented constants (no hidden weights)

- ``OI_ACTIVITY_FLOOR = 200_000.0`` contracts — minimum |net chain ΔOI| for an
  OI-based INSTITUTIONAL_LIKE pattern (conservative absolute scale reference;
  a per-underlying typical baseline requires history and is deferred).
- ``VOLUME_ACTIVITY_FLOOR = 200_000.0`` contracts — minimum total volume for a
  volume-imbalance pattern (same rationale).
- ``IMBALANCE_THRESHOLD = 0.5`` — |volume_imbalance| must reach this bound.
- ``OI_STRENGTH_REFERENCE = 1_000_000.0`` contracts and
  ``DELTA_STRENGTH_REFERENCE = 1_000_000.0`` (notional) — magnitude references
  mirroring the documented Day-20 constants: OI strength = ``min(|net|/ref, 1)``.
- Confidence table (documented, completeness-based):
  ``CONFIDENCE_FULL = 0.90``, ``CONFIDENCE_IMBALANCE = 0.85``,
  ``CONFIDENCE_SINGLE_SIDE = 0.65``, ``CONFIDENCE_NO_PRICE = 0.40``,
  ``CONFIDENCE_CONFLICT = 0.50``.
- ``CALCULATION_ID = "intelligence.institutional_like.v1"``,
  model/calculation version ``1.0.0``.

## Patterns (deterministic cascade — exactly one result per evaluation)

Priority is explicit and documented; each pattern documents its required,
corroborating, contradictory and missing-evidence behavior. All pattern
labels are INSTITUTIONAL_LIKE evidence-pattern language:

1. **POSITION_FLOW_CONFLICT** (conflicting evidence — highest priority).
   Cross-series or level evidence opposes price: ``delta_shift != 0`` with
   sign opposed to ``spot_change``; ``vega_shift_net != 0`` opposed to price;
   or a proximate Day-21 ``CONFLICTED_INTERACTION`` level. Outcome:
   ``PARTIAL``, ``direction = MIXED``, structured ``CONFLICTING_DIRECTION``
   issue — conflicting evidence is never forced bullish/bearish.
   Strength: ``min(|delta_shift| / DELTA_STRENGTH_REFERENCE, 1)`` (or the
   vega magnitude on the same reference; level-conflict uses the proximate
   conflicted level's strength); confidence ``0.50``. Required: the opposing
   series and price. Contradictory: none (it IS the contradiction). Missing:
   series present without price ⇒ no conflict is inferred.

2. **OI_BUILDUP_CONFIRMED** (accumulation-style, price-confirmed).
   ``net >= OI_ACTIVITY_FLOOR`` with usable price direction. Direction follows
   the documented Day-20 change-based convention: ``price > 0`` ⇒
   LONG_BUILDUP-style BULLISH; ``price < 0`` ⇒ SHORT_BUILDUP-style BEARISH.
   Corroborating: dominant-leg volume activity, standing asymmetry, a
   proximate Day-21 level consistent with the direction. Contradictory:
   cross-series divergence (would have fired pattern 1). Missing: one ΔOI leg
   ⇒ net unknown (falls through); volume missing lowers confidence, never
   zeroes the pattern.
   Strength ``min(net / OI_STRENGTH_REFERENCE, 1)``.

3. **OI_UNWINDING_CONFIRMED** (unwinding/distribution-style, price-confirmed).
   ``net <= −OI_ACTIVITY_FLOOR`` with usable price direction; Day-20
   convention: ``price > 0`` ⇒ SHORT_COVERING-style BULLISH; ``price < 0`` ⇒
   LONG_UNWINDING-style BEARISH. Same corroboration/missing semantics as 2;
   strength ``min(|net| / OI_STRENGTH_REFERENCE, 1)``.

4. **VOLUME_IMBALANCE_FLOW** (aggressive-looking flow).
   Fires when patterns 2/3 did not (net below floor or unknown) and
   ``total_volume >= VOLUME_ACTIVITY_FLOOR`` and
   ``|volume_imbalance| >= IMBALANCE_THRESHOLD``. Direction: imbalance and
   price agree (call-dominant + rising, put-dominant + falling) ⇒
   SUCCESS BULLISH/BEARISH; imbalance opposes price ⇒ ``PARTIAL`` +
   ``MIXED`` + ``CONFLICTING_DIRECTION`` (aggressive-looking flow against
   price is conflicting evidence, never a forced read). Price missing ⇒
   ``PARTIAL`` + ``MISSING_REQUIRED_INPUT``. Strength ``|volume_imbalance|``
   (already bounded); confidence ``0.85`` on an agreed read and ``0.50`` on
   an opposed (conflict) read.

5. **NO_PATTERN** (measured activity with no institutional-like signature).
   Usable series exist but no pattern above fired (including a measured flat
   price). ``SUCCESS``, ``direction = NEUTRAL``, strength ``0.0``,
   confidence from the completeness table (full when ΔOI legs and volume are
   present). This is a measured assessment — never fabricated zeros; evidence
   rows carry only present values.

Non-pattern statuses (mirror Day-20/21 semantics):
- No evidence at all (no OI/volume/flow series, no usable levels, no spot) ⇒
  ``UNAVAILABLE`` + ``MISSING_EVIDENCE`` (+ ``MISSING_QUALITY`` when quality
  is absent).
- ``quality = None`` ⇒ ``PARTIAL`` + ``MISSING_QUALITY`` (evidence retained,
  no directional claim).
- Usable OI but price missing ⇒ ``PARTIAL`` + ``MISSING_REQUIRED_INPUT``
  (``spot_change``); incomplete ΔOI legs ⇒ ``PARTIAL`` +
  ``MISSING_REQUIRED_INPUT`` with the missing field named.
- Levels alone (no OI/volume/flow series) ⇒ ``PARTIAL`` +
  ``MISSING_REQUIRED_INPUT`` (chain OI change / volume) with the level rows
  as evidence — static level structure alone cannot support an activity read.

## Quality / provenance / determinism

- The exact Day-12 ``QualityResult`` instance and Day-9 ``Provenance`` are
  preserved (identity); quality is never recomputed or replaced.
- ``signal_strength != confidence != quality`` — three separate fields.
- Pure module: no wall clock, randomness, network, DB, filesystem, broker or
  services imports; no mutable global state; SUCCESS rests only on present,
  finite evidence.
- Day-19 contract is authoritative; Day-20 ``positioning.py``/``flow.py`` and
  Day-21 ``levels.py`` are NOT modified.

## Scope

Allowed: new module + tests + plan + tracker evidence.
Forbidden: DB/schema/migrations, API/frontend, broker/execution/risk, GEX
changes, Day-19/20/21 contract changes, historical data subsystem, AI/ML,
backtesting, deployment, production DB, live trading, merge.

## Known limitations (documented, not blockers)

- **No participant identification** is ever attempted or implied — outputs
  describe observable evidence patterns only.
- **"Unusual"/"repeated behavior"** cannot be measured without a historical
  baseline; the engine uses documented absolute scale floors and cannot yet
  detect repeated patterns (deferred to persistence-enabled days).
- Absolute scale floors are single documented references; per-underlying
  typicals require history.
- One deterministic result per input (cascade), not an exhaustive multi-pattern
  report — a deliberately simple, testable characterization surface.

## Day 22 gate

PASS only with fresh evidence: focused tests, Days 19–22 / 14–22 / 9–22
regression, security/session + infra/migration regression (with clean-baseline
reproduction of pre-existing failures), py_compile / diff --check / AST purity
/ unused-import / secret scan, CI Status Gate + PostgreSQL compatibility,
and a scope-contained diff. Tracker documents evidence; Day 22 does not
self-declare PASS.
