# StrikeNova — Architecture

**Status:** Canonical · **Owner:** Founder · **Last reviewed:** 2026-09-18

Ground truth is the code; this document maps it. Deep-dive phase documents
live under `options-dashboard-project/docs/` (historical evidence).

---

## 1. Deployment topology (current truth)

```text
Browser
   ↓  HttpOnly strikenova_session cookie (secure session transport)
Vercel — Next.js frontend (options-dashboard-project/frontend)
   ↓  HTTPS REST (axios, withCredentials) + cookie-authenticated WebSocket
Render — FastAPI backend, uvicorn (options-dashboard-project/backend)
   ↓  SQLAlchemy 2.x + psycopg / sqlalchemy-cockroachdb
CockroachDB Cloud — production database (Alembic-managed schema)
```

- Staging deployments mirror this shape (Vercel + Render free tiers,
  documented in `docs/architecture/VERCEL_STAGING_DEPLOYMENT.md` and
  `RENDER_STAGING_DEPLOYMENT.md`).
- **Railway is historical** (superseded staging experiment) — never present it
  as current production truth ([`DECISIONS.md`](DECISIONS.md) ADR-004).
- Portability: SQLite (local), PostgreSQL (CI service container), CockroachDB
  (production target) — [`DECISIONS.md`](DECISIONS.md) ADR-003.

## 2. Backend (FastAPI)

| Layer | Location | Responsibility |
|---|---|---|
| API | `backend/app/routers/` | auth, paper, gex, chains, candles, resolve, templates, annotations, broker_diagnostics, historical_gex, live_gex |
| Auth dependencies | `backend/app/routers/deps.py` | Single canonical session resolver (`_canonical_session_id`/`get_session_id`); `CurrentUser`/`get_current_user` resolve platform identity from the cookie (broker token optional) |
| Identity | `backend/app/identity.py` | `User`, `UserSession` (hashed, durable), identity linking, `create_session_record` |
| Token/BYOB | `backend/app/services/token_store.py`, `backend/app/brokers/` | Encrypted broker credentials, HMAC-signed OAuth state, adapter-per-broker (`upstox/`) |
| Paper trading | `backend/app/services/paper_execution.py` | Server-authoritative execution, positions, exits, P&L |
| Broker sync | `backend/app/broker_sync/` | Ingestion models/pipeline for broker data |
| Data/config | `backend/app/db.py`, `backend/app/config.py` | Engine/session construction from `DATABASE_URL`; pydantic settings |
| Migrations | `backend/alembic/` | **Sole schema authority** (ADR-002) |
| Tests | `backend/tests/` | pytest suite (185 test files) |

Request authentication path (Issue #61 contract):

```text
Cookie strikenova_session → CurrentUser/get_current_user → AuthenticatedUser(user_id, access_token|None)
```

## 3. Frontend (Next.js)

| Layer | Location | Responsibility |
|---|---|---|
| App router | `frontend/app/` | `(public)` marketing pages, `(app)` dashboard/product pages |
| Session gate | `frontend/components/AuthGate.js` | `/auth/me` is the authority; 401/403 → redirect `/`; 5xx/network → retryable error, **never auto-logout** |
| Auth hook | `frontend/lib/useAuth.js` | Cookie-only auth state; transient failures preserve user; 401/403 clear it |
| API client | `frontend/lib/api.js` | axios with `withCredentials: true`; **no** `X-Session-Id` injection; WS uses cookies (`chainWsProtocols() → undefined`) |
| Session helpers | `frontend/lib/session.js` | Google id_token URL scrubber only — no session transport |
| Quant/calcs | `frontend/lib/calculations/` | Presentation-side analytics mirroring server math |
| Tests | `*.test.js` (vitest) | Unit + behavioral suites |

## 4. Cross-cutting contracts

- **Sessions:** HttpOnly `strikenova_session` cookie; server-side durable
  `UserSession`; legacy `session_id` cookie is not a transport.
  [`SECURITY.md`](SECURITY.md).
- **Brokers:** BYOB OAuth per connection; encrypted at rest; separate from
  platform identity ([`DECISIONS.md`](DECISIONS.md) ADR-005/006).
- **GEX conventions:** owned by `docs/GEX_V1_0_SPEC.md`.
- **Timezones:** standardized per `docs/PHASE_7_24_4_TIMEZONE_STANDARDIZATION.md`.

## 5. Historical architecture record

Phase-by-phase designs and audits (7.x data pipeline, 10.x identity/BYOB,
CockroachDB validations, deployment reports) live in
`options-dashboard-project/docs/` — evidence, not open work
([`DECISIONS.md`](DECISIONS.md) ADR-010).
