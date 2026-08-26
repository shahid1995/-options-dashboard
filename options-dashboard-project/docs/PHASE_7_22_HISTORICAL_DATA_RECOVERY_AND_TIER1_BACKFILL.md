# Phase 7.22 — Historical Data Recovery and Controlled Tier-1 Backfill

**Date:** 2026-08-24
**Status:** PASS
**Scope:** Rebuild historical dataset with persistent database

---

## Executive Summary

Phase 7.22 successfully rebuilt the historical dataset that was lost during the Phase 7.20 CWD bug. The production database now contains:

- **20,584 contract specifications** across 99 historical expiries
- **37,647 option candles** across 300 instruments
- **625 NIFTY index candles** (5 trading days)
- **Historical lot-size transition preserved:** 25 → 65 → 75
- **Zero duplicates, zero data corruption**
- **168 post-close option candles** (after 15:27 IST) correctly preserved

---

## 1. Database

| Metric | Before | After |
|--------|--------|-------|
| Database path | `C:\...\backend\paper_journal.db` | Same (deterministic) |
| File size | 2,097,152 bytes | Increased (data stored) |
| contract_specs | 0 | 20,584 |
| nifty_candles | 0 | 625 |
| option_candles | 0 | 37,647 |
| option_greeks | 0 | 0 (not yet calculated) |

---

## 2. Contract Metadata

| Metric | Value |
|--------|-------|
| Expiries available | 99 |
| Expiries processed | 99 |
| Contracts inserted | 20,584 |
| CE contracts | ~10,292 |
| PE contracts | ~10,292 |
| Historical lot-size distribution | 25: 2,969 / 65: 7,427 / 75: 10,188 |

### Lot-Size Transition (Verified)

| Period | Lot Size | Contracts |
|--------|----------|-----------|
| Oct 2024 | 25 | ~230 per expiry |
| Nov–Dec 2024 | 25 | ~230 per expiry |
| Jan 2025 | 25→65 transition | Mixed |
| Feb 2025+ | 65 | ~210 per expiry |
| Later period | 75 | ~210 per expiry |

**Critical verification:** The historical lot-size transition (25→65→75) is preserved exactly as returned by the Upstox API. No current lot size was substituted.

---

## 3. NIFTY Index Candles

| Metric | Value |
|--------|-------|
| Candle count | 625 |
| Trading days | 5 |
| Date range | 2026-08-11 to 2026-08-17 |
| Candles per day | 125 (09:15–15:27 IST) |
| Timezone | UTC (normalized from +05:30) |

---

## 4. Option Candles

| Metric | Value |
|--------|-------|
| Total candles | 37,647 |
| Instruments | 300 |
| Date range | 2024-10-31 to 2026-08-18 |
| Pilot (2024-10-31) | 750 candles (6 contracts) |
| Tier-1 (Feb–Aug 2026) | 36,897 candles (294 contracts) |
| Post-close candles (>15:27 IST) | 168 |
| Invalid candles | 0 |
| Duplicates | 0 |

---

## 5. Pilot Results (2024-10-31)

| Metric | Value |
|--------|-------|
| Contracts | 6 |
| Lot size | 25 (historical, preserved) |
| Candles per contract | 125 (exact trading day) |
| Total candles | 750 |
| Invalid | 0 |
| API calls | 6 |
| Elapsed | 5.33s |

### Idempotency Test

| Metric | First Run | Second Run |
|--------|-----------|------------|
| API calls | 6 | 0 |
| New candles | 750 | 0 |
| Elapsed | 5.33s | 0.03s |
| Status | ok | skipped_existing |

---

## 6. Tier-1 Backfill Results

| Metric | Value |
|--------|-------|
| Monthly expiries | 7 (Feb–Aug 2026) |
| Contracts selected | 294 |
| Contracts fetched | 294 |
| Candles persisted | 36,897 |
| Invalid candles | 0 |
| API errors | 0 |
| Elapsed | 228s (~3.8 min) |
| Rate | ~1.3 contracts/sec |

---

## 7. Post-Close Option Data

| Metric | Value |
|--------|-------|
| Post-close candles (>15:27 IST) | 168 |
| Treatment | Stored in option_candles |
| Greek calculation | Uses last NIFTY index close |

Post-close option candles (15:27–15:40 IST) are correctly preserved. When used for Greek reconstruction, they will use the last available NIFTY index close price as the spot reference.

---

## 8. Local-First Verification

The historical database now serves as the local source of truth:

- Contract metadata: 20,584 records in `contract_specs`
- Option candles: 37,647 records in `option_candles`
- Index candles: 625 records in `nifty_candles`

Future queries should read from the local database, not re-query Upstox for data that has already been stored.

---

## 9. Files Created/Modified

### Created (2)

| File | Purpose |
|------|---------|
| `backend/app/routers/backfill_endpoint.py` | Temporary backfill endpoint |
| `docs/PHASE_7_22_HISTORICAL_DATA_RECOVERY_AND_TIER1_BACKFILL.md` | This report |

### Modified (1)

| File | Change |
|------|--------|
| `backend/app/main.py` | Added backfill_endpoint router (+2 lines) |

---

## 10. Test Results

| Suite | Tests | Result |
|-------|------:|--------|
| Full backend | 1,736 | All pass |
| Full frontend | 1,357 | All pass |

---

## 11. Protected-File Scope Audit

| Area | Status |
|------|--------|
| Frontend | **ZERO diff** |
| GEX calculations | **Untouched** |
| IV calculations | **Untouched** |
| Research engine | **Untouched** |
| Auth/OAuth | **Untouched** |
| Phase 7.1–7.21 | **Untouched** |

---

## 12. Deployment Status

- **Commit:** NO
- **Push:** NO
- **Deploy:** NO

---

## 13. Remaining Work

The temporary `backfill_endpoint.py` should be removed after Phase 7.22 is complete. The next phases should:

1. **Phase 7.23:** Greek reconstruction on the local dataset
2. **Phase 7.24:** GEX integration with historical data
3. **Phase 7.25:** Daily incremental ingestion pipeline

---

*No commits, pushes, or deployments were performed.*
