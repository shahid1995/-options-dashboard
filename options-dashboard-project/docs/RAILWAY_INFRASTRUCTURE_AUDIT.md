# Railway Infrastructure Audit

**Date:** 2026-08-31
**Project:** `efficient-curiosity` (ID: `c605b992-9d1c-40c9-b4d6-6c38b583d3ef`)

---

## Existing Environments

| Environment | ID | Status |
|-------------|-----|--------|
| `production` | `23d61e12-442a-4a46-8932-486a6da7abb9` | Active |
| `pr-31` | (PR environment) | Active |

## Production Resources

### Backend Service

| Property | Value |
|----------|-------|
| Name | `-options-dashboard` |
| Service ID | `7e6badf4-0f65-4a4c-a731-25b464b9923a` |
| URL | `https://options-dashboard-production-fb47.up.railway.app` |
| Branch | `main` |
| Database | SQLite (in-container, no persistent volume) |

### Production Backend Variables (names only)

- `DATABASE_URL` — **NOT SET** (backend falls back to SQLite)
- `STRIKENOVA_MIGRATION_TARGET_URL` — points to production PostgreSQL
- `TOKEN_ENCRYPTION_KEY`
- `GOOGLE_CLIENT_ID`
- `ADDITIONAL_CORS_ORIGINS`
- `FRONTEND_URL`
- `RAILWAY_ENVIRONMENT` = `production`

### PostgreSQL Service

| Property | Value |
|----------|-------|
| Name | `Postgres` |
| Service ID | `17c4d5b5-6abd-46a1-a485-7c168cbc73ee` |
| Database | `railway` |
| Host | `postgres.railway.internal` |
| Port | `5432` |
| Volume | `postgres-volume` |

### PR #31 Environment

| Property | Value |
|----------|-------|
| Backend | `pr31-backend` (ID: `866515b1-9e44-49a2-98d7-14efc6384e6f`) |
| URL | `https://pr31-backend-pr-31.up.railway.app` |
| PostgreSQL | **None** |

## Key Findings

1. **Production backend uses SQLite** — `DATABASE_URL` is not set
2. **Production PostgreSQL exists** but is NOT used by the backend (only by `STRIKENOVA_MIGRATION_TARGET_URL`)
3. **No staging environment exists** — only `production` and `pr-31`
4. **PR #31 environment has no PostgreSQL** — it uses the production PostgreSQL via variable reference
5. **Production isolation is clear** — creating a `staging` environment will create separate services

## Staging Strategy

Create a new `staging` environment with:
1. New backend service (separate from production)
2. New PostgreSQL service (separate from production)
3. `DATABASE_URL` pointing to staging PostgreSQL
4. No shared variables with production

This provides:
- Separate services
- Separate databases
- Separate credentials
- Separate domains
- No risk to production
