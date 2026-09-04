# StrikeNova — Day 18 Implementation Plan: Scenario & Time Analysis + Portfolio Sensitivities Foundation

**Status:** Approved for execution (authorized by the user).
**Baseline:** Day 17 PASS — `9bf156a`.
**Branch:** `feat/strikenova-day1-security`.
**Gate:** Do NOT begin Day 19 (intelligence) or any downstream engine work.

---

## 1. Objective

Build the authoritative deterministic backend **Scenario & Time Analysis
Engine** on the existing Day-14 quantitative boundary foundation, providing
reusable **Price × Time × IV** scenario evaluation plus the **portfolio
sensitivity aggregation foundation** required by strategy/opportunity/risk
consumers later — without implementing any consumer, execution, persistence,
ML/AI, or Gamma-Flip/Walls logic.

```text
Market Data → Data Quality → Quantitative Boundary
    ├── Pricing (Day 16) / Greeks (Day 15) / IV (Day 16) / GEX (Day 17)
    └── Scenario & Time Analysis + Portfolio Sensitivity  ← DAY 18
```

## 2. Current-state findings

* **No backend scenario module exists** — `app/quant/` has contracts,
  boundary, greeks, pricing, iv, gex.
* **Frontend reference** (`frontend/lib/calculations/scenario.js`,
  `payoff.js`) is a rich UI/strategy-layer implementation: legs
  `{type, action, strike, expiry, qty, price}`, `dirOf(action)` ±1,
  P/L = `dir × (unitValue − price) × qty × lot × multiplier`, per-leg IV from
  its own expiry chain, row×col matrices, partial/`MISSING_IV` semantics.
  It is **reference/compatibility material only** — NOT authoritative, NOT
  deleted or modified. Notable divergences to document: frontend applies
  `lotSize × multiplier` scaling; the Day-18 backend engine prices **per
  unit-contract** and keeps quantity explicit in contracts (scaling is the
  consumer's concern, mirroring the GEX OI-in-contracts rule).
* The authoritative Day-15/16 engines already expose public **pure**
  functions (`black_scholes_merton_greeks`, `black_scholes_merton_price`)
  with independently validated goldens — Day 18 **reuses** them and must NOT
  duplicate BS/IV/Greek math (§3).

## 3. Architectural rules (documented)

* Day-18 scenario math calls the Day-16/15 **public pure functions** with
  explicit scenario coordinates — zero formula duplication, zero new model.
* The scenario engine evaluates *hypothetical* points (per-scenario spot /
  IV / time-to-expiry), so it does not fit the single-observation
  `QuantitativeEngineBoundary.run(market_data, context)` routing shape.
  Instead it **reuses the QuantResult envelope + boundary quality-gate
  semantics** (INSUFFICIENT quality and missing provenance ⇒ structured
  UNAVAILABLE; missing inputs ⇒ UNAVAILABLE/MISSING_REQUIRED_INPUT; invalid
  inputs ⇒ INVALID_INPUT) with the same CalculationStatus/CalculationIssueCode
  vocabulary. No second result envelope, no second quality framework.
* Deterministic: every environmental value (spot, T, σ, r, q) is explicit;
  time enters only as explicit scenario time-to-expiry (never wall clock).
* Broker-vs-model: all values/sensitivities are **model** values from the
  authoritative engines (Day-15/16 `BLACK_SCHOLES_MERTON_EUROPEAN` family);
  they are never presented as broker observations. Live/broker LTPs are out
  of scope (pure-data portfolio inputs only).

## 4. Scenario contract (`app/quant/scenarios.py`)

* `PositionDirection(str, Enum)`: `LONG = +1` / `SHORT = −1` — explicit; no
  implicit "all users are long".
* `OptionLeg` (frozen, pure data): `option_type: Side`, `strike: float > 0`,
  `expiry: str (YYYY-MM-DD, validated)`, `quantity: float ≥ 0` (contracts;
  zero valid), `direction: PositionDirection`, `entry_price: float | None`
  (per-unit reference — **explicit**; P/L unavailable when absent),
  `implied_volatility: float | None` (the leg's explicit current/base IV,
  decimal), plus optional `quality: QualityState | None` and
  `provenance: Provenance | None` carried into results.
* `ScenarioPoint(spot, time_to_expiry, implied_volatility)` — explicit
  coordinates; σ decimal fraction (0.2 = 20%), T in years (ACT/365 is the
  documented convention for converting calendar expiries upstream, but the
  engine only ever receives explicit T).
* `ScenarioGrid(spots, times, ivs)` — a pure coordinate product. Canonical
  deterministic ordering: **lexicographic (spot, time, iv) with iv varying
  fastest** — `for spot in spots: for t in times: for iv in ivs`.
  `len == n_spots × n_times × n_ivs` (tested).

## 5. Evaluation API (pure, deterministic)

* `scenario_value(...)` — thin documented wrapper over the Day-16
  `black_scholes_merton_price` (validates inputs; reuse, not duplication).
* `evaluate_leg(leg, context, *, spot, time_to_expiry, implied_volatility=None)`
  → `QuantResult` with:
  * values: `scenario_value` (per-unit model value), exposure-scaled
    `delta/gamma/theta/vega` (= model greek × direction × quantity, per
    Day-15 conventions: theta annualized, vega per 1.00 vol fraction), and —
    only when `entry_price` is supplied — `pnl` =
    `direction_sign × (scenario_value − entry_price) × quantity` and the
    scenario coordinates.
  * envelope: `input_quality`, `provenance`, `reference_timestamp` (context),
    `model_version`/`calculation_version`, `contract_version` preserved —
    exactly the Day-14 QuantResult fields.
  * unavailable/invalid handling: missing provenance ⇒ UNAVAILABLE/
    MISSING_PROVENANCE; INSUFFICIENT quality ⇒ UNAVAILABLE/INSUFFICIENT_
    QUALITY; no IV anywhere ⇒ UNAVAILABLE/MISSING_REQUIRED_INPUT; invalid
    spot (≤0/non-finite), negative T, negative σ, bad side/strike ⇒
    INVALID_INPUT. No NaN/Infinity, no silent coercion.
  * `time_to_expiry` default scenario: when the caller passes `None` for
    `time_to_expiry`? NO — time must be explicit. `evaluate_leg` requires
    explicit scenario `spot` and `time_to_expiry`; `implied_volatility`
    defaults to `leg.implied_volatility` (never silently derived elsewhere).
* Terminal behavior: T = 0 evaluates through the Day-16 pricing engine's
  intrinsic convention (call `max(S−K,0)`, put `max(K−S,0)`) and the Day-15
  Greeks engine's step convention — no normal-CDF evaluation at T=0.

## 6. Grid evaluation

* `evaluate_leg_grid(leg, context, grid)` → tuple of `(ScenarioPoint,
  QuantResult)` in the canonical grid order — deterministic, repeatable.
* Callers may equally iterate `grid.points()` themselves; no UI embedding.

## 7. Portfolio sensitivity foundation

* `evaluate_portfolio(legs, context, *, spot, time_to_expiry)` → frozen
  `PortfolioScenarioResult`:
  * per-leg `QuantResult`s (each leg priced with its own explicit
    `implied_volatility` default);
  * aggregated `delta/gamma/vega/theta` = Σ of per-leg exposure-scaled model
    sensitivities (model sensitivities — never claims about broker Greeks);
  * `total_pnl` = Σ leg pnl over priced legs that carry an entry price
    (`None` when no leg has an entry price);
  * `partial` flag + structured notes when legs are unavailable (quality /
    provenance / inputs) — a partial total is never presented as complete.
* Portfolio inputs are pure data — no DB, no persistence, no execution.

## 8. Testing strategy (TDD RED → GREEN)

`tests/test_day18_scenario_engine.py`:
1. **Contract** — valid leg; invalid spot/strike/time/IV/quantity/type/
   direction (pure validation); leg construction rules.
2. **Evaluation** — single/multi price, time, IV scenarios; full
   Price×Time×IV grid; canonical ordering; deterministic repeated runs.
3. **Pricing integration** — `scenario_value` equals the Day-16 engine at
   identical inputs; T=0 intrinsic (ITM/OTM call/put); deep ITM/OTM;
   call/put; near-expiry finite.
4. **P/L** — long/short call & put, quantity scaling, zero quantity, entry-
   price correctness (golden literals computed from the independently
   validated Day-16 prices).
5. **Time analysis** — value decays as T falls; explicit expiry T=0; no
   hidden current time (AST).
6. **IV analysis** — lower/unchanged/higher explicit scenario IVs; value
   monotone in σ.
7. **Portfolio** — multiple legs; mixed call/put; mixed long/short;
   aggregate P/L = Σ legs; aggregate delta/gamma/vega/theta = Σ legs;
   quantity scaling.
8. **Quality/provenance** — preserved into results; INSUFFICIENT ⇒
   UNAVAILABLE; no quality recomputation (AST: no `app.market_data.quality`
   import, no `MarketDataQualityEngine`).
9. **Numerical safety** — finite outputs; NaN/Inf inputs rejected;
   repeated-run determinism.
10. **Security/purity** — module AST checks; credential-free results.

## 9. Scope exclusions

Day 19 intelligence contract, positioning intelligence, dynamic support/
resistance, flow/divergence, regime/trap detection, opportunity/strategy/
risk engines, execution/orders, live trading, DB tables/migrations, Redis/
Kafka/microservices, ML/AI, backtesting, historical persistence, frontend
migration/removal, Gamma Flip/Walls, historical/ΔGEX. **Day 18 = scenario +
portfolio-sensitivity foundation only.**

## 10. Known limitations

* Per-unit-contract semantics (no lot-size multiplier) — documented
  divergence from the frontend strategy layer; consumers scale by lot size
  if they need rupee exposure.
* The engine consumes explicit scenario coordinates — it never derives
  "current" IV/spot internally (that is upstream market data + Day-12/13).
* Model values ≠ execution prices; broker truth remains authoritative for
  actual execution (documented, out of scope).

## 11. Verification commands

```bash
python -m pytest tests/test_day18_scenario_engine.py -q
python -m pytest tests/test_day1[4567]*.py ...   # Days 14–18 group
python -m pytest tests/test_day9*.py ... test_day18*.py   # Days 9–18 group
# security/session + migration/infra groups; legacy quant regression
python -m py_compile app/quant/scenarios.py
git diff --check; # secret scan; AST guards (auto-extend to scenarios.py)
```

## 12. Day 18 gate criteria

PASS only with fresh evidence: scenario contract correct, grid canonical and
deterministic, evaluation reuses Day-15/16 engines, P/L & long/short/
quantity semantics correct, portfolio aggregation correct, model-vs-broker
separation, quality/provenance/versions preserved, independent goldens,
numerical safety, determinism, security/static checks, regressions
classified, CI green, diff scope clean, production untouched. Otherwise
BLOCKED with exact blockers.
