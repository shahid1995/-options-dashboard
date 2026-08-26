# StrikeNova Overnight Gap Intelligence Research Blueprint

**Status:** Research specification — Phase 1
**Date:** 2026-08-24
**Scope:** NIFTY 50 next-session opening-gap prediction
**Purpose:** Benchmark a publicly inferable Vibhore Gupta POS-style approach against a transparent StrikeNova SOS model, then validate out-of-sample before any production use.

---

## 1. Research objective

Determine whether end-of-session NIFTY derivatives information can provide a statistically useful prediction of the next trading session's opening gap, and whether a StrikeNova model materially improves on:

1. simple historical baselines;
2. a publicly inferable POS-style benchmark inspired by Vibhore Gupta's publicly described Delta/Vega/positioning concepts; and
3. the market's own implied-move information.

**Important:** This document does not claim to reproduce Vibhore Gupta's proprietary POS formula. The benchmark is explicitly a public-information approximation for research comparison only.

Research sequence:

> Research → Historical data → Feature engineering → Backtest → Walk-forward validation → Out-of-sample test → Production consideration

No production trading signal should be released before the out-of-sample stage is complete.

---

## 2. Prediction target

For each trading session `T`, capture the research snapshot at the defined end-of-session cutoff. For the next trading session `T+1`, record:

`gap_points = NIFTY_open(T+1) - NIFTY_close(T)`

`gap_pct = gap_points / NIFTY_close(T)`

The research dataset must preserve the exact timestamps used for both the predictor snapshot and the next-session open.

### Direction classes

Do not hard-code a single arbitrary gap threshold. Test multiple definitions:

- raw points;
- percentage of prior close;
- volatility-normalized gap;
- a small neutral band around zero.

Primary classification:

- GAP_UP
- FLAT / NO_MEANINGFUL_GAP
- GAP_DOWN

The threshold selected for any production version must be justified by historical distribution and trading relevance.

### Magnitude targets

Also predict:

- signed gap points;
- absolute gap points;
- signed gap percentage;
- probability of exceeding selected positive/negative gap thresholds.

---

## 3. Benchmark hierarchy

### Model A — Simple baselines

At minimum:

- previous-day direction;
- previous-day gap direction;
- NIFTY futures direction/basis;
- ATM straddle-implied movement;
- historical unconditional gap distribution.

A complex model is not considered useful unless it beats relevant simple baselines out of sample.

### Model B — POS-style benchmark

Use only publicly inferable concepts:

- CE/PE Delta;
- CE/PE Vega;
- CE/PE OI and change in OI;
- option-price movement;
- normalized CE/PE sentiment;
- ATM/near-ATM weighting;
- end-of-session positional state.

This is a benchmark, not a claim about the proprietary POS implementation.

### Model C — StrikeNova SOS

Extend the benchmark with:

- Gamma;
- GEX;
- IV and IV change;
- IV skew and skew change;
- NIFTY futures basis;
- futures OI and volume;
- option premium/volume pressure;
- bid/ask pressure where legally and technically available;
- India VIX;
- gamma regime;
- strike concentration;
- spot distance from important gamma levels;
- cross-component confluence and dispersion.

---

## 4. Raw data schema

The research layer should retain strike-level observations before aggregation.

### Underlying

- timestamp
- trading_date
- NIFTY spot LTP
- NIFTY open/high/low/close where applicable
- NIFTY futures LTP
- futures OI
- futures volume
- futures basis
- India VIX

### Option strike — CE and PE

- expiry
- strike
- option_type
- LTP
- bid
- ask
- bid_quantity
- ask_quantity
- volume
- OI
- change_in_OI
- IV
- Delta
- Gamma
- Vega
- Theta

The raw snapshot should be immutable once captured so that later feature changes do not alter historical source observations.

---

## 5. Strike universe

Do not reduce the raw data to a fixed number of strikes during ingestion.

Derive analytical windows around ATM after ingestion, including tests for:

- ATM;
- ATM ± 1, ±2, ±3;
- wider near-ATM ranges;
- OTM-only ranges;
- full available ATM/OTM universe subject to data quality.

The research should determine empirically where predictive information is concentrated.

All strike weighting must be tested rather than assumed.

---

## 6. Feature engineering

### 6.1 Delta pressure

Calculate:

- CE Delta;
- absolute PE Delta;
- CE/PE Delta difference;
- intraday/end-of-session Delta change;
- Delta pressure;
- Delta concentration by strike distance.

Use PE sign normalization consistently. Do not mix raw negative PE Delta with absolute PE Delta without an explicit convention.

### 6.2 Vega pressure

Calculate:

- CE Vega;
- PE Vega;
- Vega difference;
- Vega change;
- normalized Vega pressure;
- CE/PE Vega divergence.

Raw Vega must not be allowed to dominate merely because of scale. Use normalized and strike-aware representations.

### 6.3 OI positioning

Calculate:

- CE OI;
- PE OI;
- CE/PE OI change;
- PCR;
- OI concentration;
- OI migration;
- price/OI buildup classification where valid.

Possible classifications include long buildup, short buildup, long unwinding and short covering, but each classification must be tested for predictive value rather than assumed directional truth.

### 6.4 IV and skew

Calculate:

- ATM IV;
- CE IV;
- PE IV;
- IV change;
- put-call IV skew;
- skew change;
- skew normalized by historical regime.

### 6.5 Gamma / GEX

Calculate:

- CE Gamma;
- PE Gamma;
- Gamma change;
- Call GEX;
- Put GEX;
- total GEX;
- GEX change;
- gamma concentration;
- gamma flip level where the methodology permits;
- spot-to-gamma-flip distance;
- positive/negative gamma regime.

GEX should initially be treated primarily as a market-regime/volatility variable, not automatically as a bullish/bearish signal.

### 6.6 Futures

Calculate:

- futures basis;
- basis change;
- futures price change;
- futures OI change;
- price/OI classification;
- futures volume pressure.

### 6.7 Option flow

Where source data supports it, calculate:

- CE premium pressure;
- PE premium pressure;
- volume-weighted premium pressure;
- bid/ask pressure;
- CE/PE flow difference;
- net option flow.

Do not infer trade direction from LTP alone when bid/ask information is available.

### 6.8 India VIX

Calculate:

- current VIX;
- VIX change;
- VIX percentile/regime;
- VIX relationship to option IV;
- VIX shock flags.

---

## 7. Normalization

Raw features have incompatible scales. Initial research should use rolling historical normalization, such as:

`z = (x - rolling_mean) / rolling_std`

with robust alternatives tested where distributions are heavy-tailed.

Extreme observations should be winsorized or otherwise bounded only after documenting the transformation.

No normalization may use future observations relative to the prediction timestamp.

---

## 8. POS-style benchmark score

Create a transparent benchmark score in `[-100, +100]`.

Conceptually:

`POS_delta = normalized directional Delta pressure`

`POS_vega = normalized CE/PE Vega pressure`

`POS_oi = normalized positioning pressure`

`POS_price = normalized option-price pressure`

Then:

`POS_style = weighted_sum(POS_delta, POS_vega, POS_oi, POS_price)`

Initial weights must be documented and fixed for the first benchmark. Later weight optimization must occur only inside the training period.

The benchmark must remain explainable at every historical observation.

---

## 9. StrikeNova SOS score

Each major component is converted to a bounded directional score in `[-1, +1]`:

- Delta;
- Vega;
- OI;
- IV/skew;
- futures;
- option flow;
- GEX regime contribution;
- VIX/regime contribution;
- price structure.

Then calculate:

`SOS_direction = weighted_sum(component_scores)`

and independently:

`SOS_agreement = 1 - normalized_dispersion(component_scores)`

The model must preserve both values.

### Why two values?

A score of +0.70 produced by nine agreeing components is fundamentally different from +0.70 produced by strongly contradictory components.

This creates a first-class:

- Direction Score
- Agreement / Confluence Score
- Dispersion / Conflict State

The model must be capable of returning `NO_EDGE`.

---

## 10. Expected gap and probability

The system should eventually produce separate outputs for:

### Direction probability

- P(GAP_UP)
- P(FLAT)
- P(GAP_DOWN)

### Magnitude

- expected signed gap;
- expected absolute gap;
- expected range.

### Tail probabilities

Examples:

- P(gap >= +50 points)
- P(gap >= +100 points)
- P(gap <= -50 points)
- P(gap <= -100 points)

Thresholds must be configurable and evaluated historically.

---

## 11. Options-implied movement comparison

Estimate the market-implied movement from ATM option pricing / IV.

Compare:

`model_expected_gap`

against:

`options_implied_move`

This produces a potential second-order feature:

`model_vs_implied_gap = model_expected_gap / implied_move`

A directional signal alone should not be interpreted as a large-gap opportunity unless its expected magnitude is also evaluated against implied movement.

---

## 12. Confluence / no-edge logic

Initial research should classify observations into:

- STRONG_BULLISH
- BULLISH
- NEUTRAL
- BEARISH
- STRONG_BEARISH
- NO_EDGE

`NO_EDGE` should be possible when:

- direction score is weak;
- component dispersion is high;
- historical performance for the current regime is poor;
- expected edge is not economically meaningful.

Do not force a directional prediction every day.

---

## 13. Regime analysis

Backtests must be segmented by:

- low/normal/high/extreme India VIX;
- positive/neutral/negative GEX;
- expiry vs non-expiry;
- weekly expiry proximity;
- strong trend vs range;
- large previous-day move vs normal move;
- high vs low IV;
- large vs small previous gap;
- high vs low option volume/OI environment.

The purpose is to discover where the signal works and where it should be suppressed.

---

## 14. Backtesting rules

### No look-ahead

At prediction time, only information available before the defined cutoff may be used.

The next-session open is never available to feature generation.

### Chronological split

Do not randomly shuffle time-series observations.

Use chronological train/validation/test periods.

### Walk-forward validation

Preferred final methodology:

`train → predict future window → advance window → retrain → predict → repeat`

### Data quality

Each observation must have explicit completeness flags. Missing Greeks or stale quotes must not silently become zero.

---

## 15. Evaluation metrics

### Classification

- accuracy;
- balanced accuracy;
- precision;
- recall;
- F1;
- confusion matrix;
- ROC-AUC where applicable.

### Probabilities

- Brier score;
- calibration curve;
- reliability by confidence bucket.

### Gap magnitude

- MAE;
- RMSE;
- signed error;
- absolute error;
- threshold hit rates.

### Trading relevance

- hit rate by confidence;
- hit rate by regime;
- average favorable/adverse gap;
- expectancy after reasonable cost/slippage assumptions;
- maximum adverse movement.

A model is not accepted merely because its raw classification accuracy exceeds 50%.

---

## 16. Machine-learning roadmap

Machine learning is a second-stage enhancement, not the starting point.

### Stage 1

Transparent mathematical POS-style and SOS models.

### Stage 2

Logistic regression for GAP_UP / FLAT / GAP_DOWN.

### Stage 3

Regression model for gap magnitude.

### Stage 4

Nonlinear gradient-boosting model for interactions.

### Stage 5

Regime-specific models if walk-forward results justify them.

ML must be compared against the transparent SOS model. If ML does not provide stable out-of-sample improvement, the simpler model remains preferred.

---

## 17. Overnight enhancement — SOS-OPEN

The EOD model should first be validated independently.

Only then add information that becomes available after the Indian close, such as:

- GIFT Nifty;
- US market/futures movement;
- Asian market movement;
- USD/INR;
- crude;
- global volatility;
- major scheduled event flags.

This creates two clearly separated products/models:

### SOS-EOD

Prediction using information available near the Indian market close.

### SOS-OPEN

Final next-open forecast incorporating permitted overnight information.

This separation prevents the EOD model from being contaminated by information that was not available at the time it claims to predict.

---

## 18. Data-source and legal constraints

The research system should not rely on scraping or redistributing restricted exchange website data.

The existing StrikeNova architecture should continue to prefer user-authorized broker/API market data and comply with the applicable broker/API and exchange terms.

No paid market-data vendor should be assumed for this research. The architecture should prioritize genuinely free data paths already available to the project and user-authorized broker data.

---

## 19. Historical dataset design

Recommended logical tables/files:

### `gap_prediction_sessions`

One row per trading session containing:

- session date;
- cutoff timestamp;
- prior close;
- next open;
- gap points;
- gap percentage;
- gap class;
- data completeness status.

### `option_chain_snapshots`

Immutable strike-level snapshots.

### `underlying_snapshots`

Spot/futures/VIX observations.

### `gap_features`

Derived research features.

### `gap_predictions`

Model outputs and later realized outcomes.

### `gap_backtest_results`

Aggregate evaluation by model, period and regime.

The exact database implementation should follow the project's existing database conventions rather than introducing a second database architecture.

---

## 20. Acceptance criteria for Phase 1

Phase 1 is complete only when:

- raw research schema is defined;
- target definition is fixed and documented;
- POS-style benchmark is reproducible;
- SOS feature dictionary is reproducible;
- no-lookahead rules are tested;
- historical dataset can be generated from authorized data;
- baseline backtests run;
- POS-style benchmark backtest runs;
- SOS backtest runs;
- results are stored reproducibly;
- walk-forward methodology is implemented or specified sufficiently for implementation;
- regime breakdown is available;
- no production UI signal is enabled.

---

## 21. Phase 2 acceptance criteria

Before production consideration:

- out-of-sample performance is statistically and economically meaningful;
- SOS beats the POS-style benchmark after accounting for data availability and costs;
- performance is not explained by one short historical period;
- confidence calibration is acceptable;
- performance is reported by regime;
- failure/no-edge conditions are documented;
- model versioning is implemented;
- historical predictions are immutable and auditable.

---

## 22. Proposed user-facing output

Eventually, the product may expose:

**STRIKENOVA OVERNIGHT FORECAST**

- Direction: Bullish / Neutral / Bearish
- Direction score: -100 to +100
- Confidence: 0–100
- Agreement: 0–100
- Gap Up probability
- Flat probability
- Gap Down probability
- Expected gap in points
- Expected range
- Options-implied move
- Model vs implied move
- Current regime
- Key contributing factors
- NO EDGE state when appropriate

No user-facing percentage should be displayed until the underlying model is calibrated and validated.

---

## 23. Research principle

The purpose of this project is not to produce an impressive-looking indicator. It is to determine whether the information available before the next NIFTY opening contains a repeatable, measurable edge.

The model must be allowed to fail, abstain, and expose uncertainty.

The final production decision must be based on out-of-sample evidence, not on whether the formula appears intuitively convincing.
