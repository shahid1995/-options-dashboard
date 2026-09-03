# StrikeNova Day 21 — Dynamic Support/Resistance Intelligence Engine

**Status:** In implementation
**Branch:** `feat/strikenova-day1-security`
**Baseline:** `558d656` (Day 20 final)

## Objective

Implement the deterministic **Dynamic Support/Resistance Intelligence Engine**
on the Day-19 Intelligence Contract, consuming Day-20 positioning row types:

```text
Canonical rows (Day-20 StrikePositioning) → quality → chain context
    → Level Candidates (measured concentration facts)
    → Derived Level Evidence (shares, activity, interaction)
    → Support/Resistance Classification (deterministic rule table)
    → per-level Day-19 IntelligenceResult
```

Core principle honored: **a high-OI strike is a measured concentration fact,
NOT automatically support/resistance.** Static concentration alone never
classifies; classification requires a corroborating dynamic/activity/
interaction/asymmetry component.

## Master-plan Day-21 tasks

Combine OI, ΔOI, volume, price reaction, GEX, flow, historical reactions and
regime context → evidence-weighted dynamic levels. **Deferred pieces are
documented, not invented**: historical price-reaction persistence needs a
canonical historical-touch interface that does not exist (never fabricated);
gamma-wall/GEX level evidence needs a canonical gamma-wall interface that
Day-17 explicitly deferred (a per-strike net-GEX "wall" convention would be
invented here — out of scope). Dynamic S/R therefore classifies from the
available OI/ΔOI/volume/price-interaction/asymmetry evidence and explicitly
reports static/insufficient states when dynamic confirmation is absent.

## Placement & reuse

- New module: `backend/app/intelligence/levels.py` (pure; imports
  `app.market_data` types, `app.intelligence.contracts`, and the Day-20
  `app.intelligence.positioning.StrikePositioning` row type — no earlier-day
  contract is modified; no brokers/services/routers/IO/wall-clock).
- Input rows reuse the Day-20 `StrikePositioning` raw contract (same
  package): per-strike CE/PE OI, signed ΔOI, volumes; missing stays `None`.

## Layered design (kept separate — no opaque composite score)

1. **Raw observations** — input rows (reused Day-20 type).
2. **Chain context (derived)** — per-side maxima over the chain:
   `max_call_oi`, `max_put_oi`, `max_call_abs_delta`, `max_put_abs_delta`,
   `max_call_volume`, `max_put_volume` (all `None` when the side is absent).
3. **Candidate layer** — every strike row; per-side measured shares:
   `call_share = call_oi / max_call_oi`, `put_share = put_oi / max_put_oi`,
   `call_delta_share = |call_d| / max_call_abs_delta` (sign kept),
   `put_delta_share`, `call_vol_share`, `put_vol_share` — all in `[0,1]`,
   `None` when a component is missing.
4. **Classification layer** — deterministic per-strike rule table →
   `LevelKind` (`SUPPORT | RESISTANCE | UNCLASSIFIED`) and `LevelState`
   (`STATIC | STRENGTHENING | WEAKENING | CONFIRMED_INTERACTION |
   CONFLICTED_INTERACTION | MIXED_EVIDENCE | INSUFFICIENT_EVIDENCE`).
5. **Interpretation layer** — `evaluate_levels(inp) -> tuple[IntelligenceResult, ...]`
   (one per classified level cluster; Day-19 envelope; **no direction claim** —
   a level is positional, not directional, so `direction=NEUTRAL`; level
   classification lives in the typed classification layer).

## Classification rule table (documented constants)

Thresholds (module constants): `CONCENTRATION_THRESHOLD = 0.5`,
`ACTIVITY_THRESHOLD = 0.5`.

- **SUPPORT** (put-side): `put_share >= CONCENTRATION_THRESHOLD` AND at least
  one corroborator: put ΔOI > 0 (strengthening), put ΔOI < 0 with
  `put_delta_share >= ACTIVITY_THRESHOLD` (weakening but active), put volume
  `put_vol_share >= ACTIVITY_THRESHOLD`, price interaction (below), or
  put-heavy asymmetry (`put_oi > call_oi`).
- **RESISTANCE** (call-side): the exact mirror on the call side.
- **UNCLASSIFIED**: static concentration only (measured fact, no level claim —
  the "highest OI alone" guard), or insufficient evidence, or **balanced
  CE/PE evidence** (both sides satisfy their rule → `MIXED_EVIDENCE`, never
  forced to a side).
- Corroboration by asymmetry alone yields a `STATIC` level (concentration +
  standing asymmetry; explicitly no dynamic confirmation — documented
  limitation, never fabricated).

**Price interaction** (deterministic, single-snapshot; no historical touches):
with `d = strike − spot`, `approach` when `sign(spot_change) == sign(d)` and
`spot_change != 0`. For a SUPPORT strike, `CONFLICTED_INTERACTION` when price
is below the strike and still falling (`spot < strike`, `spot_change < 0`);
for RESISTANCE when price is above the strike and still rising
(`spot > strike`, `spot_change > 0`). Otherwise `NO_INTERACTION`.
Interaction is only *confirmation evidence* when corroborated; price reaction
history is never fabricated.

**Level state priority** (documented): `CONFLICTED_INTERACTION` >
`CONFIRMED_INTERACTION` > `STRENGTHENING` > `WEAKENING` > `STATIC` >
`INSUFFICIENT_EVIDENCE` (strengthening/weakening measured on the classifying
side's ΔOI; MIXED_EVIDENCE replaces the kind when both sides classify).

## Level strength (bounded, explainable, no hidden weights)

`level_strength = clamp(mean(components), 0, 1)` where components are the
**present** normalized shares of the classifying side — side share,
`|side ΔOI| share` (strengthening sign kept positive), side volume share —
plus the interaction component (`1.0` on CONFIRMED_INTERACTION,
`0.0` on CONFLICTED_INTERACTION, **excluded** when there is no price
interaction: missing component ≠ zero). Documented equal-weight mean; no
magical 0–100 scale; strength is the deterministic magnitude of the level
evidence.

## Confidence (separate from strength and quality)

Completeness-based documented table: full context (both side ΔOI series +
price) → `0.90`; price missing → `0.50`; classifying side's ΔOI missing →
`0.65`; otherwise `0.80`. `confidence != level_strength != quality` always;
the exact Day-12 `QualityResult` is preserved (identity), Day-9 `Provenance`
verbatim; missing quality ⇒ non-SUCCESS with `MISSING_QUALITY`.

## Clustering (deterministic, strike-distance based)

Classified same-kind levels with strike gap `<= CLUSTER_STRIKE_DISTANCE`
(default module constant `50.0`, documented; inclusive boundary) merge into
one cluster spanning `[min_strike, max_strike]`. Representative strike = the
member with the highest strength; deterministic tie-break = **lower strike**.
Strikes of different kinds never merge. Boundaries tested (gap `==` threshold
merges; `>` threshold does not).

## Evidence per emitted level (only values that exist)

Each level's `IntelligenceResult` evidence carries (when present): side
shares, side ΔOI (signed), side volume, CE/PE asymmetry, interaction
classification input, spot/spot-change, chain context maxima, the exact
Day-12 quality score as a QUALITY_ASSESSMENT citation — each with the Day-9
provenance and explicit versions. Never fabricated. Missing side series are
reported via structured issues (`MISSING_REQUIRED_INPUT`,
`INSUFFICIENT_QUALITY`, `MISSING_QUALITY`) and `PARTIAL`/`UNAVAILABLE`
statuses per the Day-19 semantics.

## Purity / determinism

No `datetime.now()`/`time.time()`/random/UUID/DB/HTTP/filesystem/broker
imports or calls; identical input ⇒ identical output; deterministic ordering
of candidates, clusters and evidence; no hidden defaults. AST-guarded in
tests (the Day-14 glob covers only `app/quant`).

## Testing strategy (TDD RED → GREEN → REFACTOR)

Independent golden fixtures (hand arithmetic). Coverage (30 areas): highest-OI-
alone guard, PE-concentration→support, CE-concentration→resistance,
strengthening/weakening ΔOI, volume evidence, price confirmation/conflict,
balanced CE/PE, multiple candidates, nearby clustering + boundary conditions,
missing OI/ΔOI/volume/price, one-sided chains, insufficient quality, missing
provenance, provenance/quality preservation, determinism, finite values,
serialization round-trip, zero-vs-missing, wall-clock/random/IO/broker purity,
conflicting evidence.

## Verification plan

Focused → Days 19–21 → Days 14–21 → Days 9–21 → security/session group →
infra/migration group (from the `backend` dir) → `py_compile` →
`git diff --check` → unused-import check → AST purity → secret scan.
Pre-existing failures reproduced at the clean Day-20 baseline `558d656`.
CI: StrikeNova Status Gate + PostgreSQL compatibility on both commits.

## Day 21 gate

**PASS** only with fresh evidence; otherwise **FAIL** with exact blockers.
Day 22 must not begin. Scope exclusions honored: no institutional/regime/
event/expiry/trap/synthesis/opportunity/strategy/risk/execution, no AI/ML/
backtesting, no frontend/DB/persistence changes, no production access.
