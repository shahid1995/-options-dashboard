# Research Conversation Archive — Market-Respected Level / NIFTY Options Research

**Purpose:** Preserve the substantive research conversation in a readable, narrative form so that the project does not depend on ChatGPT conversation history remaining available.

**Project:** NIFTY options research / options dashboard
**Canonical research blueprint:** `docs/RESEARCH_BLUEPRINT.md`
**Research branch:** `research/market-level-blueprint`
**Conversation reference:** https://chatgpt.com/share/6a87f63e-84e8-83e8-8d91-fbc368b6f2b0

> This file is intentionally more detailed than the blueprint. The blueprint records the methodology and decisions; this archive records the reasoning, questions, conclusions, and product direction that led to those decisions.
>
> The original shared ChatGPT URL could not be programmatically fetched from the current environment, so this archive preserves the substantive conversation available in the active project context and the research discussion carried forward here. It should be treated as a project handoff/archive, not as a byte-for-byte export of the ChatGPT UI transcript.

---

# 1. Why We Started This Research

The research began from a practical trading problem: conventional support/resistance calculations often tell us where a level is, but not whether the market is actually likely to respect that level under the current option-market structure.

The desired system is therefore not another indicator dashboard. The objective is to discover, from historical NIFTY and publicly observable options data, whether there are repeatable relationships that can identify price levels that are statistically more likely to be respected, rejected, retested, falsely broken, or broken with continuation.

The central philosophy became:

> Do not start with a formula and look for evidence to support it. Start with market behavior, label what actually happened, examine what was observable before it happened, and reverse-engineer the relationship.

This is the foundation of the research.

---

# 2. The Core Research Question

The central question was reframed as:

> Given everything that was publicly observable immediately before a swing or level interaction, can we identify the price level the market was most likely to respect?

This is deliberately different from asking:

> What is the support or resistance?

The system should eventually answer something closer to:

> Given the current market regime and the observable option structure, which candidate price level has the highest historical probability of producing a meaningful reaction, and what evidence supports that conclusion?

The eventual live output should therefore be probabilistic and evidence-based rather than a binary support/resistance label.

---

# 3. The Most Important Methodological Decision: Reverse Engineer From Market Behavior

A key discussion point was that we should not invent a formula such as:

`Resistance = Maximum CE OI strike`

or:

`Support = Maximum PE OI strike`

and then attempt to justify it.

Instead, historical intraday price behavior should identify the levels that were actually respected. Once those events are identified, we look backward only to information that was available at that time and ask which variables distinguished successful levels from failed levels.

The research therefore follows this causal order:

`Historical price behavior -> objective level/event label -> pre-event market state -> feature extraction -> statistical discovery -> validation -> formula/model`

This is the opposite of indicator-first research.

---

# 4. Defining a Respected Level Objectively

A major part of the discussion was that a chart visually showing a rejection is not enough. We need an objective definition that can be calculated for thousands of historical events.

For every candidate level we should measure:

### Reaction

How far price moved away from the level after interacting with it.

Conceptually:

`Reaction = maximum favorable movement away from the level during the defined future horizon.`

### Penetration

How far price moved through the candidate level before the reaction or continuation was established.

### Time-to-reaction

How quickly a meaningful reaction developed after the level interaction.

### Retest

Whether price later returned to the same area and again rejected/respected it.

### Continuation

Whether the level was broken and price continued in the direction of the break.

Initial classifications were proposed as:

- Strong Respect
- Moderate Respect
- Weak Respect
- Breakout
- False Breakout
- No Reaction

The thresholds should be volatility-normalized rather than arbitrary fixed point values.

---

# 5. Why False Breakouts Matter

An important observation was that a market-respected level does not necessarily mean price never crosses it.

A level can behave as:

`cross -> absorption/failed continuation -> reversal`

That behavior may be more informative than a simple clean rejection.

Therefore false breakouts should be retained as a distinct outcome class rather than being treated as noise.

This may eventually become one of the most valuable patterns in the system because it can capture situations where liquidity is taken through an apparent level and price subsequently reverses.

---

# 6. Volatility Normalization

The research explicitly rejected fixed-point thresholds because a 20-point NIFTY move does not have the same meaning under different volatility conditions.

For example, the same penetration can be insignificant during a high-volatility session and significant during a low-volatility session.

Therefore reaction and penetration should be normalized using a contemporaneous volatility/range measure such as 3-minute ATR or another validated estimator.

Conceptually:

`NormalizedReaction = Reaction / ATR`

`NormalizedPenetration = Penetration / ATR`

India VIX can additionally serve as a regime variable.

---

# 7. The Dot-to-Dot Idea Becomes a Data Object

The existing idea of identifying market-respected levels through a "dot-to-dot" approach was converted into a measurable historical event framework.

Instead of manually drawing lines between visually important highs/lows, each historical swing becomes an observation.

Example conceptual event sequence:

- Swing event -> 25,180
- Swing event -> 25,245
- Swing event -> 25,198
- Swing event -> 25,310

We then test whether these observations cluster into statistically meaningful zones.

If repeated historical levels cluster around approximately 25,200, that region may represent a market-respected zone rather than six unrelated exact prices.

The research should therefore estimate a continuous level-density structure rather than assume every level is an exact strike or round number.

---

# 8. Avoiding Hindsight Bias

One of the strongest rules established during the research was:

> Every level must have a formation timestamp, and its predictor state may only use information available at or before that timestamp.

If an event occurs at time T, the predictor can use snapshots such as:

- T-30 minutes
- T-15 minutes
- T-9 minutes
- T-6 minutes
- T-3 minutes
- T0

Future observations after T are allowed only for constructing the outcome label.

This distinction is critical:

**Predictor:** what we knew at T.

**Label:** what happened after T.

Future price action must never leak into a live predictor.

---

# 9. Dynamic ATM Instead of Fixed Opening ATM

Another important design decision was that ATM should be recalculated at every snapshot.

A complete session must not be anchored to the opening ATM because NIFTY may move through multiple strike intervals during the day.

At each timestamp:

1. Read the contemporaneous NIFTY reference price.
2. Determine the nearest valid strike.
3. Assign relative strike position.
4. Map CE/PE contracts into the relative-strike matrix.

Both absolute strike and relative strike should be retained.

Example:

`ATM-2, ATM-1, ATM, ATM+1, ATM+2`

This prevents the model from simply memorizing absolute strike numbers.

---

# 10. ATM-Relative and Level-Relative Analysis

The research then introduced an additional representation that is especially important for reverse engineering.

For every candidate respected level, we calculate:

`DistanceFromLevel = Strike - CandidateLevel`

This means the option chain is not examined only relative to ATM. It is also examined relative to the candidate price level itself.

Example:

| Strike | Distance from candidate level |
|---:|---:|
| 24,900 | -300 |
| 25,000 | -200 |
| 25,100 | -100 |
| 25,200 | 0 |
| 25,300 | +100 |
| 25,400 | +200 |

This allows the research to test whether option-market positioning concentrates around the price level that the underlying subsequently respects.

Both representations are required:

- ATM-relative structure
- Level-relative structure

---

# 11. Option-Market Feature Families

The discussion expanded the predictor set into organized feature families rather than an uncontrolled collection of columns.

### Price structure

Potential variables include:

- distance from previous high/low
- swing magnitude
- ATR
- momentum
- VWAP distance
- gap
- range position
- return structure

### Option price structure

Potential variables include:

- CE price
- PE price
- CE/PE price ratio
- price slope
- price acceleration
- relative option-price changes

### Greeks

- Delta
- Gamma
- Vega
- Theta
- IV

### Greek changes

The research explicitly noted that absolute Greek values may not be enough. We also need:

- change
- slope
- acceleration
- directional persistence
- normalized forms where appropriate

### Volume

- CE volume
- PE volume
- CE/PE volume ratio
- relative volume
- volume acceleration
- strike migration proxies

### OI

OI was deliberately marked as conditional:

> Only use historical intraday OI as a predictor after its historical availability and integrity have been independently verified.

Potential OI variables include:

- CE OI
- PE OI
- delta OI
- OI concentration
- OI migration
- OI imbalance
- buildup/unwinding classifications

We must never fabricate unavailable historical OI.

### GEX

The research includes:

- call GEX
- put GEX
- net GEX
- gamma concentration
- gamma flip
- gamma slope

GEX is a research feature, not an assumed predictor.

### VIX / volatility

- India VIX
- VIX change
- VIX percentile
- VIX acceleration
- relative ATR

---

# 12. Feature Trajectory Instead of Static Values

A major insight was that an absolute value often tells less than its trajectory.

For example, a CE Gamma value of 0.0021 by itself may be uninformative.

But a sequence such as:

`0.0011 -> 0.0014 -> 0.0017 -> 0.0019 -> 0.0020 -> 0.0021`

shows persistent gamma expansion into the candidate level.

Therefore every important feature should be represented through:

- current value
- change over the pre-event window
- slope
- acceleration
- persistence

Conceptually:

`X_T`

`X_T - X_T-30`

`Slope(X)`

`Acceleration(X)`

`Persistence(X)`

This lets the research identify buildup and decay rather than only static conditions.

---

# 13. Statistical Discovery Instead of Guessing Weights

Once objective outcomes are available, events can be divided into groups such as Respect and Failure.

For each feature we compare its distribution between groups.

The research should use tools such as:

- conditional means and medians
- distribution separation
- effect size
- bootstrap confidence intervals
- permutation tests
- Mann-Whitney U where appropriate
- mutual information for nonlinear relationships

Correlation alone is not sufficient because a useful feature may have a nonlinear relationship with the outcome.

Example conceptual relationship:

`low -> poor`

`medium -> excellent`

`high -> poor`

Such a feature may have weak linear correlation while still being useful.

---

# 14. Interaction Research

A recurring theme was that individual variables may be weak while combinations are strong.

Examples to test include:

`CE Gamma trend + PE Gamma trend + spot fails to make a new high`

`CE Volume + CE OI + CE price direction`

`PE Volume + PE OI + PE price direction`

`Option-price divergence + spot structure`

`OI migration + Gamma concentration`

`GEX regime + VIX regime`

These are hypotheses only. The system must measure whether they actually work.

---

# 15. The Model Ladder

The research proposed incremental models so that every data family has to prove its value.

### M0

Price only.

### M1

Price + option price.

### M2

Price + option price + Greeks.

### M3

Add volume.

### M4

Add verified historical OI.

### M5

Add GEX.

### M6

Add VIX/regime variables.

The purpose is ablation: if a sophisticated data family adds no robust out-of-sample value, it should be removed instead of being retained because it sounds advanced.

---

# 16. Baselines

The advanced model must beat simple alternatives.

Candidate baselines include:

- random direction
- previous/nearest swing level
- nearest round strike
- previous day's high/low
- conventional pivot levels
- maximum-OI strike, only when valid historical OI exists

If the complex model cannot beat simple baselines out of sample, there is no justification for its complexity.

---

# 17. Regime Detection

The discussion concluded that one universal formula should not be assumed.

At minimum, the research should distinguish:

- trend vs range
- high vs low volatility
- high vs low VIX
- expiry vs non-expiry
- opening vs midday vs late session

The eventual relationship may become:

`Score = f(features, regime)`

rather than one fixed formula for every condition.

---

# 18. Walk-Forward Validation

Random train/test splitting is inappropriate for adjacent market observations because time-series observations are correlated.

The research therefore uses chronological validation and walk-forward testing.

Conceptually:

`Past -> Train -> Later validation -> Later unseen test`

Then the training window moves forward and the experiment repeats.

The model must demonstrate that relationships persist when market conditions change.

---

# 19. Robustness Standard

The research explicitly rejected accepting a formula because it produces a high backtest percentage on one sample.

A candidate relationship must survive:

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

Parameter stability is especially important.

A threshold that works only at one exact value is a warning sign for overfitting.

---

# 20. What the Final Live Engine Should Eventually Do

The conceptual live pipeline became:

`Current NIFTY -> candidate levels -> historical level state -> current option/Greek/volume/OI/GEX state -> regime -> level score -> respect/break probabilities -> confidence`

The output should be explainable.

A trader should be able to see:

### WHAT?

Example: `25,220 is a high-probability resistance zone.`

### HOW STRONG?

Example: `Respect probability: 82%`.

### WHY?

Example: `Price structure strong + gamma concentration + option-flow structure + historical analogues.`

### WHAT INVALIDATES IT?

Example: `Sustained penetration above the level with confirming structure.`

### WHAT NEXT?

Example: `Rejection vs breakout probabilities.`

### HOW CONFIDENT?

Example: `High confidence based on the number and quality of comparable historical observations.`

The numbers above are illustrative only; the actual values must come from the research.

---

# 21. Product / UX Discussion Inspired by Pleurat

The conversation then asked whether https://www.pleurat.com/ could provide inspiration for the platform.

The conclusion was that Pleurat should be treated primarily as a product-design and UX inspiration source, not as a source of trading methodology.

The useful principles identified were:

### Show, don't explain

Put the actual conclusion and work in front of the user instead of forcing them to interpret a large collection of technical indicators.

### Selected work / selected intelligence

Instead of displaying every metric simultaneously, surface the most important market structures first.

### Design-system thinking

Create reusable components so that Market Intelligence, Strategy Builder, Paper Trading, Research Lab and other modules share a coherent visual language.

### Progressive disclosure

The interface should reveal information in layers.

#### Level 1 — What is happening?

Example:

`NIFTY 25,184`

`Nearest strong resistance: 25,220`

`Respect probability: 82%`

`Confidence: HIGH`

#### Level 2 — Why?

Show high-level evidence:

- Price structure
- Gamma structure
- OI structure
- Volume
- IV
- VIX
- Historical analogue strength

#### Level 3 — Raw evidence

Allow the user to inspect the actual option chain, OI, volume, Greeks, GEX and VIX values.

#### Level 4 — Mathematical model

For quantitative users, show:

- feature
- normalization
- contribution
- weight
- confidence
- historical sample size
- calculation version

This lets a beginner understand the conclusion while a quantitative user can audit the evidence.

---

# 22. Product Differentiation

A key conclusion from the UX discussion was that we should not build merely another option-chain dashboard.

Many platforms already expose combinations of:

- option chain
- Greeks
- OI
- max pain
- straddle information
- volatility surface
- GEX
- gamma density
- IV smile
- OI profile
- strategy builder
- execution
- journals

Therefore our differentiation should be the interpretation layer.

### Conventional platform

`Data -> Charts -> Indicators -> User interprets`

### Intended platform

`Data -> Market structure engine -> Evidence -> Probability -> Explanation -> Decision support`

The platform should convert raw data into a coherent market story rather than simply present more numbers.

---

# 23. Market Story Concept

The interface may eventually tell a structured story such as:

`TODAY'S MARKET STORY`

`NIFTY 25,184`

`Support 25,050 — historical respect probability 76%`

`Resistance 25,220 — historical respect probability 82%`

`Current zone -> dealer/gamma state -> expected behavior`

Then show:

`Rejection: X%`

`Breakout: Y%`

Again, actual probabilities must be research-derived, not hard-coded.

This is intended to make the output actionable without making the underlying research opaque.

---

# 24. Research Data Integrity Rules

The following rules were repeatedly reinforced during the discussion:

- Never fabricate historical OI.
- Never silently fill missing market observations.
- Never use future observations as predictors.
- Preserve raw data separately from derived features.
- Preserve source and timestamp for every raw observation.
- Preserve calculation/version metadata for derived features.
- Record missing-data quality explicitly.
- Do not allow low-quality snapshots into training without a documented rule.
- Prefer genuinely free data/tools; do not assume paid market-data services.

The free-only constraint is a standing project constraint.

---

# 25. Pilot-First Strategy

The research should not start with years of data.

The agreed sequence is:

1. One complete trading day
2. Ten trading days
3. One month
4. Multiple expiry cycles
5. Larger historical sample
6. Walk-forward / unseen-period validation

The one-day pilot is intended to verify:

- timestamp alignment
- NIFTY candles
- option contract metadata
- expiry mapping
- strike mapping
- dynamic ATM
- CE/PE mapping
- volume
- any available OI
- Greeks/IV calculations
- GEX calculations
- missing-data behavior
- event detection
- label construction
- database joins

A failed pilot means data acquisition/integrity is fixed before scaling.

---

# 26. Current Research State

At the point this archive was created, the research architecture through Step 5 had been established.

The canonical blueprint contains the formal methodology.

The substantive reasoning preserved here explains why the methodology was chosen.

The next stage is **Step 6 — Mathematical Feature Dictionary**.

Step 6 must define every candidate feature precisely before implementation:

1. Raw source field
2. Exact formula
3. Units
4. Normalization
5. Timestamp alignment
6. Missing-data behavior
7. Interpretation
8. Whether it is permitted at T0
9. Whether it is a predictor or label
10. Whether it is absolute, change, slope, acceleration, or interaction

Only after this mathematical specification is frozen should implementation against the pilot dataset begin.

---

# 27. Project Handoff Rule

When the research is resumed in another ChatGPT conversation, coding session, or development tool:

1. Read `docs/RESEARCH_BLUEPRINT.md` first.
2. Read this conversation archive for the reasoning behind the decisions.
3. Do not jump directly into implementation unless Step 6 and the relevant data specification have been completed.
4. Do not change the free-only constraint without an explicit project decision.
5. Do not introduce lookahead or data leakage.
6. Do not turn research hypotheses into hard-coded trading rules without statistical validation.

The canonical research path is:

`Conversation reasoning -> Research Blueprint -> Mathematical Specification -> Data Specification -> Pilot -> Historical Dataset -> Feature Discovery -> Model Validation -> Live Market Intelligence`

---

# 28. Preservation Note

This archive is intentionally written as a durable project document rather than a short checklist. The purpose is to preserve not only *what* was decided, but *why* it was decided, so future contributors can challenge assumptions intelligently without accidentally reverting to the original indicator-first approach.
