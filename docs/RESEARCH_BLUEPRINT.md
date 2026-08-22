# Market-Respected Level Research Blueprint

**Status:** Research architecture frozen through Step 5  
**Date:** 2026-08-21  
**Project:** NIFTY options research / options dashboard  
**Canonical purpose:** Preserve the research plan, assumptions, data rules, methodology, and product/UX principles so future conversations can resume without losing context.

> This document is the canonical handoff for the market-respected-level research work. It is intentionally separate from production application code.

## 0. Research Objective

Determine whether publicly observable NIFTY/options-market data can be used to identify price levels that the market is statistically more likely to respect, reject, retest, or break.

The goal is **not** to assume a market-maker position or manufacture a support/resistance formula. The goal is to reverse-engineer repeatable relationships from historical data and validate them out of sample.

The eventual live output should look conceptually like:

- candidate price levels around current NIFTY
- historical/structural evidence for each level
- probability of meaningful reaction/respect
- probability of breakout/failure
- market-regime classification
- confidence/quality score
- human-readable explanation of the evidence

No claim of 90%+ accuracy is allowed unless it survives the validation framework defined below.

## 1. Core Research Principle

**Data first -> objective event labels -> historical predictor state -> statistical discovery -> validation -> formula.**

Do not start by choosing a formula and then searching for evidence supporting it.

Do not use future market information as a predictor.

Future price action may be used only to create the outcome label for an event that was already observable at time T.

## 2. Product / UX Design Principles

The research engine and eventual dashboard should follow a **conclusion-first, evidence-underneath** philosophy. The inspiration is the product-design approach seen on Pleurat: clear work presentation, reusable design systems, consistent navigation, and tools that expose useful context without forcing users through unnecessary complexity. Pleurat explicitly emphasizes design systems, workflow improvement, consistency, and user-centric product design. citeturn1search0turn1search1

These are principles, not a request to copy Pleurat's visual style.

### 2.1 Show the conclusion first

The primary user experience should answer:

1. **WHAT is happening?**
2. **HOW strong is it?**
3. **WHY does the engine believe it?**
4. **WHAT would invalidate it?**
5. **WHAT are the alternative outcomes?**
6. **HOW confident is the model?**

Raw OI, Greeks, volume, IV, GEX, VIX, and other fields should support the conclusion rather than overwhelm the primary screen.

### 2.2 Progressive disclosure

The future interface should expose information in layers:

**Level 1 — Market conclusion**

- current NIFTY
- strongest nearby level(s)
- respect probability
- break probability
- directional interpretation, when justified
- confidence

**Level 2 — Evidence summary**

- price structure
- option-price structure
- Greeks
- volume
- verified OI
- GEX
- IV/VIX regime

**Level 3 — Raw evidence**

- strike-by-strike values
- timestamped changes
- trajectories
- migrations
- distributions

**Level 4 — Mathematical/model evidence**

- feature value
- normalization
- learned contribution/weight
- sample size
- historical analogue count
- model/version
- data-quality flags

A beginner should be able to understand Level 1, while an advanced researcher should be able to inspect Levels 2–4.

### 2.3 Market intelligence, not indicator dumping

The product should translate observable market data into interpretable market structures.

Prefer:

> **25,220 — high-probability resistance zone; 82% historical respect probability; gamma and option-flow structure are the strongest supporting evidence.**

over:

> CE OI +12.4%, PE OI -7.2%, Gamma +18%, IV +2.1%, VIX -1.8%.

The raw values remain available, but interpretation is the primary product layer.

### 2.4 Reusable design system

Define reusable components early so future modules remain visually and behaviorally consistent.

Candidate components:

- price card
- level card
- probability card
- signal card
- confidence badge
- regime badge
- strike row
- OI profile
- gamma/GEX profile
- divergence panel
- event marker
- explanation drawer
- historical analogue card
- data-quality indicator

The same component language should eventually work across Market Intelligence, Strategy Builder, Paper Trading, Research Lab, Journal, and future live-trading surfaces.

### 2.5 Tell the market story

The dashboard should eventually present the current session as a structured market story rather than a disconnected collection of widgets:

`Current NIFTY -> candidate levels -> historical level state -> current option structure -> dealer/gamma state inference -> regime -> expected behavior -> alternative outcomes`

The interface should make the causal/evidentiary chain visible without claiming access to private market-maker positions.

### 2.6 Explain uncertainty

The engine must never hide uncertainty behind a single score.

A level result should be able to expose:

- respect probability
- break probability
- confidence/quality
- comparable historical sample size
- regime
- strongest supporting features
- conflicting features
- invalidation condition
- data-quality limitations

### 2.7 Product differentiation principle

The project should not compete by being merely another option-chain dashboard.

The intended product progression is:

`Raw market data -> market-structure engine -> evidence -> probability -> explanation -> decision support`

This is the product-level expression of the research architecture.

## 3. Data Availability / Free-Only Constraint

The project should prioritize genuinely free data/tools and must not assume a paid market-data vendor.

Important distinction:

- NIFTY historical 3-minute price data: required and should be verified first.
- Expired option contract metadata: required to reconstruct the contract universe.
- Historical option OHLC/volume: required for option-price/volume research; availability and entitlement must be verified.
- Intraday historical full-chain OI: **not assumed to be freely available**. It must be independently verified before becoming a required predictor.
- India VIX historical data: available from NSE and can be used for daily/regime features.

If a field cannot be obtained reliably and freely, store it as unavailable/null rather than fabricate, interpolate, or silently substitute.

## 4. Pilot Before Scaling

Never begin with years of data.

First construct one complete NIFTY trading day and verify every field, timestamp, contract, calculation, and join.

Then expand progressively:

1. One trading day
2. Ten trading days
3. One month
4. Multiple expiry cycles
5. Larger historical sample
6. Walk-forward / unseen-period validation

A failed pilot means data acquisition/integrity is fixed before research expands.

## 5. Master Timeline

NIFTY 3-minute candles are the master timeline.

Trading session target:

- 09:15-15:30 IST
- 3-minute candles

All option observations and derived features must align to the NIFTY timestamp.

Required underlying fields:

- timestamp
- open
- high
- low
- close
- volume, if available
- derived volatility/range fields

## 6. Option Contract Universe

For each selected historical expiry, preserve contract metadata:

- instrument key
- trading symbol
- expiry
- strike
- CE/PE
- lot size

The pilot should initially use a manageable matrix such as ATM +/- 10 strikes, both CE and PE.

At approximately 75 three-minute observations in a session, ATM +/- 10 with CE+PE gives roughly 3,150 option observations per day before adding extra fields.

## 7. Dynamic ATM Rule

ATM is recalculated independently at every snapshot.

Never anchor the entire day to one opening ATM.

For each timestamp:

1. read the contemporaneous NIFTY spot/reference price
2. determine the nearest valid strike
3. define relative strike position
4. map the available CE/PE contracts into the relative-strike matrix

Store both absolute strike and relative strike.

Example:

| Relative position | Example strike |
|---:|---:|
| ATM-2 | 25,000 |
| ATM-1 | 25,100 |
| ATM | 25,200 |
| ATM+1 | 25,300 |
| ATM+2 | 25,400 |

The model should learn structural position, not memorize absolute strike numbers.

## 8. Event Detection and Labeling

The underlying swing engine identifies candidate swing highs/lows and eventually confirmed structural events.

Every event receives an event timestamp T.

Predictor snapshots are taken only from information available at or before T:

- T-30
- T-15
- T-9
- T-6
- T-3
- T0

Future observations after T are reserved exclusively for outcome labels.

## 9. Objective Level Outcome Definitions

A candidate level is not simply called support/resistance because it looks correct on a chart.

Measure:

### Reaction

Maximum favorable movement away from the candidate level during the defined future horizon.

### Penetration

Maximum movement through the candidate level before/while evaluating the reaction.

### Time-to-reaction

Time from level interaction to meaningful reaction.

### Retest

Whether price later revisits the level and rejects/respects it again.

### Continuation

Whether price breaks the level and continues in the same direction.

Initial outcome classes:

- Strong Respect
- Moderate Respect
- Weak Respect
- Breakout
- False Breakout
- No Reaction

Thresholds should be volatility-normalized rather than fixed-point wherever possible.

## 10. Volatility Normalization

A fixed 20-point move has different meaning under different volatility regimes.

Normalize reaction and penetration by a contemporaneous volatility measure such as 3-minute ATR or another validated range estimator.

Conceptually:

`NormalizedReaction = Reaction / ATR`

`NormalizedPenetration = Penetration / ATR`

India VIX can additionally be used as a regime variable.

## 11. Level Clustering / Dot-to-Dot Research

Historical swing levels are treated as observations rather than manually drawn lines.

If repeated historical levels cluster around a price region, estimate a continuous level-density function instead of assuming a single exact number.

The research should test whether repeated prior interactions form statistically meaningful zones.

Each level must retain its formation timestamp so historical information is never leaked from the future.

At time T:

`LevelStrength(L,T) = f(all qualifying historical events before T)`

Future events cannot contribute to the predictor state at T.

## 12. Level-Relative Option Map

For every candidate level, calculate the relationship between option strikes and the candidate level:

`DistanceFromLevel = Strike - CandidateLevel`

This allows us to test whether option-market structure concentrates around the eventual respected price rather than only around ATM.

Both ATM-relative and level-relative representations should be retained.

## 13. Feature Families

Features are organized into families before modeling.

### A. Price structure

- distance from prior high/low
- swing magnitude
- ATR
- momentum
- VWAP distance
- gap
- range position
- return structure

### B. Option price structure

- CE price
- PE price
- CE/PE price ratio
- price slope
- price acceleration
- relative option-price changes

### C. Greeks

- Delta
- Gamma
- Vega
- Theta
- IV

### D. Greek changes

- Delta change
- Gamma change
- Vega change
- Theta change
- IV change
- slopes
- acceleration
- persistence

### E. Volume

- CE volume
- PE volume
- CE/PE volume ratio
- relative volume
- volume acceleration
- strike migration proxies

### F. OI (only after historical integrity is verified)

- CE OI
- PE OI
- delta OI
- OI concentration
- OI migration
- OI imbalance
- buildup/unwinding classifications

### G. GEX

- call GEX
- put GEX
- net GEX
- gamma concentration
- gamma flip
- gamma slope

### H. VIX / volatility regime

- VIX level
- VIX change
- VIX percentile
- VIX acceleration
- relative ATR

## 14. Feature Trajectory Representation

Absolute values alone are insufficient.

For each important variable X, retain:

- `X_T`
- `X_T - X_T-30`
- slope across snapshots
- acceleration
- directional persistence
- optionally normalized/z-scored forms

This allows the research to detect buildup/decay rather than only static levels.

## 15. Initial Statistical Discovery

Split events into outcome groups such as Respect vs Failure.

For every feature calculate and compare:

- conditional means/medians
- distribution separation
- effect size
- confidence intervals
- permutation significance where appropriate
- Mann-Whitney U where appropriate
- mutual information for nonlinear relationships

Correlation alone is not sufficient.

A feature with a nonlinear relationship may have weak linear correlation while remaining highly informative.

## 16. Interaction Research

Explicitly test combinations because individual variables may be weak while their joint state is strong.

Examples to investigate:

- CE Gamma trend + PE Gamma trend + spot failure to make a new high
- CE volume + CE OI + CE price direction
- PE volume + PE OI + PE price direction
- option-price divergence + spot structure
- OI migration + Gamma concentration
- GEX regime + VIX regime

These are hypotheses to test, not assumed truths.

## 17. Model Ladder / Ablation

Build models incrementally so the contribution of each data family is measurable.

Suggested sequence:

- M0: price only
- M1: price + option price
- M2: + Greeks
- M3: + volume
- M4: + verified OI
- M5: + GEX
- M6: + VIX/regime variables

If a data family adds no robust out-of-sample value, it should not be retained merely because it sounds sophisticated.

## 18. Baselines

Every advanced model must beat simple benchmarks such as:

- random direction
- nearest/previous swing level
- nearest round strike
- previous day's high/low
- conventional pivot levels
- maximum-OI strike, only when valid historical OI exists

The complex system is successful only if it demonstrates incremental predictive value over these baselines.

## 19. Regime Conditioning

A single universal formula is not assumed.

At minimum test:

- trend vs range
- high vs low volatility
- high vs low VIX
- expiry vs non-expiry
- opening/midday/late session

The target formulation may become:

`Score = f(features, regime)`

rather than one fixed formula for every market condition.

## 20. Validation / Leakage Prevention

Never randomly mix adjacent time-series observations between train and test.

Use chronological validation and walk-forward testing.

Example structure:

- historical period -> training
- later period -> validation
- later unseen period -> test
- final forward period -> completely unseen validation

The exact dates depend on the clean dataset.

## 21. Robustness Requirements

No formula is accepted as robust without surviving:

1. Out-of-sample testing
2. Walk-forward testing
3. Different market regimes
4. Different expiry cycles
5. Different volatility conditions
6. Transaction-cost assumptions
7. Slippage assumptions
8. Parameter perturbation
9. Feature ablation
10. Multiple-testing controls

Parameter stability is required. A narrow magic threshold is evidence of possible overfitting.

## 22. Final Live-System Concept

The eventual live engine should conceptually operate as:

`Current NIFTY -> candidate levels -> historical level state -> current option/Greek/volume/OI/GEX state -> regime -> level score -> respect/break probabilities -> confidence`

The system should explain why a level received its score rather than outputting an opaque number.

## 23. Data Integrity Rules

- Never fabricate historical OI.
- Never silently fill missing market observations.
- Never use future observations as predictors.
- Preserve raw data separately from derived features.
- Preserve source and timestamp for every raw observation.
- Preserve calculation version for derived features.
- Record missing-data quality explicitly.
- Do not let a low-quality snapshot enter model training without a documented rule.

## 24. Proposed Research Tables

### `nifty_candles`

- timestamp
- OHLC
- volume
- derived range/volatility fields

### `option_contracts`

- instrument_key
- trading_symbol
- expiry
- strike
- option_type
- lot_size

### `option_candles`

- timestamp
- instrument_key
- OHLC
- volume
- OI, only when genuinely available

### `research_events`

- event timestamp
- event type
- candidate level
- swing metadata
- outcome class
- reaction
- penetration
- time-to-reaction
- retest/breakout labels

### `research_features`

- event id
- snapshot timestamp
- ATM-relative strike
- level-relative strike
- price features
- option features
- Greek features
- volume features
- verified OI features
- GEX features
- VIX/regime features
- data-quality flags

## 25. Current Research State

Completed conceptually:

- objective research goal defined
- no-hindsight principle defined
- pilot-first acquisition strategy defined
- master NIFTY 3-minute timeline defined
- dynamic ATM design defined
- ATM-relative and level-relative normalization defined
- event outcome framework defined
- volatility normalization defined
- feature families defined
- statistical discovery framework defined
- interaction research defined
- model-ablation framework defined
- baseline framework defined
- regime framework defined
- walk-forward validation framework defined
- robustness requirements defined
- product/UX principle defined: conclusion first, evidence underneath
- progressive disclosure defined
- reusable component/design-system principle defined
- market-story presentation defined

## 26. Immediate Next Step: Step 6

**Do not jump into modeling yet.**

Step 6 is to create the exact mathematical feature dictionary.

For every candidate variable, define:

1. raw source field
2. exact formula
3. units
4. normalization
5. timestamp alignment
6. missing-data behavior
7. interpretation
8. whether it is allowed at T0
9. whether it is a predictor or label
10. whether it is an absolute, change, slope, acceleration, or interaction feature

Only after this mathematical specification is frozen should implementation against the pilot dataset begin.

## 27. Conversation Handoff

This blueprint preserves the decisions from the research conversation that led to this stage.

Reference conversation:
https://chatgpt.com/share/6a87f63e-84e8-83e8-8d91-fbc368b6f2b0

When resuming the work, read this file first and continue from **Step 6 — Mathematical Feature Dictionary** unless a later research document supersedes it.

## 28. Non-Goals

This research does not claim to literally identify the private positions of market makers.

It attempts to infer statistically useful market structure from publicly observable data.

It does not guarantee profitable trading.

It does not use future data in live predictors.

It does not depend on paid data services unless the project owner explicitly changes the free-only constraint.
