# GEX Data Quality Contract — Phase 7.8L

## Overview

The GEX Data Quality Contract provides a deterministic, transparent framework for assessing the quality of the Historical GEX dataset. It produces machine-readable quality reports with per-metric coverage, a composite 0-100 score, and clear classifications.

## Design Principles

1. **Every metric is visible** — the score never hides individual weaknesses.
2. **Missing data is never converted into valid data.**
3. **All thresholds are documented and justified.**
4. **The engine is read-only** against production data.
5. **No fabrication, interpolation, or forward-filling.**

## Quality Classifications

| Classification | Score | Critical Metrics | Justification |
|---|---|---|---|
| EXCELLENT | ≥ 95 | All ≥ 95% | High-confidence research and analysis |
| GOOD | ≥ 85 | All ≥ 85% | Acceptable for research/exploration |
| DEGRADED | ≥ 70 | All ≥ 70% | Known limitations, document them |
| INSUFFICIENT | < 70 | Any < 70% | Unreliable for conclusions |

Thresholds are derived from the observed production dataset and validated against real-world expectations for financial data.

## Composite Score Calculation

```
weighted_sum = Σ(metric_value × weight)
total_weight = Σ(weights)

raw_score = (weighted_sum / total_weight) × 100

score = min(raw_score, 100 × min_critical_metric)
```

- **Critical metrics**: weight = 2.0
- **Non-critical metrics**: weight = 1.0
- **Score cap**: Cannot exceed `100 × worst_critical_metric`

This ensures the score never exceeds the weakest critical metric.

## Metrics

### Critical Metrics (affect classification and score cap)

| Metric | Definition | Weight |
|---|---|---|
| `oi_coverage` | % of option_candles with OI > 0 | 2.0 |
| `gex_success_rate` | % of historical_gex rows with status = SUCCESS | 2.0 |
| `gex_coverage` | Same as gex_success_rate (clarity alias) | 2.0 |
| `timestamp_coverage` | % of distinct timestamps that have GEX rows | 2.0 |
| `numerical_validity` | % of GEX rows with non-NULL raw_gex and signed_gex | 2.0 |

### Non-Critical Metrics

| Metric | Definition |
|---|---|
| `zero_oi_count` | Absolute count of zero-OI rows |
| `zero_oi_pct` | % of option_candles with OI = 0 |
| `gex_excluded_count` | Absolute count of EXCLUDED GEX rows |
| `total_timestamps` | Total distinct timestamps in option_candles |
| `chain_completeness` | % of timestamps with chain size ≥ median × 0.5 |
| `avg_chain_size` | Average number of instruments per timestamp |
| `ce_pe_balance` | min(CE, PE) / max(CE, PE) for instrument count |
| `ce_count` | Number of unique CE instruments |
| `pe_count` | Number of unique PE instruments |

## Exclusion Reasons

Every excluded GEX observation carries a machine-readable reason:

| Reason | Description | Root Cause |
|---|---|---|
| `ZERO_OI` | Open interest is zero | Upstox V2 API limitation on expiry day |
| `MISSING_OI` | OI field is NULL | Source data gap |
| `INVALID_OI` | OI has non-numeric value | Data corruption |
| `MISSING_SPOT` | Spot price unavailable | Greek calculation failed |
| `INVALID_SPOT` | Spot is non-positive/NaN/Inf | Data error |
| `MISSING_GAMMA` | Gamma is NULL | Greek calculation failed |
| `INVALID_GAMMA` | Gamma is NaN or Inf | Data error |
| `NEGATIVE_GAMMA` | Gamma < 0 (impossible for standard options) | Data error |
| `MISSING_STRIKE` | Strike is NULL | Contract spec missing |
| `INVALID_STRIKE` | Strike is non-positive | Data error |
| `UNKNOWN_OPTION_TYPE` | Not CE or PE | Data error |
| `MISSING_OPTION_TYPE` | Option type is NULL | Data error |
| `NON_SUCCESS_GREEKS` | Greek calculation didn't complete | Pipeline error |
| `INCOMPLETE_CHAIN` | Option chain incomplete at timestamp | Data gap |
| `EXPIRY_DAY_LIMITATION` | Upstox API returns OI=0 on expiry day | Known limitation |

## Known Upstox API Limitations

### Expiry-Day Zero OI

The Upstox V2 expired-instruments historical candle API returns `open_interest = 0` for certain instruments on their weekly expiry day. This affects:

- **26 weekly NIFTY expiries** from 2024-10-03 to 2025-04-09
- **~171 unique instruments** (deep OTM/far-OTM weekly options)
- **9,342 rows** total (5,250 from 2025-10-07 + 4,092 scattered)
- All affected instruments have candles fetched **only on their expiry date**
- The GEX engine correctly marks these as `EXCLUDED`

**This is an irrecoverable API limitation.** Re-fetching via Upstox will return the same zero OI.

## Current Production Dataset (as of Phase 7.8L)

```
option_candles:  514,610
option_greeks:   514,610
historical_gex:  507,185
nifty_candles:    57,675
contract_specs:   20,584

Timestamps:      12,390
GEX SUCCESS:    497,991
GEX EXCLUDED:     9,194

Quality Score:      94.2
Classification:     GOOD
```

### Key Metrics

```
OI Coverage:              98.18%
GEX Success Rate:         98.19%
Timestamp Coverage:      100.00%
Numerical Validity:      100.00%
CE/PE Balance:            99.95%
Chain Completeness:       98.98%
```

### Exclusion Breakdown

```
ZERO_OI:  9,194 rows (100% of excluded)
  ├── 2025-10-07 expiry: 5,250 rows (57.1%)
  └── 26 weekly expiries: 4,092 rows (42.9%)
```

## API Endpoint

```
GET /gex/data-quality
```

Query parameters:
- `startDate` — ISO date filter (inclusive)
- `endDate` — ISO date filter (inclusive)

Returns a comprehensive JSON report including score, classification, metrics, exclusions, affected expiries, and warnings.

## File Locations

```
backend/app/services/gex_data_quality.py    — Quality engine
backend/app/routers/historical_gex.py       — API endpoint (GET /gex/data-quality)
backend/tests/test_gex_data_quality.py      — Test suite (26 tests)
docs/GEX_DATA_QUALITY_CONTRACT.md           — This document
```

## Test Coverage

26 isolated tests covering:
- Empty database
- Perfect quality dataset
- Missing/zero OI
- Missing spot
- Incomplete chain
- CE/PE balance
- Numerical validity
- Score calculation and capping
- Classification boundaries
- Expiry-day exclusions
- Date filtering
- Mixed quality datasets
- Report structure
- Production DB protection
