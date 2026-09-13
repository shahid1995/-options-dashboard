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
| Auto-deploy | **OFF** (manual deploys only — corrected post-publication, see §18) |
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
* Auto-deploy is **OFF** (changed 2026-09-13, after this report was first published —
  see §18): a Git push does **not** trigger a Render deployment. Deployments are manual
  and controlled, per StrikeNova standing policy:

  ```text
  Git push
     ↓
  NO automatic Render deployment

  Manual deployment
     ↓
  Render staging
  ```

* Because deploys are manual, a broken commit can never auto-replace the live staging
  service; Render keeps the last healthy deploy available for rollback.
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
* **CORS update required after Vercel staging URL is known** — the Vercel staging frontend
  does not exist yet, so its origin cannot be defined; do not pre-broaden CORS to guessed
  origins (planning session of 2026-09-13).

## 17. Known follow-ups

1. If a staging frontend needs CORS access, configure `FRONTEND_URL`/
   `ADDITIONAL_CORS_ORIGINS` on the Render service.
2. Free-tier sleep/cold-start is accepted for staging; do not use for load or soak tests.
3. The Northflank path remains documented and ready if billing ever changes (§13–§14 of the
   Northflank report).
4. `c7d3e5f8a9b2` raw-string `postgresql_where` remains a latent SQLite-path defect
   (non-blocking for CRDB; documented in the Northflank report §13).
5. CORS: set `FRONTEND_URL`/`ADDITIONAL_CORS_ORIGINS` on Render once the Vercel staging
   URL exists (§16 — update required after Vercel staging URL is known).
6. ~~Google OAuth needs `TOKEN_ENCRYPTION_KEY` on the service~~ — **DONE 2026-09-13**, see §19.
7. ~~Google OAuth needs `GOOGLE_CLIENT_ID` on the service~~ — **DONE 2026-09-13**, see §20.
8. Frontend OAuth-state defect fixed upstream in the same commit this service now runs
   (`4a3d31e`); no backend change was required.

## 20. Post-publication configuration change #3 — GOOGLE_CLIENT_ID + staging OAuth client (2026-09-13)

Follow-up to §19, completing the staging Google OAuth chain with a **separate** staging
Google Cloud project and Web OAuth client (production OAuth client untouched):

* **`GOOGLE_CLIENT_ID` configured: YES** — set to the new **staging** Client ID via the
  Render API env-vars PUT (bare-array). No client secret exists or is used: the flow is a
  public-client `response_type=id_token` browser flow, and the backend verifies the ID
  token's `aud` against this same Client ID (`jwt_decode(..., audience=client_id)`).
* **Environment set after the change** (names verified via API):
  `[ADDITIONAL_CORS_ORIGINS, DATABASE_URL, GOOGLE_CLIENT_ID, TOKEN_ENCRYPTION_KEY]` —
  the three pre-existing variables preserved byte-for-byte (re-verified after the write).
* **Same-Client-ID proof:** the Render value equals the staging Client ID baked into the
  served Vercel staging bundle — frontend and backend verified to share one staging client.
* **Manual deployment** (auto-deploy remains OFF): deploy `dep-dajb7ruk1f9s73cv940g`,
  commit `4a3d31e` — `fix(auth): pass mandatory OAuth state on Google callback login` —
  status **live**. `/health` 200, `/readiness` 200 (database ok).
* **Google-state endpoint result:** `POST /auth/google/state` → **HTTP 200** with CORS
  headers and the expected `{state, nonce}` shape (lengths 129/43; values never recorded).
* **Browser result:** "Continue with Google" on the staging frontend completes the backend
  handshake (200) with no CORS failure, no 500, no missing-state error; the redirect toward
  Google's authorization UI is stopped only by the local loopback-preview harness boundary.
* **Google-side acceptance:** a server-rendered preflight of the exact auth URL built by the
  frontend bundle (staging Client ID + staging origin as both JavaScript origin and redirect
  URI) returned the real **"Sign in – Google Accounts"** page with **no** `invalid_client`,
  **no** `redirect_uri_mismatch`, and no other OAuth error — Google accepts the staging
  client and origin configuration.
* **Email/password regression sweep:** register → login → `/auth/me` 200 →
  `/auth/status` `logged_in:true` → `/paper/capital` 200 (CRDB-backed) → logout 200 →
  post-logout `/auth/me` **401**. Unaffected.
* **Full Google login:** PENDING — the final consent step requires an interactive human
  Google account in a normal browser; no remaining external configuration is known to be
  required. Production cutover was NOT performed.

## 21. Final verification — full Google login completed (2026-09-13)

The account owner completed the interactive Google consent in a normal browser. The
staging backend's request logs provide direct server-side evidence of the complete flow
(requests originated from the authenticated staging browser session):

```text
15:08:21Z  POST /auth/google/state   200   (state + nonce issued)
           --- 11 s Google consent ---
15:08:32Z  POST /auth/google         200   (ID token aud-validated against the staging client;
                                           signed state + nonce verified; session created)
15:08:32Z  GET  /auth/me             200
15:08:33Z  GET  /auth/status         200
15:08:41Z  GET  /paper/capital       200   (DB-backed, CRDB, under the Google session)
15:09:16Z  POST /auth/logout         200
```

* Post-logout invalidation re-verified server-side (fresh round-trip: login → me 200 →
  `/paper/capital` 200 → logout 200 → me **401**).
* Zero OAuth errors in the log window: no `invalid_client`, no `redirect_uri_mismatch`,
  no state errors, no CORS failures (preflights 200), no `TOKEN_ENCRYPTION_KEY` error.
* Client-ID parity re-verified after login: served frontend bundle and Render
  `GOOGLE_CLIENT_ID` both equal the staging Client ID; env set remains exactly
  `[ADDITIONAL_CORS_ORIGINS, DATABASE_URL, GOOGLE_CLIENT_ID, TOKEN_ENCRYPTION_KEY]`.
* Freshness: `/health` 200, `/readiness` 200, `POST /auth/google/state` 200.
* This service was NOT redeployed or reconfigured for the login itself — it already ran
  the verified configuration. Production (Vercel `options-dashboard`, Railway, production
  DB, production Google OAuth client) untouched.

**Verdict: `GOOGLE OAUTH STAGING FULLY VERIFIED`.**

## 22. Post-publication configuration change #4 — BACKEND_URL (2026-09-13)

Preparation for real Upstox OAuth staging validation
(`UPSTOX_STAGING_OAUTH_VALIDATION.md`):

* **`BACKEND_URL` configured: YES** — `https://strikenova-api-staging.onrender.com`,
  added via the Render API env-vars PUT (bare-array). All five variables
  verified after write:
  `[ADDITIONAL_CORS_ORIGINS, BACKEND_URL, DATABASE_URL, GOOGLE_CLIENT_ID,
  TOKEN_ENCRYPTION_KEY]` — the four pre-existing variables preserved
  byte-for-byte.
* The application derives `UPSTOX_REDIRECT_URI = {BACKEND_URL}/auth/callback`
  when unset (verified against the committed `config.py`), yielding exactly
  `https://strikenova-api-staging.onrender.com/auth/callback` — the URI the
  staging Upstox Developer App must be registered with.
* **Manual deployment** (auto-deploy remains OFF; exactly one deploy):
  deploy `dep-dajco2fqj5pc73d3uhe0`, commit `f1dea0a`, status **live**.
* **Resulting health:** `/health` 200, `/readiness` 200 (`database: ok`,
  `token_store: ok`). Post-deploy regression sweep green (register → login →
  `/auth/me` → `/paper/capital` → `/auth/google/state` → logout → 401).
* `UPSTOX_API_KEY` / `UPSTOX_API_SECRET` / `UPSTOX_REDIRECT_URI` are
  deliberately NOT set — the BYOB per-user flow stores user credentials
  encrypted per connection; service-level Upstox vars are a documented
  fallback pending the user's staging Developer App.

## 19. Post-publication configuration change #2 — TOKEN_ENCRYPTION_KEY (2026-09-13)

Follow-up to §18, resolving the Google OAuth 500 found during staging browser acceptance
(`STAGING_BROWSER_ACCEPTANCE.md` §11/§18):

* `TOKEN_ENCRYPTION_KEY` **configured: YES** — value **NEVER RECORDED** (generated
  cryptographically random in-process, piped directly into the Render API write; never
  printed, logged, or committed). It exists only in Render's secret store.
* Safety: staging DB verified to contain **zero** encrypted broker-credential rows before
  the key was introduced (setting a key is lossless on an empty credential store).
* `DATABASE_URL` and `ADDITIONAL_CORS_ORIGINS` preserved byte-for-byte (verified after write).
* **Manual deployment** (auto-deploy remains OFF): deploy `dep-daj7qtgae00c738tspo0`,
  commit `e97d692` (docs-only HEAD; app code identical to the validated baseline),
  status **live**.
* **Resulting health:** `/health` 200, `/readiness` 200 with `database: ok`.
* **Google-state endpoint result:** `POST /auth/google/state` → **200** with correct CORS
  headers and the expected `{state, nonce}` shape — the previous 500 is resolved.
* Remaining (external, not this service): register the Vercel staging origin in the Google
  OAuth client's Authorized JavaScript origins (account-owner action; shared-with-production
  client left untouched by this session).

## 18. Post-publication configuration change (2026-09-13)

After this report was first published, Render auto-deploy was disabled to enforce the
StrikeNova standing deployment policy (deployments are manual and controlled; a Git push
must NOT automatically deploy the backend).

* **Change:** service `srv-daj4vetg1s2s739ecvfg` `autoDeploy: on → off`
  (`autoDeployTrigger: commit → off`).
* **Method:** Render CLI v2.28.0 `services update <id> --auto-deploy=false --confirm`.
* **Verification (explicit, not assumed):** fresh `services get` shows
  `autoDeploy: no`, `autoDeployTrigger: off`; the subsequent documentation push
  (`2139097..390cdfe`) created **zero** new deploys (deploy list unchanged at 2 entries);
  live deploy `dep-daj57j3m8hqs73evpme0` remained `live` at commit `2139097` with
  `/health` and `/readiness` both 200 and `database: ok`.
* No other service configuration was altered; no redeploy was triggered by the change.
* This section records the delta; §1 reflects the current state.
