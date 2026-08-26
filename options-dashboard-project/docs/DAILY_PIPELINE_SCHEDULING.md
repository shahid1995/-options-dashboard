# StrikeNova — Daily Pipeline Scheduling Guide

## Overview

The daily data pipeline automatically discovers NIFTY option contracts, fetches missing candles, calculates Greeks, and computes historical GEX. It runs once per trading day after market close.

## Pipeline Stages

```
Stage 1: NIFTY underlying candles (3min)
Stage 2: Contract metadata refresh (3 most recent expiries)
Stage 3: Option candles (incremental, deduplicated)
Stage 4: Historical Greeks (Black-Scholes, only missing)
Stage 5: Historical GEX (only missing)
Stage 6: Validation report
```

## Scheduling

### Railway (Recommended)

Add a **Scheduled Job** in Railway dashboard:

```
Service: strikenova-backend
Command: cd /app && python run_daily.py
Schedule: 30 16 * * 1-5
Timezone: Asia/Kolkata
```

This runs at **16:30 IST** (11:00 UTC) on weekdays, giving 1 hour after market close for data availability.

### GitHub Actions (Alternative)

Add to `.github/workflows/ci.yml` or create a separate workflow:

```yaml
name: Daily Ingestion
on:
  schedule:
    - cron: '30 11 * * 1-5'  # 16:30 IST = 11:00 UTC
  workflow_dispatch:
    inputs:
      date:
        description: 'Target date (YYYY-MM-DD)'
        required: false
```

### Manual Execution

```bash
# Run for last trading day
python run_daily.py

# Run for specific date
python run_daily.py --date 2026-08-26

# Dry run (no API calls)
python run_daily.py --dry-run

# Skip specific stages
python run_daily.py --skip-greeks --skip-gex

# Show current status
python run_daily.py --status
```

## Environment Variables

Required for the daily pipeline:

```bash
# Upstox API credentials
UPSTOX_API_KEY=your_api_key
UPSTOX_API_SECRET=your_api_secret
UPSTOX_REDIRECT_URI=https://your-app.com/auth/callback

# Database (Railway auto-provides PostgreSQL URL)
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Frontend
FRONTEND_URL=https://your-app.vercel.app
```

## Concurrency Protection

The pipeline uses a run_id-based lock to prevent concurrent execution:

```python
# In DailyIngestionPipeline
self.run_id = f"daily_{uuid.uuid4().hex[:12]}"
```

Each run logs to `ingestion_log` with a unique `run_id`. Two runs for the same date will detect existing data and skip duplicates.

## Failure Recovery

The pipeline is idempotent and resumable:

- **Partial failure**: Successful stages are committed; failed stages can be retried
- **Process crash**: Next run resumes from missing data (incremental by design)
- **Duplicate run**: Existing records are detected and skipped (unique constraints)

## Monitoring

Check pipeline status:

```bash
python run_daily.py --status
```

This shows:
- Current IST time
- Last trading day
- Contract specs count
- NIFTY candles count
- Option candles count
- Recent daily ingestion runs

## Expected Runtime

| Stage | Typical Duration |
|---|---|
| NIFTY candles | 2-5 seconds |
| Contract refresh | 5-10 seconds |
| Option candles | 5-15 minutes |
| Greeks | 2-5 minutes |
| GEX | 1-3 minutes |
| **Total** | **~10-25 minutes** |

## Troubleshooting

### "No valid access token"
User must log in via `/auth/login` before the daily pipeline can run. The pipeline uses the in-memory token store.

### "Market may not be closed yet"
Run after 16:00 IST. The pipeline warns if run before market close.

### Partial failure
Check `run_daily.py --status` for error details. Failed instruments are logged but don't block other instruments.
