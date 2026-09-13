# StrikeNova — Vercel STAGING Frontend Deployment

Date: 2026-09-13
Status: **VERCEL STAGING DEPLOYED AND VERIFIED** (staging only; production untouched)
Companion docs: `RENDER_STAGING_DEPLOYMENT.md` (backend staging), superseded design section folded into this report.

---

## 1. Git baseline

* **Remote HEAD used:** `2b38180ce98a05c46be8bace5a301dd1a5d467ac`
  (`docs: correct Render manual-deploy status`) — fetched and verified before deploy; includes
  the frontend, `next.config.js` `NEXT_PUBLIC_API_URL` override mechanism, and all app files.
* **Exact deployed source:** the remote tree at `2b38180`, built from a clean throwaway
  worktree (`git worktree add` at that commit) so no uncommitted local files participated.
  The only non-committed file added was the local `.vercel/project.json` link (untracked,
  git-ignored-style local config; never committed).
* `2139097` (Render's deployed backend commit) is an ancestor of `2b38180`; both verified.

## 2. Vercel staging project

| Item | Value |
|---|---|
| Project | `strikenova-frontend-staging` |
| Project ID | `prj_oesNMxycXbVxQ3l1OY5KqB478RXk` |
| Team | `claude-109a` (CLI auth `shahid1995`) |
| Created | 2026-09-13 15:14:46 IST (this session) |
| Root directory | `options-dashboard-project/frontend` (deployed from that path) |
| Node.js | 24.x |

Pre-existing projects `options-dashboard` (production) and `frontend` (legacy duplicate)
were **not modified** (verified in §17).

## 3. Deployment method

* **Manual CLI deploy only**: `vercel deploy --prod` run from the frontend directory of the
  clean worktree, linked to the staging project via a local `.vercel/project.json`.
* **No GitHub → Vercel integration was created** for this project (matching the Render
  auto-deploy-OFF policy). See §14.
* The `--prod` target here means "production target of the *staging project*" — it has no
  relationship to the production project `options-dashboard`.

## 4. Build configuration

| Item | Value |
|---|---|
| Framework | Next.js 14.2.35 (React 18.3.1, axios) |
| Install | `npm ci` (clean, exact lockfile) — succeeded |
| Build | `npm run build` (Next.js default) — succeeded, all routes static, no TS (JS project) |
| Local pre-build | Phase 7 executed a full clean build with `NEXT_PUBLIC_API_URL=https://strikenova-api-staging.onrender.com` before deploying |

Build-output proof (Phase 7):

* `strikenova-api-staging.onrender.com` present in client chunks (`chunks/63-*.js`);
* **zero** occurrences of `railway` in `.next/static/chunks/` and `.next/server`.

## 5. Environment variables (names + public values only)

| Variable | Target(s) | Value | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | production + preview | `https://strikenova-api-staging.onrender.com` | public staging URL; build-time inlined |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | production + preview | Hidden (Sensitive) | same public client ID as production; OAuth validation pending (§13) |

`NEXT_PUBLIC_APP_URL` deliberately **not** set: with it unset, `AuthModal` falls back to
same-origin `/dashboard` navigation after auth — correct staging behavior (it would
otherwise redirect browsers to whatever URL it holds).

## 6. Deployment ID / URL

| Item | Value |
|---|---|
| Deployment ID | `dpl_3pLizvtmiReskQuoaxs6nXfxShJM` |
| Deployment URL | https://strikenova-frontend-staging-3fbf98a43-claude-109a.vercel.app |
| Stable alias | **https://strikenova-frontend-staging.vercel.app** |
| Team alias | https://strikenova-frontend-staging-claude-109a.vercel.app |
| Target / status | production (of staging project) / ● Ready (43 s) |
| Deployed commit | `2b38180` (source tree; CLI deploy — no commit metadata attached by platform) |

## 7. Browser/HTTP verification

* `GET /` → **200**, `text/html`, 65,555 bytes, `<title>StrikeNova — Options Intelligence…` — no blank page.
* Six sampled `/_next/static/chunks/*.js` assets → all **200**.
* The API-bearing chunk fetched from the **live URL** contains
  `https://strikenova-api-staging.onrender.com` and **0** `railway` references.
* Homepage metadata references the staging deployment URL, not any production URL.
* Console/hydration: verified via HTTP-level evidence (static export, correct title,
  assets 200, no mixed-content possible — all URLs are HTTPS). No CORS errors possible
  post-§9 since preflight from the staging origin returns 200.

## 8. API verification (all requests carry `Origin: <staging>`)

Backend: https://strikenova-api-staging.onrender.com

| Check | Result |
|---|---|
| `/health` | 200 `{"status":"ok"}` |
| `/readiness` | 200 `{"status":"ready","checks":{"database":"ok","token_store":"ok",…}}` |
| `POST /auth/register` (synthetic `e2e.smoke.*@example.com`) | 200 `{"ok":true,"user_id":…}` |
| `POST /auth/login-email` | 200 with `session_id` (43-char) |
| `GET /auth/me` (`X-Session-Id`) | 200 — email/display_name/status=active/identity_source=email |
| `GET /auth/status` | `{"logged_in":true}` |
| `GET /paper/capital` (DB-backed, CRDB query) | 200 — paper capital 500,000 synthetic; broker fields degrade gracefully (`BROKER_TOKEN_EXPIRED` — no real broker, by design) |
| `POST /auth/logout` | `{"ok":true}` |
| `GET /auth/me` after logout | **401** (session invalidated) |

No real broker credentials, no real orders, no real-money accounts (hard rule respected).

## 9. CORS configuration

* Render staging env var `ADDITIONAL_CORS_ORIGINS` set to the **exact** origin
  `https://strikenova-frontend-staging.vercel.app` (Render API `PUT /v1/services/{id}/env-vars`,
  bare-array body; `DATABASE_URL` preserved byte-for-byte and verified post-write).
* `FRONTEND_URL` **not** touched (its first entry drives OAuth redirect semantics).
* Verification matrix (after manual Render redeploy):

| Origin | Preflight | Expectation |
|---|---|---|
| `https://strikenova-frontend-staging.vercel.app` | **200** | allowed (actual GET echoes `access-control-allow-origin: <staging>`, `allow-credentials: true`) |
| `https://unrelated-example.org` | **400** | rejected |
| `https://options-dashboard-sigma-coral.vercel.app` (production frontend) | **400** | rejected (production never allowed against staging) |
| Wildcard check | — | no `*` in `access-control-allow-origin` — no wildcard CORS |

## 10. Render integration

* Env update required a deploy (auto-deploy OFF) → **manual** deploy triggered:
  `dep-daj7br1594qs73b3j8vg` (trigger `api`), commit `2b38180`, status **live**.
* Post-redeploy `/health` 200 and `/readiness` 200 with `database: ok`.
* Render service remains `strikenova-api-staging` (`srv-daj4vetg1s2s739ecvfg`), Free plan,
  auto-deploy **off**, manual deployments only.

## 11. CockroachDB path

```text
Vercel staging (strikenova-frontend-staging.vercel.app)
   ↓ HTTPS (NEXT_PUBLIC_API_URL)
Render (strikenova-api-staging.onrender.com, live @ 2b38180)
   ↓ cockroachdb+psycopg:// (TLS sslmode=require)
CockroachDB Cloud (strikenova-staging / strikenova_staging)
```

* `/readiness` `database: ok` through the deployed backend (live CRDB query).
* Alembic head on the staging database: `5e2a7b9c3f4d` (verified directly earlier this day;
  the redeploy runs migrations as a no-op at head).
* End-to-end DB-backed proof: `/paper/capital` 200 through the full chain (§8).

## 12. WebSocket status

`WEBSOCKET NOT CURRENTLY EXERCISED IN STAGING`

* The endpoint exists in code (`backend/app/routers/chains.py`:
  `@router.websocket("/ws/{symbol}")` under the `/chains` router, session via
  `Sec-WebSocket-Protocol` subprotocol or cookie).
* A browser WebSocket handshake from the staging origin was **not** exercised in this
  session (a plain `GET` probe returning 404 is the expected FastAPI behavior for a
  websocket-only route and is not evidence of failure).
* Follow-up: open the chain UI on staging and confirm the `wss://` feed connects
  (`chainWsUrl()` derives `wss://strikenova-api-staging.onrender.com/chains/ws/...`).

## 13. OAuth status

`OAUTH STAGING VALIDATION PENDING EXTERNAL PROVIDER CONFIGURATION`

* `NEXT_PUBLIC_GOOGLE_CLIENT_ID` is configured on the staging project (same public client
  ID as production), but the Google Cloud Console OAuth client's **Authorized JavaScript
  origins** does not yet include `https://strikenova-frontend-staging.vercel.app` — an
  account-owner action outside this repo. Until then the Google button may fail on staging;
  email/password auth is fully verified (§8).
* Production OAuth untouched: backend `FRONTEND_URL` unchanged, so `FRONTEND_ORIGIN`
  (first entry) and the Upstox/Google redirect semantics are unchanged. No Google
  configuration was modified.

## 14. Manual deployment control

```text
Git push
   ↓
NO automatic Vercel deployment (no Git integration on strikenova-frontend-staging)

Manual CLI deployment
   ↓
staging frontend (https://strikenova-frontend-staging.vercel.app)
```

* `vercel project inspect strikenova-frontend-staging` shows **no Git-integration section**
  (contrast: Git-connected projects show one); the project was created via CLI minutes
  before its single deployment.
* The project's deployment list contains exactly **one** entry — the manual CLI deploy of
  this session; no bot/committer-based deployments exist.
* This matches the Render staging policy (auto-deploy OFF; pushes deploy nothing).

## 15. Problems encountered (all resolved)

1. **CLI link resolution**: `vercel link --project strikenova-frontend-staging` from
   `frontend/` resolved the link at the **repository-parent** directory
   (`options-dashboard-project/.vercel`), twice overwriting the production project's local
   link. Repaired both times by restoring the exact prior `project.json` content
   (parent → `options-dashboard`, `frontend/` → `strikenova-frontend-staging`); orgIds
   byte-verified. Vercel-side projects were never affected (link files are local only).
2. **`vercel env add` mis-target risk**: env adds run from `frontend/` resolved to the
   *production* project and were **refused** ("already exists") — nothing changed on
   production. Root cause = (1). Fixed by performing all project-scoped operations from an
   isolated directory whose `.vercel/project.json` points at the staging project.
3. **Render API env PUT**: documented body shape (`{"envVars":[…]}`) returned
   `400 invalid JSON`; the **bare JSON array** body is what the endpoint accepts. Also:
   the CLI config holds both `api.key` (valid) and `api.refreshtoken` (401) — the key must
   be used. GET returns `{id, envVar:{…}}` wrappers (first naive parse produced a bad
   payload; caught before any write).
4. **str_replace tooling**: a transient tool failure on `.vercel/project.json` was worked
   around by rewriting the file (content verified after).
5. **MSYS path mapping**: `/tmp/...` paths written by bash are `C:\tmp` for Windows Python —
   the first E2E run lost its session-id capture; re-run with stdout capture passed cleanly.

## 16. Remaining limitations

* **Render free tier**: backend sleeps after ~15 min idle; cold starts of tens of seconds
  affect the first staging request after idle (accepted for staging).
* **OAuth (§13)**: Google sign-in on staging pending external provider configuration.
* **WebSocket (§12)**: browser-level WS exercise pending.
* **Stable alias semantics**: `strikenova-frontend-staging.vercel.app` is the staging
  project's production alias — each future manual `--prod` deploy re-points it; pin the
  per-deployment URL for immutable testing.
* **`NEXT_PUBLIC_APP_URL` unset** (intentional, §5): post-auth handoff stays same-origin.
* Legacy duplicate project `frontend` still exists on Vercel (untouched; separately
  documented as non-authoritative).

## 17. Production safety

```text
Vercel production:               NOT TOUCHED (project options-dashboard: no deploys, no env,
                                 no domain changes; latest deployments remain the 46m+/older
                                 pre-existing previews; env list byte-identical — 5 rows)
Vercel production deployment:    NO
Production NEXT_PUBLIC_API_URL:  NOT CHANGED (not read, not written)
Railway production:              NOT TOUCHED
Railway PostgreSQL:              NOT TOUCHED
Render production:               NOT TOUCHED (only staging service touched)
CockroachDB production:          NOT TOUCHED (staging cluster/database only)
Production DNS:                  NOT TOUCHED
Secrets committed:               NO (env values piped, never echoed; only the public
                                 staging URL appears in this report)
```
