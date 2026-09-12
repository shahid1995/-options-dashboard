# StrikeNova — Northflank Staging Deployment

**Deployment ID:** NORTHFLANK-STAGING-001  
**Date:** 2026-09-12  
**Status:** 🔴 BLOCKED — AUTHENTICATION UNAVAILABLE  
**Baseline commit:** `a29b3edccce278a4366695f390d54f96252cdc26`  
**Migration head:** `5e2a7b9c3f4d`

---

## 1. Deployment Summary

**Status:** BLOCKED

The Northflank staging deployment cannot proceed because authenticated access to both Northflank and CockroachDB Cloud is unavailable in this environment.

---

## 2. Git Commit Deployed

**Commit SHA:** `a29b3edccce278a4366695f390d54f96252cdc26`  
**Branch:** `feat/strikenova-day35-portfolio-intelligence`  
**Message:** `docs: publish StrikeNova Obsidian discovery report`

This is the latest validated commit containing all CRDB compatibility fixes.

---

## 3. Blockers

### 3.1 Northflank Authentication

**Status:** UNAVAILABLE

- `northflank` CLI: NOT FOUND
- `.northflank` config files: NOT FOUND
- `NORTHFLANK_*` environment variables: NOT FOUND

**Required:** Northflank API token or CLI authentication to create/manage projects and services.

### 3.2 CockroachDB Cloud Access

**Status:** UNAVAILABLE

- `cockroach` CLI: NOT FOUND (local test binary exists but is not CockroachDB Cloud)
- `.cockroach` config files: NOT FOUND
- `COCKROACH_*` environment variables: NOT FOUND

**Required:** CockroachDB Cloud API key or connection string for a dedicated staging cluster.

---

## 4. Pre-Deployment Readiness

The following have been validated and are ready for deployment:

| Component | Status | Evidence |
|-----------|--------|----------|
| Application code | ✅ Ready | Latest commit includes all CRDB fixes |
| Migration chain | ✅ Ready | Head: `5e2a7b9c3f4d` |
| CRDB compatibility | ✅ Validated | Runtime validation passed |
| Dockerfile | ✅ Present | `Dockerfile` at repository root |
| Health endpoint | ✅ Present | `/health` endpoint exists |
| Alembic config | ✅ Present | `alembic.ini` and `alembic/env.py` |

---

## 5. Required Actions to Unblock

To proceed with Northflank staging deployment, the following are needed:

1. **Northflank Authentication**
   - Install Northflank CLI: `npm install -g @northflank/cli`
   - OR set `NORTHFLANK_API_TOKEN` environment variable
   - Verify access: `northflank auth status`

2. **CockroachDB Cloud Access**
   - Create/select a dedicated CockroachDB Cloud cluster for staging
   - Create a `strikenova_staging` database
   - Create a dedicated application user (`strikenova_staging_app`)
   - Obtain the connection string for Northflank secrets

---

## 6. Infrastructure Design (Pending)

The intended staging architecture:

```
GitHub (feat/strikenova-day35-portfolio-intelligence)
  │
  ▼
Northflank Project: strikenova-staging
  │
  └── Service: strikenova-api-staging
          │
          │ HTTPS
          ▼
     CockroachDB Cloud Cluster (staging)
          │
          └── Database: strikenova_staging
                  │
                  └── User: strikenova_staging_app
```

---

## 7. Production Safety

| Resource | Status |
|----------|--------|
| Railway production | NOT TOUCHED |
| Railway PostgreSQL | NOT TOUCHED |
| Vercel production | NOT TOUCHED |
| Production DNS | NOT TOUCHED |
| Production data | NOT TOUCHED |

---

## 8. Next Steps

1. Obtain Northflank authentication
2. Obtain CockroachDB Cloud access for staging
3. Re-attempt deployment with authenticated access

---

*End of deployment report.*
