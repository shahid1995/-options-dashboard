# Staging Observation Procedure

**Date:** 2026-08-31
**Staging URL:** `https://staging-backend.up.railway.app`
**PostgreSQL:** `Postgres-EYbJ` (9.6MB)

---

## Available Railway Metrics

| Metric | Availability | Command |
|--------|-------------|---------|
| Deployment status | ✅ CLI | `railway service status --service staging-backend` |
| Application logs | ✅ CLI | `railway logs --service staging-backend` |
| PostgreSQL size | ✅ SSH + psql | `pg_size_pretty(pg_database_size('railway'))` |
| PostgreSQL connections | ✅ SSH + psql | `SELECT count(*) FROM pg_stat_activity` |
| CPU/Memory | ⚠️ Dashboard only | Not available via CLI |
| Error rate | ⚠️ Manual log inspection | `railway logs \| grep -i error` |

## Manual Observation Schedule

| Frequency | Check | Command |
|-----------|-------|---------|
| Every 4 hours | Service status | `railway service status --service staging-backend` |
| Every 4 hours | Health endpoint | `curl -s https://staging-backend.up.railway.app/health` |
| On error | Application logs | `railway logs --service staging-backend \| grep -i error` |
| Daily | PostgreSQL size | `psql -c "SELECT pg_size_pretty(pg_database_size('railway'))"` |
| Daily | Connection count | `psql -c "SELECT count(*) FROM pg_stat_activity"` |

## Evidence Collected

### 2026-08-31 Initial Observation

| Check | Result |
|-------|--------|
| Service status | ✅ SUCCESS |
| Health endpoint | ✅ `{"status":"ok"}` |
| Application logs | ✅ Clean startup, no errors |
| PostgreSQL size | ✅ 9.6MB |
| PostgreSQL connections | ✅ Active |
| Error count | ✅ 0 |

### No automated monitoring is configured.

This is a manual observation procedure. Evidence is collected by running the commands above at the specified intervals.
