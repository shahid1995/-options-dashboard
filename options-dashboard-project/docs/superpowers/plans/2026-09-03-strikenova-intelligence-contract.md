# StrikeNova Day 19 — Deterministic Intelligence Contract Foundation

**Status:** In implementation
**Branch:** `feat/strikenova-day1-security`
**Baseline:** `049a3e1` (Day 18 PASS — Scenario & Time Analysis / Portfolio Sensitivity Gate)

## Objective

Establish the canonical, deterministic, broker-neutral **Intelligence Contract**
that becomes the interface between the Quantitative Core (Days 14–18) and every
future Intelligence Engine (Days 20–26+):

```text
Market Data → Data Quality → Quantitative Core → Intelligence Contract → Intelligence Engines
```

Day 19 implements the **contract only** — no positioning/flow/regime/event/trap
engines, no synthesis, no opportunity/strategy/risk consumers.

## Current-state findings

- No existing `app/intelligence` package; zero signal/intelligence vocabulary in
  the backend (verified by search for BULLISH/BEARISH/confidence/intelligence).
- Reusable canonical surfaces confirmed:
  - Day-9 `app.market_data.contracts`: `Provenance`, `QualityState`, `DataMode`,
    `ContractVersion` — broker-free, frozen.
  - Day-12 `app.market_data.quality`: `QualityResult` (quality_score int 0–100,
    quality_state, structured `QualityIssue` tuple) — the canonical quality
    envelope to **preserve whole**, never recompute or re-score.
  - Day-14 `app.quant.contracts`: `QuantResult`/`QuantIssue`/
    `CalculationIssueCode`/`CalculationContext`/`CalculationStatus` —
    the precedent for frozen contracts, structured machine-readable issues,
    deterministic status semantics and version hygiene.
- Day-14 AST purity guards glob only `app/quant/*.py`; the new package therefore
  carries its own module-level AST guards in the Day-19 tests.

## Architecture & placement

New pure package `backend/app/intelligence/` (contracts only this day):

```text
QuantResult / canonical observations / Day-12 QualityResult
        ↓
IntelligenceEvidence   (one piece of supporting evidence)
        ↓
IntelligenceObservation (metric name + value + unit — what was measured/derived)
        ↓
IntelligenceResult     (direction × strength × confidence × horizon × regime,
                        quality preserved, provenance/versions, status + issues)
```

Direction of dependency: `app.intelligence` may import `app.market_data`
(canonical) and `app.quant` (downstream of quant core); it must never import
`app.brokers`, `app.services`, `app.routers`, or perform I/O.

## Contract surface

### Enums (broker-neutral, explicit, frozen vocabulary)

- `IntelligenceStatus`: `SUCCESS | PARTIAL | UNAVAILABLE | INVALID`
- `IntelligenceDirection`: `BULLISH | BEARISH | NEUTRAL | MIXED | UNKNOWN`
  — MIXED and UNKNOWN are **distinct** states, never collapsed into NEUTRAL.
- `TimeHorizon`: `INTRADAY | SHORT_TERM | SWING | EXPIRY | UNKNOWN`
- `EvidenceType`: `MARKET_OBSERVATION | QUANT_DERIVED | QUALITY_ASSESSMENT`
  (engines extend additively later; CE/PE/underlying identity is carried by the
  canonical instrument reference in `source_reference_id`, never by an
  evidence-type hack).
- `RegimeLabel`: `UNKNOWN | RISK_ON | RISK_OFF | TRENDING | RANGING |
  HIGH_VOLATILITY | LOW_VOLATILITY` — a **type-only** attachment vocabulary.
  Day 23 owns actual regime detection and may extend the enum additively.
- `IntelligenceIssueCode`: `MISSING_REQUIRED_INPUT | MISSING_EVIDENCE |
  MISSING_QUALITY | INSUFFICIENT_QUALITY | MISSING_PROVENANCE |
  MISSING_DIRECTION | MISSING_CONFIDENCE | MISSING_SIGNAL_STRENGTH |
  MISSING_HORIZON | PARTIAL_EVIDENCE | CONFLICTING_DIRECTION |
  INVALID_INPUT_VALUE | INVALID_TIMESTAMP | INTERNAL_ERROR`

### Frozen dataclasses

- `IntelligenceEvidence` — `source_reference_id` (required), `evidence_type`
  (required), `value: float | None` (finite or None; None = genuinely missing,
  never coerced), `unit`, `reference_timestamp` (aware-or-None), `provenance`
  (Day-9, optional), `model_version`, `calculation_version`.
- `IntelligenceObservation` — `metric_name` (required non-empty), `value`
  (required finite), `unit | None`.
- `MarketRegime` — `label: RegimeLabel = UNKNOWN`, `source`, `model_version`,
  `reference_timestamp` (aware-or-None). Attachment only.
- `IntelligenceIssue` — `code`, safe static `message`, `field | None`
  (mirrors `QuantIssue`).
- `IntelligenceResult` — `calculation_id` (required), `status`, `direction`,
  `signal_strength` (0..1), `confidence` (0..1), `time_horizon`, `observation`,
  `evidence: tuple[...]`, `regime`,  `quality: QualityResult | None` (the whole
  Day-12 envelope preserved — score, state and issues; **required for
  `SUCCESS`** — a successful intelligence result must carry the canonical
  Day-12 assessment, never a synthetic/fabricated one), `provenance`,
  `reference_timestamp`, `contract_version` (defaults to the module constant
  `INTELLIGENCE_CONTRACT_VERSION = "1.0.0"`), `model_version`,
  `calculation_version`, `issues: tuple[IntelligenceIssue, ...]`.

## Deterministic structural rules (validated at construction — never intelligence)

1. **Signal strength and confidence are separate fields** with their own ranges
   ([0,1]); neither is interchangeable with data quality (`quality` is the
   Day-12 `QualityResult`). Tests lock the separation.
2. **Missing data never becomes zero / neutral / success**: `SUCCESS` requires a
   non-empty evidence tuple whose entries carry finite values, an observation,
   direction, strength, confidence, horizon, provenance and reference timestamp,
   and an empty issue list. A `None`-valued evidence entry can never underpin
   `SUCCESS`.
3. **Status/issue consistency**:
   - `PARTIAL` ⇒ non-empty evidence + at least one structured issue.
   - `UNAVAILABLE` / `INVALID` ⇒ direction/strength/confidence/horizon all
     `None` + at least one structured issue (reason never lost).
   - `SUCCESS` ⇒ zero issues, and `quality` is the preserved Day-12
     `QualityResult` (never `None`, never recomputed, never converted to
     EXCELLENT/GOOD when missing).

   Remediation note (`96122a4`): timestamps are validated by genuine
   `utcoffset()` awareness semantics — a tzinfo whose `utcoffset()` returns
   `None` is rejected along with fully naive datetimes.
4. **Field validity**: non-finite numbers rejected; strength/confidence outside
   [0,1] rejected; enum instances type-checked (raw strings rejected); timestamps
   must be timezone-aware when present; `source_reference_id`, `metric_name`,
   `calculation_id` non-empty.
5. **Directional contradictions (structural only)**: `BULLISH`/`BEARISH`/`MIXED`
   require positive signal strength and positive confidence; `NEUTRAL` and
   `UNKNOWN` accept any strength/confidence (an engine may be confident that a
   market is neutral). No market-domain inference is performed.
6. **Immutability**: all dataclasses frozen; no dict fields (tuples only).
7. **No quality recomputation**: the module holds a `QualityResult` (import of the
   canonical type only) — it never instantiates or calls the Day-12 engine.

## Serialization

- `to_dict()` on each contract: deterministic key order, enums → `.value`,
  datetimes → ISO-8601 (tz-aware), tuples → lists, `None` preserved.
- `from_dict()` classmethods rebuild the frozen contracts (enums/datetimes
  parsed back). Round-trip equality is tested.
- `json.dumps(result.to_dict(), sort_keys=True)` is stable and deterministic.

## Versioning

- `INTELLIGENCE_CONTRACT_VERSION = "1.0.0"` (module constant; no mutable global
  state).
- Model/calculation versions are **supplied by the producing engine** through the
  result (or the underlying evidence); the contract never invents them.

## Purity / security

The package must contain no: wall-clock reads, randomness, network, filesystem,
DB access, broker imports, credentials, sensitive logging, or mutable module
state. Timestamps come only from explicit fields. Enforced by module-level AST
guards in the tests (the Day-14 glob does not cover this package).

## Scope exclusions (Day 19)

No Positioning / Flow-Divergence / Dynamic S-R / Institutional / Regime Engine /
Event / Expiry / Trap detection; no Intelligence Synthesis or conflict
resolution; no Opportunity / Strategy / Risk changes; no execution/broker/DB
changes; no migrations; no Redis/Kafka/workers; no AI/ML; no backtesting; no
frontend changes; no production access. **Days 20+ engines are not started.**

## Verification plan

1. Focused: `tests/test_day19_intelligence_contract.py`.
2. Regression: Days 14–19 quant/intelligence; Days 9–13 market-data group;
   security/session group; infra/migration group (bounded commands).
3. Static: `py_compile`, `git diff --check`, unused-import scan, module AST guard,
   secret scan.
4. CI: StrikeNova Status Gate + PostgreSQL compatibility on the implementation
   and docs commits.
5. Tracker: Day 19 section in `STRIKENOVA_IMPLEMENTATION_STATUS.md`.

## Day 19 gate

**PASS** only with fresh evidence for every item above; otherwise **FAIL** with
exact blockers. Day 20 must not begin.
