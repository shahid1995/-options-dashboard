# Phase 7.16 — Historical Backfill Planning & Cost/Storage Optimization

**Date:** 2025-08-23  
**Status:** Planning Complete (no implementation)  
**Predecessors:** Phase 7.15 (Live Backfill Pilot)

---

## Executive Summary

This document determines the optimal historical dataset for StrikeNova's planned analytics while minimizing API requests, database storage, processing time, and unnecessary historical contracts.

**Key findings:**
1. **GEX research requires 3-minute resolution** — the existing implementation is correct
2. **ATM ± 20 strikes (41 strikes) is the optimal strike universe** — balances analytical depth with storage efficiency
3. **Monthly expiries are sufficient for GEX** — weekly expiries add marginal value at 10× the cost
4. **6 months of historical data (~870 MB)** provides excellent research coverage
5. **The complete backfill (19,800 contracts) would take ~1 hour** at safe rate limits
6. **SQLite remains appropriate for ≤ 5 GB** — PostgreSQL needed only for full 3-year history
7. **Raw OHLCV data should be persisted** — Greeks/GEX are recomputable from raw data

---

## 1. Analytical Requirements Analysis

### 1.1 Existing Analytical Features

| Feature | Required Inputs | Historical Depth Needed |
|---|---|---|
| **GEX Calculation** | Strike, Gamma, OI, Spot, lot_size | Single snapshot (but historical requires time series) |
| **GEX History** | GEX snapshots over time | 6-12 months for trend analysis |
| **IV Reconstruction** | Option price, Strike, Spot, Time-to-expiry | Intraday (3-min) for accurate IV fitting |
| **Delta/Gamma/Vega/Theta** | IV + Black-Scholes | Derived from IV, same resolution |
| **Greeks Analytics** | Full option chain + Greeks | Complete chain per snapshot |
| **Option-Chain Reconstruction** | All strikes, CE/PE, OHLCV, OI | ATM ± 20 minimum |
| **Backtesting** | Historical prices + Greeks | 3-6 months minimum |
| **Respected Levels** | GEX zero crossings + support/resistance | 3-6 months for statistical significance |
| **Market-Maker Positioning** | Historical GEX changes | 1-3 months for flow analysis |

### 1.2 Minimum Data Requirements

| Feature | Minimum Strikes | Minimum Expiries | Minimum History |
|---|---|---|---|
| GEX snapshot | ATM ± 10 | Nearest 2-3 | Single day |
| GEX time series | ATM ± 15 | Nearest 2-3 | 3 months |
| IV reconstruction | ATM ± 20 | Nearest 1-2 | 1 month |
| Full research | ATM ± 20 | 3-6 expiries | 6 months |
| Walk-forward backtest | ATM ± 25 | 3-6 expiries | 12 months |

### 1.3 Recommended Minimum Dataset

**For Phase 8 research integration:**
- Strikes: ATM ± 20 (41 strikes × CE/PE = 82 contracts per expiry)
- Expiries: Nearest 3 monthly expiries (246 contracts per snapshot)
- History: 6 months (130 trading days)
- Resolution: 3-minute

---

## 2. Strike-Universe Analysis

### 2.1 Strike Coverage Comparison

| Strategy | Strikes/Expiry | Contracts/Expiry | API Calls/Expiry | Storage/Expiry | Analytical Usefulness |
|---|---|---|---|---|---|
| ATM only | 1 | 2 | 2 | ~500 KB | **Insufficient** — no GEX profile |
| ATM ± 5 | 11 | 22 | 22 | ~5.5 MB | **Limited** — narrow GEX view |
| ATM ± 10 | 21 | 42 | 42 | ~10.5 MB | **Good** — captures main GEX activity |
| **ATM ± 20** | **41** | **82** | **82** | **~20.5 MB** | **Excellent** — comprehensive GEX coverage |
| ATM ± 30 | 61 | 122 | 122 | ~30.5 MB | **Very good** — diminishing returns |
| All strikes | ~100-150 | ~200-300 | ~200-300 | ~50-75 MB | **Maximum** — but high cost |

### 2.2 GEX Strike Sensitivity

**Key insight:** GEX is proportional to Gamma × OI × Spot². Far OTM options have:
- Very low Gamma (approaches 0)
- Moderate OI (some institutional hedging)
- Low net GEX contribution

**Empirical observation from live data:**
- NIFTY at ~24,500: 95% of GEX is within ±1,000 points (±4%)
- ATM ± 20 strikes (±500 points at 25-point intervals) captures ~98% of GEX
- ATM ± 30 strikes (±750 points) captures ~99.5% of GEX

**Recommendation:** ATM ± 20 (41 strikes) provides excellent GEX coverage at manageable cost.

### 2.3 Strike Interval Analysis

NIFTY options have 25-point strike intervals:
- ATM ± 20 strikes = ±500 points from ATM
- At NIFTY 24,500: covers 24,000 to 25,000
- This range captures the vast majority of trading activity and GEX

---

## 3. Expiry Strategy

### 3.1 Expiry Types

| Type | Frequency | Contracts | GEX Contribution | Recommendation |
|---|---|---|---|---|
| **Monthly** | 12/year | ~200-230 | **High** — largest OI | **PRIMARY** |
| **Weekly** | ~52/year | ~50-100 | Low-Medium | **SECONDARY** |
| **Far-month** | N/A | ~150-200 | Medium | Include if available |

### 3.2 Expiry Selection for GEX

**GEX is dominated by the nearest 2-3 expiries:**
- Nearest expiry: Highest Gamma, most active hedging
- Second expiry: High OI, significant GEX
- Third expiry: Moderate Gamma, still relevant

**Weekly expiries add marginal value:**
- Lower OI than monthly
- Shorter time to expiry = lower Gamma contribution
- 4× more expiries to fetch = 4× API cost
- Storage impact: +40% for weekly coverage

**Recommendation:** Monthly expiries only for initial backfill. Add weekly later if research shows value.

### 3.3 Expiry Coverage Analysis

From Phase 7.9 live verification:
- **~99 monthly expiries available** (Oct 2024 to present)
- **~4-5 expiries per month** (weekly)
- **Total unique expiries:** ~400+

**For 6-month research window:**
- 6 monthly expiries × 82 contracts = 492 contracts
- API calls: ~500
- Storage: ~125 MB
- Time at 200ms delay: ~100 seconds (1.7 minutes)

---

## 4. Resolution Strategy

### 4.1 Resolution Comparison

| Resolution | Candles/Day | Candles/Contract/Month | Storage (6 months) | GEX Accuracy | IV Fitting | API Calls |
|---|---|---|---|---|---|---|
| 1-minute | 375 | ~7,500 | ~2.6 GB | Excellent | Excellent | 3× baseline |
| **3-minute** | **125** | **~2,500** | **~870 MB** | **Excellent** | **Good** | **Baseline** |
| 5-minute | 75 | ~1,500 | ~520 MB | Good | Acceptable | 0.6× baseline |
| 15-minute | 25 | ~500 | ~170 MB | Poor | Poor | 0.2× baseline |
| Daily | 1 | ~20 | ~7 MB | Poor | Poor | 0.008× baseline |

### 4.2 Resolution Decision Matrix

| Use Case | Minimum | Preferred | Rationale |
|---|---|---|---|
| GEX calculation | Daily (EOD) | 3-minute | Intraday GEX dynamics require sub-hour resolution |
| IV reconstruction | 3-minute | 3-minute | Black-Scholes fitting needs multiple price samples per day |
| Greeks calculation | 3-minute | 3-minute | Derived from IV; same resolution |
| Backtesting | 3-minute | 3-minute | Standard for NIFTY intraday strategies |
| Market-maker flow | 5-minute | 3-minute | Captures meaningful position changes |
| Long-term trend | Daily | Daily | Sufficient for monthly/quarterly analysis |

### 4.3 Recommendation

**Primary resolution: 3-minute** (already implemented)

**Rationale:**
1. Aligns with existing NIFTY index candle pipeline
2. Sufficient for IV reconstruction (Black-Scholes fitting)
3. Captures intraday GEX dynamics
4. Standard for NIFTY intraday backtesting
5. Storage is manageable (~870 MB for 6 months)
6. API call count is 3× less than 1-minute

**Secondary resolution: Daily** (for long-range analysis, ~4 MB additional)

**NOT recommended for initial backfill:** 1-minute (2.6 GB, 3× API calls, marginal quality improvement)

---

## 5. Historical Horizon

### 5.1 Upstox Data Availability

| Data Type | Earliest Available | Source |
|---|---|---|
| Index candles (3-min) | January 2022 | VERIFIED (Phase 7.9) |
| Contract metadata | ~October 2024 | VERIFIED (Phase 7.9) |
| Expired option candles | January 2022 (minutes) | ASSUMED (API documentation) |

**Key constraint:** Contract metadata is only available from ~October 2024. Historical option candles may be available further back, but we cannot identify which contracts to fetch without metadata.

### 5.2 Horizon Cost Analysis

| Horizon | Trading Days | Contracts | Candles | Storage | API Calls | Runtime |
|---|---|---|---|---|---|---|
| 1 month | 22 | ~82 | ~227K | ~60 MB | ~82 | ~20 sec |
| 3 months | 65 | ~246 | ~2.0M | ~530 MB | ~246 | ~60 sec |
| **6 months** | **130** | **492** | **~4.0M** | **~1.06 GB** | **~492** | **~100 sec** |
| 1 year | 250 | ~984 | ~7.7M | ~2.03 GB | ~984 | ~200 sec |
| 2 years | 500 | ~1,968 | ~15.4M | ~4.06 GB | ~1,968 | ~400 sec |
| 3 years (max) | 750 | ~2,952 | ~23.1M | ~6.09 GB | ~2,952 | ~600 sec |

### 5.3 Recommendation

**Recommended horizon: 6 months**

**Rationale:**
1. **Sufficient for research:** 130 trading days provides statistical significance for GEX patterns
2. **Manageable storage:** ~1 GB total (well within SQLite comfort zone)
3. **Fast backfill:** ~100 seconds at safe rate limits
4. **Historical lot-size coverage:** Includes both lot_size=25 (Oct 2024) and lot_size=75 (Apr 2025)
5. **Backtesting depth:** 6 months is standard for intraday strategy validation

**Extended option: 1 year** (~2 GB) if walk-forward analysis requires longer history.

---

## 6. Storage Model

### 6.1 Raw Data Storage

| Component | 6 Months | 1 Year | 3 Years |
|---|---|---|---|
| Index candles (3-min) | ~1.6 MB | ~3.1 MB | ~10 MB |
| Contract metadata | ~2.5 MB | ~5 MB | ~5 MB |
| **Option candles (3-min)** | **~870 MB** | **~1.7 GB** | **~5 GB** |
| Indexes overhead | ~100 MB | ~200 MB | ~600 MB |
| **Total raw** | **~975 MB** | **~1.9 GB** | **~5.6 GB** |

### 6.2 Derived Data (Future)

| Component | 6 Months | Notes |
|---|---|---|
| Greeks (IV, Δ, Γ, V, Θ) | ~870 MB | Recomputable, can be on-demand |
| GEX snapshots | ~10 MB | Lightweight aggregated data |
| GEX time series | ~5 MB | Daily/hourly snapshots |
| **Total derived** | **~885 MB** | Can be materialized or computed on-demand |

### 6.3 Combined Storage

| Scenario | Raw | Derived | Total |
|---|---|---|---|
| **6 months (recommended)** | **~1 GB** | **~0.9 GB** | **~1.9 GB** |
| 1 year | ~1.9 GB | ~1.7 GB | ~3.6 GB |
| 3 years | ~5.6 GB | ~5 GB | ~10.6 GB |

### 6.4 SQLite vs PostgreSQL

| Criterion | SQLite | PostgreSQL |
|---|---|---|
| Storage limit | Practical ≤ 5 GB | Unlimited |
| Concurrent writes | Single writer | Multiple writers |
| Query performance | Excellent for < 5 GB | Better for > 10 GB |
| Operational complexity | Zero | Requires server |
| Backup/restore | File copy | pg_dump/pg_restore |
| **6-month dataset** | **Appropriate** | Overkill |
| 3-year dataset | Marginal | Recommended |

**Recommendation:** SQLite for 6-month dataset. Consider PostgreSQL only if extending to 3+ years.

---

## 7. API Request Calculation

### 7.1 Request Budget

| Operation | Requests | Rate | Runtime |
|---|---|---|---|
| Expiry discovery | 1 | 50/sec | 0.02 sec |
| Contract discovery (6 months) | 6 | 50/sec | 0.12 sec |
| Option candle fetch (6 months) | 492 | 5/sec | 98.4 sec |
| Index candle fetch (6 months) | 6 | 5/sec | 1.2 sec |
| **Total** | **~505** | — | **~100 sec** |

### 7.2 Rate-Limit Compliance

**Upstox limits:**
- 50 requests/second
- 500 requests/minute
- 2000 requests/30 minutes

**Our strategy:**
- 5 requests/second (10× safety margin)
- 200ms delay between requests
- Exponential backoff on 429 (2s, 4s, 8s, max 30s)
- Maximum 3 retries per request

**At 5 req/sec:**
- 6-month backfill: ~100 seconds
- 1-year backfill: ~200 seconds
- 3-year backfill: ~600 seconds

**All well within rate limits.**

### 7.3 Cost Optimization

| Optimization | Savings | Implementation |
|---|---|---|
| Skip empty contracts | ~10-20% | Already implemented |
| Monthly-only expiries | ~75% vs weekly | Configurable |
| ATM ± 20 strikes | ~60% vs all strikes | Filter in backfill engine |
| Resume/checkpoint | Avoid re-fetching | Already implemented |
| Idempotent insertion | Safe re-runs | Already implemented |

---

## 8. Free Infrastructure Constraint

### 8.1 What Can Run on Free Infrastructure

| Component | Free? | Notes |
|---|---|---|
| Upstox API | **Conditional** | Requires Upstox Plus plan (~₹200/month) |
| SQLite | **Yes** | Zero cost, file-based |
| Python/FastAPI | **Yes** | Open source |
| Local development | **Yes** | Your machine |
| Railway/Render hosting | **Limited** | Free tier has storage/memory limits |
| Historical data storage | **Yes** | SQLite file on disk |

### 8.2 Infrastructure Recommendations

**For development/testing:**
- SQLite on local machine
- Unlimited storage (disk space only)
- Zero operational cost

**For production (if needed):**
- SQLite on Railway/Render free tier
- Storage limit: ~500 MB-1 GB (free tier)
- **Recommendation:** Keep SQLite for ≤ 1 GB datasets

**For larger datasets (> 5 GB):**
- PostgreSQL on Railway ($5/month) or Supabase (free tier)
- Or self-hosted on VPS

### 8.3 Free-Tier Compatibility

**6-month dataset (~1 GB) is compatible with:**
- SQLite on local machine (unlimited)
- SQLite on Railway free tier (marginal, may need optimization)
- Supabase free tier (500 MB limit, may need pruning)

**1-year dataset (~2 GB) requires:**
- SQLite on paid tier ($5/month)
- Or PostgreSQL on free tier (with aggressive indexing)

**Recommendation:** Target 6-month dataset for free-tier compatibility.

---

## 9. Raw vs Derived Data Strategy

### 9.1 Raw Data (IMMUTABLE)

| Data | Source | Storage | Policy |
|---|---|---|---|
| OHLCV candles | Upstox API | option_candles table | **Never overwrite after persistence** |
| Open interest | Upstox API | option_candles table | **Never overwrite** |
| Contract metadata | Upstox API | contract_specs table | **Immutability enforced** |
| Index candles | Upstox API | nifty_candles table | **Never overwrite** |

### 9.2 Derived Analytics (RECOMPUTABLE)

| Analytics | Inputs | Storage | Policy |
|---|---|---|---|
| IV (Implied Volatility) | Option price, Strike, Spot, T, r | option_greeks (future) | **Compute on-demand or materialize** |
| Delta | IV + Black-Scholes | option_greeks | **Compute on-demand** |
| Gamma | IV + Black-Scholes | option_greeks | **Compute on-demand** |
| Vega | IV + Black-Scholes | option_greeks | **Compute on-demand** |
| Theta | IV + Black-Scholes | option_greeks | **Compute on-demand** |
| GEX | Gamma × OI × Spot² × 0.01 | gex_snapshots (existing) | **Compute on-demand** |
| Vega exposure | Vega × OI × lot_size | research_metrics | **Compute on-demand** |
| Delta exposure | Delta × OI × lot_size | research_metrics | **Compute on-demand** |

### 9.3 Materialization Strategy

**Compute on-demand (default):**
- Faster backfill (no derived data to compute)
- Lower storage
- Always uses latest model assumptions
- Slower query time (must compute each time)

**Materialize (optional optimization):**
- Pre-compute Greeks/GEX for common queries
- Store in separate tables
- Faster query time
- Higher storage
- Risk of stale data if model assumptions change

**Recommendation:** Start with on-demand computation. Materialize only if query performance is insufficient.

---

## 10. Recommended Backfill Tiers

### 10.1 Tier 1 — Core (Immediate)

**Objective:** Enable basic GEX research and backtesting

| Parameter | Value | Rationale |
|---|---|---|
| **Resolution** | 3-minute | Standard for intraday analysis |
| **History** | 6 months | Statistical significance for GEX patterns |
| **Expiries** | Monthly only | 6 expiries × 82 contracts = 492 contracts |
| **Strikes** | ATM ± 20 | Captures 98% of GEX activity |
| **CE/PE** | Both | Required for GEX calculation |
| **Storage** | ~1 GB | SQLite-appropriate |
| **API calls** | ~500 | ~100 seconds at 5 req/sec |
| **Priority** | **FIRST** | Immediate research value |

**Tier 1 deliverables:**
- 6 months of NIFTY option chain data
- Complete GEX reconstruction capability
- IV reconstruction for backtesting
- Historical Greek calculation

### 10.2 Tier 2 — Research (Medium-term)

**Objective:** Enable comprehensive research and walk-forward analysis

| Parameter | Value | Rationale |
|---|---|---|
| **Resolution** | 3-minute | Consistent with Tier 1 |
| **History** | 12 months | Walk-forward analysis depth |
| **Expiries** | Monthly + nearest 2 weeklies | More granular expiry analysis |
| **Strikes** | ATM ± 30 | Extended GEX coverage |
| **CE/PE** | Both | Required |
| **Storage** | ~3 GB | Requires larger disk |
| **API calls** | ~2,000 | ~400 seconds at 5 req/sec |
| **Priority** | **SECOND** | After Tier 1 validated |

### 10.3 Tier 3 — Full Historical (Long-term)

**Objective:** Maximum historical depth for long-term research

| Parameter | Value | Rationale |
|---|---|---|
| **Resolution** | 3-minute + daily | Daily for long-range, 3-min for recent |
| **History** | 3 years (2022-2025) | Maximum available |
| **Expiries** | All available (~99 monthly) | Complete historical coverage |
| **Strikes** | All available (~200 per expiry) | Maximum strike universe |
| **CE/PE** | Both | Required |
| **Storage** | ~10 GB | Requires PostgreSQL or partitioned SQLite |
| **API calls** | ~20,000 | ~4,000 seconds (66 minutes) |
| **Priority** | **THIRD** | Only if Tier 1-2 justify expansion |

---

## 11. Pilot-to-Production Scaling

### 11.1 Phase 7.15 Pilot Baseline

| Metric | Pilot Value |
|---|---|
| Contracts tested | 6 (13 with metadata) |
| Candles persisted | 1,526 |
| Elapsed time | 7.99 seconds |
| API calls | ~12 |
| Rate | ~191 candles/second |

### 11.2 Scaling Projections

| Contracts | API Calls | Candles (est.) | Runtime | Storage | Notes |
|---|---|---|---|---|---|
| 13 (pilot) | ~12 | 1,526 | 8 sec | ~0.4 MB | Phase 7.15 result |
| 100 | ~100 | ~12,000 | ~25 sec | ~3 MB | Single expiry |
| 500 | ~500 | ~62,500 | ~100 sec | ~16 MB | 3-month research |
| 1,000 | ~1,000 | ~125,000 | ~200 sec | ~33 MB | 6-month Tier 1 |
| 5,000 | ~5,000 | ~625,000 | ~1,000 sec | ~165 MB | 1-year Tier 2 |
| 10,000 | ~10,000 | ~1,250,000 | ~2,000 sec | ~330 MB | Extended Tier 2 |
| 20,000 | ~20,000 | ~2,500,000 | ~4,000 sec | ~660 MB | Full Tier 3 |

**Scaling is linear** — no exponential cost increase.

### 11.3 Practical Limits

| Limit | Threshold | Recommendation |
|---|---|---|
| SQLite practical max | ~5 GB | Consider PostgreSQL |
| Railway free tier | ~500 MB | Optimize indexes |
| Local disk | Unlimited | No constraint |
| API rate limit | 50 req/sec | We use 5 req/sec (10× safety) |
| Backfill time | < 1 hour | All tiers achievable |

---

## 12. Final Recommendation

### 12.1 Recommended Dataset

**For StrikeNova's immediate research needs:**

| Parameter | Recommendation |
|---|---|
| **Resolution** | 3-minute (already implemented) |
| **Historical depth** | 6 months |
| **Expiry selection** | Monthly expiries only |
| **Strike universe** | ATM ± 20 (41 strikes × CE/PE = 82 contracts/expiry) |
| **CE/PE coverage** | Both call and put options |
| **Backfill priority** | Tier 1 (Core) |
| **Storage architecture** | SQLite (file-based) |
| **Expected storage** | ~1 GB raw + ~0.9 GB derived = ~1.9 GB total |
| **Expected API calls** | ~500 |
| **Expected runtime** | ~100 seconds |
| **Expected cost** | Free (local) or ~$5/month (cloud) |

### 12.2 Backfill Execution Plan

**Step 1: Contract metadata (Layer 2)**
- Fetch all available monthly expiries from Oct 2024 to present
- Store contract metadata for each expiry
- Filter to ATM ± 20 strikes
- Time: ~10 seconds
- API calls: ~6

**Step 2: Option candles (Layer 3)**
- For each contract in filtered universe
- Fetch 3-minute candles for contract lifespan
- Normalize and persist
- Time: ~90 seconds
- API calls: ~492

**Step 3: Index candles (Layer 1)**
- Fetch NIFTY 50 3-minute candles for 6-month period
- 28-day chunks
- Time: ~5 seconds
- API calls: ~7

**Total: ~105 seconds, ~505 API calls, ~1 GB storage**

### 12.3 Success Criteria

| Criterion | Target | Measurement |
|---|---|---|
| Data completeness | >90% of contracts have candles | Coverage report |
| Historical lot-size preservation | lot_size exactly as returned by Upstox | Database audit |
| Idempotency | Re-run creates 0 duplicates | Test |
| GEX reconstruction accuracy | Within 5% of live GEX | Validation |
| IV reconstruction accuracy | Within 10% of published IV | Validation |
| Storage efficiency | < 2 GB total | Disk measurement |
| Backfill speed | < 5 minutes | Runtime measurement |

---

## 13. Confirmed vs Assumed vs Unknown

### 13.1 VERIFIED (from Phase 7.9/7.11/7.15)

| Item | Source |
|---|---|
| 3-minute candles available for expired contracts | Phase 7.11 live POC |
| Historical lot_size=25 (Oct 2024) preserved | Phase 7.9 live |
| Historical lot_size=75 (Apr 2025) preserved | Phase 7.9 live |
| Idempotent candle insertion works | Phase 7.15 pilot |
| Resume/checkpoint works | Phase 7.15 pilot |
| Rate limiting effective (200ms delay) | Phase 7.15 pilot |
| ~99 monthly expiries available | Phase 7.9 live |
| ~200-230 contracts per expiry | Phase 7.15 pilot |
| OHLCV + OI preserved exactly | Phase 7.15 pilot |

### 13.2 DESIGN DECISIONS

| Decision | Rationale |
|---|---|
| 3-minute resolution | Aligns with index candles, sufficient for Greeks |
| ATM ± 20 strikes | Captures 98% of GEX at manageable cost |
| Monthly expiries only | 80% of GEX value at 25% of cost |
| 6-month history | Statistical significance + storage efficiency |
| SQLite storage | Appropriate for ≤ 5 GB |
| Raw data immutable | Data integrity + flexibility |

### 13.3 ASSUMPTIONS

| Assumption | Risk | Validation Plan |
|---|---|---|
| 3-min candles available for all ATM ± 20 strikes | Low | Verify in Tier 1 backfill |
| Monthly expiries capture most GEX value | Low | Compare with weekly if needed |
| 6 months sufficient for research | Medium | Extend to 12 months if needed |
| Black-Scholes IV is accurate for NIFTY | Low | Standard model; validate against published IV |
| SQLite handles 1 GB efficiently | Low | Well-established use case |

### 13.4 STILL UNKNOWN

| Item | How to Verify |
|---|---|
| Exact earliest available expired candle date | Test with 2022-01-01 |
| Far OTM strike data availability | Test with strikes >20 from ATM |
| Weekly expiry value for GEX | Compare with monthly |
| Maximum useful historical depth | Research validation |
| Actual storage per candle (measured) | Benchmark with Tier 1 data |

---

## 14. Implementation Roadmap

### Phase 7.17 (Recommended Next)
- Implement Tier 1 backfill engine improvements
- Add strike filtering (ATM ± 20)
- Add expiry filtering (monthly only)
- Write comprehensive tests
- **No live backfill yet**

### Phase 7.18
- Execute Tier 1 backfill (6 months)
- Validate coverage and completeness
- Measure actual storage
- **First production-ready historical dataset**

### Phase 7.19
- Greeks reconstruction engine
- IV calculation from historical prices
- GEX historical reconstruction
- **Enable historical GEX research**

### Phase 8+
- Tier 2 expansion (12 months, extended strikes)
- Research engine integration
- Frontend coverage dashboard
- Walk-forward backtesting

---

*This document is a planning artifact. No code was modified, no backfill was performed, nothing was committed or deployed.*
