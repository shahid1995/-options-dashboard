# StrikeNova — Upstox Identity Linking Design

Date: 2026-09-13
Status: **DESIGN — NOT IMPLEMENTED** (implementation requires explicit authorization)
Scope: broker OAuth callback identity resolution, broker-identity ownership, transaction/concurrency design
Companion evidence: `UPSTOX_STAGING_OAUTH_VALIDATION.md` §19 (live staging failure record)

---

## 1. Problem

The staging Upstox OAuth flow currently completes:

```text
Upstox consent
  → GET /auth/callback (state validated)
  → server-side authorization-code exchange
  → Upstox profile fetch (broker user 3CCJPA)
```

and then fails provisioning the StrikeNova user:

```text
sqlalchemy.exc.IntegrityError
UniqueViolation on users.email (ix_users_email)
```

Root cause (code-verified): `get_or_create_user_from_upstox()
(backend/app/identity.py)` looks up users **only** by
`(broker_provider, broker_user_id)`; on first sight of a broker identity it
INSERTs a brand-new `User` carrying the Upstox profile email. When that email
already belongs to an existing platform account (registered via email/password
or Google), the insert collides with `users.email`'s unique index.

The collision is only the visible symptom. The deeper defect is that **the
callback creates a second platform user at all**: the OAuth state already
binds the authenticated StrikeNova session that initiated the connection, but
provisioning ignores it. Even without an email collision, today's behavior
would silently fork one human into two StrikeNova users (an `identity_source=
"email"` account and an `identity_source="upstox"` account) with their data
split across both.

## 2. Existing identity architecture

StrikeNova separates two identity planes:

* **Platform identity** — the `users` row (id, email, password_hash,
  google_sub, status). One per human. Email is unique-nullable; Google
  identity via `google_sub`; legacy broker-login columns
  `(broker_provider, broker_user_id)` carry a unique constraint
  `uq_users_broker_identity`.
* **Broker connection identity** — `broker_connections` rows owned by a
  `users.id` (FK, indexed). One row per `(user_id, broker,
  broker_account_id)` (`uq_broker_connection`). Credentials are encrypted
  per row (BYOB). Status lifecycle `pending → connected → expired |
  disconnected`, plus independent `data_status` / `trading_status`
  capability columns. `broker_account_id` is `NOT NULL` with the sentinel
  `"pending"` for pre-OAuth rows.
* **Broker tokens** — `broker_tokens`, one row per
  `(connection_id, session_hash)` (`uq_broker_token_per_session`),
  encrypted at rest, `ON DELETE CASCADE` from the connection.
* **Sessions** — `user_sessions` (hashed session id unique,
  `broker_connection_id` nullable FK) plus the in-memory token store
  (`app/services/token_store.py`) which holds the *platform* session for
  email/Google logins and a *broker-token-bound* session created by the
  OAuth callback.

Sign-in methods today:

* email/password (`/auth/register`, `/auth/login-email`)
* Google (`get_or_create_user_from_google` — links by verified Google
  identity first, then by **email**)
* Upstox OAuth callback (`get_or_create_user_from_upstox` — no linking at
  all; always creates on first sight of the broker identity)

The module docstring itself states the intent: identity.py "owns only
identity metadata and session ownership; broker tokens remain in the
existing token store", and it exists to migrate "from broker-coupled
identity to a durable StrikeNova account". The Upstox provisioner is the
last broker-coupled remnant.

## 3. Current failure

Live staging, 2026-09-13T17:39:07Z (deployed app logs):

1. Callback accepted; state validated; code exchanged server-side; profile
   fetched (broker user `3CCJPA`, email matching the tester's platform
   account email).
2. `get_or_create_user_from_upstox` found no
   `(UPSTOX, 3CCJPA)` user → INSERT new user with the profile email.
3. `users.email` unique violation → exception → callback catch-all:
   `db.rollback()`, `token_store.clear_token(session_id)` (the freshly
   exchanged Upstox token discarded), redirect to
   `?login_error=account_setup_failed`.
4. Net state: correct rollback behavior (no partial rows), but the entire
   connection attempt is unusable for any user whose platform email
   matches their Upstox profile email — which is the common case.

## 4. Current callback flow (exact call graph)

### 4.1 Initiation — `GET /auth/login` (auth.py)

```text
login(broker, session_id)                                   auth.py:59
├─ token_store.get_token(session_id) is None → 401          (Day 3: no anonymous OAuth)
├─ get_active_session(db, session_id) is None → 401         (DB session record must exist)
├─ resolve_user_credentials(session.user_id, broker, db)    identity.py — BYOB creds
│    missing → 400 "No {broker} credentials found…"
├─ token_store.create_oauth_state(session_id, broker)       token_store.py:269
├─ gateway.create(broker, **user_credentials)               brokers/registry.py
└─ 307 RedirectResponse(adapter.get_authorization_url(state))
```

### 4.2 OAuth state contents — `token_store.py`

* `create_oauth_state(session_id, broker)` builds
  `payload = {"sid": session_id, "brk": broker, "ts": int(now)}`,
  base64url-encodes it, signs with HMAC-SHA256 (32 hex chars) using
  `_get_state_hmac_key()`, and records it in the in-memory
  `_pending_states` map. TTL `_STATE_TTL_SECONDS = 600` (10 minutes),
  garbage-collected on each call.
* `consume_oauth_state(state)` rejects unsigned states (no dot), rejects
  HMAC mismatch, rejects `ts` older than the TTL, pops the entry
  (**single-use**), and returns `{"session_id", "broker"}`.
* Consequence: state is bound to the initiating platform session, is
  single-use, expires in 10 minutes, and dies with any process restart
  (in-memory) — all deliberate.

### 4.3 Completion — `GET /auth/callback` (auth.py:117)

```text
callback(code, error, state, broker)                        auth.py:117
├─ error → redirect FRONTEND ?login_error=<error>
├─ token_store.consume_oauth_state(state) → None → 400 "Invalid or expired OAuth state"
├─ bound_session_id = state_data["session_id"]; broker from state (never query param)
├─ get_active_session(db, bound_session_id) → None → 400 "Session expired or invalid"
├─ user_id_for_connection = session.user_id          ← initiating user IS resolved here
├─ resolve_user_credentials(user_id_for_connection, broker_id, db)
│    missing → 400 "No {broker} credentials found for this user."
│   (pre_db closed — external I/O happens with no open local transaction)
├─ adapter.exchange_authorization_code(code)         [EXTERNAL — Upstox]
├─ adapter(get_profile)                              [EXTERNAL — Upstox]
├─ db = SessionLocal()                               ← transaction scope starts
├─ get_or_create_user_from_upstox(db, profile)       identity.py:197  ← DEFECT
│    lookup by (broker_provider, broker_user_id) ONLY
│    else INSERT User(email=profile.email, identity_source="upstox", …)
│    → UniqueViolation ix_users_email when profile email already owned
├─ adapter.extract_account_id(profile)               (AD-6)
├─ get_or_create_connection(db, user.id, broker, broker_account_id)
│                                                    identity.py:504
│    pending row (user,broker) → upgrade to real account id
│    else existing (user,broker,account) row → refresh timestamps/status
│    else INSERT new connection
├─ token_store.set_token(access_token, connection_id=…, expires_at=+24h)
│    token_store.py:71 — NEW session_id; memory cache; then
│    _persist_token_to_db() on its OWN session (failure → "non-critical" warning)
├─ create_session_record(db, user.id, session_id, broker_connection_id=…)
├─ db.commit()
│  except HTTPException/Exception:
│    db.rollback(); token_store.clear_token(session_id)
│    → redirect FRONTEND ?login_error=account_setup_failed
└─ 302 FRONTEND/dashboard#session_id=<new session>; Set-Cookie session_id
      (httponly, secure, samesite=none, max_age 24h)
```

Answering the ten required questions directly:

1. State created in `/auth/login` via `create_oauth_state(session_id, broker)`.
2. State carries `{sid, brk, ts}` HMAC-signed; nothing else (no user id —
   the session id is the pointer).
3. `session_id` is embedded in the signed payload at initiation.
4. Callback validates signature, TTL, single-use pop, then re-validates the
   session record is still active in DB.
5. The initiating user **is** resolved (`user_id_for_connection`) — but is
   used only for credential lookup, not for provisioning.
6. `adapter.exchange_authorization_code(code)` — outside any local DB
   transaction (correct).
7. `get_profile()` on a token-initialized adapter — also outside.
8. Provisioning: `get_or_create_user_from_upstox` — broker-keyed
   lookup-or-create; the defect.
9. `get_or_create_connection` — per-user unique constraint only.
10. `token_store.set_token` → `broker_tokens` row via
    `_persist_token_to_db` on a **separate** DB session (fire-and-forget).
11. Commit/rollback in the callback's explicit `try/except` around a single
    `SessionLocal()`; the token-persist write is NOT inside that
    transaction.

## 5. Security analysis

* **Account takeover via email match (Option B) — rejected.** Upstox profile
  email is a claim supplied by the broker profile; StrikeNova performs no
  verification of it. "Broker profile shows victim@example.com" does not
  prove the broker-account holder controls victim@example.com's StrikeNova
  account (stale profiles, unverified addresses, KYC-era emails, or a
  different mailbox than the one StrikeNova knows). Auto-merging on it
  would let an attacker link *their* broker identity into *someone else's*
  platform account, gaining broker-token-backed data access inside it.
  This is the classic email-claim trust error; Google's flow is different
  only because Google ID tokens carry a platform-verified email claim — and
  even there the linking is a deliberate sign-in-method design, not broker
  connection.
* **Session binding — already present and strong.** HMAC-signed state,
  10-minute TTL, single-use, bound to an initiating session that is
  re-validated against `user_sessions` at callback time. The callback can
  therefore trust `bound_session_id → user` as the authenticated principal.
* **Session fixation** — the callback mints a *fresh* session id
  (`secrets.token_urlsafe(32)`) server-side after authentication; the
  initiating session is not reused for broker-token binding; ids are stored
  hashed (`session_hash`, SHA-256) at rest; cookie is `Secure`,
  `HttpOnly`, `SameSite=None` (required for the cross-site OAuth redirect),
  24 h max-age.
* **Replay** — the state entry is popped on first consume (single-use) and
  the authorization code is single-use at Upstox; both replay paths fail
  closed.
* **CSRF on initiation** — `/auth/login` requires an authenticated session;
  the state returned is bound to that session, so a forged initiation
  cannot attach a victim to an attacker's broker flow.
* **Broker identity collision** — today nothing prevents the same
  `(broker, broker_account_id)` from being linked to two users (constraint
  is per-user only; the legacy `uq_users_broker_identity` covers only the
  user-table stamping columns). Invariant 1 currently has **no database
  enforcement** → needs a global unique index (§11, §14).
* **Token ownership** — `broker_tokens` ownership derives entirely from the
  `connection_id`; resolving the user from the validated session and the
  connection from the verified broker profile keeps the chain
  `session → user → connection → token` coherent. The one structural gap:
  the token-persist write runs on its own DB session outside the callback
  transaction (§10).
* **Transaction rollback** — the current catch-all rollback is correct and
  was proven live (staging failure left zero partial rows). The design
  keeps and tightens this (single transaction, token row included).
* **Concurrent linking** — two simultaneous connects of one broker identity
  must be arbitrated by the database, not by check-then-act code (§11).

## 6. Options considered

### Option A — Session-bound broker linking (RECOMMENDED)

The callback resolves the StrikeNova user **exclusively** from the
state-bound session's `user_id`. The broker identity is attached to that
user via `broker_connections` (and, where unset, stamped onto the legacy
`users.broker_*` columns for sign-in mapping). A broker identity already
owned by a different user is rejected. No user is ever created by the
broker callback.

* Advantages: strongest binding (authenticated principal, not a profile
  claim); fits the existing BYOB architecture (`/auth/login` already
  requires an authenticated session, so the required precondition already
  exists); eliminates duplicate platform accounts entirely; no email
  takeover surface; reuses every existing security mechanism.
* Disadvantages: broker OAuth can no longer act as an anonymous sign-up
  method (by design since the Day 3 fix removed anonymous initiation);
  legacy users who exist *only* as an Upstox identity need a preserved
  sign-in path (§16, Open decision 1).

### Option B — Email-based automatic merge (REJECTED)

Link by `Upstox profile email == users.email`.

* Security risk: email match is not authenticated platform identity proof.
  The profile email is an unverified (by us) broker-side claim; merging on
  it creates a direct account-takeover vector (attacker-controlled Upstox
  account whose profile email names the victim's platform account).
* Even with re-verification (e.g., email confirmation loops), it adds an
  out-of-band verification channel, UX friction, and edge-case abuse
  (aliasing, delayed takeover of the mailbox) — for zero benefit over
  Option A, which never needs email as authority.
* Verdict: do **not** implement. Email equality may appear only as an
  informational consistency signal in logs/metadata — never as authority.

### Option C — Reject and require manual linking (FALLBACK UX ONLY)

When the broker identity is owned by another user, reject with a clear
message directing the human to sign in as that owner. This is not a
replacement for Option A — it is exactly Option A's Case 3 behavior
(Invariant 7) plus friendly UX copy. As a *primary* design it is rejected:
it makes the common case (first connect) impossible without a second
flow.

## 7. Recommended design

**Option A — session-bound broker linking**, with the rule:

> Broker OAuth may link a broker identity only to the already-authenticated
> StrikeNova user whose session initiated the connection. The broker
> callback never creates platform users. A broker identity belongs to at
> most one StrikeNova user; contested ownership is rejected, never
> transferred.

Concrete callback re-architecture (all within the current files; no new
services):

```text
OAuth callback
   ↓ consume_oauth_state (signature, TTL, single-use)          [unchanged]
   ↓ get_active_session(bound_session_id) → initiator          [unchanged]
   ↓ resolve_user_credentials(initiator)                       [unchanged]
   ↓ exchange_authorization_code                               [EXTERNAL, unchanged]
   ↓ get_profile                                               [EXTERNAL, unchanged]
   ↓ ── local transaction begins (single SessionLocal) ──
   ↓ RESOLVE user = session.user_id        ← replaces get_or_create_user_from_upstox
   ↓ OWNERSHIP CHECKS
   │    users row where (broker_provider, broker_user_id) = profile identity:
   │      another user's → REJECT (redirect login_error=broker_identity_in_use)
   │      initiator's own or absent → continue
   │    broker_connections row where (broker, broker_account_id):
   │      another user's → REJECT (same signal)
   │      initiator's own → idempotent reconnect path
   ↓ STAMP legacy columns: users.broker_provider/broker_user_id = identity
   │    (only if NULL; if already the same value it is a no-op)
   │    profile email/display_name are INFORMATIONAL — stored in
   │    provider_metadata_json on the connection, never written to users.email
   ↓ UPSERT BrokerConnection (get_or_create_connection, unchanged semantics)
   ↓ INSERT user_sessions row for the NEW broker session (resolved user)
   ↓ INSERT broker_tokens row (same session/transaction — §10)
   ↓ COMMIT
   ↓ set in-memory token cache (idempotent, post-commit)
   ↓ redirect /dashboard#session_id=…
```

Failure anywhere inside the transaction → single `rollback()`, no
`clear_token` needed for rows that never committed, redirect
`?login_error=…`. Failure in the external phase → nothing local was
written at all.

### Why this preserves the legacy Upstox sign-in population

The callback stops creating users, so a person whose *only* platform
identity is an existing `(UPSTOX, broker_user_id)` user keeps signing in by
lookup-only: if the profile identity maps to an existing user, that user is
authenticated (token + fresh session minted exactly as today); if not, the
flow is a *connection* attempt and requires the authenticated session that
`/auth/login` already enforces. "Lookup-only sign-in, never create" is the
complete replacement for the create-path. (Open decision 1 covers whether
lookup-only sign-in ships in the same change.)

## 8. Identity invariants

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | **Broker identity uniqueness** — `(provider, broker_user_id)` / `(broker, broker_account_id)` maps to at most one StrikeNova user | New partial unique index on `broker_connections (broker, broker_account_id) WHERE broker_account_id <> 'pending'` + existing `uq_users_broker_identity` on the legacy stamping columns; app pre-checks give friendly rejection, DB gives the guarantee |
| 2 | **Existing platform user preservation** — connecting a broker never creates a second user when an authenticated session exists | Callback resolves user only from the bound session; the create path is deleted from the broker callback |
| 3 | **Session binding** — callback bound to the initiating session | Already implemented (HMAC state + `get_active_session` re-validation); design keeps it and makes the resolved user the only provisioning source |
| 4 | **No email takeover** — broker profile email never grants platform access | Profile email is informational only (`provider_metadata_json`); no code path writes it to `users.email` or compares it for authorization |
| 5 | **Token ownership** — token belongs to the user+connection established by the validated flow | `broker_tokens.connection_id` → connection upserted for the resolved user in the same transaction |
| 6 | **Atomicity** — no partial connection/token/user/orphan credentials | One transaction wrapping ownership checks + connection upsert + session record + token row; external I/O strictly outside it; rollback discards everything |
| 7 | **Existing broker identity collision** — never silently reassigned | Ownership checks reject with `broker_identity_in_use`; DB unique index is the backstop against races |

## 9. Data-model implications

Inspected models (`backend/app/identity.py`):

* `User` — `email` unique-nullable; `UniqueConstraint(broker_provider,
  broker_user_id)` (`uq_users_broker_identity`, NULL-safe: multiple users
  without broker stamping are legal in SQLite and PostgreSQL).
* `BrokerConnection` — `UniqueConstraint(user_id, broker,
  broker_account_id)` (`uq_broker_connection`); **no global uniqueness on
  `(broker, broker_account_id)`** — two users may each hold a connection
  row for the same broker account today. The `"pending"` sentinel makes a
  plain unique index wrong (every user may hold one pending row per
  broker), hence the partial index in §14.
* `BrokerToken` — `UniqueConstraint(connection_id, session_hash)`;
  `FK … ondelete=CASCADE`; encrypted columns. No changes needed.
* `UserSession` — hashed `session_id` unique; `broker_connection_id` FK.
  No changes needed.
* Capability columns (`data_status`, `data_source`, `trading_status`) and
  `provider_metadata_json` exist and are sufficient to carry profile
  metadata without schema change.

Conclusion: the recommended architecture is supported by the existing
models except for the one missing global ownership constraint (§14).

## 10. Transaction boundary

```text
Phase 0 — no local transaction open
   validate state (consume)            [reject: invalid/expired/replayed]
   validate initiating session         [reject: expired/revoked]
   resolve BYOB credentials            [reject: none]
   EXTERNAL: exchange code             [failure → nothing persisted anywhere]
   EXTERNAL: fetch profile             [failure → nothing persisted anywhere]

Phase 1 — ONE transaction (single SessionLocal)
   ownership pre-checks (SELECTs)
   resolve user from session (SELECT; no INSERT)
   stamp users.broker_* when NULL (UPDATE, rarely)
   upsert BrokerConnection (INSERT/UPDATE)
   INSERT user_sessions (new broker session)
   INSERT broker_tokens (token row on the SAME session — see note)
   COMMIT

Phase 2 — post-commit, idempotent
   populate in-memory token cache
   redirect
```

**Handling "Upstox token obtained, local DB transaction fails":** because
all external I/O happens in Phase 0, a Phase-1 failure means the freshly
obtained Upstox access token has *not* been persisted anywhere — the
process simply drops it. Nothing inconsistent can survive: no connection
row, no token row, no session record, no user changes. The user retries
the connect (a new code + exchange; Upstox authorization is re-obtainable
at will and tokens are daily-rotatable). Optional hardening: if the
adapter exposes a token-revocation call, best-effort revoke the orphaned
token before discarding (open decision 2); never log it.

**Token-row placement note:** today `_persist_token_to_db` writes on its
own DB session *before* the callback commits, so an FK-to-uncommitted-row
failure is swallowed as "non-critical" and the DB copy is silently lost
(memory cache still works until restart). The design moves the token-row
insert into the callback's transaction (thread the `Session` through, or
insert the row inline) so `broker_tokens` persistence is atomic with the
connection it references, while the in-memory cache remains the fast path
and DB remains the restart-recovery copy.

## 11. Concurrency model

Scenario: users A and B both connect Upstox identity X simultaneously.

* Both pass Phase 0 (Upstox will happily issue codes/tokens to both —
  external state is not the arbiter).
* Both enter Phase 1. Ownership checks are point-in-time reads; the race
  must be closed by the database, not by the checks:
  * stamping race on `users.broker_*`: `uq_users_broker_identity` — loser
    gets `IntegrityError` → rollback → friendly rejection.
  * connection race: new partial unique index
    `(broker, broker_account_id) WHERE broker_account_id <> 'pending'` —
    second committer gets `IntegrityError` → rollback → rejection.
* Result: exactly one owner; the loser sees
  `login_error=broker_identity_in_use`; no duplicate ownership; no partial
  state (Invariant 6 holds under concurrency).
* Same-user idempotent reconnect (Case 2) is race-free: both transactions
  target the same existing rows; unique constraints are satisfied; the
  second commit merely refreshes timestamps/status.

Current-constraint verdict: **not sufficient** — the per-user
`uq_broker_connection` cannot express global broker-identity ownership;
the explicit partial unique index (§14) is required, with the app-level
checks retained purely to produce friendly errors before hitting the
constraint.

## 12. Edge cases

| Case | Scenario | Designed behavior |
|------|----------|-------------------|
| 1 | Authenticated user connects a never-seen Upstox identity | Link to the session's user: stamp legacy columns (if NULL), create connection, mint broker session + token. No user creation. |
| 2 | Same user reconnects an identity they already own | Idempotent: existing connection row refreshed (status/connected_at), token row for the new session, existing user untouched. |
| 3 | Authenticated user connects an identity owned by ANOTHER user | Reject before any write (`login_error=broker_identity_in_use`). Never transfer ownership. DB index backstops the race. |
| 4 | Upstox email ≠ StrikeNova email | Allowed — email is never an authority. Profile email stored as metadata on the connection only. |
| 5 | Upstox email matches ANOTHER user's platform email, broker identity new | Link to the currently authenticated user. The email collision is irrelevant (no `users.email` write). The other account is untouched. |
| 6 | OAuth state expired/consumed/tampered/restart | `consume_oauth_state` → 400 "Invalid or expired OAuth state". Nothing persisted; no token persistence. |
| 7 | Token exchange succeeds, local DB write fails | Rollback the single transaction; the Upstox token is dropped (never persisted, never logged); user retries. See §10 for the optional revoke hardening. |
| 8 | Multiple broker connections per user | Platform user stays singular; connections remain separately scoped rows (`uq_broker_connection` per user+broker+account). Partial index does not restrict *distinct* broker accounts per user. |

## 13. Test plan

Framework: repository-standard pytest (SQLite in-memory via
`tests/conftest.py`; the Postgres-only concurrency test follows the
existing `test_day41_phase10_postgres_concurrency.py` harness pattern).
Upstox exchange/profile are monkeypatched at the gateway/adapter seam
(the same approach `test_auth_router.py` uses); **no test contains real
broker credentials, codes, or tokens**.

1. **New broker linked to existing session user** — email/password user,
   BYOB creds stored, full mocked callback → same user id returned, one
   connection row, token row, session record; user count unchanged.
2. **Same broker reconnected by same user** — run callback twice → one
   connection row (id stable), refreshed status/timestamps, two
   independent session/token pairs.
3. **Broker already owned by different user** — pre-link X to user B;
   user A connects X → redirect `login_error=broker_identity_in_use`, no
   rows written by A, B's rows unchanged.
4. **Email mismatch** — profile email different from platform email →
   success; `users.email` unchanged; profile email only in
   `provider_metadata_json`.
5. **Email collision with another platform user** — profile email equals
   user C's email; connector is user A; identity X new → success for A;
   C untouched; no `UniqueViolation`; no new user rows.
6. **Expired state** — backdate `_pending_states` (existing
   `test_day7_session_persistence.py` technique) → 400, no writes.
7. **Invalid state** — unsigned/forged/replayed state → 400, no writes
   (extends `test_day3_security.py`).
8. **DB failure after token exchange** — force `flush()`/commit failure
   inside Phase 1 (e.g., constrain a poisoned value) → rollback verified:
   zero new users/connections/tokens/sessions; Upstox token never
   persisted; error redirect.
9. **Concurrent linking** (Postgres) — two threads/sessions connect the
   same identity; exactly one commits, the loser hits the unique index →
   409-equivalent rejection; final state has exactly one owner row and
   one connection.
10. **No duplicate users** — invariant sweep across cases 1–5 and 9:
    total user count before == after in every scenario.

Regression guards: the existing
`test_identity_foundation.py` / `test_byob_credentials.py` /
`test_platform_session_no_broker.py` suites must remain green unchanged
except where they assert the deleted create-path behavior (update those
assertions deliberately, never silently).

## 14. Migration requirements

**YES — exactly one migration**, following the repo's own convention that
partial indexes are created by Alembic only, never in ORM metadata
(mirroring `125e1807df8d` / the `uq_one_default_per_user_broker`
comment in identity.py):

```text
upgrade:
  CREATE UNIQUE INDEX uq_broker_identity_global
      ON broker_connections (broker, broker_account_id)
      WHERE broker_account_id <> 'pending';
downgrade:
  DROP INDEX uq_broker_identity_global;
```

* Valid on PostgreSQL (staging/production) and SQLite (dev/test).
* The `<> 'pending'` predicate preserves the documented sentinel
  semantics (one pre-OAuth row per user+broker).
* **Pre-migration data audit required** (part of the migration PR, not a
  schema change): a SELECT for
  `(broker, broker_account_id)` groups with more than one distinct
  `user_id` — per the staging evidence none should exist (the defect
  crashed before creating duplicates), but the audit turns that belief
  into evidence before the index enforces it.
* No column additions/changes; no data backfill.

## 15. Rollback strategy

* Application: revert the implementation commit(s). Behavior returns to
  the current flow (which is broken for the email-collision case but
  otherwise known).
* Schema: `alembic downgrade` drops the single index; zero data loss
  (the index is a constraint, not data).
* Ordering: deploy code + migration together (code relies on the index
  for the concurrency guarantee); rollback = downgrade then revert, or
  revert code first and keep the index (harmless to the old code — the
  old code never inserts colliding connected rows without first
  crashing on email anyway).
* Blast radius: staging-first deployment (Render manual deploy),
  full smoke suite (`STAGING_SMOKE=1`, broker suite with
  `STAGING_BROKER_SMOKE=1`), then the live OAuth re-validation recorded
  in §19 of the companion report.

## 16. Open decisions

1. **Legacy lookup-only Upstox sign-in** — should the callback retain
   "authenticate an existing `(UPSTOX, broker_user_id)` user" (no
   creation) so historical Upstox-only accounts keep their sign-in path,
   or is that population empty/retired? (Evidence suggests the staging DB
   has none; production must be audited.)
2. **Orphaned-token revocation** — best-effort revoke the discarded
   Upstox token when Phase 1 fails, or accept silent discard? (Upstox
   tokens are short-lived and re-obtainable; revoke is hygiene, not
   correctness.)
3. **Rejection UX** — whether `broker_identity_in_use` should deep-link
   the frontend to a specific screen (needs a frontend contract) or only
   the query-param signal.
4. **Multi-account per user** — the design supports multiple *distinct*
   Upstox accounts per platform user (Case 8); confirm product intent
   before any future UI exposes it.
5. **Google-flow symmetry** — `get_or_create_user_from_google` links by
   Google-verified email; that is a sign-in-method decision with a
   verified-claim basis and is out of scope here, but a follow-up review
   should record the distinction explicitly.

---

## Approval gate

This document is a design baseline. Implementation is **NOT authorized**
by this document. Implementation requires: (1) owner approval of §7 and
the open decisions above, (2) an explicit implementation authorization,
then (3) the TDD plan in §13 as the acceptance contract.
