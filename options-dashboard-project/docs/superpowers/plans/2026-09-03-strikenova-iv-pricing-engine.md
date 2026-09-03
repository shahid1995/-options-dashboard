# StrikeNova — Day 16 Implementation Plan: IV + Pricing Engine

**Status:** Approved for execution (authorized by the user).
**Baseline:** Day 15 PASS — `79d4551`.
**Branch:** `feat/strikenova-day1-security`.
**Gate:** Do NOT begin Day 17 (GEX) — this plan authorizes Pricing + IV only.

---

## 1. Objective

Implement the shared, broker-neutral quantitative capabilities on top of the
Day-14 quantitative boundary and the Day-15 Greeks engine:

1. **European Black-Scholes-Merton option pricing** — deterministic, pure,
   DB-free, broker-free.
2. **Implied Volatility solver** — deterministic bounded root solver
   (Brent) with an explicit failure taxonomy.

The resulting engine layer is registered through the Day-14
`QuantitativeEngineBoundary` and returns results through the `QuantResult`
envelope, exactly like the Day-15 Greeks engine.

```text
Canonical Market Data → Data Quality → Quantitative Boundary
    ├── Greeks Engine            (Day 15 — app/quant/greeks.py)
    ├── Pricing Engine           (Day 16 — app/quant/pricing.py)  ← NEW
    └── Implied Volatility       (Day 16 — app/quant/iv.py)       ← NEW
```

## 2. Current-state findings

* **No `app/quant` pricing/IV engine existed.** Day 14 created only the
  boundary contracts (`contracts.py`, `boundary.py`) and Day 15 added the
  Greeks engine (`greeks.py`).
* **Legacy math exists and is verified:** `app/services/historical_greeks.py`
  (`Phase 7.19B`) contains a deterministic BSM `bs_price` + bisection IV
  solver with explicit bounds (`IV_MIN=0.001`, `IV_MAX=10.0`), intrinsic and
  theoretical-price gates, decimal IV, and a structured failure taxonomy
  (`BELOW_INTRINSIC`, `ABOVE_THEORETICAL_MAX`, `NO_BRACKET`,
  `CONVERGENCE_FAILED`, `EXPIRED`, …). The module is DB-coupled, broker-side
  (`"CE"/"PE"` strings), has no `q` in its IV solver, and is deliberately NOT
  modified on Day 16.
* **Frontend `frontend/lib/calculations/pricing.js`** contains its own
  `bsCall/bsPut/bsGreeks/timeToExpiry` used as a presentation/scenario
  compatibility layer. Not deleted or refactored on Day 16; documented as a
  migration candidate in the tracker.
* **Dependencies:** backend `requirements`/lock contain **zero third-party
  numerical libraries** (no SciPy, NumPy, py_vollib — verified by search).
  All existing math is stdlib (`math.erf`). A pure-Python deterministic
  Brent solver is therefore the correct choice — no new dependency.
* The Day-14 boundary AST tests auto-scan **every** `app/quant/*.py` for
  wall-clock calls, forbidden I/O imports (`os/sys/random/sqlalchemy/
  requests/httpx/urllib/fastapi`) and Day-12 quality re-scoring — new
  modules inherit those guards automatically.

## 3. Reuse decisions

| Source | Decision |
|---|---|
| `historical_greeks.bs_price` / zero-vol / expiry conventions | **Reuse the sound math** — re-implemented pure in `app/quant/pricing.py` with the same BSM-Merton formulation as Day-15 greeks. Legacy module untouched. |
| `historical_greeks` IV failure taxonomy | **Reuse the taxonomy semantics** (below-intrinsic / above-max / no-bracket / convergence-failed / expired) mapped into the Day-14 boundary issue-code architecture. |
| Day-15 `greeks.py` model identity | **Reuse** `BLACK_SCHOLES_MERTON_EUROPEAN` (imported from `app.quant.greeks`) so pricing/IV/Greeks share ONE canonical model family name. No inconsistent `BLACK_SCHOLES_EUROPEAN` label. |
| Day-15 norm helpers | pricing/iv define their own private `_norm_cdf`/`_norm_pdf` (identical `math.erf` formulas). No circular dependency is created; cross-engine consistency is proven by finite-difference tests against the Day-15 Greeks engine. |
| SciPy / py_vollib | **Not added.** Pure stdlib Brent implementation, consistent with the repo's existing dependency policy. |

## 4. Pricing model (documented + tested)

European Black-Scholes-Merton with continuous dividend yield `q` and
continuously compounded rate `r` (identical convention family to Day 15):

```text
d1 = (ln(S/K) + (r − q + σ²/2)·T) / (σ·√T)
d2 = d1 − σ·√T
Call = S·e^(−qT)·N(d1) − K·e^(−rT)·N(d2)
Put  = K·e^(−rT)·N(−d2) − S·e^(−qT)·N(−d1)
```

Degenerate conventions (documented + tested):

* `T == 0` → intrinsic value: `max(S−K,0)` call / `max(K−S,0)` put. The
  normal-distribution formula is NEVER evaluated at `T == 0`.
* `σ == 0`, `T > 0` → deterministic forward-value convention (the exact
  σ→0 limit of the model):
  `Call = max(S·e^(−qT) − K·e^(−rT), 0)`, `Put = max(K·e^(−rT) − S·e^(−qT), 0)`.
* Invalid inputs (`S ≤ 0`, `K ≤ 0`, `T < 0`, `σ < 0`, non-finite, bad side)
  raise `ValueError` from the pure function; the engine converts to a
  structured `INVALID_INPUT` result. Never NaN/Infinity.

**Units:** price returned per-unit (not scaled by lot size). Same as the
entire existing platform convention.

## 5. IV solver

**Algorithm:** deterministic bounded **Brent** root solve (pure stdlib) on
`g(σ) = model_price(σ) − market_price`, with the documented bracket
`[volatility_min, volatility_max] = [0.0, 10.0]`. Because the price is
strictly monotone increasing in σ for `T > 0` (vega > 0) and the σ=0
degenerate price equals the lower bound exactly, a sign change always exists
inside the bracket whenever the market price lies strictly between the
theoretical lower bound and the σ=10 model price. Bisection fallback inside
the Brent loop keeps convergence robust.

**Theoretical bounds (per §14 of the authorization):**

```text
Call lower = max(S·e^(−qT) − K·e^(−rT), 0)   Call upper = S·e^(−qT)
Put  lower = max(K·e^(−rT) − S·e^(−qT), 0)   Put  upper = K·e^(−rT)
```

A documented relative bound tolerance (`1e-8 × max(1, upper)`) forgives
floating-point noise without accepting genuinely infeasible quotes.

**Convergence policy (explicit):**

* `price_tolerance` — residual `|g(σ)| ≤ 1e-9 × max(1, market_price)`.
* `sigma_tolerance` — bracket width `≤ 1e-10 × max(1, σ)`.
* `max_iterations = 100`.
* Volatility returned as a **decimal fraction** (0.1824 = 18.24%) — never a
  percentage-point number. Display layers convert later.

**IV failure taxonomy → boundary semantics:**

| Solver outcome | Boundary status | Boundary issue code |
|---|---|---|
| Success | SUCCESS | — |
| Expired (`T == 0`) | UNAVAILABLE | `EXPIRED` |
| Market < lower bound − tol | INVALID_INPUT | `BELOW_LOWER_BOUND` |
| Market at lower bound (± tol) | SUCCESS, σ = 0.0 | — (exact zero-vol inverse) |
| Market > theoretical max + tol | INVALID_INPUT | `ABOVE_THEORETICAL_MAX` |
| No sign change in [0, 10] (price in (price(10), upper]) | FAILED | `NO_BRACKET` |
| Solver exhausts iterations | FAILED | `CONVERGENCE_FAILED` |

The taxonomy is added to the Day-14 `CalculationIssueCode` enum
(additive — no existing member changes). Invalid scalar inputs (e.g. a
non-positive market price) raise `ValueError` in the pure function and
become `INVALID_INPUT` / `INVALID_INPUT_VALUE` at the engine boundary.

## 6. Input / output contracts

* **Inputs:** the existing Day-14 `OptionMarketData` + `CalculationContext`
  (unchanged semantics). Pricing consumes `instrument.strike/expiry/
  option_type`, `spot`, `implied_volatility` (required), context `r`, `q`,
  `reference_timestamp`. IV consumes the same plus `market_price`
  (required, strictly positive). Time-to-expiry always via Day-14 ACT/365
  `time_to_expiry()` — the engines never read the clock.
* **Outputs:** `QuantResult` with `values = {"price": …}` (pricing) or
  `values = {"implied_volatility": …}` (IV), plus propagated
  quality/provenance/versions — identical envelope shape to Day 15.

## 7. Versioning

* Model family: `BLACK_SCHOLES_MERTON_EUROPEAN` (imported from Day 15).
* Pricing: `calculation_id = "pricing.black_scholes_european"`,
  `model_version = "1.0.0"`, `calculation_version = "1.0.0"`.
* IV: `calculation_id = "implied_volatility.black_scholes_european"`,
  `model_version = "1.0.0"`, `calculation_version = "1.0.0"`.

## 8. Provenance / quality

* Identical Day-14/15 rules: provenance and quality are consumed from
  `OptionMarketData`, never recomputed; INSUFFICIENT quality and missing
  provenance are blocked by the boundary BEFORE either engine runs.
* Model IV/Greeks remain distinct from Day-9 `GreeksObservation(
  source="BROKER")` — never overwritten.

## 9. Testing strategy (TDD RED → GREEN)

`tests/test_day16_iv_pricing_engine.py`:

1. **Golden prices** — independently computed closed-form reference values
   (12 dp), cross-checked against two independent implementations (a scratch
   direct evaluation and the verified legacy `bs_price` — agreement
   `< 1e-12`) plus the classic textbook ATM anchor
   (S=K=100, r=5%, σ=20%, T=1 → call ≈ 10.4506).
2. **Expiry / near-expiry / zero-volatility** degenerate conventions.
3. **Invalid inputs** (pure fn + engine `INVALID_INPUT`).
4. **Put-call parity** across a grid of S/K/T/r/q/σ.
5. **Monotonicity** — price(σ) non-decreasing; call(S) non-decreasing;
   put(S) non-increasing.
6. **Greeks consistency** — finite-difference ∂Price/∂S, ∂Price/∂σ,
   ∂Price/∂r, −∂Price/∂T and ∂²Price/∂S² against the Day-15 engine outputs.
7. **IV round trips** — known σ → price → solve → recovered σ ≈ original σ
   across ATM/ITM/OTM call+put, short/long expiry, q/r ≠ 0, low/high vol.
8. **Bounds & taxonomy** — below-lower, at-lower (σ=0), above-max,
   expired, missing market price, no-bracket band, forced convergence failure.
9. **Decimal-fraction IV convention** (0.18 returned, never 18.x).
10. **Determinism** — identical results for identical inputs.
11. **Quality propagation / provenance / versioning** — mirror Day 15.
12. **Boundary routing + broker neutrality.**
13. **Security/static** — module-level AST checks for the two new modules.

## 10. Verification commands

```bash
# focused (RED then GREEN)
python -m pytest tests/test_day16_iv_pricing_engine.py -q
# Greeks + boundary re-run
python -m pytest tests/test_day15_greeks_engine.py tests/test_day14_quant_boundary.py -q
# quant + market-data groups (Days 9–15)
# security/session + infra/migration groups (Days 3–8, 12/13 documented pre-existing failures)
# static
python -m py_compile app/quant/pricing.py app/quant/iv.py app/quant/contracts.py
git diff --check
# secret scan (repository-established procedure)
```

Every regression failure is classified; pre-existing claims are reproduced
against the clean Day-15 baseline `79d4551` before being accepted.

## 11. Scope exclusions (Day 16 MUST NOT implement)

GEX / gamma walls / gamma flip / scenario engine / portfolio sensitivities /
positioning / flow intelligence / regime / opportunity / strategy / risk /
execution / historical ingestion / backtesting / ML / AI / Redis / Kafka /
microservices / DB migrations / frontend redesign / deployment / PostgreSQL
cutover / live trading. **Day 16 = Pricing + IV only.**

## 12. Known limitations

* The Brent solver domain caps volatility at 10.0 (1000%); a market price
  between the σ=10 model price and the theoretical maximum is honestly
  reported as `NO_BRACKET` (documented deterministic outcome), not solved
  with a fabricated σ > 10.
* The zero-volatility boundary returns σ = 0.0 exactly for prices within the
  documented bound tolerance of the forward intrinsic value.
* Expiry vs post-expiry are indistinguishable through the Day-14
  `time_to_expiry` floor at 0 — both are EXPIRED for IV, intrinsic for
  pricing.

## 13. Day 16 gate criteria

PASS only if: pricing mathematically validated (goldens + textbook anchor),
IV solver validated (round trips + parity + monotonicity), BSM-Merton
conventions match Day 15, put-call parity passes, bounds explicit + tested,
convergence explicit, invalid inputs safe, no NaN/Infinity in valid cases,
quality propagated, provenance preserved, versions explicit, boundary
integration works, broker neutrality proven, determinism proven, security
checks pass, focused tests pass, regressions classified, CI passes, scope
clean, working tree clean except pre-existing artifacts. Otherwise BLOCKED
with exact blockers.
