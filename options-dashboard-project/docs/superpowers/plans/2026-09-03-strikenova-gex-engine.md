# StrikeNova — Day 17 Implementation Plan: GEX Calculation & Gamma Profile Foundation

**Status:** Approved for execution (authorized by the user).
**Baseline:** Day 16 PASS — `a21b195`.
**Branch:** `feat/strikenova-day1-security`.
**Gate:** Do NOT begin Day 18 (scenarios) or any Gamma-Flip/Walls work.

---

## 1. Objective

Establish the authoritative, deterministic **GEX Calculation Engine** on top
of the Day-14 quantitative boundary and the Day-15/16 quantitative
foundation — the reusable backend/shared GEX foundation required by later
Gamma Flip, Gamma Walls, historical GEX and intelligence work:

```text
Canonical Market Data → Data Quality → Quantitative Boundary
    ├── Greeks (Day 15) / Pricing (Day 16) / IV (Day 16)
    └── GEX Engine + Gamma Profile  ← DAY 17
```

## 2. Current-state findings (fresh repository inspection)

* **The canonical convention already exists and is approved**
  (`docs/GEX_V1_0_SPEC.md`, `app/services/live_gex.py`, frontend `gex.js`):

  ```text
  Raw GEX_i = Gamma_i × OI_i × S² × 0.01
  Call GEX = + Raw GEX     Put GEX = − Raw GEX
  positioning_model = NAIVE_DEALER_CONVENTION, call_sign = +1, put_sign = −1
  methodology = GEX_STANDARD_V1
  ```

* **OI units:** OI is in **contracts** — never lots. The V1.0 spec §11
  documents a 7-point evidence chain (Upstox `market_data.oi` passes through
  unconverted; Upstox APIs operate in contract units; NSE/BSE report
  outstanding contracts). `live_gex.py` metadata: `oiUnit=contracts`,
  `lotSizeFactorApplied=False`.
* **Existing backend service** `live_gex.py` (Phase 8A) is chain-dict-based
  (broker-shaped input `{call:{gamma,oi},...}`), datetime-coupled
  (`datetime.now` for `captured_at`/chain age — not a pure quant engine),
  and treats zero OI/gamma as *row exclusions* (`ZERO_OI`) rather than valid
  zero contributions. It is NOT a Day-14-boundary engine. Kept untouched.
* **The quant boundary has no GEX engine.** `app/quant/` contains contracts,
  boundary, greeks, pricing, iv. Day-14 classification: `live_gex.py` =
  "reusable foundation (migrated Day 17)" — this plan migrates the *math and
  conventions*, not the chain service.
* **Frontend `gex.js` + Phase 7.2+ analytics** stay as-is (presentation/
  analytics layer). Documented; no migration.
* **Broker/model separation (Day 9):** `GreeksObservation.source =
  "BROKER"|"MODEL"` with `calc_model`/`calc_version`. GEX must not silently
  mix gamma sources.
* **Contracts safety:** `OptionMarketData`/`QuantResult` are constructed
  keyword-only across the repo (verified) — additive trailing optional
  fields break nothing.

## 3. Additive contract changes (Day-14 contracts, backward compatible)

1. `OptionMarketData` gains three optional trailing fields:
   * `gamma: float | None = None` — option gamma (per-unit-per-unit),
     validated finite and non-negative when present (0 = legitimately zero,
     distinct from missing None).
   * `open_interest: float | None = None` — **contracts**, never lots,
     validated finite and non-negative when present.
   * `greeks_source: str | None = None` — `"BROKER"` or `"MODEL"` token
     (the Day-9 GreeksObservation source vocabulary) identifying where the
     input gamma came from. Token validation lives in the GEX engine.
2. `QuantResult` gains one optional trailing field:
   * `greeks_source: str | None = None` — carried through the envelope so a
     GEX result explicitly identifies whether its gamma input was
     broker-observed or model-calculated. Days 14–16 results leave it None.

No existing member, ordering, or behavior changes. No migrations.

## 4. GEX engine (`app/quant/gex.py`)

* Constants (explicit, matching the approved spec): `GEX_FACTOR = 0.01`,
  `SIGN_CONVENTION = "NAIVE_DEALER_CONVENTION"`,
  `METHOD_VERSION = "GEX_STANDARD_V1"`, `call_sign = +1`, `put_sign = −1`.
* Model identity: `model = "GAMMA_EXPOSURE"`, `calculation_id =
  "gex.naive_dealer_v1"`, versions explicit.
* Pure functions (no I/O, no clock, deterministic):
  * `raw_gex(gamma, oi, spot) = gamma × oi × spot × spot × 0.01`
  * `dealer_signed_gex(side, gamma, oi, spot)` = `+raw` for CALL, `−raw` for
    PUT (the documented NAIVE_DEALER_CONVENTION — a modeling assumption,
    never a claim about observed dealer positions).
* `GexCalculationEngine` implements the Day-14 `QuantEngine` protocol:
  * Requires `gamma`, `open_interest`, and a valid `greeks_source`
    (`"BROKER"|"MODEL"`) — missing → `UNAVAILABLE/MISSING_REQUIRED_INPUT`;
    unknown source token → `INVALID_INPUT`.
  * Runs through `QuantitativeEngineBoundary` (provenance + INSUFFICIENT
    quality gates apply before the engine) and returns `QuantResult` with
    `values = {"raw_gex": …, "signed_gex": …}`, `greeks_source` preserved.
  * Zero gamma/OI are valid inputs producing 0.0 (documented divergence from
    the legacy service's ZERO_OI *row-exclusion* semantics — the V1.0 spec
    only declares NaN/inf/non-numeric gamma and negative OI invalid).

## 5. Gamma profile foundation

* `build_gamma_profile(rows, …)`: pure, deterministic aggregation over
  per-side rows (each row is an `OptionMarketData`):
  * Structural row validation: gamma/OI finite non-negative and present,
    greeks_source token, provenance present, quality not INSUFFICIENT —
    invalid rows are **excluded with a structured reason**, never fabricated
    and never silently dropped.
  * Uniformity guards: all rows must share the same positive finite spot
    (deterministic error otherwise); all *valid* rows must share the same
    greeks_source — **broker and model gamma are never mixed**.
  * Per-strike output rows sorted by strike ascending:
    `strike, call_gex, put_gex, net_gex` (a missing side stays `None` —
    missing is not zero).
  * Aggregates: `total_call_gex`, `total_put_gex`, `total_net_gex`
    (totals `None` when no row of that side exists; net is the signed sum of
    present contributions).
  * Duplicate (strike, side) rows each contribute (each row is a separate
    observation; the builder sums contributions per (strike, side) — the
    same "each row contributes" semantics the legacy chain service applies).
* Zero-OI/zero-gamma rows contribute exactly 0.0 (valid, included).

## 6. Validation & numerical safety

* Spot/strike/gamma/OI: finite, sign-checked per spec; gamma ≥ 0; OI ≥ 0;
  side must be CALL/PUT; source token explicit. Non-finite never escapes.
* Edge coverage: ATM/ITM/OTM/deep moneyness, gamma = 0, OI = 0, very large
  finite OI, tiny gamma, large spot, negative signed values where the
  convention permits (PE), non-finite inputs rejected.

## 7. Testing strategy (TDD RED → GREEN)

`tests/test_day17_gex_engine.py`:

1. **Golden values — independent.** Expected GEX computed by hand/scratch
   (raw = γ·OI·S²·0.01 with explicit numbers), never by calling the
   production function. Cross-checked against an independent scratch
   evaluation and the existing `live_gex._raw_gex`/`_signed_gex` (a
   pre-existing, separate implementation) where applicable.
2. **OI unit regression:** `OI = 100` contracts is used directly as 100 —
   no lot-size multiplication (e.g., NIFTY lot 65 must NOT appear);
   `raw(γ=0.002, OI=100, S=24000) = 0.002×100×24000²×0.01` independently.
3. **Sign convention:** CE + / PE − under NAIVE_DEALER_CONVENTION; convention
   constants + call/put signs asserted; a put's signed GEX is negative.
4. **Engine/contract:** boundary routing, QuantResult envelope,
   quality/provenance/version propagation, greeks_source preservation,
   missing gamma/OI → UNAVAILABLE, missing/bad source → INVALID_INPUT,
   INSUFFICIENT quality/missing provenance blocked before the engine.
5. **Invariants (independent properties):** doubling OI doubles GEX; doubling
   gamma doubles GEX; GEX ∝ S² (holding γ/OI fixed, 4× spot² ⇒ 4× GEX);
   γ=0 ⇒ 0; OI=0 ⇒ 0.
6. **Profile:** one strike, multiple strikes, CE-only, PE-only, both legs,
   unsorted input → sorted output, duplicate rows, zero-OI rows, missing leg,
   empty profile, mixed valid/invalid rows with exclusions, mixed
   broker/model sources rejected, mismatched spots rejected, conservation
   (Σ strike net = total net).
7. **Determinism:** identical inputs ⇒ identical results; no hidden clock/
   random/env/DB/network (Day-14 AST guards auto-extend to the new module).
8. **Security:** module-level AST static checks + credential-free outputs.

## 8. Scope exclusions

Gamma Flip, zero-crossing detection, Gamma Walls, historical GEX
persistence/snapshots/ΔGEX history, scenario engine, portfolio sensitivities,
intelligence/opportunity/strategy/risk engines, execution, ingestion,
backtesting, ML/AI, Redis/Kafka/microservices, frontend changes, DB schema
changes, deployment, cutover, live trading. **Day 17 = GEX calc + gamma
profile foundation only.**

## 9. Known limitations

* The engine computes under the declared NAIVE_DEALER_CONVENTION — a modeling
  convention, not observed dealer positioning (spec §6.1).
* Legacy `live_gex.py` row-level `ZERO_OI`/zero-gamma exclusion semantics
  differ from the pure engine's "zero is a valid zero contribution" (spec
  §10 only bans NaN/inf/non-numeric gamma and negative OI). Documented;
  legacy service untouched; consumers migrate later.
* Expiry-scope aggregation (by expiry, multi-expiry chains) is out of scope
  — profile rows carry `instrument.expiry` so later days can partition.

## 10. Verification commands

```bash
python -m pytest tests/test_day17_gex_engine.py -q            # RED then GREEN
python -m pytest tests/test_day1[456]*.py ...                 # quant groups
# market-data (days 9–13), security/session, legacy GEX, infra/migration groups
python -m py_compile app/quant/gex.py app/quant/contracts.py
git diff --check
# secret scan; AST guards (auto-extend from Day 14)
```

## 11. Day 17 gate criteria

PASS only with fresh evidence for: canonical formula, OI units, sign
convention, broker/model gamma separation, profile aggregation, boundary
integration + QuantResult preservation, quality/provenance/version
propagation, independent goldens, invariants, edge cases, determinism,
security/static checks, regression (failures independently proven
pre-existing), CI, clean diff scope, production untouched. Otherwise BLOCKED
with exact blockers.
