# Phase 7.10 — Historical Data Coverage & Backfill Architecture

**Date:** 2025-08-23
**Status:** Read-Only Investigation (no implementation)
**Phase 7.9:** CLOSED

---

## Executive Summary

This document maps the complete Upstox historical data landscape available for our NIFTY research system, based on live API verification (Phase 7.9), codebase audit, and Upstox documentation research.

**Key discoveries:**
1. **Expired Historical Candle Data API** — Upstox provides OHLC candles for individual expired option contracts. This is the missing piece for historical option-chain reconstruction.
2. **Historical lot-size variation confirmed** — lot_size=25 (Oct 2024) vs lot_size=75 (Apr 2025) from real API.
3. **Index candles from Jan 2022** — V3 API provides 3-minute NIFTY candles back to January 2022.
4. **Option contract metadata for ~99 expiries** — spanning approximately Oct 2024 to present.
5. **Storage is the primary constraint** — full historical option-chain reconstruction requires ~5–10 GB.

---

## 1. Upstox API Inventory

### 1.1 APIs Already Integrated (Phase 7.8)

| API | Endpoint | Status | Purpose |
|---|---|---|---|
| V3 Historical Candle | `GET /v3/historical-candle/{key}/{unit}/{interval}/{to_date}[/{from_date}]` | Integrated | Index OHLC candles |
| V3 Intraday Candle | `GET /v3/historical-candle/intraday/{key}/{unit}/{interval}` | Integrated | Current day candles |
| V2 Expired Expiries | `GET /v2/expired-instruments/expiries?instrument_key={key}` | Integrated | Available expiry dates |
| V2 Expired Option Contracts | `GET /v2/expired-instruments/option/contract?instrument_key={key}&expiry_date={date}` | Integrated | Contract metadata |

### 1.2 APIs NOT Yet Integrated (Discovered in Phase 7.10)

| API | Endpoint | Status | Purpose |
|---|---|---|---|
| **V2 Expired Historical Candle** | `GET /v2/expired-instruments/historical-candle/{expired_key}/{interval}/{to_date}/{from_date}` | **NOT integrated** | **OHLC for individual expired option contracts** |
| V2 Expired Future Contracts | `GET /v2/expired-instruments/future/contract?instrument_key={key}&expiry_date={date}` | NOT integrated | Future contract metadata |

**The Expired Historical Candle API is the critical missing piece for option-chain reconstruction.**

---

## 2. Historical Data Availability

### 2.1 V3 Index Candle Data (NIFTY 50)

| Unit | Interval | Historical Depth | Max Retrieval Window |
|---|---|---|---|
| minutes | 1–15 | January 2022 | 1 month |
| minutes | 16–300 | January 2022 | 1 quarter |
| hours | 1–5 | January 2022 | 1 quarter |
| days | 1 | January 2000 | 1 decade |
| weeks | 1 | January 2000 | Unlimited |
| months | 1 | January 2000 | Unlimited |

**Verified from live API:** 3-minute candles from 2022-01-01 to present = ~3.5 years of data.

### 2.2 Expired Option Contract Metadata

| Parameter | Value | Source |
|---|---|---|
| Available expiries | ~99 | Live verification (Phase 7.9) |
| Earliest expiry observed | 2024-10-03 | Live verification |
| Latest expiry observed | 2025-04-17 | Live verification |
| Contracts per monthly expiry | ~200–230 | Live verification |
| Lot sizes observed | 25 (Oct 2024), 75 (Apr 2025) | Live verification |
| Plan requirement | Upstox Plus | API documentation |

### 2.3 Expired Historical Candle Data (NEW DISCOVERY)

| Parameter | Value | Source |
|---|---|---|
| Endpoint | `/v2/expired-instruments/historical-candle/{expired_key}/{interval}/{to_date}/{from_date}` | API docs |
| Available intervals | 1min, 3min, 5min, 15min, 30min, day | API docs |
| Historical depth | Minutes from Jan 2022; Days from 2000 | API docs |
| Sample range | 2020-02-24 to 2025-04-24 (5+ years) | API docs sample code |
| expired_instrument_key format | `NSE_FO|{token}|{DD-MM-YYYY}` | API docs |
| Plan requirement | Upstox Plus | API docs |
| Response format | `[timestamp, open, high, low, close, volume, open_interest]` | API docs |

**This API is NOT yet integrated in our codebase.** It is the key enabler for historical option-chain reconstruction.

---

## 3. Candle Count Estimates

### 3.1 Index Candles (NIFTY 50, 3-minute)

| Period | Trading Days | Candles | Storage (est.) |
|---|---|---|---|
| 1 month | ~22 | 2,750 | ~275 KB |
| 6 months | ~130 | 16,250 | ~1.6 MB |
| 1 year | ~250 | 31,250 | ~3.1 MB |
| 3 years (2022–2025) | ~750 | 93,750 | ~9.4 MB |

**Verdict:** Index candle storage is trivially small. No concern here.

### 3.2 Option Contract Metadata

| Parameter | Estimate |
|---|---|
| Available expiries | ~99 |
| Contracts per monthly expiry | ~200–230 |
| Total contracts | ~20,000–23,000 |
| Storage per contract | ~200 bytes |
| **Total metadata** | **~4–5 MB** |

**Verdict:** Contract metadata is trivially small.

### 3.3 Option Contract Candles (THE BIG ONE)

This is the estimated storage for historical OHLC candles of individual expired option contracts.

| Parameter | Estimate | Basis |
|---|---|---|
| Expired expiries available | ~99 | Live verification |
| Contracts per expiry (CE+PE) | ~200 | Live verification |
| Total contracts needing candles | ~19,800 | 99 × 200 |
| Candles per contract (1 month lifespan) | ~2,500 | 20 trading days × 125 candles |
| **Total candles** | **~49.5 million** | 19,800 × 2,500 |
| Storage per candle (SQLite) | ~100 bytes | Based on NiftyCandle model |
| **Total storage** | **~5 GB** | Conservative estimate |

**Range estimate:** 3–10 GB depending on strike count and data availability.

### 3.4 Combined Storage

| Component | Storage |
|---|---|
| Index candles (3 years) | ~10 MB |
| Contract metadata | ~5 MB |
| Option contract candles | ~5 GB |
| **Total** | **~5 GB** |

---

## 4. API Rate Limits

### 4.1 Official Limits (from Upstox documentation)

| API Category | Per Second | Per Minute | Per 30 Minutes |
|---|---|---|---|
| Historical Candles (Standard) | 50 | 500 | 2,000 |
| Expired Instruments (Standard) | 50 | 500 | 2,000 |
| Order Placement (Regular) | 10 | 500 | 2,000 |

### 4.2 Backfill Rate-Limit Budget

For option contract candle backfill:

| Metric | Value |
|---|---|
| Total API calls needed | ~19,800 (one per contract) |
| Safe rate (10 req/sec) | 1,980 seconds = 33 minutes |
| Safe rate (5 req/sec) | 3,960 seconds = 66 minutes |
| Conservative (1 req/sec) | 19,800 seconds = 5.5 hours |
| With 28-day chunking (index) | ~30 chunks × 1 req = 30 calls = trivial |

**Index candle backfill is fast.** Option contract candle backfill requires careful rate management.

---

## 5. Backfill Architecture

### 5.1 Three-Layer Architecture

```
Layer 1: Index Candle Backfill (NIFTY 50, 3-min)
    - Upstox V3 Historical Candle API
    - 28-day chunks
    - ~30 API calls for full 3-year coverage
    - Already implemented (candle_backfill.py)

Layer 2: Contract Metadata Backfill
    - Upstox V2 Expired Expiries + Expired Option Contracts
    - ~99 API calls (one per expiry)
    - Already implemented (contract_metadata_backfill.py)

Layer 3: Option Contract Candle Backfill (NOT YET IMPLEMENTED)
    - Upstox V2 Expired Historical Candle API
    - ~19,800 API calls (one per contract)
    - Requires expired_instrument_key from Layer 2
    - Requires rate-limit management
    - PRIMARY FUTURE WORK
```

### 5.2 Data Dependencies

```
Layer 1 (Index Candles) ────────────────────────── Independent
                                                        │
Layer 2 (Contract Metadata) ──────────────────────── Independent
        │                                               │
        │ expired_instrument_key ───────────────────────┤
        │                                               │
Layer 3 (Option Candles) ──────── Depends on Layer 2 ──┘
```

### 5.3 Checkpoint/Resume Strategy

**Already implemented for Layers 1 and 2:**
- Layer 1: `_has_candles_for_date_range()` skips chunks with existing data
- Layer 2: Idempotent upsert via `upsert_contract_spec()` (conflict detection)

**Required for Layer 3:**
- Track which contracts have been fully fetched
- Store `fetched_at` timestamp on successful fetch
- Skip contracts where `fetched_at` is recent (configurable TTL)
- Store partial progress (fetched N of M contracts)

### 5.4 Idempotent Insertion

| Layer | Strategy | Implementation |
|---|---|---|
| Index candles | SQLite upsert on `(symbol, interval, open_time)` | `record_candles()` |
| Contract metadata | Upsert on `instrument_key` with lot-size immutability | `upsert_contract_spec()` |
| Option candles | **TBD** — needs design | Likely upsert on `(instrument_key, interval, open_time)` |

---

## 6. Critical Design Decisions (For Future Implementation)

### 6.1 Option Candle Table Schema

**Not yet implemented.** A new table is needed:

```
option_candles:
  - id: integer (PK)
  - instrument_key: string (indexed, FK to contract_specs)
  - interval: string (e.g., "3min")
  - open_time: datetime (indexed)
  - open, high, low, close: float
  - volume: float
  - open_interest: float
  - UniqueConstraint(instrument_key, interval, open_time)
```

Key differences from `nifty_candles`:
- `instrument_key` replaces `symbol` as the identity
- `open_interest` is preserved (relevant for options, irrelevant for index)
- `volume` is actual tradeable instrument volume (not index proxy)

### 6.2 Lot-Size Integration Point

Option GEX calculation will need:
```
spec = get_contract_specification(instrument_key)
if spec is None or spec.lot_size is None:
    mark as insufficient_metadata
else:
    historical_lot_size = spec.lot_size
```

This is the **only** point where lot_size enters the research pipeline.

### 6.3 Backfill Order

**Recommended execution order:**

1. **Layer 1** (Index Candles) — Fast, independent, immediately useful
2. **Layer 2** (Contract Metadata) — Fast, independent, prerequisite for Layer 3
3. **Layer 3** (Option Candles) — Slow, depends on Layer 2, requires rate management

### 6.4 Rate-Limit Strategy for Layer 3

```
Per-contract:
  1. Fetch expired_instrument_key from contract_specs
  2. Fetch candle data via Expired Historical Candle API
  3. Normalize and persist
  4. Sleep 200ms between requests (5 req/sec = well under 50/sec limit)
  5. If 429 received: exponential backoff (2s, 4s, 8s, max 30s)
  6. Track progress for resume
```

---

## 7. Confirmed vs Assumed vs Unknown

### 7.1 Verified from Live Upstox API (Phase 7.9)

| Item | Status |
|---|---|
| V3 index candle response structure | CONFIRMED |
| Timestamp format (+05:30, normalized to Z) | CONFIRMED |
| Volume=0 for index candles | CONFIRMED |
| Descending candle order | CONFIRMED |
| V2 expired contract response structure | CONFIRMED |
| freeze_quantity as float (1800.0) | CONFIRMED |
| Historical lot_size=25 (Oct 2024) | CONFIRMED |
| Historical lot_size=75 (Apr 2025) | CONFIRMED |
| ~99 expiry dates available | CONFIRMED |
| All 14 contract fields present | CONFIRMED |

### 7.2 Verified from Existing Code/Tests

| Item | Status |
|---|---|
| 28-day chunk generation | VERIFIED (unit tests) |
| Idempotent candle upsert | VERIFIED (unit tests) |
| Contract metadata immutability | VERIFIED (unit tests + live) |
| Retry with exponential backoff | VERIFIED (unit tests) |
| Validation (hard errors + soft warnings) | VERIFIED (unit tests) |
| Coverage calculation | VERIFIED (unit tests) |
| Candle normalization (IST→UTC) | VERIFIED (unit tests) |

### 7.3 Assumptions (Not Yet Verified)

| Item | Assumption | Risk |
|---|---|---|
| Expired Historical Candle API date range | Minutes from Jan 2022 | Medium — needs live test |
| Expired Historical Candle API response format | Same as V3 index candles | Low — documented |
| Option candle volume is non-zero | Actual tradeable instrument | Low — logically certain |
| ~200 contracts per monthly expiry | Based on live Oct 2024 data | Low — observed |
| 250 trading days/year for storage estimates | Standard NSE calendar | Low |

### 7.4 Still Unknown

| Item | Why Unknown | How to Verify |
|---|---|---|
| Exact earliest available expired candle data | Not tested live | Run test API call for 2022 |
| Whether expired candle API returns ALL strikes or a subset | Not tested | Compare contract count vs candle availability |
| Rate-limit behavior under sustained load | Not tested | Controlled backfill test |
| Actual storage per option candle in SQLite | Not measured | Benchmark with real data |
| Whether weekly expiries have different coverage | Not tested | Query weekly expiry dates |
| Whether far OTM strikes have candle data | Not tested | Query low-volume strikes |
| Upstox Plus plan coverage limits | Not documented explicitly | Test with expired contract data |

---

## 8. Recommended Next Steps (Phase 8+)

### 8.1 Immediate (Phase 8)

1. **Verify the Expired Historical Candle API** — Make a real API call for one expired NIFTY option contract to confirm response structure and date range.
2. **Design option_candles table schema** — Based on the real API response.
3. **Implement Layer 3 adapter** — `get_expired_candle()` function in `upstox.py`.
4. **Implement option candle ingestion** — Normalize and persist option candles.

### 8.2 Medium-Term (Phase 8–9)

5. **Controlled Layer 3 backfill** — Start with one expiry (2024-10-31) to validate the pipeline.
6. **Rate-limit tuning** — Measure actual throughput and adjust delay.
7. **Storage benchmarking** — Measure actual bytes per option candle.
8. **Coverage verification** — Ensure all contracts have candle data.

### 8.3 Long-Term (Phase 9+)

9. **Full historical backfill** — All 99 expiries, all contracts.
10. **GEX reconstruction** — Combine index candles + contract metadata + option candles.
11. **Research readiness** — Validate coverage meets research engine requirements.

---

## 9. Storage Requirements Summary

| Horizon | Index Candles | Contract Metadata | Option Candles | Total |
|---|---|---|---|---|
| 1 month | ~275 KB | ~5 MB | ~250 MB | ~255 MB |
| 6 months | ~1.6 MB | ~5 MB | ~1.5 GB | ~1.5 GB |
| 1 year (2024) | ~3.1 MB | ~5 MB | ~3 GB | ~3 GB |
| Full available (2022–2025) | ~10 MB | ~5 MB | ~5 GB | ~5 GB |

**Note:** Option candle estimates assume all strikes have data. Actual may be lower if Upstox doesn't return data for far OTM strikes.

---

*This document is a read-only investigation. No code was modified, no backfill was performed, nothing was committed or deployed.*
