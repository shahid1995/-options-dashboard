# StrikeNova Day 35 — Portfolio Intelligence Design

**Version:** 1.0
**Date:** 2026-09-05
**Status:** Proposed for written-spec review

## 1. Objective

Build a deterministic, broker-neutral Portfolio Intelligence layer that normalizes authoritative portfolio positions and produces multidimensional analytics for exposures, Greeks, GEX, scenario sensitivities, concentration, directional state, and regime-aware risk views.

Day 35 is an analytics/interpretation boundary. It does not replace broker truth, paper Position truth, Day 33 Central Risk, capital/margin, execution, or user approval.

## 2. Architectural Boundary

```text
Authoritative Position Truth
  broker positions where applicable
  paper Position for paper portfolios
          |
          v
  Portfolio Normalization
          |
    +-----+------+------+------+------+ 
    |            |      |      |       |
 exposures    Greeks   GEX  scenarios concentration
    |            |      |      |       |
    +------------+------+------+-------+
                 |
                 v
          Portfolio State
                 |
       +---------+---------+
       |         |         |
 directional  regime    portfolio
    view       view     risk views
```

The normalizer consumes existing authoritative position/exposure services. Derived analytics are explicitly distinguished from broker-observed values. No new position source of truth is introduced.

## 3. Authoritative Data Rules

1. Actual broker positions remain authoritative for broker portfolios.
2. Existing paper `Position` records remain authoritative for paper net exposure.
3. `StrategyLegExposure` remains authoritative for per-execution/per-leg attribution where applicable.
4. Broker/model/derived values must remain distinguishable in contracts and explanations.
5. Missing data is never silently converted to zero.
6. The portfolio layer must not infer fills, quantities, broker positions, or account state.
7. Portfolio analytics may consume broker-observed market values and shared derived intelligence, but may not rewrite their source of truth.

## 4. Portfolio Position Normalization

Create a broker-neutral immutable representation of each authoritative position containing canonical instrument identity, expiry, strike, option type, signed quantity/direction, authoritative entry/current valuation where available, contract multiplier/lot size where authoritative, and source/quality/provenance metadata.

Normalization must preserve whether each value is broker-observed, paper-authoritative, or model/derived. Position identity and quantity must be deterministic.

For missing optional inputs, retain absence explicitly. A missing Greek, GEX, price, or scenario value must remain missing and must affect completeness/quality rather than becoming zero.

## 5. Exposure Analytics

Aggregate signed portfolio exposure from authoritative positions using existing quantity and contract-unit conventions. Expose leg contributions and portfolio totals where available.

Exposure analytics are descriptive. They do not constitute an execution decision or a risk-policy authorization.

## 6. Greek Analytics

Aggregate authoritative/shared model Greek inputs across positions using the existing quantitative unit contracts. Reuse existing Greek calculations and conversions; do not implement a second Black-Scholes/Greek engine.

At minimum, support delta, gamma, theta, vega, and rho when the authoritative input is available. Partial Greek coverage remains partial; missing components are not zero.

## 7. GEX Analytics

Consume the existing GEX foundation and preserve its methodology, sign convention, units, quality, provenance, and timestamps. Do not duplicate GEX mathematics.

Portfolio-level GEX and market/dealer GEX must remain separate concepts. A market GEX snapshot must never be represented as portfolio-owned exposure.

## 8. Scenario Sensitivity

Reuse the authoritative Scenario & Time Analysis foundation from Day 18. Aggregate supplied scenario outputs into portfolio-level sensitivity views while preserving scenario identity, partial state, warnings, provenance, and calculation versions.

The portfolio layer must not create a new scenario mathematics engine or invent unprovided stress outcomes.

## 9. Concentration View

Provide deterministic descriptive concentration measurements for dimensions such as strike, expiry, option type, and largest absolute exposure. Concentration is a measurement, not an automatic danger verdict.

No arbitrary concentration threshold becomes an execution block in Day 35.

## 10. Directional View

Expose deterministic directional exposure using actual aggregated position/Greek evidence, including net delta and relevant CE/PE or long/short contributions where available.

A positive/negative exposure value is not itself a prediction or probability. The view must not manufacture bullish/bearish evidence from labels alone.

## 11. Regime-Aware View

Consume the authoritative Day 23 market regime and evaluate compatibility/stress characteristics of the current portfolio. Regime labels are contextual evidence only and cannot fabricate directional evidence.

Unknown, unavailable, or non-success regime input remains explicitly unknown/partial rather than being mapped to a default regime.

## 12. Portfolio Risk Separation

Day 35 produces portfolio analytics and risk views. It does not replace Day 33 Central Risk and does not authorize execution.

```text
Portfolio Metrics != Portfolio Risk View != Central Risk Policy Decision
Portfolio Risk View != Capital/Margin Decision
Portfolio Risk View != Execution Authorization
```

Day 36 may consume Day 35 outputs for a broader risk gate, subject to a separately approved design.

## 13. Contracts

Proposed domain contracts:

- `PortfolioPosition`
- `PortfolioExposure`
- `PortfolioGreekExposure`
- `PortfolioGexExposure`
- `PortfolioScenarioSensitivity`
- `ConcentrationView`
- `DirectionalView`
- `RegimeRiskView`
- `PortfolioState`
- `PortfolioAnalyticsResult`

Contracts should use existing canonical quality and provenance types where applicable, remain deterministic/serializable, and preserve explicit assessment states such as `AVAILABLE`, `PARTIAL`, `UNAVAILABLE`, and `INVALID`.

## 14. Pure Analytics Boundary

The core portfolio intelligence layer must be deterministic and free of database, network, filesystem, broker calls, environment reads, wall-clock reads, and randomness.

Data acquisition and authoritative position retrieval remain outside the pure analytics contracts. Callers supply the position state and reference timestamp.

Repeated evaluation with identical inputs must produce byte-identical serialized results.

## 15. Context and Source Equivalence

Where the same authoritative position/market inputs are supplied, portfolio analytics must not change merely because the caller labels the source as paper, broker, research, or another analytical context. Context may identify provenance, but must not silently change mathematics.

## 16. Non-Goals

Day 35 does not include:

- capital allocation or margin authorization
- new broker/live execution
- user approval workflow
- order creation
- new Greek/IV/GEX/scenario mathematics
- replacing Position or StrategyLegExposure
- database/schema redesign
- historical ingestion
- backtesting
- ML/AI
- execution risk gates
- new risk-policy thresholds
- frontend redesign

## 17. Test Requirements

The implementation must test at minimum:

1. empty portfolio
2. single long call
3. single short call
4. mixed CE/PE
5. multi-expiry positions
6. multi-leg attribution
7. position netting
8. signed quantity correctness
9. Greek aggregation
10. missing Greek is not zero
11. GEX aggregation/source separation
12. missing GEX is not zero
13. scenario aggregation
14. missing scenario is not zero
15. concentration by strike
16. concentration by expiry
17. option-type concentration
18. directional exposure
19. unknown regime
20. regime compatibility
21. regime label cannot fabricate direction
22. broker/model source separation
23. provenance propagation
24. quality propagation
25. caller-supplied reference timestamp
26. deterministic repeated evaluation
27. deterministic serialization
28. no I/O/wall clock/randomness in the domain layer
29. paper Position authority
30. broker Position authority
31. Day 33 risk remains separate
32. no execution authority

## 18. Exit Gate

Day 35 is complete only when portfolio analytics consume authoritative position state and shared quant/intelligence services, preserve broker truth and provenance, correctly represent missing/incomplete data, provide concentration/directional/regime-aware views, and have regression evidence proving no execution or broker-truth authority has been introduced.

No Day 36 implementation begins until the Day 35 implementation is independently reviewed and approved.
