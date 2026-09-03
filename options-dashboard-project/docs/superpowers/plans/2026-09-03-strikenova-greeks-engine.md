# Day 15 — Deterministic Greeks Engine

**Status:** IN PROGRESS (authorized 2026-09-03)
**Baseline:** `be272fb` (Day 14 final — Quantitative Engine Boundary Gate PASS)
**Branch:** `feat/strikenova-day1-security`

## Objective

Implement the first real quantitative engine on the Day-14 boundary: a
**deterministic, broker-neutral European Black-Scholes-Merton Greeks engine**
(delta / gamma / theta / vega / rho for call and put) registered through
`QuantitativeEngineBoundary`, returning `QuantResult` envelopes.

## Current-state assessment

- Day 14 `app/quant` boundary exists (contracts + registry routing) — no
  engines yet.  Engine protocol: `calculate(OptionMarketData, CalculationContext) -> QuantResult`.
- **Reusable mathematics:** `app/services/historical_greeks.py` (Phase 7.19B)
  contains a sound, deterministic BS-Merton implementation (`bs_price`,
  `bs_greeks`: delta/gamma/vega/theta; NO rho).  Conventions: vega per 1.00
  vol fraction, theta annualized per year, decimal volatility, continuous
  dividend yield `q`, T in year fractions.  It is **DB-coupled legacy** —
  Day 15 ports its math into a pure engine; the legacy module is NOT modified.
- **Frontend:** `frontend/lib/calculations/greeks.js` only scales chain Greek
  data (direction × qty × lot × multiplier); it does NOT implement BS math, so
  there is no independent frontend formula to diff.  Not modified on Day 15.
- Day 9 `GreeksObservation(source="BROKER")` keeps broker vs model separation;
  model outputs identify themselves via calculation/model ids + versions.
- Day 14 `time_to_expiry()` (ACT/365, UTC-midnight expiry) is the canonical T
  source — the engine consumes it; it never computes time itself.

## Mathematical model

European Black-Scholes-Merton with continuous dividend yield `q`
(Black-76-style forward formulation identical to the legacy `bs_greeks`):

```
d1 = (ln(S/K) + (r − q + σ²/2)·T) / (σ·√T)     computed as (ln S − ln K + …)/(σ·√T)
d2 = d1 − σ·√T
φ  = N'(d1);  N = standard normal CDF (via math.erf);  dfQ = e^(−qT); dfR = e^(−rT)
Call:   delta = dfQ·N(d1)
Put:    delta = dfQ·(N(d1) − 1)
Both:   gamma  = dfQ·φ / (S·σ·√T)
        vega   = S·dfQ·φ·√T                     (per 1.00 vol fraction)
Theta (per year, annualized):
  call: −(S·dfQ·φ·σ)/(2√T) − r·K·dfR·N(d2) + q·S·dfQ·N(d1)
  put:  −(S·dfQ·φ·σ)/(2√T) + r·K·dfR·N(−d2) − q·S·dfQ·N(−d1)
Rho (per 1.00 continuously-compounded rate):
  call: K·T·dfR·N(d2)      put: −K·T·dfR·N(−d2)
```

## Input / output contracts & units

- Input: Day-14 `OptionMarketData` — `S = spot`, `K = instrument.strike`,
  side = `instrument.option_type` (Side.CALL/PUT), `σ = implied_volatility`
  (required for model Greeks; missing ⇒ UNAVAILABLE/MISSING_REQUIRED_INPUT),
  `T = time_to_expiry(instrument.expiry, context.reference_timestamp)`
  (ACT/365 — the Day-14 documented convention), `r = context.risk_free_rate`,
  `q = context.dividend_yield or 0.0` (None = no dividend assumption = 0).
- Output: `QuantResult.values` = `{delta, gamma, theta, vega, rho}` with
  documented units:
  - delta — dimensionless
  - gamma — per unit of underlying price
  - vega — per 1.00 volatility fraction (σ=0.18 ⇒ 18%)
  - theta — per year (annualized)
  - rho — per 1.00 rate unit (continuously compounded)
  These match the Day-9 `GreeksObservation` doc conventions (theta annualized
  per unit; vega per 1.00 vol move) and the legacy implementation.
- Model identity: `model = BLACK_SCHOLES_MERTON_EUROPEAN`,
  `calculation_id = greeks.black_scholes_european`,
  `model_version = 1.0.0`, `calculation_version = 1.0.0`.

## Conventions / degenerate cases (documented + tested)

- **T == 0 (terminal):** SUCCESS with the documented terminal convention
  (mirrors the legacy repo convention): delta = step value by S vs K
  (equality ⇒ 0), gamma/vega/theta/rho = 0.  No normal-distribution formula at
  T=0; no fabricated numbers.
- **σ == 0, T > 0 (zero-volatility degenerate):** SUCCESS with the documented
  deterministic convention (mirrors legacy): delta by forward comparison
  (`fwd = S·e^((r−q)T)`), gamma/vega/theta/rho = 0.
- **Invalid inputs** (S ≤ 0, K ≤ 0, T < 0, σ < 0, non-finite r/q/side
  invalid): structured `INVALID_INPUT` result (never NaN/∞, never guessed).
- **Non-finite computed output** with otherwise valid inputs: `INVALID_INPUT`
  result (defensive; not expected in tested ranges).

## Validation rules

Pure function validates and raises `ValueError` with safe static messages;
the engine converts those into `QuantResult(status=INVALID_INPUT, …)`.  The
boundary (Day 14) still runs provenance/quality guards first.

## Provenance / quality / versioning

- Result carries input `Provenance` (Day 9), `input_quality` (Day 12 state —
  preserved, never recomputed), `reference_timestamp`, `model_version`,
  `calculation_version`, `contract_version`.
- Boundary guards still apply: missing provenance / INSUFFICIENT quality ⇒
  UNAVAILABLE before the engine runs.
- Broker Greeks stay `GreeksObservation(source="BROKER")` upstream; model
  Greeks from this engine are separate (`calculation_id` + model version) and
  never overwrite broker values.

## Existing implementation reuse decision

REUSE the verified BS-Merton math/conventions from `historical_greeks.py`
(formula + units + degenerate branches) as a **pure, DB-free, broker-free
engine** in `app/quant/greeks.py`.  Legacy module untouched.  Legacy
`bs_price`/`bs_greeks` used in TESTS as the independent reference for
finite-difference and cross-check validation.  Frontend untouched.

## Testing strategy (RED first)

- Core mathematics golden tests: 11 fixtures (ATM/ITM/OTM call+put,
  7-day short, 2-year long, dividend q=2%, high vol 60%, low vol 5%) with
  independently computed closed-form expected values (Hull-reference ATM set
  cross-checked), tolerance rel 1e-9.
- Call/put relationships: `delta_call − delta_put = e^(−qT)` (several q/T),
  gamma parity, vega parity.
- Finite-difference validation against the legacy trusted `bs_price`
  (central differences for delta/gamma/vega/rho/theta) — validation only.
- Input validation; expiry (T=0 terminal, near-expiry); determinism; quality
  propagation incl. INSUFFICIENT gate; provenance/versioning; boundary
  registration/routing; security; broker-neutrality + no-hidden-clock AST
  rules (extend automatically to the new module via the Day-14 scan).
- Edge: σ=0, σ tiny, T tiny, deep ITM/OTM → finite deterministic outputs.

## Scope exclusions

No IV solver/pricing engine (Day 16), no GEX/gamma walls/flip (Day 17), no
scenario/portfolio (Day 18), no intelligence, no execution/backtest/ML/AI, no
Redis/Kafka/microservices, no DB changes, no legacy-module/frontend
modification, no deployment/cutover/live trading.

## Known limitations

- Frontend has no independent BS implementation to golden-diff against (its
  greeks.js scales chain data only); legacy backend `bs_greeks` is the
  established in-repo reference and is used for cross-validation.
- Terminal (T=0) and zero-volatility conventions are documented choices, not
  unique mathematical limits at exact ATM boundaries.
- Rho/theta unit conventions (per 1.00 rate / per year) are explicit; a
  consumer wanting per-1% or per-day values must scale.

## Verification commands

- `python -m pytest tests/test_day15_greeks_engine.py -q`
- Focused Days 9–15 group; quant regression (live/historical GEX, greeks,
  IV); security/session; Days 4–8 infra groups (bounded)
- `python -m py_compile` changed files; `git diff --check`; secret scan
- CI: Status Gate + PostgreSQL compatibility (record run IDs)

## Day 15 gate

PASS only with: mathematically correct implementation (goldens + parity +
finite-difference), determinism proven, call/put support, explicit edge/unit
handling, quality propagation, provenance preservation, explicit
model/calculation versions, boundary integration, broker neutrality, security,
focused + classified regression, CI green, clean scope and working tree.
Gate text: **PASS — Greeks Engine Gate satisfied** or **BLOCKED — Day 15 Gate
Failed**.
