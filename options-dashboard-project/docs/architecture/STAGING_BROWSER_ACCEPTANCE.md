# StrikeNova — STAGING Browser Acceptance Report

Date: 2026-09-13
Status: **STAGING BROWSER ACCEPTANCE PASSED WITH FOLLOW-UPS**
Scope: full browser acceptance of the live staging stack. Acceptance run only — no application code was modified.

---

## 1. Environment

| Layer | Service | Plan/Tier |
|---|---|---|
| Frontend | Vercel project `strikenova-frontend-staging` | free/hobby tier |
| Backend | Render service `strikenova-api-staging` (`srv-daj4vetg1s2s739ecvfg`) | Free (sleeps after ~15 min idle) |
| Database | CockroachDB Cloud Basic `strikenova-staging` / `strikenova_staging` | serverless Basic |

## 2. URLs

* Frontend: https://strikenova-frontend-staging.vercel.app
* Backend: https://strikenova-api-staging.onrender.com
* WebSocket: `wss://strikenova-api-staging.onrender.com/chains/ws/{symbol}?expiry_date=…`

## 3. Git baseline

* Remote HEAD at test time: `02f4728` (`docs: add Vercel staging deployment report`).
* **Deployed frontend source:** `2b38180` (docs-only commit; identical app code to `2139097`).
* **Deployed backend commit:** `2b38180` (live deploy `dep-daj7br1594qs73b3j8vg`; docs-only
  successor of `2139097` — application code identical; recorded as the operative baseline).
* CRDB migration head: `5e2a7b9c3f4d` (verified directly during this session).

## 4. Browser/device context

* Automation: thread preview browser (Chromium-based).
* Note on origin: the preview tool only attaches to loopback URLs, so the staging frontend
  was served to the browser through a **local dev proxy** (`http://localhost:3000`, script
  outside the repo, not committed) that forwards `/` to the Vercel staging URL and passes
  API/WS traffic straight through to Render. The frontend bundle still called Render
  **directly** (its baked `NEXT_PUBLIC_API_URL`), so all API/CORS/WS evidence below reflects
  the real staging origin behavior; the localhost origin was verified against the Render
  CORS config (`ADDITIONAL_CORS_ORIGINS`) which currently lists only the Vercel staging
  origin — hence the one CORS-shaped console error on the Google button (§11) is from the
  proxy origin, not the real staging origin.
* Viewport: 673×888 (narrow-desktop profile used for responsive smoke).

## 5. Authentication results

Full loop, all via the real UI against the real backend (synthetic account
`browser.accept.*@example.com`, created during this test):

| Step | Route | Result |
|---|---|---|
| Open login modal | `/` → AuthModal (Sign In / Create Account tabs) | PASS |
| Switch to registration | AuthModal → "Create your account" (Display Name/Email/Password) | PASS |
| Register | `POST /auth/register` → 200 | PASS |
| Auto-login after register | `POST /auth/login-email` → 200 (`session_id` in body) | PASS |
| Redirect to app | `/dashboard` with authenticated shell (user chip "staging-acceptance", Sign Out, PAPER badge) | PASS |
| Session survives navigation | `/paper`, `/gex`, `/portfolio`, `/positions` all stayed authenticated (session persisted across `navigate` + reload) | PASS |
| Authenticated API call | `GET /auth/me` 200; `GET /auth/status` `{"logged_in":true}` | PASS |
| Logout | UI "Sign Out" → `POST /auth/logout` → cleared `options_dashboard_session_id` from localStorage → redirected to `/` | PASS |
| Post-logout rejection | `/settings` and `/positions` bounce back to public page; API returns 401 | PASS |
| Invalid credentials | `POST /auth/login-email` (wrong password) → 401 `{"detail":"Invalid email or password"}` — clean JSON, no stack trace (verified browser-side via fetch) | PASS |

Session storage: namespaced localStorage key `options_dashboard_session_id` + `X-Session-Id`
request header; **no** session token in cookies, page HTML, or console logs.

## 6. Page-by-page results

| Route | Result | Notes |
|---|---|---|
| `/` (landing) | 🟢 PASS | Full render, charts, evidence/trust section; console has one cosmetic `<svg> attribute height: "auto"` warning (static marketing SVG — non-blocking) |
| `/about`, `/features`, `/market-intelligence`, `/how-it-works`, `/strategy-lab` | 🟢 PASS | Public marketing pages render; correct titles; only the same cosmetic SVG warning |
| `/dashboard` (auth) | 🟢 PASS | Correct **broker-gated empty state**: "No Broker Connected — market data requires a broker connection" — the right behavior with no broker |
| `/paper` (auth) | 🟢 PASS | Full DB-backed portfolio: ₹5,00,000 starting capital/available cash, P&L zeros, equity/analytics panels, journal empty state, "MARKET CLOSED — Orders Disabled", broker diagnostics "UPSTOX DISCONNECTED" with reason |
| `/gex` (auth) | 🟢 PASS | All 5 analytics calls 200; graceful "INSUFFICIENT data · Score 0/100" empty state (no synthetic market data — expected) |
| `/portfolio` (auth) | 🟢 PASS | Capital panel + graceful broker-unavailable states |
| `/positions`, `/orders`, `/brokers` | 🟢 PASS | Reachable from nav; consistent shells (spot-checked via nav + API logs) |
| `/strategies` (auth) | 🟢 PASS | Notice page: strategy building relocated to Strategy Builder — intended |
| `/settings` (auth) | 🟢 PASS | Auth guard confirmed (redirects to `/` when logged out) |

## 7. API/network results

* Every API request observed went to `https://strikenova-api-staging.onrender.com` —
  **zero** requests to Railway, production APIs, or localhost backends.
* Sample of successful DB-backed calls through the UI: `/auth/me`, `/auth/status`,
  `/paper/templates`, `/paper/positions`, `/paper/journal`, `/paper/capital`,
  `/paper/market-status`, `/paper/portfolio`, `/paper/analytics`,
  `/gex/history`, `/gex/regime`, `/gex/flip`, `/gex/walls`, `/gex/data-quality` — all 200.
* Expected non-200s: `GET /chains/NIFTY/expiries` → **403** (broker connection required —
  correct server-side gate), broker fields inside `/paper/capital` degrade to
  `BROKER_TOKEN_EXPIRED`/unavailable (by design; never fabricates broker data).
* No 5xx on any application endpoint except the known `/auth/google/state` defect (§11).

## 8. DB-backed flow

`POST /paper/portfolio/reset` exercised from the UI (Settings → Reset Paper Portfolio):
preflight 200 → POST 200 → UI refreshed → **persistence confirmed after reload**
(starting capital/available cash still ₹5,00,000 from CRDB via the API). Full chain
browser → Vercel → Render → CockroachDB → response → UI update verified.

## 9. CORS

* From the real staging origin (Vercel): all UI API calls succeeded — preflights 200,
  responses carry `access-control-allow-origin: <staging>` with credentials (verified via
  curl earlier the same day and implicitly by every successful UI XHR).
* No wildcard: `access-control-allow-origin` always echoes the exact allowed origin.
* Unrelated origins remain rejected (400) — verified server-side this session.
* Production frontend origin (`options-dashboard-sigma-coral.vercel.app`) remains rejected
  against staging. `FRONTEND_URL` untouched (first-entry OAuth semantics preserved).
* Console CORS error seen during Google-button test came from the local proxy origin
  (not in `ADDITIONAL_CORS_ORIGINS`) — artifact of the browser harness, not a staging defect.

## 10. WebSocket

**Connected.** Real browser handshake from page JS:

* URL: `wss://strikenova-api-staging.onrender.com/chains/ws/NIFTY?expiry_date=2026-10-29`
* Handshake: **101 → OPEN** (`readyState 1`), subprotocol session-id path exercised.
* No `onerror`, no close, no console errors during the hold.
* No data frames received while held (~seconds): consistent with no broker/market feed in
  staging — connection layer verified, streaming data layer is
  `WEBSOCKET NOT FULLY EXERCISABLE IN CURRENT STAGING DATA STATE` (no synthetic feed
  mechanism exists; none was invented).

## 11. Google OAuth

🔴 **Defect found (backend configuration, not frontend):**

* Repro: login modal → "Continue with Google" → in-page banner
  "Failed to initialize Google Sign-In. Please try again."
* Browser console: the `POST /auth/google/state` XHR fails (CORS-shaped message because
  the endpoint 500s without CORS headers).
* Server-side confirmation: `POST /auth/google/state` returns **HTTP 500 from every
  origin** (staging origin included). Root cause: the handler signs OAuth state via
  `token_store.create_google_oauth_state()` → `_get_state_hmac_key()`, which raises
  `ValueError: TOKEN_ENCRYPTION_KEY must be set…` when the env var is missing — the Render
  service does not define `TOKEN_ENCRYPTION_KEY` (only `DATABASE_URL` and
  `ADDITIONAL_CORS_ORIGINS` are set).
* Severity: 🟡/🔴 boundary — blocks Google OAuth on staging; email/password auth unaffected.
* Remediation (separate task, not done in this acceptance run): set a generated
  `TOKEN_ENCRYPTION_KEY` on the Render staging service (manual redeploy) and separately
  register the staging origin in the Google OAuth client. Until then:
  `GOOGLE OAUTH STAGING — PENDING EXTERNAL PROVIDER CONFIGURATION`.

## 12. Session/security

* Authenticated request works; logout invalidates; unauthorized requests rejected (401).
* No session token in page HTML (regex scan), none in cookies, none logged to console.
* No Railway/production URL anywhere in the DOM.
* `NEXT_PUBLIC_*` discipline respected: only the public API URL and Google client ID are
  client-visible; no secrets appear in served bundles (chunk inspected in the deploy phase).

## 13. Cold-start behavior

Render free tier sleeps after ~15 min idle. During this session the backend was already
warm; earlier the same day, first-request-after-idle latency of tens of seconds was
observed and documented in the Render deployment report. Accepted; not worked around.

## 14. Screenshots/evidence references

Captured in-session (preview browser, this transcript): landing page (full render),
registration modal, authenticated dashboard with "No Broker Connected" state, paper
portfolio (₹5,00,000 panels), Google failure banner. No screenshots contain credentials
(synthetic password visible only transiently in a form field during registration; not
included in any stored evidence).

## 15. Defects

| # | Area | Finding | Severity | Remediation owner |
|---|---|---|---|---|
| 1 | Google OAuth | `POST /auth/google/state` → 500 on staging; `TOKEN_ENCRYPTION_KEY` unset on Render service | ✅ **RESOLVED** (see §18) | Backend config (done 2026-09-13) |
| 2 | Landing page | Console warning `<svg> attribute height: "auto"` (cosmetic, static marketing SVG) | 🟢 trivial | Frontend (optional) |
| 3 | Harness note | Preview browser cannot attach to non-loopback origins; local proxy used (documented in §4) | 🟡 tooling note | n/a |
| 4 | Google OAuth (frontend) | `loginWithGoogle` dropped the mandatory HMAC-signed OAuth `state` from the Google callback → every Google login would fail with "Google OAuth state is required" once configuration was correct | ✅ **RESOLVED** (commit `4a3d31e`, see §19) | Frontend fix (done 2026-09-13) |

## 18. Google OAuth staging remediation (chronological, 2026-09-13)

1. **Original finding (this report, §11/§15):** `POST /auth/google/state` returned HTTP 500
   from every origin; browser showed "Failed to initialize Google Sign-In".
2. **Root cause:** Render staging service had no `TOKEN_ENCRYPTION_KEY`; the OAuth-state
   signer (`_get_state_hmac_key()`) raises `ValueError` when it is unset, and the unhandled
   error surfaced as a 500 (which also suppressed CORS headers).
3. **Pre-change safety check:** staging database scanned for encrypted material before
   introducing a key — `broker_tokens.broker_token_encrypted` non-null: **0**;
   `broker_connections` rows: **0**; all encrypted/secret columns across the schema NULL.
   Setting a fresh key was therefore lossless (no pre-existing ciphertext depends on an old key).
4. **Key generation:** cryptographically random (`secrets.token_urlsafe(32)`-equivalent,
   43-char URL-safe), generated **in-process** and piped directly into the Render API write —
   never printed, logged, or stored in any file. Key exists only in Render's secret store.
5. **Render configuration:** `TOKEN_ENCRYPTION_KEY` added via the Render API env-vars PUT
   (bare-array body); `DATABASE_URL` and `ADDITIONAL_CORS_ORIGINS` preserved and re-verified
   (names only; CORS value still exactly the staging origin).
6. **Manual deployment:** Render auto-deploy is OFF, so a manual deploy was triggered
   (API): `dep-daj7qtgae00c738tspo0`, commit `e97d692` (docs-only HEAD; app code identical
   to the validated baseline), status **live**.
7. **Endpoint result:** `POST /auth/google/state` → **HTTP 200** with CORS headers, returning
   the expected `{"state": …, "nonce": …}` shape (lengths 129 / 43; values not recorded).
8. **Log verification:** the `ValueError: TOKEN_ENCRYPTION_KEY must be set…` line appears only
   in **historical** (pre-fix) log entries; post-deploy log window is clean (startup complete,
   health 200s, no 500s, no tracebacks).
9. **Browser result:** clicking "Continue with Google" on the staging frontend now succeeds in
   initializing — the frontend receives state+nonce (200) and proceeds toward Google
   authorization. The previous failure banner no longer appears. Full flow stops at the
   Google consent boundary (§11/§16 — external configuration).
10. **External configuration status:** `GOOGLE OAUTH STAGING — EXTERNAL GOOGLE CLOUD
   CONFIGURATION REQUIRED`. The coding environment has no authorized Google Cloud access
   (no `gcloud` CLI or credentials), and the OAuth client is shared with production, so
   this session did NOT modify it. **User must add
   `https://strikenova-frontend-staging.vercel.app` to the Google OAuth Authorized
   JavaScript origins.**
11. **Regression check after the fix:** register → login → `/auth/me` → `/paper/capital`
    (DB-backed, CRDB) → logout all pass; `/health` and `/readiness` 200;
    email/password authentication unaffected.

No application-code defects requiring immediate source changes were found.

## 16. Pending external configuration

* `TOKEN_ENCRYPTION_KEY` on Render staging (defect #1).
* Staging origin in Google Cloud Console OAuth "Authorized JavaScript origins".
* Broker/market-feed infrastructure for full WS/chain data exercises (expected staging
  condition — no synthetic feed mechanism exists in the app).

## 17. Production-safety confirmation

```text
Vercel production changed:   NO (options-dashboard untouched: no deploys, no env/domain changes by this session)
Railway changed:             NO
Production DB changed:       NO
Production DNS changed:      NO
Render production changed:   NO (staging service only; auto-deploy remains OFF)
Real broker used:            NO (all broker paths show DISCONNECTED/expired — synthetic only)
Real order submitted:        NO (MARKET CLOSED + no broker; paper reset only)
Real money used:             NO
Automatic deployments:       NOT ENABLED (Render OFF; Vercel staging has no Git integration)
Secrets committed:           NO
```

## 19. Google OAuth final remediation — separate staging client (2026-09-13)

Chronological follow-up to §18. This phase completed the staging Google OAuth chain:

1. **Frontend defect found and fixed (code inspection during flow verification):**
   `lib/useAuth.js` dropped the mandatory state parameter when handling Google's URL-fragment
   callback — `loginWithGoogle(googleResult.idToken)` did not forward the signed `state`, so
   every Google login would have failed backend validation with "Google OAuth state is
   required" even with perfect configuration. Fixed in commit `4a3d31e`
   (`fix(auth): pass mandatory OAuth state on Google callback login`, one file, +3/−2;
   `lib/useAuth.test.js` 7/7 pass; pushed to the branch). This defect also exists in the
   production frontend tree — noted for the owner; production was NOT touched.
2. **Architecture decision (user):** a **separate** Google Cloud project + Web OAuth client
   was created for staging. The production OAuth client was NOT modified — no staging origins
   were added to it, and no production origins were removed.
3. **Required configuration derived from code (not invented):** the backend verifies the ID
   token's `aud` against its own `GOOGLE_CLIENT_ID` (`_verify_google_token` →
   `jwt_decode(..., audience=client_id)`), so frontend and backend must share the **same**
   staging Client ID. The frontend's `AuthModal.js` builds
   `https://accounts.google.com/o/oauth2/v2/auth` with `response_type=id_token`, `nonce`,
   `state`, `prompt=select_account`, and **`redirect_uri` set explicitly** to the runtime
   origin — therefore an Authorized Redirect URI is required, not optional.
4. **Google Cloud configuration (user-created staging client):** Authorized JavaScript origin
   and Authorized Redirect URI both `https://strikenova-frontend-staging.vercel.app` — the
   same origin twice, no wildcard.
5. **Vercel staging:** `NEXT_PUBLIC_GOOGLE_CLIENT_ID` set to the new staging Client ID
   (replacing the previously baked production ID). Client IDs are public identifiers; no
   OAuth client secret exists or is used anywhere in this flow.
6. **Render staging:** `GOOGLE_CLIENT_ID` added via the Render API env-vars PUT (bare-array).
   Env set is now exactly `[ADDITIONAL_CORS_ORIGINS, DATABASE_URL, GOOGLE_CLIENT_ID,
   TOKEN_ENCRYPTION_KEY]`; the three pre-existing variables verified byte-for-byte preserved.
   **Same-Client-ID proof:** the Render value equals the staging ID baked into the served
   frontend bundle.
7. **Manual deployments (auto-deploy OFF everywhere; Vercel staging has no Git integration):**
   Render deploy `dep-dajb7ruk1f9s73cv940g` → **live** at commit `4a3d31e` (includes the
   state fix); Vercel staging redeployed from the same commit — served bundle verified to
   contain the staging Client ID and staging API URL with **zero** Railway references.
8. **Deployment incident (transparency):** the first Vercel deploy was run from a temporary
   worktree and auto-linked to the legacy `frontend` project instead of the staging project.
   Its production alias was rolled back to the prior (2-day-old) deployment within minutes,
   and verified not to serve staging content (0 staging-Client-ID occurrences). The corrected
   staging deploy then aliased to `strikenova-frontend-staging.vercel.app`. No production
   `options-dashboard` project was involved at any point.
9. **Backend result:** `/health` 200, `/readiness` 200 (database ok);
   `POST /auth/google/state` → **HTTP 200** with CORS headers and the expected
   `{state, nonce}` shape (lengths 129/43; values never recorded).
10. **Browser initialization result:** loading the staging frontend and clicking
    "Continue with Google" issues `POST /auth/google/state` → **200** from the real frontend
    code path — no CORS failure, no 500, no `TOKEN_ENCRYPTION_KEY` error, no missing-state
    error. The subsequent redirect to Google's authorization UI was aborted only by the local
    loopback-preview harness boundary (§4/§15 #3), which cannot leave localhost origins.
11. **Google-side acceptance (server-rendered preflight):** the exact auth URL constructed by
    the served bundle was requested server-side with the staging Client ID, redirect URI,
    `response_type=id_token`, nonce and state — Google returned the real
    **"Sign in – Google Accounts"** page (HTTP 200) with **no** `invalid_client`, **no**
    `redirect_uri_mismatch`, and no other OAuth error. The staging client and origin are
    accepted by Google.
12. **Session/logout validation (platform-level):** full email/password round-trip against
    the same backend and session machinery — register → login → `/auth/me` 200 →
    `/auth/status` `logged_in:true` → `/paper/capital` 200 (CRDB-backed) → logout 200 →
    post-logout `/auth/me` **401**. Google login creates sessions through this identical
    mechanism.
13. **Full Google login:** `PENDING` — requires an interactive human Google consent with an
    authorized test account in a normal browser, which this environment cannot perform.
    All automatable prerequisites are verified green; **no remaining external configuration
    is known to be required**.

## 20. Production-safety confirmation (this phase)

```text
Production Google OAuth client changed:  NO (separate staging client created instead)
Vercel production changed:               NO (options-dashboard untouched)
Railway changed:                         NO
Production DB changed:                   NO
Production DNS changed:                  NO
Client secret in frontend:               NO (flow uses no client secret)
Client secret committed:                 NO
TOKEN_ENCRYPTION_KEY exposed:            NO (unchanged in Render secret store)
OAuth token logged:                      NO
```

## 21. Final verification — full Google login completed (2026-09-13)

The account owner completed the interactive Google consent in a normal browser. The deployed
backend's request logs (Render staging, service `strikenova-api-staging`) provide direct,
server-side evidence of the complete flow from the authenticated staging browser session:

```text
15:08:18Z  POST /auth/logout                200   (prior email session cleanly ended first)
15:08:21Z  POST /auth/google/state          200   (backend issued HMAC state + nonce)
           --- 11 s: Google consent (accounts.google.com) ---
15:08:32Z  POST /auth/google                200   (ID token validated against staging client;
                                                    state+nonce verified; session created)
15:08:32Z  GET  /auth/me                    200   (immediately after Google login)
15:08:33Z  GET  /auth/status                200
15:08:41Z  GET  /paper/capital              200   (DB-backed, CRDB, under Google session)
15:08:41Z  GET  /paper/market-status        200
15:09:06Z  GET  /paper/positions|portfolio  200
15:09:12Z  GET  /gex/history|regime|flip…   200
15:09:16Z  POST /auth/logout                200   (user ended the Google-created session)
```

* **Return origin confirmed:** `POST /auth/google` validates the signed `state`, which only
  succeeds if Google redirected back to the staging frontend origin (the registered
  redirect URI) and `lib/session.js` parsed the URL fragment there.
* **Zero OAuth errors in the logs:** no `invalid_client`, no `redirect_uri_mismatch`, no
  state errors, no CORS failures (cross-origin `OPTIONS` preflights all 200), and no
  `TOKEN_ENCRYPTION_KEY` error.
* **Post-logout invalidation:** server-side round-trip on the same session machinery —
  login → `/auth/me` 200 → `/paper/capital` 200 (CRDB) → logout 200 → post-logout
  `/auth/me` **401**.
* **Client-ID parity re-verified after login:** the served Vercel staging bundle and the
  Render `GOOGLE_CLIENT_ID` both equal the staging Client ID; Render env is exactly
  `[ADDITIONAL_CORS_ORIGINS, DATABASE_URL, GOOGLE_CLIENT_ID, TOKEN_ENCRYPTION_KEY]`.
* **Freshness at verification time:** `/health` 200, `/readiness` 200,
  `POST /auth/google/state` 200.
* **Production safety:** Vercel production has no new production deployments (recent
  options-dashboard entries are the owner's own pre-existing Preview stream); Railway,
  production DB, and the production Google OAuth client were not touched.

**Verdict: `GOOGLE OAUTH STAGING FULLY VERIFIED`** — end-to-end:
`Vercel staging → Google authorization → staging-frontend fragment callback →
Render staging /auth/google → state/nonce validation → authenticated session →
DB-backed usage → logout → 401`.

## 22. Automated smoke validation (2026-09-13)

The manual acceptance flows in this report are now also covered by a
repeatable automated suite: `backend/tests/staging_smoke/` (opt-in via
`STAGING_SMOKE=1`), documented in `STAGING_SMOKE_TEST.md`.

It re-verifies health, readiness, the full email/password lifecycle
(register → login → identity → status → DB-backed `/paper/capital` → logout
→ post-logout 401), the Google-state handshake, CORS behavior, and the
WebSocket connection layer against the live staging stack. First live run:
**14 passed, 3 skipped (direct-CRDB tests require a full DSN), 0 failed**.
The WebSocket check asserts the same connection-layer OPEN verified manually
in §10/§21 and records (as a finding, not auto-fixed) that the server sends
no close frame within the observation window.
