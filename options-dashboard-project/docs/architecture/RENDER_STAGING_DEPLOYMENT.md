# StrikeNova — Render Free STAGING Deployment

Date: 2026-09-13
Branch: `feat/strikenova-day35-portfolio-intelligence`
Final status: **RENDER STAGING DEPLOYED AND VERIFIED** (staging only; free tier)

```text
GitHub (shahid1995/-options-dashboard @ 2139097)
   ↓
Render Free (strikenova-api-staging, singapore)
   ↓
StrikeNova FastAPI backend (uvicorn, Procfile-equivalent start)
   ↓
CockroachDB Cloud (strikenova-staging / strikenova_staging)
```

---

## 1. Render service

| Item | Value |
|---|---|
| Service | `strikenova-api-staging` |
| ID | `srv-daj4vetg1s2s739ecvfg` |
| Plan | **free** |
| Region | `singapore` |
| Runtime | python (buildpack-style; no Dockerfile in repo) |
| URL | https://strikenova-api-staging.onrender.com |
| Auto-deploy | on (branch push) |
| Instances | 1 |

Authentication: Render CLI v2.28.0 (`render-oss/cli`), device-authorization browser login;
token stored locally by the CLI (`~/.render/cli.yaml`, 0600) — never printed or committed.

## 2. Git commit deployed

* **Commit:** `2139097f2f11bba77dd2c79c9815333306d74fe7` (`fix: repair CRDB deployment prerequisites`)
* **Remote verified:** YES — `origin/feat/strikenova-day35-portfolio-intelligence` HEAD equals
  `2139097`; contains committed `merge_day38_gex.py` and `sqlalchemy-cockroachdb==2.0.3`.
* `b847e58` NOT deployed (superseded; the deployed commit contains all its required fixes).
* No uncommitted local work was deployed (all Day41.2/parallel-session changes remain local).

## 3. Build configuration

| Item | Value |
|---|---|
| Root directory | `options-dashboard-project/backend` |
| Build command | `pip install -r requirements.txt` |
| Python runtime | Render python runtime (requirements-driven) |
| Source of truth | `backend/requirements.txt` at `2139097` |

Build log verified the exact pinned stack installed: `sqlalchemy-2.0.43`,
`sqlalchemy-cockroachdb-2.0.3`, `psycopg-3.3.5`, `alembic-1.15.2`, `fastapi-0.141.1`.

## 4. Runtime command

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

(matches the repository's committed `backend/Procfile`; Render injects `$PORT`.)

## 5. Environment variables (names only)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `cockroachdb+psycopg://…strikenova_staging…sslmode=require` (managed by Render; value never printed/committed) |

No other variables were required for staging boot; the app defaults handle the rest.
NOT changed: `UPSTOX_*`, `FRONTEND_URL`, `TOKEN_ENCRYPTION_KEY`, etc. (no production values copied).

**Tooling note (documented defect of the first attempt):** the initial CLI invocation suffered
Git-Bash path mangling — `--health-check-path /health` became `C:/Program Files/Git/health`
causing health-probe 404s and a deploy timeout — and the env var did not persist (the new CLI
v2.28.0 has no env-var flags; `services update --env-var` does not exist). Fixes: health path
re-set with `MSYS_NO_PATHCONV=1`; `DATABASE_URL` set via the Render REST API
(`PUT /v1/services/{id}/env-vars`) using the CLI's locally stored token. Both verified
afterwards via `services get` / env-vars listing (names only).

## 6. CockroachDB cluster/database

* Cluster `strikenova-staging` (CockroachDB Cloud Basic/serverless, GCP `asia-south1`, v26.2.6)
* Database `strikenova_staging`, user `strikenova_staging_app` (dedicated, least-privilege; not `root`)
* TLS `sslmode=require` — never disabled
* Network access: cluster default (public endpoint + TLS + credentials); no allowlist
  weakening performed. Narrowest practical change: none required.
* Migration head on this database: `5e2a7b9c3f4d` (pre-arrived from §13 verification);
  the deployed service confirmed the same head at runtime.

## 7. Migration result

* The application's own startup path (`init_db` → Alembic `upgrade head`) ran against
  `strikenova_staging` during boot: **no errors, already at head `5e2a7b9c3f4d`**
* No `KeyError: 'merge_day38_gex'`, no missing revisions, no untracked migration required —
  committed files only
* 37 tables present; single `alembic_version` row re-verified post-deploy

## 8. Health result

```text
GET https://strikenova-api-staging.onrender.com/health
→ 200 {"status":"ok"}
```

## 9. Readiness result

```text
GET https://strikenova-api-staging.onrender.com/readiness
→ 200 {"status":"ready","checks":{"database":"ok","token_store":"ok","active_sessions":0}}
```

`database: ok` is a real DB-backed check **through the deployed service** — this alone proves
Render → FastAPI → CockroachDB Cloud connectivity.

## 10. DB smoke test

* Readiness check (DB-backed) — PASS (above)
* Direct-to-DB re-verification of catalog/head: 37 tables, `5e2a7b9c3f4d`, single row — PASS
* Transaction commit + rollback executed against the staging database (synthetic `_render_smoke`
  table, dropped afterwards) — PASS

## 11. CRDB smoke test (staging database, deployed configuration)

| Check | Result |
|---|---|
| `ON CONFLICT (k) DO UPDATE` upsert (twice) | PASS |
| `RETURNING k, v` | PASS |
| Rollback discards RETURNING insert | PASS |

These complement (not replace) the comprehensive CRDB validation already documented in
`COCKROACH_LIVE_COMPATIBILITY_VALIDATION.md` and this repo's other CRDB audit reports.

Endpoint sanity through the public URL: `/health` 200, `/readiness` 200; unknown routes
return FastAPI 404 (no 500s observed); runtime log scan: **zero** ERROR/Traceback/KeyError/
AssertionError/ModuleNotFound lines across the deploy window.

## 12. Render free-tier limitations (documented, not worked around)

* The free service **sleeps after ~15 minutes of inactivity**; the next request pays a
  **cold start** (spin-up, potentially tens of seconds).
* Free instances have limited CPU/RAM; the first full-DB boot path (empty database, 17
  migrations over WAN) took minutes in the §13 pre-deploy proof — on an already-migrated
  database, boot is fast (observed: startup complete in ~3 s).
* Auto-deploy is ON: pushes to the branch trigger rebuilds; deploys of broken commits
  would replace the live service until rolled back (Render keeps the last healthy deploy
  available for rollback).
* **This is staging only** — it is not the intended final production hosting tier.

## 13. Security verification

* Secrets: none committed, none printed. `DATABASE_URL` lives in Render's env-var store;
  the CRDB credential file remains local-only (`~/.strikenova_staging_crdb.txt`, 0600).
* Render CLI token stored locally by the CLI; never echoed.
* TLS to CRDB enforced (`sslmode=require`); certificate validation untouched.

## 14. Northflank billing blocker (preserved history)

Northflank service creation remains blocked at the account level:
`409 Please complete your account by adding a default payment method` — attempted twice
(sessions of 2026-09-13) against the user-created `strikenova` project; user declined to add
a card; no workarounds attempted. Northflank project remains UNTOUCHED (no service created).
See `NORTHFLANK_STAGING_DEPLOYMENT.md` §13–§14 for the full record.

## 15. Production-boundary verification

```text
Railway production:      NO CHANGE
Railway PostgreSQL:      NO CHANGE
Vercel production:       NO CHANGE
Northflank:              NO SERVICE CREATED
Production DB:           NO CHANGE
Production DNS:          NO CHANGE
Production traffic:      NO CHANGE
```

## 16. CORS state (inspected, not modified)

* `OPTIONS` preflight from a non-allowed origin → `400 Bad Request` (CORSMiddleware rejects
  disallowed origins; allow-headers/methods advertised).
* `GET` with `Origin: http://localhost:3000` (default `FRONTEND_URL`) → `200` with
  `access-control-allow-origin: http://localhost:3000` echoed.
* No wildcard CORS; no broadening performed. To connect a real staging frontend later, set
  `FRONTEND_URL`/`ADDITIONAL_CORS_ORIGINS` on the Render service (follow-up, not done here).

## 17. Known follow-ups

1. If a staging frontend needs CORS access, configure `FRONTEND_URL`/
   `ADDITIONAL_CORS_ORIGINS` on the Render service.
2. Free-tier sleep/cold-start is accepted for staging; do not use for load or soak tests.
3. The Northflank path remains documented and ready if billing ever changes (§13–§14 of the
   Northflank report).
4. `c7d3e5f8a9b2` raw-string `postgresql_where` remains a latent SQLite-path defect
   (non-blocking for CRDB; documented in the Northflank report §13).
