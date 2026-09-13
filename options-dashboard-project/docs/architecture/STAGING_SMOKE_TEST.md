# StrikeNova — Automated Staging Smoke Validation

Date: 2026-09-13
Scope: repeatable smoke validation of the live staging stack

```text
Vercel staging  →  https://strikenova-frontend-staging.vercel.app
Render staging  →  https://strikenova-api-staging.onrender.com
CockroachDB     →  strikenova-staging / strikenova_staging
```

Companion documents:

* `STAGING_BROWSER_ACCEPTANCE.md` — full manual browser acceptance
* `RENDER_STAGING_DEPLOYMENT.md` — backend deployment + configuration history

---

## 1. Objective

Provide **one repeatable command** that verifies the core staging path —

```text
staging authentication → session lifecycle → CRDB-backed API → logout invalidation
```

— plus health, Google-OAuth state, CORS, and the WebSocket connection layer,
without repeating the full backend test suite and without touching production.

The suite lives at `backend/tests/staging_smoke/` and uses the repository's
existing pytest infrastructure (no new framework, no new dependencies).

---

## 2. Test command

From `options-dashboard-project/backend`:

```bash
STAGING_SMOKE=1 python -m pytest tests/staging_smoke -v
```

The suite is **opt-in**: without `STAGING_SMOKE=1` every test in the
directory is skipped automatically, so a plain `pytest` run of the backend
suite never contacts the live staging service.

---

## 3. Required configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `STAGING_SMOKE=1` | yes | opt-in gate for the live suite |
| `STAGING_API_URL` | no | override backend target (default: the Render staging URL) |
| `STAGING_FRONTEND_URL` | no | override frontend origin used in CORS/WS checks (default: the Vercel staging URL) |
| `STAGING_CRDB_DSN` | no | full `postgres://…` DSN enabling the direct-CRDB tests |
| `STAGING_CRDB_DSN_FILE` | no | override the DSN file path (default `~/.strikenova_staging_crdb.txt`) |

### Credential handling (safe by construction)

* **No credentials are stored in the repository.** Test identities are
  generated at runtime with `secrets` (`smoke-<hex>@smoke.example.com` +
  a random 20-character password) and live only in test memory.
* **Session IDs are masked** in any output (`smoke-…` prefix + length only).
* **The CRDB DSN is never printed.** It is read from the environment or a
  local user-only file and used only to open a connection. The legacy local
  file stores `<dbname>:<password>` (not a DSN); the suite deliberately
  refuses to guess host/user from it and **skips** the direct-CRDB tests
  unless a full `postgres://` DSN is supplied.
* No OAuth token, client secret, or `TOKEN_ENCRYPTION_KEY` is read,
  printed, or committed by this suite.

---

## 4. Test cases

| # | Test | What it proves |
| --- | --- | --- |
| 1 | `GET /health` → 200 `{"status":"ok"}` | service is up |
| 2 | `GET /readiness` → 200, `checks.database == "ok"` | DB connectivity from the service |
| 3 | `POST /auth/register` → 200 `ok:true` | synthetic registration |
| 4 | `POST /auth/login-email` → 200 `session_id` | session issuance (masked in output) |
| 5 | `GET /auth/me` → 200, identity matches the synthetic account | session → identity resolution |
| 6 | `GET /auth/status` → `logged_in:true` | frontend session probe contract |
| 7 | `GET /paper/capital` → 200 (authenticated) | auth → Render → **CockroachDB** |
| 8 | `POST /auth/logout` → 200 | session teardown |
| 9 | `GET /auth/me` with the old session → **401** | logout invalidation |
| 10 | `POST /auth/google/state` → 200 with `state` + `nonce` (values never printed) | Google-OAuth backend handshake |
| 11 | direct CRDB: `ON CONFLICT … RETURNING`, transaction rollback, probe cleanup | CRDB SQL features the app relies on |
| 12 | CORS: staging-origin preflight allowed with credentials; unrelated origin rejected; no wildcard | CORS contract |
| 13 | raw RFC 6455 handshake to `/chains/ws/NIFTY?expiry_date=…` | WebSocket connection layer |
| — | `test_00_targets_are_staging` | guard: all targets are staging URLs |
| B | `test_staging_broker_smoke.py` (opt-in `STAGING_BROKER_SMOKE=1`) | broker-path gates, analytics-token lifecycle, two-user isolation — see `UPSTOX_SANDBOX_STAGING_VALIDATION.md` §13 |

---

## 5. Results (2026-09-13, live run against deployed staging)

```text
STAGING_SMOKE=1 python -m pytest tests/staging_smoke -v

health             PASS
readiness          PASS
register           PASS
login              PASS
me                 PASS
status             PASS
paper/capital      PASS
logout             PASS
post-logout 401    PASS
google/state       PASS
CORS               PASS
WebSocket          PASS (connection layer; see §6)
CRDB direct smoke  SKIPPED (no full postgres:// DSN available — see §6)
```

```text
14 passed, 3 skipped, 0 failed in 51.64s
```

The DB-backed path (`authentication → Render → CockroachDB`) is proven live
by test 7 even with the direct-CRDB tests skipped.

---

## 6. Limitations and findings

1. **Direct-CRDB tests skip by design without a full DSN.** The legacy
   local credential file (`~/.strikenova_staging_crdb.txt`) stores
   `<dbname>:<password>` only — host/user are not derivable, and the suite
   will not guess. Supply `STAGING_CRDB_DSN` (full `postgres://` URL) to
   enable `test_crdb_on_conflict_returning`, `test_crdb_rollback`, and
   `test_crdb_probe_cleanup`. These features are separately evidenced by the
   committed backend suite (`test_cockroachdb_compat.py` etc., SQLite/CI
   matrix) and the live `/paper/capital` path.
2. **WebSocket is validated at the connection layer only.** Both handshake
   variants (anonymous and `options-dashboard-session` subprotocol) complete
   the RFC 6455 upgrade with a valid `Sec-WebSocket-Accept` proof
   (`101 Switching Protocols`) — identical to the manually verified browser
   behavior. **Finding (recorded, not auto-fixed):** the server sends no
   close frame within the observation window, although
   `app/routers/chains.py` appears to close platform/anonymous sessions with
   4401 before streaming. The earlier browser acceptance saw the same
   "OPEN, silent" behavior. Data frames are not expected on staging without
   a broker feed, so the suite asserts only the verified connection-layer
   behavior and records the close-frame observation.
3. **Render free-tier cold start** can add latency to the first request;
   timeouts are set generously (45 s HTTP / 30 s connect) to absorb it.

---

## 7. Security rules (enforced by the suite)

* Synthetic, runtime-generated identities only; nothing persisted.
* Session IDs masked in output; DSN, tokens, and keys never printed.
* No production host is contacted (`test_00_targets_are_staging` asserts the
  targets); no real broker account is used; no real order is placed.
* The suite never mutates Render/Vercel configuration — it is read/execute
  only against the deployed staging service plus its own throwaway
  `smoke_probe_*` tables (when the direct-CRDB path is enabled), which it
  drops afterward.

---

## 8. Production safety

```text
Vercel production touched:        NO
Railway touched:                  NO
Production DB touched:            NO
Production Google OAuth touched:  NO
Production DNS changed:           NO
Real broker used:                 NO
Real order submitted:             NO
Secrets committed:                NO
```
