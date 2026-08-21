# Options Dashboard — GEX v1.0 Specification

**Status:** Design approved for implementation planning
**Phase:** 7.1 — Gamma Exposure & Gamma Profile Foundation
**Date:** 2026-08-21
**Scope:** Architecture, mathematical contract, data model, validation, and implementation boundaries. **No production code/UI changes are included in this document.**

---

## 1. Purpose

Gamma Exposure (GEX) is a first-class market-structure analytics domain for the Options Dashboard.

The objective is **not** to claim that publicly available option-chain data reveals the actual positions of dealers/market makers. Open interest does not reveal the beneficial owner or whether a dealer is long or short the option. GEX therefore represents an **explicit positioning/hedging-pressure model under a declared sign convention**.

GEX will initially be used as market context and structural analytics. It must not directly generate a BUY/SELL instruction.

The initial architecture must support later extensions for:

- Gamma Flip / Zero Gamma
- Gamma Walls
- GEX change (Delta GEX / ΔGEX)
- Gamma migration
- Gamma concentration
- GEX percentile/anomaly detection
- GEX regime classification
- Strategy Builder conditions
- Backtesting and historical validation
- Later Vanna, Charm, and related exposure analytics

---

## 2. Architectural decision

GEX is a **market analytics domain**, not a strategy rule and not a frontend-only indicator.

Target flow:

```text
Broker Option Chain
        |
        v
Market Data Normalization
        |
        +--------------------+
        |                    |
        v                    v
 Existing Live Greeks      OI / Contract Data
        |                    |
        +---------+----------+
                  |
                  v
             GEX Engine
                  |
        +---------+----------+
        |         |          |
        v         v          v
    By Strike  By Expiry  Net Profile
        |         |          |
        +---------+----------+
                  |
                  v
        Market Structure Layer
                  |
       +----------+-----------+
       |          |           |
       v          v           v
  GEX Regime  Gamma Levels  GEX History
       |          |           |
       +----------+-----------+
                  |
                  v
        Signal / Strategy Context
                  |
                  v
             Dashboard
```

The GEX engine must not duplicate broker adapters, option-chain acquisition, existing Greek normalization, P&L, margin, capital, or strategy execution logic.

---

## 3. Existing project integration point

The repository already has a canonical Greek analytics layer. It explicitly distinguishes LIVE broker Greeks from MODEL Greeks and defines gamma as exposure change in delta per one underlying point. The GEX engine should consume the normalized/live chain gamma rather than creating a second production Greek implementation.

Reference:

`frontend/lib/calculations/greekAnalytics.js`

The existing architecture also treats missing live Greeks as unavailable rather than silently substituting zero/model values. GEX must preserve the same principle: **missing data is not zero**.

---

## 4. Scope of GEX v1.0

### Included

1. CE gamma exposure per strike.
2. PE gamma exposure per strike.
3. Net gamma exposure per strike.
4. Aggregated GEX for an expiry.
5. Aggregated GEX for the selected chain scope.
6. GEX by strike.
7. GEX by expiry.
8. Explicit methodology/sign convention metadata.
9. Input completeness and availability status.
10. Lot-size/contract-multiplier handling.
11. Deterministic calculation and test fixtures.
12. Validation against independently calculated examples.

### Not included in 7.1

- Gamma Flip calculation.
- Gamma Walls UI.
- Historical persistence.
- ΔGEX time series.
- GEX percentile.
- GEX anomaly detection.
- Strategy Builder conditions.
- BUY/SELL signals.
- Dealer-position claims.
- Vanna/Charm.

These belong to later phases.

---

## 5. Core terminology

### 5.1 Contract gamma

Gamma is the change in option delta for a one-point change in the underlying, under the feed/model convention already used by the platform.

### 5.2 Gross Call GEX

The aggregate exposure attributed to call contracts under the selected GEX sign convention.

### 5.3 Gross Put GEX

The aggregate exposure attributed to put contracts under the selected GEX sign convention.

### 5.4 Net GEX

The signed sum of call and put GEX across the selected chain scope.

### 5.5 GEX profile

The distribution of GEX across strikes, optionally separated by expiry.

### 5.6 GEX regime

A later classification derived from net GEX, gamma concentration, spot location relative to gamma flip, and historical context. It is a context classification, not a trading signal.

---

## 6. Mathematical contract

For an option at strike `K`, let:

- `Gamma_i` = normalized live gamma for option `i`
- `OI_i` = open interest in contracts/lots according to the broker-chain contract
- `Q` = underlying/index contract multiplier (NIFTY lot size in contracts)
- `S` = current underlying spot/index value

The first implementation will use the standard dollar/rupee-style 1%-move exposure form:

```text
Raw GEX_i = Gamma_i × OI_i × Q × S² × 0.01
```

The exact unit interpretation must be documented in the implementation and tests. The system must never mix an OI definition in lots with a multiplier that already includes lot size.

### 6.1 Sign convention

The first implementation uses an explicit model convention:

```text
Call GEX = + Raw GEX
Put GEX  = - Raw GEX
```

This is a **modeling convention**, not an observed dealer-position fact.

The calculation result must carry methodology metadata such as:

```text
positioning_model = "NAIVE_DEALER_CONVENTION"
call_sign = +1
put_sign = -1
```

If a future research-backed flow-inference model is introduced, it must be versioned separately and never silently replace the baseline convention.

---

## 7. Required aggregation

For every `(expiry, strike)`:

```text
call_gex(strike, expiry)
put_gex(strike, expiry)
net_gex(strike, expiry)
```

where:

```text
net_gex = call_gex + put_gex
```

At expiry level:

```text
expiry_net_gex = Σ net_gex(strike, expiry)
```

At selected chain level:

```text
chain_net_gex = Σ expiry_net_gex
```

The system must preserve both gross sides and net values. It must never expose only net GEX because cancellation can hide the underlying call/put concentration.

---

## 8. Chain scope

GEX calculations must have an explicit scope.

Supported scopes should be designed for:

- selected expiry
- nearest expiry
- selected set of expiries
- all available expiries in the fetched chain

The default dashboard scope should be explicitly configured rather than implicitly inferred.

For intraday analysis, nearest-expiry GEX should be available separately from broader-chain GEX because expiry concentration can materially change the profile.

---

## 9. Input contract

The GEX engine should consume normalized option-chain rows containing at least:

```text
underlying
spot
expiry
strike
option_type
open_interest
gamma
lot_size / contract_multiplier
quote_timestamp
```

Optional future inputs:

```text
iv
delta
volume
oi_change
bid
ask
ltp
```

GEX v1.0 must not require fields that are not mathematically needed.

---

## 10. Data-quality rules

### Missing gamma

If gamma is unavailable, that option's GEX contribution is unavailable.

Do not convert missing gamma to zero.

### Missing OI

If OI is unavailable, that option's GEX contribution is unavailable.

### Invalid OI

Negative OI is invalid.

### Invalid gamma

NaN, infinity, or non-numeric gamma is invalid.

### Invalid spot

Zero, negative, NaN, or infinity spot is invalid for GEX calculation.

### Invalid lot size

Zero, negative, NaN, or infinity lot size is invalid.

### Partial chain

The aggregate result must expose an availability status. A partial result must never be presented as if it were a complete chain calculation.

Recommended statuses:

```text
AVAILABLE
PARTIAL
UNAVAILABLE
INVALID
```

---

## 11. Unit safety

The project already has explicit canonical Greek units. GEX must have the same discipline.

The implementation must document:

- gamma unit
- OI unit (lots vs contracts)
- contract multiplier
- spot unit
- GEX output unit
- 1% move factor

A test must catch accidental double application of lot size.

Example failure that must be prevented:

```text
OI already represents contracts
        +
lot_size multiplied again
        = incorrect GEX
```

The adapter-normalized data contract must make this distinction explicit.

---

## 12. Output contract

A GEX snapshot should conceptually expose:

```text
underlying
spot
timestamp
scope
methodology

call_gex
put_gex
net_gex

availability_status
valid_option_count
total_option_count
```

A strike-level row should expose:

```text
expiry
strike
call_gex
put_gex
net_gex
call_oi
put_oi
call_gamma
put_gamma
availability_status
```

An expiry-level row should expose:

```text
expiry
call_gex
put_gex
net_gex
availability_status
```

---

## 13. No false precision

GEX should not be displayed with meaningless decimal precision.

The backend should retain sufficient numerical precision for calculations, while the frontend formatting layer decides presentation units such as:

```text
₹4,850 Cr
₹485.0 Cr
₹4.85 B
```

The display unit must be explicit and consistent.

The raw numeric API value must remain machine-readable and should not be replaced by a formatted string.

---

## 14. Validation strategy

Before production UI integration, GEX must pass four levels of validation.

### Level A — Hand calculation

Create small synthetic chains with 2–5 strikes where every GEX contribution can be calculated manually.

Example fixture:

```text
Spot = 25,000
Lot size = 65

Strike 25,000 CE:
Gamma = 0.002
OI = 1,000

Strike 25,000 PE:
Gamma = 0.003
OI = 500
```

Expected calculations must be recorded as exact test fixtures.

### Level B — Algebraic properties

Tests must verify:

- doubling OI doubles GEX
- doubling gamma doubles GEX
- doubling lot size doubles GEX
- changing spot follows the S² factor
- zero OI gives zero contribution
- call sign is positive under baseline convention
- put sign is negative under baseline convention
- net GEX equals call GEX + put GEX

### Level C — Aggregation properties

Tests must verify:

- strike aggregation equals sum of option rows
- expiry aggregation equals sum of strike rows
- chain aggregation equals sum of expiry rows
- filtered expiry scope does not include excluded expiries
- no duplicate option row silently doubles exposure

### Level D — Live chain validation

Use a real option-chain snapshot from the existing authenticated broker pipeline and independently reproduce the calculation outside the production GEX module.

The two calculations must agree within a documented numerical tolerance.

---

## 15. Independent reference calculation

The project should maintain a small independent reference calculator for tests.

The reference calculator must be deliberately simple and separate from production GEX code so that a duplicated implementation bug does not make tests pass.

Production:

```text
GEX Engine
```

Test reference:

```text
Minimal formula-only reference implementation
```

Both consume the same fixture inputs and must produce the same expected values.

---

## 16. Phase 7.2 — Gamma Flip

After 7.1 is validated, add the zero-gamma/gamma-flip calculation.

Concept:

For a range of hypothetical underlying values `S*`, recalculate chain GEX using the current option-chain inputs and identify the point where:

```text
NetGEX(S*) = 0
```

The implementation must:

1. Define the search range.
2. Define the price step or numerical solver.
3. Handle no-crossing cases.
4. Handle multiple crossings.
5. Report distance from spot.
6. Preserve the calculation methodology/version.

If multiple zero crossings exist, the result must not silently choose an arbitrary one. The API should return the candidate crossings and a deterministic selected candidate according to a documented policy.

---

## 17. Phase 7.2 — Gamma Walls

Identify structural concentrations after the base GEX profile is available.

Initial candidates:

- maximum positive call GEX strike
- maximum absolute negative put GEX strike
- maximum absolute net GEX strike

Later, use local-maximum detection rather than only global maximum so multiple meaningful walls can be displayed.

A wall is an analytical level, not guaranteed support/resistance.

---

## 18. Phase 7.3 — Historical GEX

GEX must eventually be persisted as market snapshots.

Conceptual entities:

### `gex_snapshots`

```text
id
underlying
spot
timestamp
scope
methodology
call_gex
put_gex
net_gex
gamma_flip
gamma_concentration
gex_regime
availability_status
```

### `gex_strike_snapshots`

```text
snapshot_id
expiry
strike
call_oi
put_oi
call_gamma
put_gamma
call_gex
put_gex
net_gex
```

Persistence is intentionally deferred until the calculation contract is validated.

---

## 19. Phase 7.3 — ΔGEX

Once snapshots exist:

```text
Delta GEX = Current GEX - Previous GEX
```

Required windows should eventually include:

- 5 minutes
- 15 minutes
- 30 minutes
- 60 minutes
- session open

These must be computed from timestamps rather than assuming that a snapshot arrives exactly on schedule.

Missing historical observations must not be interpreted as zero change.

---

## 20. Phase 7.4 — Gamma migration

Compare the distribution of GEX across strikes over time.

The system should detect whether dominant gamma concentration is moving:

```text
UP
DOWN
STABLE
UNDEFINED
```

This must be based on measurable changes in the profile, not visual interpretation.

The first algorithm should be deterministic and testable; more sophisticated clustering can be added later.

---

## 21. Phase 7.4 — Gamma concentration

A first concentration metric can be defined as:

```text
Top-N absolute GEX / Total absolute GEX
```

For example:

```text
Top 3 strikes absolute GEX = ₹7,500 Cr
Total absolute GEX = ₹10,000 Cr

Concentration = 75%
```

The implementation must define how ties, unavailable strikes, and zero total absolute GEX are handled.

---

## 22. Phase 7.5 — GEX percentile and anomaly

Absolute GEX is not sufficient for historical comparison because GEX changes naturally with spot, OI, expiry, and volatility.

Later, calculate historical percentile:

```text
Current GEX percentile within comparable historical observations
```

Comparability rules must be defined before implementation. At minimum, the system should consider:

- underlying
- expiry scope
- time-of-day/session
- expiry proximity

Anomaly detection should use historical distributions rather than arbitrary fixed rupee thresholds.

---

## 23. Phase 7.5 — GEX regime

Initial regime labels may be:

```text
STRONG_POSITIVE_GAMMA
POSITIVE_GAMMA
TRANSITION
NEGATIVE_GAMMA
STRONG_NEGATIVE_GAMMA
UNAVAILABLE
```

The thresholds must not be hard-coded without historical validation.

A first version can use configurable thresholds, followed by percentile-based classification after historical data exists.

The regime is **context only**.

It must not directly emit:

```text
BUY
SELL
CALL BUY
PUT BUY
```

---

## 24. Strategy Builder integration — later phase

After GEX is validated historically, Strategy Builder may expose conditions such as:

```text
Net GEX > X
Net GEX < X
GEX regime = POSITIVE_GAMMA
GEX regime = NEGATIVE_GAMMA
Spot > Gamma Flip
Spot < Gamma Flip
Distance from Gamma Flip < X%
Delta GEX(15m) > X
Delta GEX(15m) < X
Gamma concentration > X%
GEX percentile > X
GEX percentile < X
```

These should be generic market conditions, not hard-coded strategy rules.

---

## 25. Signal-engine integration — later phase

GEX should modify the **context/confidence** of existing signals rather than replace them.

Example conceptual state:

```text
Price structure
+ OI structure
+ Delta/Gamma divergence
+ IV/VIX
+ GEX regime
+ Gamma levels
= Market context
```

The probability engine must not assign GEX a fixed weight until historical testing demonstrates predictive or conditioning value.

---

## 26. Backtesting requirements

Before GEX contributes to trading probabilities, the system must test whether it improves measurable outcomes.

Required questions:

1. Does positive/negative GEX predict realized intraday volatility?
2. Does crossing the gamma flip change continuation probability?
3. Do gamma walls behave as statistically meaningful reaction zones?
4. Does ΔGEX add information beyond OI change?
5. Does GEX improve existing divergence signals?
6. Does GEX improve breakout/failure classification?
7. Does GEX improve strategy expectancy after costs/slippage assumptions?

No claimed accuracy percentage should be attached to GEX before out-of-sample testing.

---

## 27. Data-source constraint

The project has a standing requirement to prioritize genuinely free/lifetime-free data and avoid paid market-data dependencies.

GEX must therefore be calculated from option-chain data already available through the user's authenticated broker connection/pipeline rather than requiring a separate paid GEX vendor.

The project must also respect the broker/data provider's licensing and redistribution restrictions. The platform should calculate derived analytics from authorized user data rather than redistributing raw broker data to other users.

---

## 28. Security and tenancy

GEX calculation should remain market-data analytics, but any user-specific authenticated chain access must preserve existing user isolation.

No API secret belongs in frontend code or GEX records.

The GEX domain must not introduce broker-specific credentials into analytics objects.

---

## 29. Performance architecture

GEX is market-level information and should not be recalculated independently for every user when the underlying chain snapshot is identical.

Preferred future architecture:

```text
Normalized NIFTY Chain Snapshot
            |
            v
      Shared GEX Engine
            |
            v
      Cached GEX Snapshot
            |
      +-----+-----+
      |     |     |
    User1 User2 UserN
```

The initial implementation may remain request-scoped while the calculation contract is validated. Shared caching/persistence belongs to the historical/live scaling phase.

---

## 30. Error semantics

The GEX API/domain must distinguish:

```text
NO_CHAIN_DATA
PARTIAL_CHAIN_DATA
INVALID_INPUT
INVALID_GAMMA
INVALID_OI
INVALID_SPOT
INVALID_LOT_SIZE
UNSUPPORTED_SCOPE
CALCULATION_UNAVAILABLE
```

Do not convert errors to a numerical zero.

---

## 31. Observability

Every GEX result should be traceable to:

```text
underlying
chain timestamp
spot timestamp
methodology version
scope
option count
valid option count
```

For debugging, a calculation should be reproducible from the normalized input snapshot.

---

## 32. Methodology versioning

The GEX calculation must carry a methodology version, initially:

```text
GEX_STANDARD_V1
```

Future methodologies must receive new versions.

Example:

```text
GEX_STANDARD_V1
GEX_FLOW_INFERRED_V2
```

Historical records must retain the methodology version used to produce them.

---

## 33. Important interpretation rules

The UI/documentation must communicate the following:

1. GEX is an inferred exposure/hedging-pressure model.
2. Open interest does not reveal actual dealer ownership.
3. Positive/negative GEX is dependent on the selected sign convention.
4. Gamma levels are structural analytics, not guaranteed support/resistance.
5. Gamma flip is a regime boundary estimate, not a guaranteed reversal level.
6. GEX should be interpreted with price, OI, IV/VIX, and other market context.
7. GEX must not be advertised as a standalone guaranteed trading signal.

---

## 34. Implementation order

### Step 1 — Specification and fixtures

Create the calculation contract and hand-calculated fixtures.

### Step 2 — Backend/domain implementation

Implement pure GEX calculation functions without database or UI changes.

### Step 3 — Backend tests

Validate all mathematical, aggregation, data-quality, and unit-safety cases.

### Step 4 — Existing chain integration

Connect the GEX domain to the already-normalized option-chain data.

### Step 5 — API contract

Expose a read-only analytics endpoint after calculation correctness is established.

### Step 6 — Frontend display

Add a minimal GEX profile panel only after API tests pass.

### Step 7 — Historical snapshots

Add persistence only after live calculation is verified.

### Step 8 — Advanced analytics

Gamma Flip → Walls → ΔGEX → Migration → Concentration → Percentile → Regime.

### Step 9 — Strategy Builder

Expose GEX as configurable conditions only after historical validation.

---

## 35. Definition of Done — Phase 7.1

Phase 7.1 is complete only when all are true:

- [ ] Mathematical formula is implemented exactly as specified.
- [ ] Call/put sign convention is explicit and versioned.
- [ ] Lot-size handling is verified.
- [ ] OI units are verified.
- [ ] Existing normalized live gamma is reused.
- [ ] Missing values remain unavailable, not zero.
- [ ] Strike-level GEX is available.
- [ ] Expiry-level GEX is available.
- [ ] Chain-level GEX is available.
- [ ] Availability status is explicit.
- [ ] Hand-calculated fixtures pass.
- [ ] Algebraic property tests pass.
- [ ] Aggregation tests pass.
- [ ] Duplicate-row protection is tested.
- [ ] Independent reference calculation agrees.
- [ ] Real authenticated chain snapshot has been independently reproduced.
- [ ] No paid GEX data dependency is introduced.
- [ ] No raw broker secrets enter analytics.
- [ ] No trading signal is generated by GEX.
- [ ] Documentation clearly distinguishes inferred GEX from actual dealer positions.

---

## 36. Definition of Done — Advanced GEX roadmap

### 7.2

- [ ] Gamma Flip
- [ ] Multiple-crossing handling
- [ ] Gamma Walls
- [ ] Spot distance to flip

### 7.3

- [ ] Historical snapshots
- [ ] ΔGEX
- [ ] Time-window comparison

### 7.4

- [ ] Gamma migration
- [ ] Gamma concentration

### 7.5

- [ ] GEX percentile
- [ ] GEX anomaly
- [ ] GEX regime

### 7.6+

- [ ] Strategy Builder conditions
- [ ] Backtesting integration
- [ ] Signal-context integration
- [ ] Research/validation dashboards

---

## 37. Research basis

The design is consistent with widely used public GEX methodology: gamma exposure is commonly derived from option gamma, open interest, contract multiplier, and spot-price scaling, while gamma profiles, zero-gamma/flip levels, and strike-level exposure are used to describe potential hedging-pressure regimes.

Important methodological caveat: public OI does not directly reveal dealer inventory. Therefore this project deliberately treats the call-positive/put-negative convention as a model assumption rather than as ground truth.

Public references consulted during design:

- SpotGamma — GEX explanation and calculation concepts.
- LuxAlgo — gamma exposure and zero-gamma concepts.
- GEXBoard — zero-gamma/gamma-flip explanation.

These references inform the conceptual design; the project's production implementation remains independently specified and must be validated against the project's own normalized broker-chain data.

---

## 38. Final architectural principle

> **GEX is a market-structure context engine, not a magic BUY/SELL indicator.**

The platform should first calculate it correctly, preserve the assumptions, collect history, test its statistical usefulness, and only then allow strategies to consume it.

That sequence is mandatory for the integrity of the Options Dashboard.
