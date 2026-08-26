# Options Dashboard — GEX Phase 7.8: Historical NIFTY Candle Data Pipeline & Contract Metadata Registry

**Date:** 2026-08-23
**Status:** Design proposal — awaiting approval
**Predecessors:** Phase 7.1–7.7
**Scope:** Populate the existing `nifty_candles` infrastructure with real 3-minute NIFTY historical data using the user's Upstox broker authorization; build the Historical Contract Metadata Registry from the Upstox Expired Option Contracts API
**Boundaries:** Data pipeline only — no trading signals, no ML, no UI redesign, no modification of Phase 7.1–7.7 calculation logic, no historical option/GEX reconstruction

---

## 1. Objective

Phase 7.7 established the research data model (`NiftyCandle`), the persistence service (`nifty_candles.py`), and the frontend research engine (observation builder, validation framework, statistical tests). However, **the `nifty_candles` table is empty** — no real data exists.

Phase 7.8 fills this gap by building a production data pipeline that:

1. Fetches historical 3-minute NIFTY candles from the Upstox V3 Historical Candle API
2. Normalizes timestamps to UTC
3. Validates data quality (OHLC integrity, duplicates, gaps)
4. Persists idempotently using the existing `NiftyCandle` model/service
5. Provides incremental backfill with resume-after-failure
6. Delivers a coverage report so the research engine knows what data is available

Phase 7.8 also builds the **Historical Contract Metadata Registry** — a per-instrument metadata layer populated from the Upstox Get Expired Option Contracts API. This registry stores the authoritative `lot_size`, `minimum_lot`, `freeze_quantity`, and other contract specifications for every expired option instrument. It is consumed by future phases (7.9+) that reconstruct historical option chains and compute GEX.

The pipeline is designed as a **backend batch ingestion system** — standalone backfill scripts plus lightweight incremental update mechanisms. It is **not** a real-time feed.

---

## 2. Repository / Infrastructure Audit

### 2.1 NiftyCandle Model (Phase 7.7 — already implemented)

**File:** `backend/app/models.py` (lines 505–529)

```python
class NiftyCandle(Base):
    __tablename__ = "nifty_candles"
    id: int (PK)
    symbol: str (String(16), indexed)
    interval: str (String(8), default="3min")
    open_time: datetime (DateTime, indexed)
    open: float
    high: float
    low: float
    close: float
    volume: float (default=0.0)
    __table_args__ = (UniqueConstraint("symbol", "interval", "open_time"),)
```

**Key properties:**
- Identity: `(symbol, interval, open_time)` — unique constraint ensures idempotent upserts
- `open_time` is stored as a UTC datetime — the canonical deduplication key
- No user scoping — candle data is market-wide (one NIFTY index, shared by all users)
- SQLite `INSERT ... ON CONFLICT DO UPDATE` upsert already implemented in the service

### 2.2 Nifty Candle Service (Phase 7.7 — already implemented)

**File:** `backend/app/services/nifty_candles.py`

**Exports:**
- `record_candles(db, candles)` — idempotent batch upsert, returns count stored
- `get_candles(db, symbol, interval, limit, since, until)` — query oldest-first
- `get_candle_at_or_before(db, symbol, timestamp, interval)` — reference candle lookup
- `count_candles(db, symbol, interval)` — count stored candles
- `prune_candles(db, retention_days)` — delete candles older than retention

**Input format for `record_candles`:**
```python
{
    "symbol": "NIFTY",
    "interval": "3min",
    "openTime": "2026-08-22T09:15:00Z",  # ISO 8601
    "open": 25500.0,
    "high": 25520.0,
    "low": 25480.0,
    "close": 25510.0,
    "volume": 15000.0,
}
```

### 2.3 Config (Phase 7.7 — already set)

**File:** `backend/app/config.py`

```python
CANDLE_RETENTION_DAYS: int = 365
CANDLE_INTERVAL: str = "3min"
```

### 2.4 Upstox Service (existing)

**File:** `backend/app/services/upstox.py`

- `BASE_URL = "https://api.upstox.com/v2"` (V2 for existing endpoints)
- `V3_BASE_URL = "https://api.upstox.com/v3"` (V3 for funds/margin)
- Uses `httpx.AsyncClient` for all API calls
- `_request()` helper with structured error handling
- `UpstoxError(status_code, message)` exception class
- All endpoints are `async def`

### 2.5 Token Store (existing)

**File:** `backend/app/services/token_store.py`

- In-memory single-user token store
- `set_token(token) → session_id`
- `get_token(session_id) → token | None`
- `clear_token()`
- Tokens expire daily at 3:30 AM IST
- No persistence — server restart requires re-login

### 2.6 Instrument Key Resolution (existing)

**File:** `backend/app/brokers/adapters/upstox/mapper.py`

```python
UPSTOX_INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    ...
}
```

For the candle pipeline, we need `NSE_INDEX|Nifty 50` for NIFTY historical candles.

### 2.7 Frontend Research Engine (Phase 7.7 — already implemented)

**Key expectations for candle data:**

| Module | Requirement |
|---|---|
| `gexResearchData.js` | `buildResearchDataset(snapshots, candles)` — joins GEX snapshots with candles by matching `capturedAt` to candle `openTime` |
| `gexResearchData.js` | `HORIZONS = [1, 3, 5, 10, 15, 30]` — max forward horizon is 30 candles (90 minutes of 3-min data) |
| `gexResearchData.js` | `MIN_FORWARD_CANDLES = 30` — needs 30+ candles after each observation |
| `gexResearchValidation.js` | `MIN_TRAIN_SIZE = 300`, `MIN_TEST_SIZE = 100` — needs 500+ observations minimum |
| `gexResearchTests.js` | `MIN_OBSERVATIONS = 200` — minimum for statistical tests |

**Data volume requirements:**
- 3-minute candles, 6.25 hours/day × 60 min/hour ÷ 3 = **125 candles/trading day**
- ~250 trading days/year → **~31,250 candles/year**
- For 200 observations: need ~2 trading days (minimum)
- For 500 observations (full validation): need ~4 trading days (minimum)
- For robust research: 6–12 months of data (18,750–37,500 candles)

### 2.8 NSE Trading Hours

- **Trading window:** 9:15 AM to 3:30 PM IST (03:45 to 09:50 UTC)
- **3-minute candles per day:** 125 candles (9:15, 9:18, ..., 15:27)
- **Market holidays:** ~14 days/year (NSE F&O segment)
- **Weekends:** ~104 days/year
- **Trading days:** ~250 days/year

### 2.9 Critical Gaps

> **Phase 7.8 exists because of two gaps:**
>
> 1. **Candle data gap:** The `NiftyCandle` model and `nifty_candles.py` persistence service are implemented, but **there is no production data ingestion path** — no Upstox historical-candle adapter method, no backend ingestion endpoint, and no import workflow. The research engine is structurally complete but **cannot run on real data** until candles are populated.
>
> 2. **Contract metadata gap:** No mechanism exists to store historical per-instrument contract specifications (lot_size, minimum_lot, freeze_quantity). Future phases that reconstruct historical option chains and compute GEX need authoritative per-instrument metadata. The Upstox Get Expired Option Contracts API provides this data but no adapter or storage exists.

### 2.10 Historical Contract Metadata — Upstox as Primary Source

NIFTY options and futures contract specifications — particularly **lot size** — have changed multiple times through NSE circulars. As of 2025, the NIFTY lot size is 25 (reduced from 50 in October 2024, from 75 before that, and from higher values earlier).

**Authoritative source:** The Upstox **Get Expired Option Contracts** API (`GET /v2/expired-instruments/option/contract`) returns per-instrument metadata for every expired option contract, including the exact `lot_size`, `minimum_lot`, `freeze_quantity`, `tick_size`, `strike_price`, `instrument_type`, `instrument_key`, and `expiry` for each contract. This is the **primary source** for historical contract metadata.

**Why this matters for Phase 7.8:**

- The **candle data pipeline** (this phase) stores raw NIFTY index OHLCV candles. Index candle data is **independent of lot size** — NIFTY spot price, open, high, low, close, and volume do not change when the lot size changes.
- However, **future phases** (historical option-chain reconstruction, GEX calculation, exposure analysis) will need to convert contract-level OI and volume into notional exposure. Using the wrong lot size for a historical period would silently distort OI exposure, GEX magnitude, and all derived analytics.
- The contract metadata registry is therefore a **foundational metadata layer** that must be designed and populated now (Phase 7.8) even though it is not consumed until later phases.

**Phase 7.8 scope:** Design the registry data model, lookup interface, Upstox adapter methods for expired instruments, and the ingestion pipeline. Populate the registry from the Upstox API. NSE circulars serve as an independent validation source, not the primary source.

---

## 3. Upstox V3 Historical Candle API — Complete Contract

### 3.1 Endpoint: Historical Candle Data

```
GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}
```

**Path Parameters:**
| Parameter | Required | Type | Description |
|---|---|---|---|
| `instrument_key` | Yes | string | e.g. `NSE_INDEX|Nifty 50` (URL-encoded: `NSE_INDEX%7CNifty%2050`) |
| `unit` | Yes | string | `minutes`, `hours`, `days`, `weeks`, `months` |
| `interval` | Yes | string | For minutes: `1`–`300`. For 3-min: `3` |
| `to_date` | Yes | string | `YYYY-MM-DD` (inclusive) |
| `from_date` | No | string | `YYYY-MM-DD` (inclusive). Optional — omit for single-day query |

**Headers:**
```
Content-Type: application/json
Accept: application/json
Authorization: Bearer {access_token}
```

**Response (200):**
```json
{
    "status": "success",
    "data": {
        "candles": [
            [
                "2025-01-12T15:15:00+05:30",  // [0] Timestamp (IST, ISO 8601)
                2305.3,                         // [1] Open
                2307.05,                        // [2] High
                2301.0,                         // [3] Low
                2304.65,                        // [4] Close
                559982,                         // [5] Volume
                0                               // [6] Open Interest
            ]
        ]
    }
}
```

**Candle array format:** `[timestamp, open, high, low, close, volume, open_interest]`

**Error codes:**
| Code | Description |
|---|---|
| `UDAPI1021` | Instrument key format invalid |
| `UDAPI1022` | `to_date` is required — must specify `to_date` in the request |
| `UDAPI100011` | Invalid instrument key |
| `UDAPI1015` | `to_date` must be >= `from_date` |
| `UDAPI1146` | Invalid unit |
| `UDAPI1147` | Invalid interval for specified unit |
| `UDAPI1148` | Date range not valid for selected interval |

### 3.2 Endpoint: Intraday Candle Data (Current Day)

```
GET /v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}
```

Returns current trading day's candles. No date parameters.

### 3.3 Retrieval Limits (Critical)

| Unit | Interval | Historical Availability | **Max Retrieval Window** |
|---|---|---|---|
| minutes | 1–15 | Jan 2022 | **1 month** |
| minutes | 16–300 | Jan 2022 | 1 quarter |
| hours | 1–5 | Jan 2022 | 1 quarter |
| days | 1 | Jan 2000 | 1 decade |

**For 3-minute candles (interval=3): the maximum retrieval window is 1 month.**

This means a 12-month backfill requires **12 separate API calls**, each covering one calendar month.

### 3.4 Timestamp Behavior

- **All timestamps are IST (UTC+5:30)**, formatted as ISO 8601 with offset: `"2025-01-12T15:15:00+05:30"`
- Timestamps represent the **candle open time**
- The API returns candles in **reverse chronological order** (newest first)
- All timestamps must be converted to **UTC** for storage in `NiftyCandle.open_time`

### 3.5 Rate Limits

| Window | Limit |
|---|---|
| Per second | 50 requests |
| Per minute | 500 requests |
| Per 30 minutes | 2,000 requests |

For candle data fetching: 12 API calls for a 12-month backfill — well within all rate limits. No rate-limit mitigation needed for the backfill itself, but the infrastructure should still handle 429 responses gracefully.

---

## 4. Pipeline Architecture

The pipeline has seven distinct stages:

```
┌─────────────────────────────────────────────────────────────────┐
│  DATA SIDE (Phase 7.8 scope)                                    │
│                                                                 │
│  ┌───────────────────┐  ┌────────────────────────────────────┐  │
│  │ Raw Market Data    │  │ Upstox Expired Instruments API    │  │
│  │ (§5.1-5.3)        │  │ (§5.4-5.6)                       │  │
│  │ V3 Historical     │  │ V2 Get Expiries + Get Expired     │  │
│  │ Candle API        │  │ Option Contracts                  │  │
│  └────────┬──────────┘  └──────────┬─────────────────────────┘  │
│           │                        │                             │
│  ┌────────▼──────────┐  ┌──────────▼─────────────────────────┐  │
│  │ NIFTY Candles      │  │ Contract Metadata Registry        │  │
│  │ (§6, §9, §10)     │  │ (§12.6)                           │  │
│  │ Normalize, validate│  │ Per-instrument lot_size, etc.     │  │
│  │ persist            │  │ Populated from Upstox API         │  │
│  └────────┬──────────┘  └──────────┬─────────────────────────┘  │
│           │                        │                             │
│  ┌────────▼──────────┐            │                             │
│  │ Quality Audit      │            │                             │
│  │ (§11)             │            │                             │
│  │ Coverage, gaps     │            │                             │
│  └────────┬──────────┘            │                             │
│           │                        │                             │
│  ┌────────▼──────────┐            │                             │
│  │ Research Dataset   │            │                             │
│  │ (§12)             │            │                             │
│  │ Candles only;      │            │                             │
│  │ no options/GEX yet │            │                             │
│  └───────────────────┘            │                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  FUTURE (Phase 7.9+)                                            │
│                                                                 │
│  Historical Option/GEX Data → Research Dataset with exposure   │
│  (consumes contract-metadata registry + candle data)            │
└─────────────────────────────────────────────────────────────────┘

This pipeline is entirely on the DATA side.  It is completely separate from:

  GEX calculation → research analysis → statistical conclusions
```

**Key architectural principles:**
1. The contract metadata registry is an **independent metadata layer** populated from the Upstox Expired Instruments API. It is NOT embedded inside the candle persistence service.
2. Candles are raw market data (lot-size-independent). The registry is per-instrument contract metadata consumed by downstream phases.
3. The Upstox Expired Option Contracts API provides the **authoritative historical lot_size** for each instrument — no manual timeline maintenance required.

---

## 5. Data Source — Upstox V3 Adapter

### 5.1 New Method: `get_historical_candles()`

**File:** `backend/app/services/upstox.py`

Add a new async function following the existing `_request()` pattern:

```python
async def get_historical_candles(
    access_token: str,
    instrument_key: str,
    to_date: str,          # "YYYY-MM-DD"
    from_date: str | None = None,  # "YYYY-MM-DD" or None for single day
    unit: str = "minutes",
    interval: int = 3,
) -> dict:
    """Fetch historical candle data from Upstox V3.
    
    Returns the raw response dict with data.candles array.
    Each candle: [timestamp, open, high, low, close, volume, open_interest]
    Timestamps are IST (UTC+5:30).
    """
    path = f"/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}"
    if from_date:
        path += f"/{from_date}"
    
    return await _request(
        "GET",
        path,
        base_url=V3_BASE_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
```

**Design decisions:**
- Reuses the existing `_request()` helper — consistent error handling
- Uses `V3_BASE_URL` (already defined as `"https://api.upstox.com/v3"`)
- Returns raw response — normalization happens in the ingestion layer
- `instrument_key` is passed as-is — callers resolve it from the mapper

### 5.2 New Method: `get_intraday_candles()`

```python
async def get_intraday_candles(
    access_token: str,
    instrument_key: str,
    unit: str = "minutes",
    interval: int = 3,
) -> dict:
    """Fetch current trading day's intraday candle data from Upstox V3."""
    path = f"/historical-candle/intraday/{instrument_key}/{unit}/{interval}"
    
    return await _request(
        "GET",
        path,
        base_url=V3_BASE_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
```

### 5.3 NIFTY Instrument Key

**File:** `backend/app/services/candle_config.py` (new)

Centralized candle pipeline configuration:

```python
"""Configuration constants for the candle data pipeline."""

# Upstox V3 instrument key for NIFTY 50 index
NIFTY_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"

# Candle pipeline defaults
CANDLE_UNIT = "minutes"
CANDLE_INTERVAL = 3  # 3-minute candles

# Chunking: for 3-min intervals, max retrieval is 1 month
MAX_CHUNK_DAYS = 28  # conservative: 28 days per chunk

# Rate limit headroom (Upstox allows 50/sec, 500/min, 2000/30min)
# We're well below these with monthly chunks, but set a floor anyway
MIN_REQUEST_INTERVAL_SECONDS = 0.1  # 100ms between requests

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 1.0
RETRY_MAX_DELAY_SECONDS = 30.0
RETRY_BACKOFF_MULTIPLIER = 2.0

# NSE trading hours (IST)
MARKET_OPEN_IST = "09:15"
MARKET_CLOSE_IST = "15:30"
CANDLES_PER_TRADING_DAY = 125  # 6h15m / 3min = 125 candles
```

### 5.4 New Method: `get_expired_expiries()`

**File:** `backend/app/services/upstox.py`

Fetch all available expiry dates for an underlying instrument from the Upstox Expired Instruments API:

```python
async def get_expired_expiries(
    access_token: str,
    instrument_key: str,
) -> dict:
    """Fetch all available expiry dates for expired instruments.

    GET /v2/expired-instruments/expiries?instrument_key={instrument_key}

    Returns the raw response dict with data: list of YYYY-MM-DD strings.
    Covers up to 6 months of historical expiries.
    """
    return await _request(
        "GET",
        "/expired-instruments/expiries",
        params={"instrument_key": instrument_key},
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
```

### 5.5 New Method: `get_expired_option_contracts()`

```python
async def get_expired_option_contracts(
    access_token: str,
    instrument_key: str,
    expiry_date: str,
) -> dict:
    """Fetch expired option contract metadata for a given expiry date.

    GET /v2/expired-instruments/option/contract?instrument_key={instrument_key}&expiry_date={expiry_date}

    Returns the raw response dict with data: list of contract objects.
    Each contract includes: instrument_key, trading_symbol, lot_size,
    minimum_lot, freeze_quantity, tick_size, strike_price, instrument_type,
    expiry, underlying_key, underlying_type, underlying_symbol, segment,
    exchange, weekly.

    Requires Upstox Plus plan subscription.
    """
    return await _request(
        "GET",
        "/expired-instruments/option/contract",
        params={"instrument_key": instrument_key, "expiry_date": expiry_date},
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
```

### 5.6 Expired Instruments API — Response Format

**Get Expired Option Contracts response:**

```json
{
    "status": "success",
    "data": [
        {
            "name": "NIFTY",
            "segment": "NSE_FO",
            "exchange": "NSE",
            "expiry": "2025-04-17",
            "instrument_key": "NSE_FO|47983|17-04-2025",
            "exchange_token": "47983",
            "trading_symbol": "NIFTY 20400 PE 17 APR 25",
            "tick_size": 5,
            "lot_size": 75,
            "instrument_type": "PE",
            "freeze_quantity": 1800,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_type": "INDEX",
            "underlying_symbol": "NIFTY",
            "strike_price": 20400,
            "minimum_lot": 75,
            "weekly": true
        }
    ]
}
```

**Key fields for the contract metadata registry:**

| Field | Example | Description |
|---|---|---|
| `instrument_key` | `NSE_FO|47983|17-04-2025` | Unique instrument identifier — primary lookup key |
| `lot_size` | `75` | Contracts per lot — **authoritative historical value** |
| `minimum_lot` | `75` | Minimum order lot — stored separately from `lot_size` |
| `freeze_quantity` | `1800` | Maximum quantity that can be frozen |
| `tick_size` | `5` | Minimum price increment |
| `strike_price` | `20400` | Strike price |
| `instrument_type` | `PE` | Option type: CE or PE |
| `expiry` | `2025-04-17` | Expiry date |
| `underlying_key` | `NSE_INDEX|Nifty 50` | Underlying instrument key |
| `trading_symbol` | `NIFTY 20400 PE 17 APR 25` | Human-readable trading symbol |
| `weekly` | `true` | Whether this is a weekly expiry |

---

## 6. Ingestion — Fetching & Normalizing Raw Candles

### 6.1 Timestamp Normalization

The Upstox API returns timestamps in IST with offset: `"2025-01-12T15:15:00+05:30"`

The `NiftyCandle.open_time` stores UTC datetimes. Conversion:

```python
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def normalize_candle_timestamp(ist_timestamp: str) -> datetime:
    """Convert Upstox IST timestamp to UTC datetime for storage.
    
    Input:  "2025-01-12T15:15:00+05:30" (IST)
    Output: datetime(2025, 1, 12, 9, 45, 0, tzinfo=timezone.utc) (UTC)
    """
    # Parse IST timestamp with offset
    ist_dt = datetime.fromisoformat(ist_timestamp)
    
    # If naive, assume IST
    if ist_dt.tzinfo is None:
        ist_dt = ist_dt.replace(tzinfo=IST)
    
    # Convert to UTC
    utc_dt = ist_dt.astimezone(timezone.utc)
    
    # Strip timezone for SQLite storage (SQLite stores naive UTC)
    return utc_dt.replace(tzinfo=None)
```

**Critical:** The existing `nifty_candles.py` service already parses ISO 8601 timestamps with `Z` or `+00:00` offset. The ingestion layer must convert IST → UTC before passing to `record_candles()`.

### 6.1A Known Limitation — Timezone Serialization (Pre-existing, Phase 7.7)

> **This is a pre-existing Phase 7.7 issue. Phase 7.8 MUST NOT modify `_row_to_dict()` to fix it.**

The existing `_row_to_dict()` functions in both `nifty_candles.py` and `gex_history.py` serialize UTC datetimes using Python's `datetime.isoformat()` **without appending a `Z` suffix**. This produces timestamps like `"2026-08-22T09:57:00"` (no timezone indicator) instead of `"2026-08-22T09:57:00Z"`.

**Impact:** When JavaScript's `new Date("2026-08-22T09:57:00")` parses a timestamp without a timezone suffix, the ECMAScript specification mandates it be interpreted as **local browser time**, not UTC. This means:

- **`buildResearchDataset()` matching:** Both candle `openTime` and snapshot `capturedAt` are serialized the same way (naive UTC). JavaScript interprets both as local time, so the comparison `candle.openTime <= snapshot.capturedAt` is **consistent** — matching works correctly regardless of timezone.
- **`classifyTimeOfDay()`:** This function adds 5.5 hours to convert to IST. If the timestamp is already in UTC (as intended), this produces the correct IST time. But when JavaScript interprets the naive timestamp as local time, the function only produces correct IST classifications when the **browser timezone is UTC**. For users in IST, the classification would be off by 10.5 hours (double-applied offset).

**Recommended future fix (NOT in Phase 7.8):** Append `"Z"` in `_row_to_dict()`:
```python
"openTime": row.open_time.isoformat() + "Z" if row.open_time else None,
"capturedAt": row.captured_at.isoformat() + "Z" if row.captured_at else None,
```
This makes timestamps unambiguously UTC, and `classifyTimeOfDay()` works correctly in all browser timezones.

**Phase 7.8 impact:** None. The candle data produced by Phase 7.8 flows through the same `_row_to_dict()` → JavaScript path as existing GEX snapshots. Matching consistency is maintained.

### 6.2 Raw Candle Normalization

The Upstox API returns arrays: `[timestamp, open, high, low, close, volume, open_interest]`

The `record_candles()` service expects dicts with `openTime`, `open`, `high`, `low`, `close`, `volume`.

```python
def normalize_candle(raw_candle: list, symbol: str = "NIFTY", interval: str = "3min") -> dict | None:
    """Convert Upstox raw candle array to the record_candles() input format.
    
    Returns None if the candle is invalid.
    """
    if not isinstance(raw_candle, (list, tuple)) or len(raw_candle) < 6:
        return None
    
    ist_timestamp = raw_candle[0]
    open_price = raw_candle[1]
    high = raw_candle[2]
    low = raw_candle[3]
    close = raw_candle[4]
    volume = raw_candle[5]
    # raw_candle[6] is open_interest — ignored for NIFTY index
    
    # Validate numeric fields
    for name, val in [("open", open_price), ("high", high), ("low", low), ("close", close)]:
        if val is None or not isinstance(val, (int, float)):
            return None
    if not isinstance(volume, (int, float)):
        volume = 0.0
    
    # Normalize timestamp
    try:
        open_time_utc = normalize_candle_timestamp(ist_timestamp)
    except (ValueError, TypeError):
        return None
    
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "openTime": open_time_utc.isoformat() + "Z",  # ISO 8601 UTC
        "open": float(open_price),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
    }
```

### 6.3 Response Extraction

```python
def extract_candles_from_response(response: dict) -> list[list]:
    """Extract the candle array from an Upstox V3 response.
    
    Handles both success and error responses.
    Returns empty list on error or no data.
    """
    if not isinstance(response, dict):
        return []
    if response.get("status") != "success":
        return []
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    candles = data.get("candles")
    if not isinstance(candles, list):
        return []
    return candles
```

---

## 7. Date-Range Chunking

### 7.1 Chunk Generation

For 3-minute candles, the maximum retrieval window is 1 month. The backfill generates one chunk per calendar month:

```python
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

def generate_monthly_chunks(
    start_date: date,
    end_date: date,
    max_chunk_days: int = 28,
) -> list[tuple[date, date]]:
    """Generate (from_date, to_date) pairs covering start_date to end_date.
    
    Each chunk is at most max_chunk_days apart.
    Chunks are contiguous — no gaps between them.
    
    Example: 2025-08-01 to 2026-08-23
    → [(2025-08-01, 2025-08-28), (2025-08-29, 2025-09-25), ...]
    """
    chunks = []
    current = start_date
    
    while current <= end_date:
        chunk_end = min(current + timedelta(days=max_chunk_days - 1), end_date)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    
    return chunks
```

### 7.2 Why 28-Day Chunks

- Upstox allows 1 month max for 3-min intervals
- Using 28 days ensures we never hit the limit
- Calendar months have 28–31 days; 28-day chunks are uniform and safe
- For a 12-month backfill: ~13–14 chunks (`ceil(365 / 28) = 14` for a full 365-day period; the exact count depends on start/end dates)
- Each chunk covers 28 calendar days containing ~20 trading days (28 days − ~8 weekend days), yielding ~20 × 125 = **~2,500 candles per chunk**

### 7.3 Estimated Backfill Scale

| Duration | Calendar Days | Chunks | API Calls | Candles (est.) | Time (est.) |
|---|---|---|---|---|---|
| 1 month | ~30 | 1–2 | 1–2 | ~2,500 | <1 second |
| 3 months | ~90 | 4 | 4 | ~7,500 | <1 second |
| 6 months | ~180 | 7 | 7 | ~15,000 | <2 seconds |
| 12 months | ~365 | 13–14 | 13–14 | ~31,250 | <3 seconds |

**Derivation:** 250 trading days/year × 125 candles/day = 31,250 candles/year. Per chunk: 28 calendar days contain ~20 trading days → ~2,500 candles. The 12-month total (31,250) divided by chunk count (13–14) confirms ~2,200–2,400 per chunk, consistent with the ~2,500 estimate.

With 100ms between requests, a full 12-month backfill takes ~1.4 seconds of API time. The bottleneck is SQLite writes, not network.

---

## 8. Retry / Backoff & Rate-Limit Handling

### 8.1 Retry Strategy

```python
import asyncio
import logging

logger = logging.getLogger(__name__)

async def fetch_with_retry(
    fetch_fn,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_multiplier: float = 2.0,
    **kwargs,
) -> dict:
    """Execute an async fetch function with exponential backoff retry.
    
    Retries on:
    - Network errors (httpx.RequestError → mapped to UpstoxError 502)
    - Server errors (HTTP 500, 502, 503)
    - Rate limits (HTTP 429)
    
    Does NOT retry on:
    - Auth errors (HTTP 401, 403) — token is expired/invalid
    - Client errors (HTTP 400, 422) — bad request parameters
    - Instrument errors (UDAPI*) — invalid instrument key
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            result = await fetch_fn(*args, **kwargs)
            return result
        except UpstoxError as e:
            last_error = e
            status = e.status_code
            
            # Non-retryable errors
            if status in (400, 401, 403, 422):
                raise  # token expired or bad request — don't retry
            
            # Retryable errors
            if status in (429, 500, 502, 503):
                delay = min(
                    base_delay * (backoff_multiplier ** attempt),
                    max_delay,
                )
                # For 429, use Retry-After header if available
                if status == 429:
                    delay = max(delay, 2.0)  # minimum 2s for rate limit
                
                logger.warning(
                    "Upstox error %d (attempt %d/%d), retrying in %.1fs: %s",
                    status, attempt + 1, max_retries + 1, delay, e.message,
                )
                await asyncio.sleep(delay)
                continue
            
            # Unknown retryable status (5xx family)
            if status >= 500:
                delay = min(base_delay * (backoff_multiplier ** attempt), max_delay)
                logger.warning(
                    "Upstox server error %d (attempt %d/%d), retrying in %.1fs",
                    status, attempt + 1, max_retries + 1, delay,
                )
                await asyncio.sleep(delay)
                continue
            
            raise  # other errors — don't retry
    
    raise last_error  # all retries exhausted
```

### 8.2 Rate-Limit Awareness

For the candle pipeline, rate limits are not a practical concern:

- **12-month backfill:** 13–14 API calls total — far below 500/min or 2000/30min
- **Daily incremental:** 1–2 API calls — negligible
- **Intraday fetch:** 1 call — negligible

However, the retry infrastructure handles 429 responses gracefully, and a configurable `MIN_REQUEST_INTERVAL_SECONDS` (0.1s) prevents bursts if the pipeline is ever extended to multiple instruments.

---

## 9. Data Quality Validation

### 9.1 Validation Rules — Hard Errors vs Soft Warnings

Candles that trigger a **hard error** are rejected (not persisted). Candles that trigger a **soft warning** are persisted but flagged in the validation report.

**Hard errors** (candle rejected, not stored):
| Rule | Description |
|---|---|
| `PRICE_NOT_POSITIVE` | Any of open, high, low, close is `None`, non-numeric, or ≤ 0 |
| `OHLC_INTEGRITY` | `high < max(open, close)` or `low > min(open, close)` or `high < low` |
| `NEGATIVE_VOLUME` | Volume is negative |
| `TIMESTAMP_MISSING` | `openTime` is None or unparseable |
| `TIMESTAMP_FUTURE` | `openTime` is in the future (beyond today + 1 day tolerance) |

**Soft warnings** (candle stored, flagged in report):
| Rule | Description |
|---|---|
| `ZERO_VOLUME` | Volume is exactly 0 (unusual for NIFTY index during market hours) |
| `ABNORMAL_RANGE` | Single-candle range (high − low) / close > 2% (possible data error) |
| `BOUNDARY_MISALIGNMENT` | First candle of a trading day not near 09:15 IST, or last candle not near 15:27 IST |

### 9.2 Validation Pipeline

After fetching and before persisting, each candle passes through a validation chain:

```python
from dataclasses import dataclass, field

@dataclass
class CandleValidationResult:
    """Result of validating one candle."""
    candle_index: int
    is_valid: bool  # False if any hard error
    errors: list[str] = field(default_factory=list)   # hard errors → candle rejected
    warnings: list[str] = field(default_factory=list)  # soft warnings → candle stored but flagged

def validate_candle(candle: dict, index: int) -> CandleValidationResult:
    """Validate a single normalized candle.
    
    Hard errors set is_valid=False → candle is NOT persisted.
    Soft warnings are recorded but do NOT prevent persistence.
    """
    result = CandleValidationResult(candle_index=index, is_valid=True)
    
    open_p = candle.get("open")
    high = candle.get("high")
    low = candle.get("low")
    close = candle.get("close")
    volume = candle.get("volume", 0)
    open_time = candle.get("openTime")
    
    # --- Hard errors ---
    
    # Price positivity
    for name, val in [("open", open_p), ("high", high), ("low", low), ("close", close)]:
        if val is None or not isinstance(val, (int, float)) or val <= 0:
            result.is_valid = False
            result.errors.append(f"PRICE_NOT_POSITIVE: {name}={val}")
    
    # OHLC integrity
    if result.is_valid:
        if high < max(open_p, close):
            result.is_valid = False
            result.errors.append(f"OHLC_INTEGRITY: high ({high}) < max(open, close) ({max(open_p, close)})")
        if low > min(open_p, close):
            result.is_valid = False
            result.errors.append(f"OHLC_INTEGRITY: low ({low}) > min(open, close) ({min(open_p, close)})")
        if high < low:
            result.is_valid = False
            result.errors.append(f"OHLC_INTEGRITY: high ({high}) < low ({low})")
    
    # Negative volume
    if volume is not None and isinstance(volume, (int, float)) and volume < 0:
        result.is_valid = False
        result.errors.append(f"NEGATIVE_VOLUME: volume={volume}")
    
    # Timestamp validity
    if open_time is None:
        result.is_valid = False
        result.errors.append("TIMESTAMP_MISSING: openTime is None")
    
    # --- Soft warnings (only if hard-error-free) ---
    
    if result.is_valid:
        if volume is not None and isinstance(volume, (int, float)) and volume == 0:
            result.warnings.append("ZERO_VOLUME: volume is 0")
        
        if isinstance(close, (int, float)) and close > 0 and isinstance(high, (int, float)) and isinstance(low, (int, float)):
            candle_range_pct = (high - low) / close
            if candle_range_pct > 0.02:
                result.warnings.append(f"ABNORMAL_RANGE: range is {candle_range_pct:.1%} of close")
    
    return result
```

### 9.3 Batch Validation with Gap Detection

```python
def validate_candle_batch(
    candles: list[dict],
    expected_interval_minutes: int = 3,
) -> dict:
    """Validate a batch of candles and detect gaps.
    
    Returns:
    {
        "total": int,
        "valid": int,
        "invalid": int,
        "errors": list[CandleValidationResult],  # only invalid candles
        "gaps": list[GapInfo],  # detected gaps in time series
        "duplicates": list[int],  # indices of duplicate openTime values
        "statistics": {...},
    }
    """
    # 1. Validate individual candles
    results = [validate_candle(c, i) for i, c in enumerate(candles)]
    valid_candles = [c for c, r in zip(candles, results) if r.is_valid]
    invalid = [r for r in results if not r.is_valid]
    
    # 2. Detect duplicate timestamps
    seen_times = {}
    duplicates = []
    for i, c in enumerate(valid_candles):
        t = c.get("openTime")
        if t in seen_times:
            duplicates.append(i)
        else:
            seen_times[t] = i
    
    # 3. Detect gaps (missing candles within expected time series)
    gaps = _detect_time_gaps(valid_candles, expected_interval_minutes)
    
    # 4. Compute statistics
    if valid_candles:
        times = [c["openTime"] for c in valid_candles]
        statistics = {
            "earliest_candle": min(times),
            "latest_candle": max(times),
            "total_candles": len(valid_candles),
            "expected_candles_per_day": _compute_expected_per_day(expected_interval_minutes),
            "gap_count": len(gaps),
            "total_gap_candles": sum(g["missing_count"] for g in gaps),
        }
    else:
        statistics = {"total_candles": 0, "gap_count": 0, "total_gap_candles": 0}
    
    return {
        "total": len(candles),
        "valid": len(valid_candles),
        "invalid": len(invalid),
        "errors": invalid,
        "gaps": gaps,
        "duplicates": duplicates,
        "statistics": statistics,
    }
```

### 9.4 Gap Detection

```python
@dataclass
class GapInfo:
    """A gap (missing candles) in the time series."""
    gap_start: str  # ISO timestamp of candle before gap
    gap_end: str    # ISO timestamp of candle after gap
    expected_candles: int
    missing_count: int
    is_market_session: bool  # True if gap is during market hours

def _detect_time_gaps(
    candles: list[dict],
    interval_minutes: int = 3,
) -> list[GapInfo]:
    """Detect gaps in the candle time series.
    
    A gap exists when consecutive candles are more than interval_minutes apart.
    
    We distinguish:
    - Market-session gaps: gaps during 9:15–15:30 IST on trading days
      (indicates missing data — e.g. network interruption)
    - Non-market gaps: gaps during off-hours/weekends/holidays
      (expected — no candles expected)
    """
    gaps = []
    if len(candles) < 2:
        return gaps
    
    expected_delta_ms = interval_minutes * 60 * 1000
    
    for i in range(len(candles) - 1):
        t1 = candles[i].get("openTime")
        t2 = candles[i + 1].get("openTime")
        
        if not t1 or not t2:
            continue
        
        try:
            dt1 = datetime.fromisoformat(t1.replace("Z", "+00:00"))
            dt2 = datetime.fromisoformat(t2.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        
        delta_ms = (dt2 - dt1).total_seconds() * 1000
        expected_multiple = delta_ms / expected_delta_ms
        
        # Allow small tolerance (2x expected = gap of 1 candle)
        if expected_multiple > 1.5:
            missing = max(0, round(delta_ms / expected_delta_ms) - 1)
            is_market = _is_market_session(dt1)
            
            gaps.append(GapInfo(
                gap_start=t1,
                gap_end=t2,
                expected_candles=missing + 1,
                missing_count=missing,
                is_market_session=is_market,
            ))
    
    return gaps
```

### 9.5 Duplicate Handling

The existing `record_candles()` service already handles duplicates via SQLite upsert (`ON CONFLICT DO UPDATE`). When the ingestion layer detects duplicates within a batch:

1. **Keep the last occurrence** (most recent fetch wins)
2. The upsert will update the existing row with the same `(symbol, interval, open_time)`
3. This is safe because duplicate candles from the same API call have identical OHLCV data

### 9.6 Missing Candle Analysis

For research purposes, we need to know:
- How many trading days have complete 125-candle coverage?
- Which days have partial data (holidays, early close, half sessions)?
- What is the overall data completeness percentage?

This is computed in the coverage report (§11).

### 9.7 Market-Session Gap Classification

```python
def _is_market_session(dt_utc: datetime) -> bool:
    """Check if a UTC timestamp falls within NSE trading hours (IST 9:15–15:30).
    
    This is approximate — does not account for market holidays.
    Used for gap classification, not data validation.
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    ist_dt = dt_utc.astimezone(IST)
    hour = ist_dt.hour
    minute = ist_dt.minute
    time_min = hour * 60 + minute
    return 555 <= time_min <= 930  # 9:15=555, 15:30=930
```

### 9.8 Incomplete Trading Day Detection

A trading day is "incomplete" if it has fewer than expected candles:

- **Full day:** 125 candles (9:15, 9:18, ..., 15:27)
- **Half day / early close:** typically 63 candles (9:15, ..., 12:30)
- **Holiday / no data:** 0 candles
- **Partial (data loss):** anything between 1–124 candles

The coverage report (§11) tracks this per-day.

---

## 10. Idempotent Persistence

### 10.1 Using Existing `record_candles()`

The persistence layer delegates entirely to the existing `nifty_candles.record_candles()`:

```python
from app.services.nifty_candles import record_candles

def persist_normalized_candles(db: Session, normalized_candles: list[dict]) -> int:
    """Persist normalized candles using the existing service.
    
    Idempotent: re-fetching the same date range produces the same data.
    Upsert behavior: existing candles are updated, new ones inserted.
    """
    if not normalized_candles:
        return 0
    
    return record_candles(db, normalized_candles)
```

### 10.2 Idempotency Guarantees

| Scenario | Behavior | Safe? |
|---|---|---|
| Fetch same date range twice | Upsert overwrites identical data | ✅ |
| Fetch overlapping date ranges | Last write wins for overlaps | ✅ |
| Resume after partial failure | Unfetched chunks re-fetched, already-persisted chunks skipped | ✅ |
| Concurrent backfill runs | SQLite serialization prevents corruption | ✅ |
| Server restart mid-backfill | Progress tracked in DB; resume from last completed chunk | ✅ |
| Partial API response | Upstox returns all candles for a range or an error; no partial delivery. If an unexpected partial response occurs, the candle count is logged and the chunk is retried | ✅ |
| Future date requested | Backfill script caps `to_date` at `min(requested_date, today)` to avoid requesting data that cannot exist | ✅ |

### 10.3 Progress Tracking

The backfill script tracks progress by querying the database for the earliest and latest persisted candles:

```python
def get_backfill_progress(db: Session, symbol: str = "NIFTY") -> dict:
    """Check current backfill progress for a symbol.
    
    Returns:
    {
        "total_candles": int,
        "earliest_candle": str | None,  # ISO timestamp
        "latest_candle": str | None,    # ISO timestamp
        "date_range_days": int | None,  # span in days
    }
    """
    count = count_candles(db, symbol=symbol)
    
    # Query earliest and latest
    stmt = (
        select(NiftyCandle.open_time)
        .where(NiftyCandle.symbol == symbol.upper())
        .order_by(NiftyCandle.open_time.asc())
        .limit(1)
    )
    earliest = db.scalar(stmt)
    
    stmt = (
        select(NiftyCandle.open_time)
        .where(NiftyCandle.symbol == symbol.upper())
        .order_by(NiftyCandle.open_time.desc())
        .limit(1)
    )
    latest = db.scalar(stmt)
    
    date_range_days = None
    if earliest and latest:
        date_range_days = (latest - earliest).days
    
    return {
        "total_candles": count,
        "earliest_candle": earliest.isoformat() if earliest else None,
        "latest_candle": latest.isoformat() if latest else None,
        "date_range_days": date_range_days,
    }
```

---

## 11. Historical Data Coverage Reporting

### 11.1 Coverage Report Structure

```python
def generate_coverage_report(
    db: Session,
    symbol: str = "NIFTY",
    interval: str = "3min",
) -> dict:
    """Generate a comprehensive coverage report for stored candle data.
    
    Returns:
    {
        "symbol": "NIFTY",
        "interval": "3min",
        "total_candles": int,
        "date_range": {
            "earliest": "2025-08-23T03:45:00Z",
            "latest": "2026-08-22T09:27:00Z",
            "span_days": 365,
        },
        "daily_coverage": [
            {
                "date": "2026-08-22",
                "candle_count": 125,
                "expected": 125,
                "completeness_pct": 100.0,
                "is_complete": True,
                "first_candle": "2026-08-22T03:45:00Z",
                "last_candle": "2026-08-22T09:27:00Z",
            },
            ...
        ],
        "summary": {
            "total_trading_days": int,
            "complete_days": int,
            "partial_days": int,
            "empty_days": int,
            "average_completeness_pct": float,
            "expected_total_candles": int,
            "actual_total_candles": int,
            "coverage_pct": float,
            "data_start_date": "2025-08-23",
            "data_end_date": "2026-08-22",
            "missing_date_ranges": [
                {"from": "2025-12-25", "to": "2025-12-26", "reason": "likely_holiday"},
                ...
            ],
        },
        "research_readiness": {
            "min_observations_met": bool,  # >= 200 candles
            "full_validation_met": bool,   # >= 500 candles
            "robust_research_met": bool,   # >= 5000 candles
            "recommended_data_range": "6-12 months",
        },
    }
    """
```

### 11.2 Research Readiness Assessment

The coverage report directly answers the Phase 7.7 research engine's data requirements:

| Requirement | Minimum | Source |
|---|---|---|
| Basic statistical tests | 200 observations | `gexResearchTests.js: MIN_OBSERVATIONS` |
| Full validation pipeline | 500 observations | `gexResearchValidation.js: MIN_TRAIN_SIZE + MIN_TEST_SIZE` |
| Robust walk-forward | 3,000+ observations | `gexResearchValidation.js: MIN_WALK_FORWARD_WINDOWS × MIN_TRAIN_SIZE` |
| Complete forward outcomes | 30 candles after each observation | `gexResearchData.js: MIN_FORWARD_CANDLES` |

A single trading day provides 125 candles — enough for basic tests but insufficient for full validation. The coverage report tells the user exactly when they have enough data.

---

## 12. Research Dataset Integration with Phase 7.7

### 12.1 How Phase 7.7 Consumes Candle Data

The Phase 7.7 frontend research engine (`gexResearchData.js`) builds observations by:

1. Taking GEX snapshots (with `capturedAt` timestamps)
2. Joining each snapshot with the candle at or before `capturedAt` (the "reference candle")
3. Computing forward outcomes from candles AFTER the reference candle
4. Computing baseline features from candles BEFORE the reference candle

**The candle data is the FOUNDATION of the entire research pipeline.**

### 12.2 Data Flow: Backend → Frontend

```
Backend: nifty_candles table
    ↓ (GET /candles endpoint — NEW in Phase 7.8)
Frontend: gexResearchData.js → buildResearchDataset(snapshots, candles)
    ↓
Frontend: gexResearchTests.js → quintileAnalysis(...)
    ↓
Frontend: gexResearchValidation.js → validateFeature(...)
    ↓
Frontend: gexResearchRegistry.js → buildFeatureRegistry(...)
```

### 12.3 New Backend Endpoint for Research Data

Phase 7.8 adds a lightweight endpoint to serve candle data to the frontend:

**File:** `backend/app/routers/candles.py` (new)

```python
"""Candle data API (Phase 7.8).

Endpoints:
  GET /candles              — query stored candles
  GET /candles/count        — count stored candles
  GET /candles/coverage     — coverage report
"""

@router.get("/candles", response_model=CandleListOut)
def list_candles(
    symbol: str = Query("NIFTY"),
    interval: str = Query("3min"),
    limit: int = Query(500, ge=1, le=10000),
    since: str | None = Query(None),
    until: str | None = Query(None),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /candles — Query stored candles (oldest-first)."""
    require_session(session_id)
    # ... parse since/until, call get_candles(), return

@router.get("/candles/count")
def candle_count(
    symbol: str = Query("NIFTY"),
    interval: str = Query("3min"),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /candles/count — Count stored candles."""
    require_session(session_id)
    return {"count": count_candles(db, symbol=symbol, interval=interval)}

@router.get("/candles/coverage")
def candle_coverage(
    symbol: str = Query("NIFTY"),
    interval: str = Query("3min"),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /candles/coverage — Data coverage report."""
    require_session(session_id)
    return generate_coverage_report(db, symbol=symbol, interval=interval)
```

### 12.4 Separate Concerns

The data pipeline (Phase 7.8) is strictly on the **DATA** side:

```
PHASE 7.8 (this phase):          PHASE 7.7 (existing):
─────────────────────────        ─────────────────────────
Candle Pipeline:                 GEX Calculation →
  Data Source → Ingestion →      Research Analysis →
  Validation → Persistence →     Statistical Conclusions
  Quality Audit
     ↕ (shared nifty_candles table)

Contract Metadata Registry:      FUTURE (Phase 7.9+):
  Upstox Expired Instruments →   Historical Option/GEX
  Population → Lookup            Reconstruction
     ↕ (contract_specs table)
```

Phase 7.8 does NOT:
- Modify any GEX calculation logic
- Modify the research/statistical engine
- Add trading signals
- Introduce ML
- Redesign the UI
- Implement historical option/GEX reconstruction

### 12.5 Raw Data Preservation — Lot-Size Independence

> **Core principle: Raw market data must never be rewritten because of a later metadata change.**

The following data items are **lot-size-independent** and must NEVER be altered, recalculated, or back-filled based on a lot-size change:

| Data Item | Lot-Size Dependent? | Rationale |
|---|---|---|
| NIFTY candle OHLC (open, high, low, close) | **No** | Index price is independent of contract specifications |
| NIFTY candle volume | **No** | Index-level volume is not scaled by lot size |
| Historical raw OI (from option chain) | **No** (raw value preserved) | OI is a contract count; the raw count must not be rewritten |
| Historical raw volume (from option chain) | **No** (raw value preserved) | Per-contract volume must not be rewritten |
| Lot size | **Metadata only** | Used when converting quantities to notional exposure |
| Notional OI exposure (OI × lot_size × spot) | **Yes** (derived) | Must record which lot_size was used for the calculation |
| GEX (gamma × OI × S² × 0.01) | **Depends on OI** | OI is raw; GEX uses raw OI; lot_size affects notional interpretation |

**Rules:**
1. Historical raw OI and volume are **immutable source values** — they are never rewritten when lot-size regimes change.
2. Candle OHLC data is **completely independent** of lot size.
3. Lot size is **metadata** used only when converting contract-level quantities into notional exposure or units.
4. Any calculated/normalized field that depends on lot size must **retain the lot-size regime** that was in effect at the time of calculation.
5. Research datasets must be able to **reproduce which lot size was used** for any observation.
6. Historical `lot_size` from the Upstox API is **immutable after storage** — never overwritten, never inferred from current values.
7. `lot_size` and `minimum_lot` are **stored separately** — never assumed equal.

### 12.5A Historical Lot Size Architecture

The historical lot_size architecture follows these principles:

1. **V3 candle data does not provide lot_size.** The Upstox V3 Historical Candle API returns `[timestamp, O, H, L, C, volume, open_interest]` — no lot_size field. Candle ingestion is and must remain completely independent of contract metadata.

2. **Upstox Expired Option Contracts API is the authoritative source.** When available, it returns per-instrument metadata including the exact `lot_size` for each expired contract. This is the primary source.

3. **lot_size is associated with the specific instrument_key.** Each expired instrument has a unique `instrument_key` (e.g., `NSE_FO|47983|17-04-2025`). The lot_size belongs to that specific instrument — not to a date range, not to a regime.

4. **Contract metadata is an independent enrichment layer.** The `contract_specs` table is separate from `nifty_candles`. The candle pipeline never reads from or writes to `contract_specs`.

5. **Historical lot_size is never inferred.** It is never derived from:
   - The current NIFTY lot size
   - Effective-date rules or NSE circular assumptions
   - minimum_lot, freeze_quantity, or any other field
   - Any hardcoded timeline

6. **Missing lot_size remains NULL/unknown.** When the Expired Option Contracts API is unavailable or returns no data, `lot_size` stays `NULL`. The system degrades safely.

7. **Current lot_size is never substituted.** There is no code path that writes `25` (or any current value) into a historical `lot_size` field.

8. **NSE specifications/circulars are validation only.** They may be used to cross-check Upstox data, but never as a replacement source when authoritative Upstox metadata exists.

### 12.5B Free-Data Constraint

**IMPORTANT:** The Expired Option Contracts API is NOT universally free.

The API documentation indicates that access may require an Upstox Plus plan subscription (error UDAPI1149). Therefore:

- **Contract metadata is OPTIONAL.** The candle pipeline and basic research work without it.
- **The research pipeline does NOT depend on expired-contract metadata.** Missing metadata means `lot_size = NULL`, not a system failure.
- **No paid data service is required or recommended.** The system degrades gracefully when the API is unavailable.
- **When metadata IS available**, it provides authoritative per-instrument lot_size for future GEX/exposure calculations.

### 12.5C Data Lineage

Every contract metadata record retains full provenance:

- `source = "UPSTOX_EXPIRED_INSTRUMENTS"` — identifies the data provider
- `source_reference` — contains the API endpoint and request parameters for audit
- `fetched_at` — timestamp of when the metadata was retrieved

This ensures every `lot_size` value can be traced back to its authoritative source.

### 12.6 Historical Contract Metadata Registry

#### 12.6.1 Purpose

The registry is an **independent metadata layer** that stores per-instrument contract specifications sourced from the **Upstox Get Expired Option Contracts API**. It maps `instrument_key` → full contract metadata (lot_size, minimum_lot, freeze_quantity, tick_size, strike, expiry, etc.).

**Architectural principles:**
- **Primary source:** Upstox Get Expired Option Contracts API — authoritative historical instrument metadata
- **Validation source:** NSE circulars/specifications — independent cross-check, not the primary source
- **lot_size is stored exactly as returned by Upstox** — never inferred from the current lot size
- **lot_size is never overwritten** after initial storage
- **lot_size and minimum_lot are stored separately** — never assumed equal even if currently equal
- NOT embedded inside `nifty_candles.py` or `candle_ingestion.py`
- NOT consumed by the candle pipeline itself (candles are lot-size-independent)
- Consumed by **future phases** (7.9+) that reconstruct historical option chains, compute GEX, and analyze exposure

#### 12.6.2 Data Model

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class ContractSpecification:
    """Historical contract specification for an expired option instrument.

    Each row represents ONE specific instrument, identified by instrument_key.
    The metadata is sourced directly from the Upstox Get Expired Option
    Contracts API and stored EXACTLY as returned.

    Historical lot_size is NEVER inferred from the current lot size.
    Historical lot_size is NEVER overwritten after initial storage.
    """
    # Identity
    instrument_key: str          # "NSE_FO|47983|17-04-2025" — primary lookup key
    underlying: str              # "NIFTY"
    underlying_key: str          # "NSE_INDEX|Nifty 50"
    expiry: str                  # "2025-04-17"
    strike_price: float          # 20400.0
    instrument_type: str         # "CE" or "PE"

    # Contract specifications — exact values from Upstox API
    lot_size: int                # 75 — from Upstox, NEVER inferred
    minimum_lot: int             # 75 — stored separately, may differ from lot_size
    freeze_quantity: int         # 1800
    tick_size: float             # 5.0

    # Descriptive metadata
    trading_symbol: str          # "NIFTY 20400 PE 17 APR 25"
    segment: str                 # "NSE_FO"
    exchange: str                # "NSE"
    weekly: bool                 # True

    # Provenance
    source: str                  # "UPSTOX_EXPIRED_INSTRUMENTS"
    source_reference: str        # API endpoint + request parameters
    fetched_at: datetime         # when this metadata was fetched
```

**Why instrument_key is the primary key (not effective_from/effective_to):**
- Each expired instrument has a unique `instrument_key` (e.g., `NSE_FO|47983|17-04-2025`)
- The Upstox API returns per-instrument metadata — no need to interpolate or maintain a timeline
- Different expiries (weekly vs monthly) naturally have their own instrument_keys and lot_sizes
- No regime boundary logic needed — each instrument carries its own authoritative metadata
- The `lot_size` for each instrument is the exact value that was in effect when that contract was traded

#### 12.6.3 Lookup Interface

```python
def get_contract_specification(instrument_key: str) -> dict | None:
    """Resolve historical contract specification by instrument_key.

    Returns the full specification dict, or None if not found.

    Returns:
        {
            "instrument_key": str,
            "underlying": str,
            "underlying_key": str,
            "expiry": str,
            "strike_price": float,
            "instrument_type": str,
            "lot_size": int,
            "minimum_lot": int,
            "freeze_quantity": int,
            "tick_size": float,
            "trading_symbol": str,
            "segment": str,
            "exchange": str,
            "weekly": bool,
            "source": str,
            "source_reference": str,
            "fetched_at": str,  # ISO 8601
        }

    Returns None when no matching specification exists.

    NEVER silently substitutes the current lot size.
    NEVER infers historical lot_size from the current lot size.
    """
```

**Design decisions:**
- `instrument_key` is the primary lookup key — each expired contract has a unique key.
- Returns `None` (not a default) when the specification cannot be found — callers must handle this explicitly.
- Returns the complete metadata dict so callers have all fields available (lot_size, minimum_lot, freeze_quantity, etc.).
- The `lot_size` in the returned dict is the **authoritative historical value** from the Upstox API.

#### 12.6.4 Storage

```python
# SQLAlchemy model (new table)
class ContractSpec(Base):
    __tablename__ = "contract_specs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Identity
    instrument_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    underlying_key: Mapped[str] = mapped_column(String(32))
    expiry: Mapped[str] = mapped_column(String(10), index=True)
    strike_price: Mapped[float] = mapped_column(Float)
    instrument_type: Mapped[str] = mapped_column(String(8))  # CE or PE

    # Contract specifications — exact values from Upstox API
    # Nullable: historical lot_size may be unknown when API is unavailable
    lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_lot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    freeze_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Descriptive metadata
    trading_symbol: Mapped[str] = mapped_column(String(64))
    segment: Mapped[str] = mapped_column(String(16))
    exchange: Mapped[str] = mapped_column(String(8))
    weekly: Mapped[bool] = mapped_column(default=False)

    # Provenance
    source: Mapped[str] = mapped_column(String(32))
    source_reference: Mapped[str] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("instrument_key", name="uq_contract_spec_key"),
    )
```

**Key design decisions:**
- `instrument_key` has a unique constraint — one row per instrument, idempotent upsert
- `lot_size` and `minimum_lot` are **separate columns** — never assumed equal
- `expiry` is indexed for range queries ("give me all contracts expiring in Q1 2025")
- `underlying` is indexed for multi-underlying support (NIFTY, BANKNIFTY, etc.)
- `source` and `source_reference` provide full provenance for every row
- `fetched_at` records when the metadata was retrieved (API data may be updated)

#### 12.6.5 Population Flow

```
Step 1: Get Expiries API
  GET /v2/expired-instruments/expiries?instrument_key=NSE_INDEX|Nifty 50
  → List of expiry dates (e.g. ["2024-10-03", "2024-10-10", ...])

Step 2: For each expiry date, Get Expired Option Contracts API
  GET /v2/expired-instruments/option/contract?instrument_key=NSE_INDEX|Nifty 50&expiry_date=2024-10-03
  → List of contract objects with lot_size, minimum_lot, freeze_quantity, etc.

Step 3: Upsert each contract into contract_specs table
  instrument_key = unique key
  Immutability rules:
  - New row → insert with whatever lot_size the API returned
  - Existing row, same lot_size → idempotent no-op
  - Existing row, NULL lot_size + valid API lot_size → fill it
  - Existing row, valid lot_size + DIFFERENT API lot_size → DO NOT overwrite
    Report conflict. Preserve the existing authoritative value.

Step 4: Verify population
  - Count distinct instrument_keys in contract_specs
  - Verify lot_size values match API responses
  - Check for any missing expiry dates
```

**Rate limit consideration:**
- Get Expiries: 1 API call → returns ~29 expiry dates (6 months of weekly + monthly)
- Get Expired Option Contracts: 1 API call per expiry → ~29 calls for 6 months
- Total: ~30 API calls for a 6-month backfill — well within rate limits (500/min)
- Each expiry returns ~100-200 contracts (all strikes × CE/PE)
- Total contracts stored: ~3,000-6,000 rows for 6 months

### 12.7 Why Lot Size Matters for GEX

Incorrect historical lot-size assumptions silently distort derived analytics:

| Affected Metric | How Lot-Size Error Propagates | Impact |
|---|---|---|
| **OI exposure** | `notional_OI = OI × lot_size × spot` | Linear error in exposure magnitude |
| **OI shifts (ΔOI)** | `delta_OI = OI(t) × lot_size(t) - OI(t-1) × lot_size(t-1)` | If lot_size changes mid-series, a apparent ΔOI spike is actually a spec change |
| **GEX** | `GEX = gamma × OI × S² × 0.01` | OI is in raw contracts; GEX uses raw OI. Lot size affects notional interpretation |
| **Delta/Gamma/Vega exposure** | `exposure = greek × OI × lot_size × multiplier` | Direct linear error |
| **Historical comparisons** | Comparing OI/GEX across lot-size boundaries | Apparent regime change that is actually a specification change |
| **Contract-level research** | Per-expiry analysis | Wrong lot size → wrong notional → wrong research conclusions |

**Critical distinction:**

```
INDEX DATA (lot-size-independent):
  NIFTY candle OHLCV → Used directly in Phase 7.7/7.8 research.
  Does NOT depend on lot size.  Safe to compute across any time range.

OPTIONS/CONTRACT DATA (lot-size-dependent):
  OI, volume, exposure, Greeks, GEX → Require contract-specific lot size.
  Must be computed per-instrument.  Cannot assume a single lot size.
```

The candle pipeline (Phase 7.8) operates exclusively on **index data** and is therefore unaffected by lot-size changes. The registry is designed for **future phases** that will operate on contract data.

### 12.8 Historical Metadata Safety Requirements

The contract metadata registry must satisfy all of the following:

| # | Requirement | Rationale |
|---|---|---|
| 1 | **Historical lot_size is sourced from Upstox API** | Authoritative per-instrument metadata, not manually curated |
| 2 | **Store lot_size exactly as returned by Upstox** | Never infer, interpolate, or approximate historical lot_size |
| 3 | **Never overwrite raw historical lot_size** | Once stored, the value is immutable |
| 4 | **Store lot_size and minimum_lot separately** | They may differ; never assume equality |
| 5 | **Preserve instrument_key, expiry, strike, option type, underlying** | Full contract identity for downstream consumption |
| 6 | **Preserve freeze_quantity and tick_size** | Required for order-level accuracy in future phases |
| 7 | **Store provenance for every row** | Source, source_reference, fetched_at for audit trail |
| 8 | **Make missing specs explicit** | Return NULL, never silently assume a value |
| 9 | **Never silently substitute the current lot size** | This would corrupt all historical analytics |
| 10 | **Ensure historical calculations are reproducible** | Store which lot_size was used for every derived value |
| 11 | **NSE circulars serve as independent validation** | Cross-check Upstox data, not replace it |

### 12.9 Authoritative Source Strategy

> **Primary source: Upstox Get Expired Option Contracts API.** NSE circulars serve as independent validation.

The registry is populated from the Upstox API, which provides per-instrument metadata including the exact `lot_size` for each expired contract. This eliminates the need for manually maintained lot-size timelines.

**Population sequence:**

1. **Upstox API (primary):** Call Get Expiries → Get Expired Option Contracts for each expiry → upsert into `contract_specs`
2. **NSE circulars (validation):** Cross-check a sample of Upstox lot_size values against NSE contract specifications or circulars
3. **Discrepancy resolution:** If Upstox and NSE disagree, investigate and document in `source_reference`

**What the Upstox API provides per contract:**
- `lot_size` — the authoritative contracts-per-lot value
- `minimum_lot` — the minimum order lot (may differ from lot_size)
- `freeze_quantity` — maximum freeze quantity
- `tick_size` — minimum price increment
- `strike_price`, `instrument_type`, `expiry`, `instrument_key`
- `underlying_key`, `underlying_type`, `underlying_symbol`
- `trading_symbol`, `segment`, `exchange`, `weekly`

**What NSE circulars provide (validation only):**
- Lot-size change effective dates (cross-check against Upstox values)
- Contract specification changes (tick size, freeze quantity)
- Regulatory directives affecting contract specifications

### 12.10 Phase Boundary — What Phase 7.8 Does and Does NOT Include

| In Scope (Phase 7.8) | Out of Scope (Future Phase) |
|---|---|
| NIFTY candle ingestion, validation, persistence | Historical option-chain reconstruction |
| Candle coverage reporting | Historical GEX calculation |
| Contract metadata **registry data model** and **lookup interface** | Consuming the registry in GEX/exposure calculations |
| Contract metadata **storage model** (`contract_specs` table) | NSE circular validation (independent verification) |
| Contract metadata **upsert with immutability rules** | Registry population backfill script |
| Upstox expired instruments **adapter methods** | Expired historical candle data for options |
| Registry **population from Upstox API** | Real-time option chain reconstruction |
| **Historical Lot Size Architecture** documentation | |
| **Free-data constraint** documentation | |
| **Data lineage** (source, source_reference, fetched_at) | |

**Future work:** A dedicated **Phase 7.9 — Historical Option Contract/GEX Reconstruction** will:
1. Reconstruct historical option chains using Upstox V2 option-chain API (where available)
2. Compute historical GEX using the correct lot_size from the registry for each instrument
3. Feed the research dataset with both index-level (candle) and contract-level (GEX) data
4. Validate registry lot_size values against NSE circulars independently

---

## 13. Security & Credential Handling

### 13.1 Token Usage

- The candle pipeline uses the **existing user's Upstox access token** from `token_store.get_token()`
- Tokens are **never persisted** — they live in memory only
- Tokens expire daily at 3:30 AM IST — backfill must be completed within a session
- If the token expires during backfill, the pipeline stops gracefully with a clear error message

### 13.2 No New Credentials

- No new API keys, secrets, or OAuth flows
- No new environment variables
- The existing `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI` are reused
- The Upstox V3 Historical Candle API uses the **same access token** as all other Upstox endpoints
- The Upstox V2 Expired Instruments API also uses the **same access token** (requires Upstox Plus plan)

### 13.3 Backfill Script Security

The backfill scripts run as **backend CLI commands** (not web endpoints):

```bash
# --- Candle backfill ---
# Backfill last 6 months
python -m app.tools.candle_backfill --months 6

# Backfill specific date range
python -m app.tools.candle_backfill --from 2025-08-01 --to 2026-02-01

# Check current progress
python -m app.tools.candle_backfill --status

# Run coverage report
python -m app.tools.candle_backfill --report

# --- Contract metadata backfill ---
# Populate registry from Upstox expired instruments API
python -m app.tools.contract_metadata_backfill

# Check registry status
python -m app.tools.contract_metadata_backfill --status

# Validate lot_size against sample (optional)
python -m app.tools.contract_metadata_backfill --validate
```

The scripts:
1. Require an active Upstox session (uses `token_store`)
2. Do NOT accept tokens via command line or environment
3. Do NOT log or print tokens
4. Print progress to stdout (counts, chunk progress, errors)
5. The contract metadata backfill requires Upstox Plus plan

---

## 14. Rate-Limit Strategy

### 14.1 Current Upstox Documentation

| Window | Limit | Our Usage (12-month backfill) |
|---|---|---|
| Per second | 50 requests | 1 request/chunk, ~13–14 chunks = 13–14 requests total |
| Per minute | 500 requests | 13–14 requests / 1 minute = 13–14 req/min |
| Per 30 minutes | 2,000 requests | 13–14 requests / 30 minutes = 13–14 req/30min |

**We are nowhere near any rate limit for the candle pipeline.**

### 14.2 Conservative Defaults

Despite the headroom, the pipeline includes:
- `MIN_REQUEST_INTERVAL_SECONDS = 0.1` (100ms between requests)
- Exponential backoff retry on 429 responses
- Maximum 3 retries per request

### 14.3 Expired Instruments API Rate Limits

The contract metadata registry population requires:
- 1 API call for Get Expiries → returns ~29 expiry dates (6 months)
- ~29 API calls for Get Expired Option Contracts (one per expiry)
- Total: ~30 API calls — well within all rate limits
- With 100ms spacing: ~3 seconds total
- The existing retry/backoff infrastructure handles 429 responses gracefully

### 14.4 Future Considerations

If the pipeline is extended to multiple instruments (BANKNIFTY, FINNIFTY, etc.), the rate limiter becomes relevant:
- 4 instruments × 13 chunks = 52 requests for candles
- 4 instruments × 30 calls = 120 requests for contract metadata
- With 100ms spacing: ~12 seconds total — still well within limits
- The rate limiter infrastructure handles this gracefully

---

## 15. Failure / Recovery Scenarios

### 15.1 Scenario Matrix

| Scenario | Detection | Recovery | Data Impact |
|---|---|---|---|
| **Token expired (401/403)** | HTTP status code | Stop; user re-authenticates; resume | No data loss — upserts are idempotent |
| **Rate limited (429)** | HTTP status code | Retry with backoff (2s min delay) | Temporary delay only |
| **Server error (500/502/503)** | HTTP status code | Retry with exponential backoff | Temporary — data is still available |
| **Network timeout** | `httpx.RequestError` → 502 | Retry with backoff | Temporary |
| **Invalid instrument key (UDAPI100011)** | API error code | Stop; fix instrument key | No data loss |
| **Date range error (UDAPI1148)** | API error code | Adjust chunk boundaries | No data loss |
| **Partial chunk success** | Count candles vs expected | Next chunk starts where this ended | Gap may exist — coverage report shows it |
| **Server restart mid-backfill** | Script loses DB connection | Re-run script — checks progress, resumes | Already-persisted data safe |
| **SQLite locked** | SQLAlchemy OperationalError | Retry after brief delay | Temporary |
| **Disk full** | OS error on write | Stop; free space; re-run | Already-persisted data safe |
| **Concurrent backfill runs** | SQLite serialization | Last writer wins (idempotent upserts) | No corruption — may waste work |
| **Upstox Plus not subscribed (UDAPI1149)** | API error code | Surface clear error to user; candle pipeline unaffected | Contract metadata not populated |
| **Expired Instruments API partial failure** | Missing expiry dates | Re-run script — idempotent upserts skip already-populated contracts | Partial registry — lookup returns None for missing contracts |

### 15.2 Resume-After-Failure Strategy

The backfill script is designed to be **resumable**:

1. Before fetching a chunk, check if data already exists for that date range
2. If yes, skip the API call
3. If no, fetch and persist
4. If interrupted, re-run — already-completed chunks are skipped

This means a 12-month backfill interrupted at month 7 can be resumed to complete months 8–12 without re-fetching months 1–7.

### 15.3 Graceful Degradation

- If only 3 months of data are available (user logged in recently), the pipeline persists what it can and reports the gap
- The research engine adapts to whatever data is available (more data = more robust results)
- The coverage report tells the user exactly what they have

---

## 16. Testing Strategy

### 16.1 Backend Tests (pytest)

| Test File | Coverage | Est. Tests |
|---|---|---|
| `test_candle_upstox_adapter.py` | Upstox V3 adapter methods (mocked HTTP) | ~15 |
| `test_candle_normalization.py` | Timestamp conversion, OHLC normalization, gap detection | ~25 |
| `test_candle_validation.py` | OHLC integrity, duplicates, missing data, invalid candles | ~20 |
| `test_candle_backfill.py` | Backfill script logic, chunk generation, progress tracking | ~20 |
| `test_candle_coverage.py` | Coverage report, research readiness assessment | ~10 |
| `test_candle_router.py` | Candle API endpoints (auth, query, count, coverage) | ~15 |
| `test_upstox_expired_adapter.py` | Expired instruments adapter methods (mocked HTTP) | ~15 |
| `test_contract_metadata.py` | Registry population, lookup, idempotency, lot_size immutability | ~20 |
| `test_nifty_candles.py` | Existing service tests (may need additions) | ~5 |
| **Total backend tests** | | **~145** |

### 16.2 Test Approach

- **Unit tests** for normalization, validation, gap detection (pure functions)
- **Integration tests** for backfill logic with mocked Upstox responses
- **API tests** for the candle router endpoints (mocked DB)
- **No live API calls** in tests — all Upstox responses are mocked
- **Edge cases:** empty responses, malformed timestamps, zero-volume candles, holiday gaps, early-close days, weekend boundaries

### 16.3 Frontend Tests

No new frontend tests needed — the Phase 7.7 research engine is already fully tested. The new backend endpoint is a simple data query that doesn't change frontend logic.

---

## 17. Implementation Phases & File-Level Scope

### Phase 7.8A: Upstox V3 Adapter Methods

**Estimated scope:** ~80 lines of production code, ~40 lines of tests

| File | Action | Description |
|---|---|---|
| `backend/app/services/upstox.py` | Modify | Add `get_historical_candles()` and `get_intraday_candles()` methods |
| `backend/app/services/candle_config.py` | Create | Pipeline configuration constants (instrument key, chunk size, retry params) |
| `backend/tests/test_candle_upstox_adapter.py` | Create | Tests for adapter methods (mocked HTTP) |

**Verification:** Adapter methods can be called with a valid token and return candle data.

### Phase 7.8B: Ingestion & Normalization

**Estimated scope:** ~150 lines of production code, ~60 lines of tests

| File | Action | Description |
|---|---|---|
| `backend/app/services/candle_ingestion.py` | Create | Timestamp normalization, OHLC normalization, response extraction |
| `backend/tests/test_candle_normalization.py` | Create | Tests for normalization functions |

**Verification:** Raw Upstox candle arrays are correctly normalized to `record_candles()` format.

### Phase 7.8C: Validation & Quality

**Estimated scope:** ~200 lines of production code, ~80 lines of tests

| File | Action | Description |
|---|---|---|
| `backend/app/services/candle_validation.py` | Create | OHLC integrity, gap detection, duplicate detection, batch validation |
| `backend/tests/test_candle_validation.py` | Create | Tests for all validation scenarios |

**Verification:** Invalid candles are rejected, gaps are detected, duplicates are flagged.

### Phase 7.8D: Backfill Script & Retry

**Estimated scope:** ~250 lines of production code, ~80 lines of tests

| File | Action | Description |
|---|---|---|
| `backend/app/tools/__init__.py` | Create | Package marker for CLI tools |
| `backend/app/tools/candle_backfill.py` | Create | CLI backfill script with chunking, retry, progress tracking |
| `backend/app/services/candle_retry.py` | Create | Retry/backoff infrastructure |
| `backend/tests/test_candle_backfill.py` | Create | Tests for backfill logic, chunk generation, resume |

**Verification:** Backfill script can fetch 1+ months of data, persist it, and resume after interruption.

### Phase 7.8E: Coverage Report & API

**Estimated scope:** ~200 lines of production code, ~40 lines of tests

| File | Action | Description |
|---|---|---|
| `backend/app/services/candle_coverage.py` | Create | Coverage report generation, research readiness assessment |
| `backend/app/routers/candles.py` | Create | Candle data API endpoints |
| `backend/app/main.py` | Modify | Register the new candles router |
| `backend/tests/test_candle_coverage.py` | Create | Tests for coverage report |
| `backend/tests/test_candle_router.py` | Create | Tests for candle API endpoints |

**Verification:** Coverage report accurately reflects stored data; API endpoints work correctly.

### Phase 7.8F: Expired Instruments Adapter & Registry

**Estimated scope:** ~250 lines of production code, ~150 lines of tests

| File | Action | Description |
|---|---|---|
| `backend/app/services/upstox.py` | Modify | Add `get_expired_expiries()` and `get_expired_option_contracts()` methods |
| `backend/app/services/contract_metadata.py` | Create | Contract metadata registry: population, lookup, validation |
| `backend/app/tools/contract_metadata_backfill.py` | Create | CLI script to populate registry from Upstox expired instruments API |
| `backend/tests/test_contract_metadata.py` | Create | Tests for registry population, lookup, idempotency |
| `backend/tests/test_upstox_expired_adapter.py` | Create | Tests for expired instruments adapter methods (mocked HTTP) |

**Verification:** Registry can be populated from Upstox API, lookup returns correct lot_size for known expired contracts.

### Phase 7.8G: Integration & Documentation

**Estimated scope:** ~100 lines of documentation, config additions

| File | Action | Description |
|---|---|---|
| `backend/app/config.py` | Modify | Add `CANDLE_BACKFILL_ENABLED` config option |
| `backend/app/services/nifty_candles.py` | Modify | Append `+ "Z"` in `_row_to_dict()` for unambiguous UTC timestamps | +2 |
| `docs/GEX_PHASE_7_8_DESIGN.md` | Modify | Update status to "implemented" |

---

## 18. Files Summary

### Files to Create

| # | File | Purpose | Est. Lines |
|---|---|---|---|
| 1 | `backend/app/services/candle_config.py` | Pipeline constants | ~40 |
| 2 | `backend/app/services/candle_ingestion.py` | Normalization, response parsing | ~150 |
| 3 | `backend/app/services/candle_validation.py` | OHLC integrity, gap detection | ~200 |
| 4 | `backend/app/services/candle_retry.py` | Retry/backoff infrastructure | ~80 |
| 5 | `backend/app/services/candle_coverage.py` | Coverage report, research readiness | ~200 |
| 6 | `backend/app/services/contract_metadata.py` | Contract metadata registry: population, lookup, validation | ~200 |
| 7 | `backend/app/tools/__init__.py` | Package marker | ~1 |
| 8 | `backend/app/tools/candle_backfill.py` | CLI backfill script | ~250 |
| 9 | `backend/app/tools/contract_metadata_backfill.py` | CLI script to populate registry from Upstox API | ~150 |
| 10 | `backend/app/routers/candles.py` | Candle data API endpoints | ~120 |
| 11 | `backend/tests/test_candle_upstox_adapter.py` | Adapter tests | ~100 |
| 12 | `backend/tests/test_candle_normalization.py` | Normalization tests | ~150 |
| 13 | `backend/tests/test_candle_validation.py` | Validation tests | ~200 |
| 14 | `backend/tests/test_candle_backfill.py` | Backfill tests | ~200 |
| 15 | `backend/tests/test_candle_coverage.py` | Coverage report tests | ~100 |
| 16 | `backend/tests/test_candle_router.py` | API endpoint tests | ~150 |
| 17 | `backend/tests/test_contract_metadata.py` | Registry population, lookup, idempotency tests | ~150 |
| 18 | `backend/tests/test_upstox_expired_adapter.py` | Expired instruments adapter tests (mocked HTTP) | ~100 |
| **Total new** | | | **~2,340** |

### Files to Modify

| # | File | Change | Est. Lines Changed |
|---|---|---|---|
| 1 | `backend/app/services/upstox.py` | Add 4 adapter methods (candle + expired instruments) | +60 |
| 2 | `backend/app/models.py` | Add `ContractSpec` model | +35 |
| 3 | `backend/app/main.py` | Register candles router | +2 |
| 4 | `backend/app/config.py` | Add CANDLE_BACKFILL_ENABLED | +2 |
| 5 | `backend/app/services/nifty_candles.py` | Append `+ "Z"` in `_row_to_dict()` | +2 |
| **Total modified** | | | **+101** |

### Files That Must Remain Untouched

| File | Reason |
|---|---|
| `frontend/lib/calculations/gexResearchData.js` | Phase 7.7 research engine — no changes |
| `frontend/lib/calculations/gexResearchTests.js` | Phase 7.7 statistical engine — no changes |
| `frontend/lib/calculations/gexResearchValidation.js` | Phase 7.7 validation framework — no changes |
| `frontend/lib/calculations/gexResearchRegistry.js` | Phase 7.7 registry — no changes |
| `backend/app/services/gex_history.py` | GEX history — separate concern |
| All Phase 7.1–7.7 frontend files | Explicitly excluded from Phase 7.8 scope |

> **Note on `nifty_candles.py`:** The core persistence logic (`record_candles()`, `get_candles()`, `count_candles()`, `prune_candles()`) remains **completely untouched**. The only change is a 2-character addition to `_row_to_dict()` (appending `+ "Z"` to the ISO timestamp string) to ensure unambiguous UTC serialization. This is a Phase 7.8 fix for the pre-existing timezone limitation documented in §6.1A.
>
> **Note on `models.py`:** The `NiftyCandle` model is untouched. The only addition is the new `ContractSpec` model for the contract metadata registry.

---

## 19. Estimated Implementation Scope

| Metric | Estimate |
|---|---|
| **Production code** | ~1,440 lines |
| **Test code** | ~900 lines |
| **Total new code** | ~2,340 lines |
| **Files created** | 18 |
| **Files modified** | 5 |
| **Files untouched** | All Phase 7.1–7.7 frontend files |
| **New API endpoints** | 3 (GET /candles, /candles/count, /candles/coverage) |
| **New CLI commands** | 2 (candle_backfill, contract_metadata_backfill) |
| **New config options** | 1 (CANDLE_BACKFILL_ENABLED) |
| **New DB tables** | 1 (contract_specs) |
| **Implementation phases** | 7 (7.8A through 7.8G) |

---

## 20. Test Count Estimate

| Category | Count |
|---|---|
| Backend tests (new) | ~145 |
| Backend tests (existing, unchanged) | 1,110 |
| **Total backend tests** | **~1,255** |
| Frontend tests (unchanged) | 1,357 |
| **Total tests** | **~2,612** |

---

## 21. Risks

### 21.1 Upstox API Changes

**Risk:** Upstox may deprecate or modify the V3 Historical Candle API.
**Mitigation:** The adapter layer isolates all Upstox-specific code. Only `upstox.py` and `candle_config.py` need updating if the API changes.

### 21.2 Data Completeness

**Risk:** Upstox may not have complete historical data for all dates (data gaps before the API's availability window).
**Mitigation:** The coverage report explicitly quantifies data completeness. The research engine adapts to whatever data is available.

### 21.3 Timestamp Precision

**Risk:** Upstox timestamps may not be perfectly aligned to 3-minute boundaries (e.g. 9:15, 9:18, 9:21...).
**Mitigation:** The normalization layer stores whatever timestamp the API provides. The research engine matches by `openTime` proximity, not exact alignment.

### 21.4 Token Expiry During Backfill

**Risk:** Upstox tokens expire daily at 3:30 AM IST. A backfill started late in the day may run out of token lifetime.
**Mitigation:** A 12-month backfill takes <3 seconds of API time. Even a 1-month backfill takes <1 second. Token expiry is only a risk if the user starts backfill and then walks away for hours (unusual).

### 21.5 SQLite Performance at Scale

**Risk:** 31,250+ candles in one table may slow queries.
**Mitigation:** The `nifty_candles` table has indexes on `symbol`, `interval`, and `open_time`. SQLite handles millions of rows efficiently with proper indexes. 31K rows is trivial.

### 21.6 NSE Holiday Calendar

**Risk:** Missing candles on market holidays are expected but may be flagged as gaps.
**Mitigation:** The gap detector classifies gaps as "market session" vs "non-market session." Coverage report distinguishes expected gaps (holidays/weekends) from unexpected gaps (data loss).

### 21.7 Upstox Expired Instruments API Availability

**Risk:** The Get Expired Option Contracts API requires an Upstox Plus plan subscription (error code UDAPI1149).
**Mitigation:** Check for UDAPI1149 and surface a clear message to the user. The candle pipeline (7.8A-7.8E) is independent and works without expired instruments.

### 21.8 Upstox Expired Instruments Data Completeness

**Risk:** The Get Expiries API covers only ~6 months of historical expiries. Contracts older than 6 months may not be available.
**Mitigation:** The registry stores whatever the API returns. Missing contracts are explicitly absent from the registry (lookup returns None). The coverage report quantifies registry completeness. Future phases can supplement with NSE circular data if needed.

### 21.9 Contract Metadata lot_size Consistency

**Risk:** Upstox API lot_size values might not match NSE circular specifications.
**Mitigation:** NSE circulars serve as an independent validation source. A validation script can cross-check a sample of registry values against NSE specifications. Discrepancies are documented in source_reference.

### 21.10 Registry Population Rate Limits

**Risk:** Populating the registry requires ~30 API calls (1 for expiries + ~29 for contracts). If the user has rate-limited themselves, some calls may fail.
**Mitigation:** Use the existing retry/backoff infrastructure. The population script is idempotent — re-running it skips already-populated contracts.

---

## 22. Recommended Implementation Order

```
Phase 7.8A: Upstox V3 Adapter Methods (candle + expired instruments)
    ↓ (prerequisite for all subsequent phases)
Phase 7.8B: Ingestion & Normalization
    ↓ (prerequisite for validation and backfill)
Phase 7.8C: Validation & Quality
    ↓ (prerequisite for backfill quality checks)
Phase 7.8D: Backfill Script & Retry
    ↓ (depends on A, B, C)
Phase 7.8E: Coverage Report & API
    ↓ (depends on D for meaningful reports)
Phase 7.8F: Expired Instruments Adapter & Registry
    ↓ (depends on A for adapter methods)
Phase 7.8G: Integration & Documentation
    (depends on all above)
```

**Critical path:** 7.8A → 7.8B → 7.8D → 7.8E

**Parallelizable:**
- 7.8C can be developed alongside 7.8B (validation is independent of normalization)
- 7.8F can be developed alongside 7.8D/7.8E (registry is independent of candle pipeline)

**Total estimated implementation time:** 2–3 focused sessions.

---

## 23. Assumptions to Verify Before Implementation

| # | Assumption | How to Verify | Risk if Wrong |
|---|---|---|---|
| 1 | Upstox V3 Historical Candle API accepts the same access token as other V2/V3 endpoints | Test with a valid token against the V3 historical-candle endpoint | Pipeline cannot authenticate |
| 2 | NIFTY instrument key `NSE_INDEX|Nifty 50` works for historical candles (not just option chains) | Test: `GET /v3/historical-candle/NSE_INDEX|Nifty 50/minutes/3/2026-08-22/2026-08-21` | Wrong instrument key — no data |
| 3 | 3-minute interval returns data from 2022 to present | Fetch a known date (e.g. 2024-01-02) and verify candles are returned | Data availability window narrower than expected |
| 4 | The `from_date` parameter is truly optional (omitting it returns one day) | Test: `GET /v3/historical-candle/NSE_INDEX|Nifty 50/minutes/3/2026-08-22` | Must always provide both dates |
| 5 | Upstox returns candles in reverse chronological order (newest first) | Fetch 2+ days and verify order | Must sort after fetch |
| 6 | Timestamps are consistently IST with `+05:30` offset | Fetch and inspect timestamp format | May need different parsing logic |
| 7 | Volume for NIFTY index is meaningful (not always 0) | Fetch and check volume values | May need to handle zero-volume candles |
| 8 | Open interest for NIFTY index is always 0 (it's an index, not a future/option) | Fetch and check OI values | May need to handle non-zero OI |
| 9 | The existing `record_candles()` SQLite upsert works correctly with the V3 response format after normalization | Run the full pipeline on one chunk and verify data in the DB | May need to adjust normalization |
| 10 | Rate limits (50/sec, 500/min, 2000/30min) apply to historical candle endpoints specifically, not just order endpoints | Check Upstox rate-limit docs or test empirically | May need more conservative pacing |
| 11 | Upstox Get Expiries API returns all available expiry dates for NIFTY (weekly + monthly) covering ~6 months | Test with a valid token: `GET /v2/expired-instruments/expiries?instrument_key=NSE_INDEX|Nifty 50` | Registry may have incomplete coverage |
| 12 | Upstox Get Expired Option Contracts API returns per-contract metadata including lot_size, minimum_lot, freeze_quantity | Test with a known expiry: `GET /v2/expired-instruments/option/contract?instrument_key=NSE_INDEX|Nifty 50&expiry_date=2025-04-17` | Registry cannot be populated |
| 13 | Expired Option Contracts API requires Upstox Plus plan (error UDAPI1149 if not subscribed) | Test without Plus plan and check for UDAPI1149 | Pipeline must surface clear error |
| 14 | Expired Option Contracts API returns lot_size = 75 for NIFTY contracts expiring in April 2025 (pre-lot-size-reduction) | Fetch a known expired contract and verify lot_size | Registry would store wrong values |
| 15 | lot_size and minimum_lot may differ for some instruments (currently equal for NIFTY but not guaranteed) | Check multiple expired contracts for different values | Must store separately, never assume equality |

---

## 24. Appendix: API Request/Response Examples

### 24.1 Historical Candle Request

```bash
curl --location 'https://api.upstox.com/v3/historical-candle/NSE_INDEX%7CNifty%2050/minutes/3/2026-08-22/2026-08-21' \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json' \
  --header 'Authorization: Bearer {access_token}'
```

### 24.2 Historical Candle Response

```json
{
    "status": "success",
    "data": {
        "candles": [
            ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
            ["2026-08-22T15:24:00+05:30", 25490.0, 25505.0, 25475.0, 25500.0, 12000, 0],
            ["2026-08-22T09:15:00+05:30", 25400.0, 25410.0, 25390.0, 25405.0, 18000, 0]
        ]
    }
}
```

### 24.3 Normalized for Storage

```python
# After IST → UTC conversion and format normalization:
{
    "symbol": "NIFTY",
    "interval": "3min",
    "openTime": "2026-08-22T09:57:00Z",  # 15:27 IST → 09:57 UTC
    "open": 25500.0,
    "high": 25520.0,
    "low": 25480.0,
    "close": 25510.0,
    "volume": 15000.0,
}
```

### 24.4 Get Expiries Request

```bash
curl --location 'https://api.upstox.com/v2/expired-instruments/expiries?instrument_key=NSE_INDEX%7CNifty%2050' \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json' \
  --header 'Authorization: Bearer {access_token}'
```

### 24.5 Get Expiries Response

```json
{
    "status": "success",
    "data": [
        "2024-10-03",
        "2024-10-10",
        "2024-10-17",
        "2024-10-24",
        "2024-10-31",
        "2024-11-07",
        "2024-11-14",
        "2024-11-21",
        "2024-11-28",
        "2024-12-05",
        "2024-12-12",
        "2024-12-19",
        "2024-12-26",
        "2025-01-02",
        "2025-01-09",
        "2025-01-16",
        "2025-01-23",
        "2025-01-30",
        "2025-02-06",
        "2025-02-13",
        "2025-02-20",
        "2025-02-27",
        "2025-03-06",
        "2025-03-13",
        "2025-03-20",
        "2025-03-27",
        "2025-04-03",
        "2025-04-09",
        "2025-04-17"
    ]
}
```

### 24.6 Get Expired Option Contracts Request

```bash
curl --location 'https://api.upstox.com/v2/expired-instruments/option/contract?instrument_key=NSE_INDEX%7CNifty%2050&expiry_date=2025-04-17' \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json' \
  --header 'Authorization: Bearer {access_token}'
```

### 24.7 Get Expired Option Contracts Response

```json
{
    "status": "success",
    "data": [
        {
            "name": "NIFTY",
            "segment": "NSE_FO",
            "exchange": "NSE",
            "expiry": "2025-04-17",
            "instrument_key": "NSE_FO|47983|17-04-2025",
            "exchange_token": "47983",
            "trading_symbol": "NIFTY 20400 PE 17 APR 25",
            "tick_size": 5,
            "lot_size": 75,
            "instrument_type": "PE",
            "freeze_quantity": 1800,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_type": "INDEX",
            "underlying_symbol": "NIFTY",
            "strike_price": 20400,
            "minimum_lot": 75,
            "weekly": true
        },
        {
            "name": "NIFTY",
            "segment": "NSE_FO",
            "exchange": "NSE",
            "expiry": "2025-04-17",
            "instrument_key": "NSE_FO|47982|17-04-2025",
            "exchange_token": "47982",
            "trading_symbol": "NIFTY 20400 CE 17 APR 25",
            "tick_size": 5,
            "lot_size": 75,
            "instrument_type": "CE",
            "freeze_quantity": 1800,
            "underlying_key": "NSE_INDEX|Nifty 50",
            "underlying_type": "INDEX",
            "underlying_symbol": "NIFTY",
            "strike_price": 20400,
            "minimum_lot": 75,
            "weekly": true
        }
    ]
}
```

### 24.8 Normalized for Contract Metadata Registry

```python
# After extracting from Upstox API response:
{
    "instrument_key": "NSE_FO|47983|17-04-2025",
    "underlying": "NIFTY",
    "underlying_key": "NSE_INDEX|Nifty 50",
    "expiry": "2025-04-17",
    "strike_price": 20400.0,
    "instrument_type": "PE",
    "lot_size": 75,           # authoritative from Upstox
    "minimum_lot": 75,         # stored separately
    "freeze_quantity": 1800,
    "tick_size": 5.0,
    "trading_symbol": "NIFTY 20400 PE 17 APR 25",
    "segment": "NSE_FO",
    "exchange": "NSE",
    "weekly": True,
    "source": "UPSTOX_EXPIRED_INSTRUMENTS",
    "source_reference": "GET /v2/expired-instruments/option/contract?instrument_key=NSE_INDEX|Nifty 50&expiry_date=2025-04-17",
    "fetched_at": "2026-08-23T12:00:00Z",
}
```
