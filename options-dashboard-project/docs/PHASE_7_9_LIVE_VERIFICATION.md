# Phase 7.9 — Live Upstox API Verification Report

**Date:** 2025-08-23
**Status:** PASS
**Server:** localhost:8000 (development only)

---

## Executive Summary

Phase 7.9 verified our Phase 7.8 implementation against the **real production Upstox API** using an authenticated user session. All three verification sections passed:

1. **Historical Candle API** — 125 NIFTY 3-minute candles for 2025-08-20 successfully fetched, normalized, validated, and persisted.
2. **Expired Contract API** — 202 contracts for 2025-04-17 and 230 contracts for 2024-10-31 successfully retrieved with **different historical lot sizes (75 vs 25)**.
3. **Database Round-Trip** — Complete pipeline verified: API → normalize → validate → persist → read back.

**Key finding:** The Upstox Expired Option Contracts API provides authoritative historical lot-size data. NIFTY contracts from 2024-10-31 have `lot_size=25`, while contracts from 2025-04-17 have `lot_size=75`. Our system preserves these exact values.

---

## 1. Historical Candle API

### Configuration
- **Endpoint:** `GET /v3/historical-candle/NSE_INDEX|Nifty 50/minutes/3/2025-08-20/2025-08-20`
- **Instrument:** `NSE_INDEX|Nifty 50`
- **Date:** 2025-08-20 (Wednesday, regular NSE trading day)
- **Interval:** 3-minute candles
- **from_date:** Explicitly set to `2025-08-20` (same as to_date for single-day verification)

### Results
| Metric | Value |
|---|---|
| HTTP status | 200 OK |
| Raw candle count | **125** |
| Normalized count | **125** |
| Validation valid | **125** |
| Validation invalid | **0** |
| Warning total | **125** (all ZERO_VOLUME) |
| API native order | **descending** (newest first) |
| API order valid | **true** (descending is valid) |
| Normalized order | **descending** (normalization preserves raw order) |
| Duplicates | **false** |
| Unique timestamps | 125 |

### Timestamps
- **Format:** `2025-08-20T09:15:00+05:30` (IST, UTC+5:30)
- **+05:30 present:** Yes
- **Normalized Z suffix:** Yes (`2025-08-20T03:45:00Z`)
- **First candle:** 09:15 IST (market open)
- **Last candle:** 15:27 IST (near market close)

### Field Types
| Field | Actual Type |
|---|---|
| timestamp | str |
| open | float |
| high | float |
| low | float |
| close | float |
| volume | int |
| open_interest | int |

### ZERO_VOLUME Warning Analysis

All 125 candles received a `ZERO_VOLUME` soft validation warning. This is **not a hard error** — all candles are valid and were persisted.

**Root cause:** The Upstox V3 Historical Candle API returns `volume=0` and `open_interest=0` for NIFTY **index** candles. This is expected behavior — NIFTY 50 is a price-weighted index, not a tradeable instrument. Index candle volume/OI is fundamentally different from option-contract volume/OI.

**Impact:** None. The candle pipeline processes these candles correctly. Volume is stored as `0.0`. The warning is informational and does not affect data quality for research purposes.

### Candle Ordering

Upstox returns historical candles in **descending order** (newest first). This is the documented API behavior. Our system:

- Accepts descending order as valid (`api_order_is_valid: true`)
- `normalize_candles()` preserves the raw order
- Database queries use `.order_by(NiftyCandle.open_time.asc())`, so downstream consumers always receive ascending data
- `record_candles()` upserts are order-independent

---

## 2. Expired Contract API — Current Period (2025-04-17)

### Configuration
- **Endpoint:** `GET /v2/expired-instruments/option/contract?instrument_key=NSE_INDEX|Nifty 50&expiry_date=2025-04-17`
- **Expiry:** 2025-04-17 (monthly expiry)

### Results
| Metric | Value |
|---|---|
| Contract count | **202** |
| CE count | **101** |
| PE count | **101** |
| Unique lot sizes | **[75]** |
| Lot sizes vary | false |
| Available expiries | 99 |

### Field Verification
All 14 expected fields present and correctly typed:

| Field | Present | Actual Type | Example | Matches Expected |
|---|---|---|---|---|
| instrument_key | yes | str | `NSE_FO|47983|17-04-2025` | yes |
| trading_symbol | yes | str | `NIFTY 20400 PE 17 APR 25` | yes |
| expiry | yes | str | `2025-04-17` | yes |
| strike_price | yes | float | `20400.0` | yes |
| instrument_type | yes | str | `PE` | yes |
| lot_size | yes | int | `75` | yes |
| minimum_lot | yes | int | `75` | yes |
| freeze_quantity | yes | **float** | `1800.0` | yes (number) |
| tick_size | yes | float | `5.0` | yes |
| underlying_key | yes | str | `NSE_INDEX|Nifty 50` | yes |
| underlying_symbol | yes | str | `NIFTY` | yes |
| segment | yes | str | `NSE_FO` | yes |
| exchange | yes | str | `NSE` | yes |
| weekly | yes | bool | `true` | yes |

### freeze_quantity Type Note

The Upstox API returns `freeze_quantity` as a JSON number, which may be serialized as `1800` (int) or `1800.0` (float) depending on the server. In this run, it was `1800.0` (float). The verification accepts this via the `"number"` type expectation, which matches both int and float. The database stores it as Integer via SQLAlchemy automatic conversion.

---

## 3. Expired Contract API — Historical Period (2024-10-31)

### Configuration
- **Endpoint:** `GET /v2/expired-instruments/option/contract?instrument_key=NSE_INDEX|Nifty 50&expiry_date=2024-10-31`
- **Expiry:** 2024-10-31 (monthly expiry, pre-November-2024 lot-size change)

### Results
| Metric | Value |
|---|---|
| Contract count | **230** |
| CE count | **115** |
| PE count | **115** |
| Unique lot sizes | **[25]** |
| Lot sizes vary | false |

### Historical Lot-Size Verification

| Expiry | lot_size | Sample Contract |
|---|---|---|
| 2024-10-31 | **25** | `NIFTY 22250 PE 31 OCT 24` (`NSE_FO|48891|31-10-2024`) |
| 2025-04-17 | **75** | `NIFTY 20400 PE 17 APR 25` (`NSE_FO|47983|17-04-2025`) |

**This is the most critical finding of Phase 7.9:**

1. The Upstox Expired Option Contracts API **does** provide historical lot-size variation.
2. NIFTY lot_size was **25** in October 2024 and **75** in April 2025.
3. Different historical lot sizes coexist across different `instrument_key` values.
4. Our system architecture correctly preserves the exact `lot_size` returned by Upstox.
5. No current lot-size fallback is needed or used.

### Implication for System Architecture

The `ContractSpec` model's instrument_key-based lookup correctly handles historical lot-size variation:

- `get_contract_specification("NSE_FO|48891|31-10-2024")` → `lot_size=25`
- `get_contract_specification("NSE_FO|47983|17-04-2025")` → `lot_size=75`

Each instrument carries its own authoritative historical lot_size. No date-based interpolation or hardcoded timeline is needed.

---

## 4. Database Round-Trip

### Configuration
- In-memory SQLite database (test isolation)
- 125 real candles from Upstox API
- 3 synthetic contract metadata records (lot_sizes: 75, 50, 25)

### Results
| Metric | Value |
|---|---|
| Candles persisted | **125** |
| Contracts persisted | **3** |
| Immutability verified | **true** (overwrite attempt rejected) |
| openTime Z suffix | **true** |
| OHLCV fields preserved | **true** |
| DB read-back Z suffix | **true** |

### Contract Metadata Immutability

| Operation | lot_size before | lot_size after | Action |
|---|---|---|---|
| Insert (TEST_A) | n/a | 75 | inserted |
| Insert (TEST_B) | n/a | 50 | inserted |
| Insert (TEST_C) | n/a | 25 | inserted |
| Overwrite attempt (TEST_A) | 75 | **75** | conflict (not overwritten) |

The immutability rule is verified: once a lot_size is stored, it cannot be silently replaced.

---

## 5. Credential Security

| Check | Result |
|---|---|
| Access token in response | **CLEAN** — not present |
| API key in response | **CLEAN** — not present |
| API secret in response | **CLEAN** — not present |
| Session ID in response | **CLEAN** — not present |
| OAuth code in response | **CLEAN** — not present |

---

## 6. API Contract Documentation

### V3 Historical Candle API
- **Endpoint:** `GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}[/{from_date}]`
- **Authentication:** Bearer token required
- **from_date behavior:** Optional. When omitted, returns ~1 month of data before to_date.
- **Ordering:** Descending (newest first)
- **Timestamp format:** ISO 8601 with IST offset (`+05:30`)
- **Volume for index candles:** Returns 0 (index is not tradeable)
- **Rate limits:** 50/sec, 500/min, 2000/30min

### V2 Expired Option Contracts API
- **Endpoint:** `GET /v2/expired-instruments/option/contract?instrument_key={key}&expiry_date={date}`
- **Authentication:** Bearer token required
- **Plan requirement:** Upstox Plus (error UDAPI1149 if not subscribed)
- **Date coverage:** ~99 expiry dates available (at least Oct 2024 to present)
- **freeze_quantity type:** JSON number (may be int or float)
- **lot_size:** Authoritative per-instrument historical value

### V2 Expired Expiries API
- **Endpoint:** `GET /v2/expired-instruments/expiries?instrument_key={key}`
- **Returns:** Array of YYYY-MM-DD expiry date strings
- **Coverage:** ~99 expiry dates

---

## 7. Confirmed vs Assumed

| Item | Status |
|---|---|
| V3 historical candle response structure | **CONFIRMED** from real API |
| Timestamp format +05:30 | **CONFIRMED** from real API |
| Volume=0 for index candles | **CONFIRMED** from real API |
| Descending candle order | **CONFIRMED** from real API |
| V2 expired contract response structure | **CONFIRMED** from real API |
| freeze_quantity as float | **CONFIRMED** from real API |
| Historical lot_size=25 (Oct 2024) | **CONFIRMED** from real API |
| Historical lot_size=75 (Apr 2025) | **CONFIRMED** from real API |
| Different lot sizes across expiries | **CONFIRMED** from real API |
| ~99 expiry dates available | **CONFIRMED** from real API |
| Upstox Plus plan required for expired contracts | **CONFIRMED** (user has Plus) |

---

## 8. Discrepancies Found

| # | Item | Expected | Actual | Action |
|---|---|---|---|---|
| 1 | NIFTY lot_size Oct 2024 | Possibly 50 | **25** | Document as real finding |
| 2 | freeze_quantity type | int | float (1800.0) | Accept via "number" type |
| 3 | Index candle volume | Unknown | 0 (all candles) | Document as expected behavior |

---

## 9. No Production Code Changes Required

All Phase 7.8 production code remains untouched. The findings confirm our architecture is correct:

- Candle pipeline is lot-size independent ✓
- Contract metadata preserves authoritative Upstox lot_size ✓
- Immutability rules work correctly ✓
- No current-lot-size fallback exists ✓
- Historical lot sizes coexist across instrument_keys ✓

---

*Report generated by Phase 7.9 live verification. No credentials are included.*
