# Day 14 — Quantitative Engine Boundary

**Status:** IN PROGRESS (authorized 2026-09-03)
**Baseline:** `df085a5` (Day 13 final — Streaming Lifecycle Gate PASS)
**Branch:** `feat/strikenova-day1-security`

## Objective

Establish the **broker-neutral, deterministic Quantitative Engine Boundary** —
the shared backend quant domain that will become authoritative for platform
decisions — WITHOUT implementing any engine (Greeks/IV/pricing/GEX/scenario/
portfolio are Days 15–18).

## Current-state findings

- **No `app/quant` package exists.** The backend has no shared quant domain.
- Frontend `frontend/lib/calculations/` owns today's calculations: `greeks.js`,
  `pricing.js`, `ivAnalytics.js`, `scenario.js`, `gex.js`, `gexPhase72.js`,
  `greekAnalytics.js`, `marketAnalytics.js`, `payoff.js` — **frontend authority
  today**; deliberately NOT migrated/deleted on Day 14 (Blueprint §9 allows
  frontend to remain temporarily; backend becomes authoritative for platform
  decisions later).
- Backend quant-adjacent implementations (classification):
  - `app/services/historical_greeks.py` (Phase 7.19B) — IV + BS Greeks into the
    DB, `calc_version="1.0.0"` convention, deterministic discipline,
    **DB-coupled legacy; candidate for later migration** (not touched Day 14).
  - `app/services/live_gex.py` (Phase 8A) — authoritative backend GEX over the
    canonical chain dict (DB-free); **reusable foundation**; migrated under the
    shared core in Day 17.
  - Broker-passed Greeks/IV enter via Day 9 `GreeksObservation(source="BROKER")`
    — the model-vs-broker separation ALREADY EXISTS in the Day-9 contract.
- Days 9–13 established the canonical upstream chain the boundary consumes:
  Day 9 contracts (identity/provenance/quality enums), Day 11 gateway, Day 12
  quality engine, Day 13 streaming lifecycle.

## Architecture boundary

```
Canonical Market Data (Day 9)        ← NormalizedInstrument / Provenance / QualityState / DataMode
        ↓
Data Quality (Day 12)                ← authoritative quality; consumed, never recomputed
        ↓
Quantitative Engine Boundary (NEW app/quant)
        deterministic CalculationContext   (reference timestamp, r, q, versions, tolerance)
        canonical OptionMarketData input   (terms + market values + provenance + quality)
        QuantEngine protocol + boundary routing (registry-lite)
        QuantResult envelope               (status / values / issues / quality / provenance / versions)
        ↓
Day 15+ engines (Greeks / IV / pricing / GEX / scenario / portfolio)
        ↓
Intelligence
```

Rules: broker-neutral (zero broker imports), deterministic (no wall clock, no
DB, no HTTP, no broker SDKs, no hidden global state), versioned, provenance-
aware, quality-aware, independent of FastAPI request state, reusable by
backend/backtest/paper/AI.

## Contracts (frozen dataclasses in `app/quant/contracts.py`)

- `NumericalTolerance` — deterministic precision policy (relative + absolute
  defaults 1e-9 / 1e-12, validated) + `nearly_equal(a, b)` comparator.
- `CalculationContext` — **required aware `reference_timestamp`** (the ONLY
  notion of now; engines may never read the wall clock), `risk_free_rate`,
  `dividend_yield` (assumption, None = not assumed), `model_version`,
  `calculation_version`, `tolerance`.  Validated at construction.
- `OptionMarketData` — canonical calculation input: `instrument`
  (`NormalizedInstrument`, must be a concrete option contract), `spot`,
  `market_price` (None when not observed), `implied_volatility` (None when not
  observed), `market_timestamp`, `received_timestamp` (aware), `data_mode`,
  `quality` (`QualityState` from Day 12 — consumed, never recomputed),
  `provenance` (Day 9).  Missing/inapplicable stays None — never fabricated.
- `QuantIssue` / `CalculationIssueCode` — compact quant-domain structured
  issues: `MISSING_REQUIRED_INPUT`, `INVALID_INPUT_VALUE`, `INVALID_TIMESTAMP`,
  `INVALID_EXPIRY`, `MISSING_PROVENANCE`, `INSUFFICIENT_QUALITY`,
  `NOT_IMPLEMENTED`, `INTERNAL_ERROR`.  (New domain taxonomy — Day 12 quality
  codes remain quality-scoped.)
- `QuantResult` — status / values / issues / `input_quality` (propagated) /
  `provenance` (preserved) / `reference_timestamp` / `calculation_id` /
  `model_version` / `calculation_version`.  Keeps **calculation output,
  input quality, calculation status and provenance separate** — never collapsed
  into a single confidence/score.
- `CalculationStatus` — `SUCCESS` / `UNAVAILABLE` / `INVALID_INPUT` / `FAILED`.
- Pure helper `time_to_expiry(expiry, reference_timestamp)` — ACT/365 day-count
  convention constant (boundary-level input normalization only; NOT a model).

## Authority model / semantics

- Model-vs-broker separation: broker-provided Greeks/IV are Day-9
  `GreeksObservation(source="BROKER")`; model outputs will be
  `source="MODEL"` carrying `calculation_id` + versions (Day 15+).  The Day-14
  boundary documents this mapping and does not duplicate the separation.
- Versioning: contract (`ContractVersion`), model and calculation versions are
  explicit envelope fields.  No model registry beyond the boundary's own
  registry-lite (Day 14); engine-specific versioning arrives with engines.

## Deterministic calculation context

- Engines receive every environmental value through `CalculationContext`.
- **Static enforcement tests**: `app/quant/` must not import/call
  `datetime.now` / `datetime.utcnow` / `time.time` / `random` / `os.environ` /
  DB / HTTP / broker modules — enforced by AST-scan tests, plus same-input ⇒
  same-result behavior tests with a test-only stub engine.

## Provenance & quality propagation

- `OptionMarketData.provenance` (Day 9) is preserved into `QuantResult`; missing
  provenance ⇒ `UNAVAILABLE` with `MISSING_PROVENANCE` (never replaced by a
  fabricated "unknown" that implies a valid source).
- Quality policy (documented + tested): EXCELLENT/GOOD ⇒ calculation permitted;
  DEGRADED ⇒ permitted but `input_quality=DEGRADED` preserved (result stays
  degraded); INSUFFICIENT ⇒ `UNAVAILABLE` with `INSUFFICIENT_QUALITY` when
  required inputs are unreliable.  The boundary never scores quality itself —
  Day 12 remains authoritative.

## Missing/invalid data

Never fabricate spot / price / vol / expiry / strike / r / q / timestamps /
provenance.  Distinguish missing input, invalid input, unavailable
calculation, and failure via `CalculationStatus` + structured `QuantIssue`s.
No broker payloads or credentials in issues/messages.

## Test strategy (RED first)

- Contract/validation tests (frozen semantics, aware timestamps, concrete
  option terms, negative/NaN/invalid values, invalid expiry, impossible
  combinations).
- Determinism: identical input + context ⇒ byte-identical result; time affects
  a calculation only through `reference_timestamp`; hidden-wall-clock/import
  bans via AST scan.
- Quality: propagation, DEGRADED preservation, INSUFFICIENT gate, no duplicated
  scoring (boundary never invokes the Day-12 engine).
- Provenance: preservation + missing-provenance behavior.
- Boundary routing: unknown calculation ⇒ deterministic `UNAVAILABLE`
  (`NOT_IMPLEMENTED`); registered test-only stub engine routes correctly.
- Errors/security: no broker payload/token leakage in issues.
- Broker neutrality: `app/quant` imports no `app.brokers`/broker SDK modules
  (AST scan).
- Golden fixtures: representative NIFTY option contracts (terms + expiry
  conventions) with invariants — the Day-15 golden-dataset seed.

## Scope exclusions (NOT in Day 14)

No Greeks/IV/Black-Scholes/pricing math, no GEX/gamma-walls/gamma-flip, no
scenario engine, no portfolio sensitivities, no positioning/flow/regime/
opportunity/strategy/risk intelligence, no execution, no historical ingestion,
no backtesting, no ML/AI, no Redis/Kafka/microservices, no DB schema/migrations,
no frontend changes, no deployment/cutover/live trading.  Existing quant code
(`historical_greeks`, `live_gex`, frontend JS) untouched.

## Risks

- Boundary over-build (mitigated: registry-lite, no engines, small taxonomy).
- Accidentally pulling Day-15 math into Day 14 (mitigated: the only numeric
  helper is the ACT/365 `time_to_expiry` input-normalization convention, tested
  and versioned; all engine math is out of scope).
- Static determinism tests becoming brittle (mitigated: narrow AST rules on
  `app/quant` only).

## Verification commands (bounded)

- `python -m pytest tests/test_day14_quant_boundary.py -q` (focused)
- `python -m pytest tests/test_day9_market_data_contracts.py tests/test_day10_upstox_quote_chain.py tests/test_day11_market_data_gateway.py tests/test_day12_data_quality.py tests/test_day13_streaming_lifecycle.py -q`
- quant regression: existing GEX/greeks-adjacent suites
- security/session + Days 4–8/infrastructure groups (bounded)
- `python -m py_compile` changed files; `git diff --check`; secret scan
- CI: Status Gate + PostgreSQL compatibility (record run IDs)

## Day 14 gate criteria

Boundary broker-neutral; deterministic context exists and is enforced; frozen
contracts tested; provenance preserved (never fabricated); quality propagated
without duplication; versioning explicit; invalid/missing inputs handled with
structured statuses; no hidden wall clock/external state; security checks pass;
focused + regression classified; CI green; scope clean; working tree clean
except pre-existing artifacts.  Gate text: **PASS — Quantitative Engine
Boundary Gate satisfied** or **BLOCKED — Day 14 Gate Failed**.
