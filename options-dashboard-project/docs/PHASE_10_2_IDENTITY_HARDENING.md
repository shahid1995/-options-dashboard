# Phase 10.2 — Identity & Session Hardening

_Created: 2026-08-27_
_Status: DESIGN — Pending Principal Architect approval_
_Based on: Phase 10.2 Architectural Audit (Issue #21)_

## 1. Context

Phase 10.1A/B established Alembic as the sole schema management mechanism and completed the identity foundation (`User`/`UserSession` models, OAuth flow, session hashing). The post-merge audit identified several architectural weaknesses in the identity/session system that must be addressed before the platform can support multi-user deployment, multi-instance scaling, or reliable session management.

This document defines the design for Phase 10.2, which hardens the identity and session infrastructure.

## 2. Problems Identified

### P0 — Security

| # | Problem | Evidence | Severity |
|---|---------|----------|----------|
| 1 | `historical_gex` router (7 endpoints) has zero authentication | `routers/historical_gex.py` — no `session_id`, no `require_session()` | SECURITY |

### P1 — Architectural

| # | Problem | Evidence | Severity |
|---|---------|----------|----------|
| 2 | Token store is entirely in-memory — all sessions lost on restart | `token_store.py:27` — `_sessions: dict = {}` | ARCHITECTURE |
| 3 | `session_id` used as user key for paper trading isolation instead of `user.id` | `paper.py:64` — `return session_id, token` | CORRECTNESS |
| 4 | Dual identity system (in-memory token store + DB user/session) not integrated | `token_store.py` + `identity.py` | ARCHITECTURE |

### P2 — Technical Debt

| # | Problem | Evidence | Severity |
|---|---------|----------|----------|
| 5 | `UserSession` rows accumulate forever — no cleanup | `identity.py` — no TTL sweep | DEBT |
| 6 | `create_session_record()` calls `db.commit()` directly | `identity.py:96` | DEBT |
| 7 | Composite indexes not in Alembic baseline | `db.py:178-185` — raw SQL | DEBT |
| 8 | Suspended users retain active sessions | `auth.py` — only checks on login | DEBT |
| 9 | Duplicate WAL listener in `_engine()` | `db.py:44,60` | BUG |

## 3. Design Decisions

### Decision 1: Token Store Persistence

**Choice**: Persist tokens to the database (`user_sessions` table) rather than Redis or external store.

**Rationale**:
- The project already has a PostgreSQL database in production (Railway)
- `user_sessions` table already exists with `session_hash`, `expires_at`, `revoked_at`
- Adding a `broker_token_encrypted` column is the minimal change
- Redis would introduce a new infrastructure dependency
- In-memory store can remain as a fast cache layer in front of the DB

**Architecture**:
```
Request → token_store.get_token(session_id)
  → Check in-memory cache (fast path)
  → Cache miss → Query user_sessions DB (slow path)
  → Populate cache → Return token
```

**Encryption**: Broker tokens must be encrypted at rest. Use Fernet symmetric encryption with a key derived from `UPSTOX_API_SECRET` (already in environment). The token store becomes a thin encryption/decryption layer.

**Migration**: New Alembic migration adds `broker_token_encrypted` column to `user_sessions`. Existing in-memory tokens are lost on restart (current behavior) — this is acceptable during the transition.

### Decision 2: User Identity Unification

**Choice**: Resolve `session_id` → `user.id` at request time via a FastAPI dependency.

**Rationale**:
- Every authenticated endpoint needs `user.id` for ownership checks
- Current pattern: each router independently calls `require_session()` and extracts `session_id` as the user key
- New pattern: single `get_current_user()` dependency returns `User` object

**Architecture**:
```python
# New dependency in deps.py
def get_current_user(session_id: str | None = Depends(get_session_id), db: Session = Depends(get_db)) -> User:
    """Resolve session to authenticated User. Raises 401 if invalid."""
    # 1. Validate session exists and is not expired/revoked
    # 2. Look up User by session.user_id
    # 3. Check user.status == "active"
    # 4. Return User object
```

**Migration strategy**: Phase 10.2 introduces the new dependency. Existing routers are updated incrementally (not all at once). The old `require_session()` pattern continues to work during transition.

### Decision 3: Historical GEX Authentication

**Choice**: Add `get_current_user()` dependency to all `historical_gex` endpoints.

**Rationale**:
- Market data is user-scoped in the current architecture (GEX snapshots have `owner_id`)
- Multi-user deployment requires access control
- Consistent with all other routers

**Risk**: If historical GEX is intended to be public (market data), this would break that. The Principal Architect should confirm.

### Decision 4: Session Lifecycle Management

**Choice**: Background task for session cleanup + startup sweep.

**Rationale**:
- `UserSession` rows accumulate without cleanup
- Expired token_store entries are cleaned on access only
- Need proactive cleanup for DB hygiene

**Architecture**:
- Startup sweep: delete `UserSession` rows where `expires_at < now()` and `revoked_at IS NOT NULL`
- Background task: run every 1 hour, delete expired sessions
- Token store: add TTL-based cleanup on access (already exists) + periodic sweep

## 4. Scope

### Phase 10.2A — Security & Correctness (P0/P1)

1. **Add authentication to `historical_gex` router** (P0)
   - Add `get_current_user()` dependency to all 7 endpoints
   - Verify user isolation where applicable

2. **Resolve session_id → user.id at request time** (P1)
   - Create `get_current_user()` dependency in `deps.py`
   - Update `paper.py` to use `user.id` instead of `session_id` as user key
   - Update `gex.py` to use `user.id` instead of `session_id` as owner_id
   - Update `annotations.py` to use `user.id`

3. **Fix `create_session_record()` commit pattern** (P2)
   - Remove direct `db.commit()` — let request-scoped session handle transaction

### Phase 10.2B — Token Persistence (P1)

4. **Persist broker tokens to database** (P1)
   - Add `broker_token_encrypted` column to `user_sessions` (Alembic migration)
   - Implement Fernet encryption/decryption in token_store
   - Update `set_token()` to write to both cache and DB
   - Update `get_token()` to fall back to DB on cache miss
   - Update `clear_token()` to clear both cache and DB

5. **Remove `get_any_token()` deprecated function** (P3)
   - Verify no callers remain
   - Remove function

### Phase 10.2C — Session Lifecycle (P2)

6. **Add session cleanup** (P2)
   - Startup sweep: delete revoked+expired sessions
   - Background task: hourly cleanup of expired sessions
   - Token store: periodic sweep of expired in-memory entries

7. **Revoke sessions on account suspension** (P2)
   - When `user.status` changes to "suspended", revoke all active sessions
   - Clear tokens for suspended user

### Phase 10.2D — Schema Cleanup (P2/P3)

8. **Move composite indexes to Alembic** (P2)
   - Create Alembic migration for the 4 composite indexes currently in `init_db()`
   - Remove raw SQL from `init_db()`

9. **Fix duplicate WAL listener** (P3)
   - Remove the second `_set_wal` registration in `db.py`

## 5. Files Affected

### New Files
- `backend/alembic/versions/<next>_add_session_columns_and_indexes.py` — migration for token persistence + composite indexes

### Modified Files
| File | Change |
|------|--------|
| `backend/app/routers/deps.py` | Add `get_current_user()` dependency |
| `backend/app/routers/historical_gex.py` | Add auth dependency to all endpoints |
| `backend/app/routers/paper.py` | Use `user.id` instead of `session_id` for isolation |
| `backend/app/routers/gex.py` | Use `user.id` instead of `session_id` for owner_id |
| `backend/app/routers/annotations.py` | Use `user.id` for ownership |
| `backend/app/services/token_store.py` | Add DB persistence, encryption, cleanup |
| `backend/app/identity.py` | Fix `create_session_record()` commit, add session cleanup |
| `backend/app/db.py` | Fix duplicate WAL, remove composite index SQL |
| `backend/app/models.py` | Add `broker_token_encrypted` to `UserSession` |

### Test Files
| File | Change |
|------|--------|
| `backend/tests/test_alembic_migrations.py` | Add migration verification tests |
| `backend/tests/test_identity_foundation.py` | Add session lifecycle tests |
| `backend/tests/test_db_migration.py` | Add index migration tests |
| `backend/tests/test_phase9_security.py` | Add auth boundary tests for historical_gex |

## 6. Migration Strategy

### Alembic Migration
```python
# New migration: add session persistence columns + composite indexes
def upgrade():
    # Token persistence
    op.add_column('user_sessions', sa.Column('broker_token_encrypted', sa.Text, nullable=True))
    
    # Composite indexes (moved from init_db raw SQL)
    op.create_index('ix_ingestion_log_operation_status', 'ingestion_log', ['operation', 'status'])
    op.create_index('ix_ingestion_log_completed_at', 'ingestion_log', ['completed_at'])
    op.create_index('ix_data_completeness_status', 'data_completeness', ['status'])
    op.create_index('ix_ingestion_checkpoint_status', 'ingestion_checkpoint', ['pipeline', 'status'])

def downgrade():
    op.drop_index('ix_ingestion_checkpoint_status')
    op.drop_index('ix_data_completeness_status')
    op.drop_index('ix_ingestion_log_completed_at')
    op.drop_index('ix_ingestion_log_operation_status')
    op.drop_column('user_sessions', 'broker_token_encrypted')
```

### Backward Compatibility
- Existing sessions without `broker_token_encrypted` continue to work (token in memory)
- New sessions write encrypted token to DB
- On restart, sessions without DB persistence are lost (current behavior)
- No data loss for existing users — they simply re-login

## 7. Security Considerations

### Token Encryption
- Fernet symmetric encryption with key derived from `UPSTOX_API_SECRET`
- Key derivation: `PBKDF2HMAC` with random salt, stored in environment
- Token never stored in plaintext in database
- Encryption/decryption happens in token_store layer only

### Session Revocation
- On suspension: revoke all `UserSession` rows for the user, clear all token_store entries
- On logout: revoke specific session, clear specific token
- On expiry: background sweep removes expired sessions

### Auth Boundary Consistency
- All routers use `get_current_user()` dependency
- No endpoint bypasses authentication (except `/auth/login`, `/auth/callback`, `/health`, `/readiness`)
- Historical GEX endpoints gain authentication in Phase 10.2A

## 8. Testing Strategy

### Unit Tests
- Token encryption/decryption round-trip
- `get_current_user()` with valid/invalid/expired/revoked sessions
- Session cleanup (startup sweep, background task)
- User isolation with `user.id` (not `session_id`)

### Integration Tests
- Full OAuth flow → token persistence → restart → session recovery
- Suspension → session revocation → token cleared
- Multi-session same user → isolated portfolios

### Regression Tests
- All existing Phase 10.1A/B tests continue to pass
- Auth router tests updated for new dependency
- Paper trading isolation tests updated for `user.id`

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Token encryption key management | Use existing `UPSTOX_API_SECRET` — no new secrets |
| Breaking existing sessions on deploy | Acceptable — users re-login once |
| Performance impact of DB token lookup | In-memory cache as fast path; DB as fallback |
| `user.id` migration breaks existing data | `session_id` and `user.id` are both strings; migration is transparent |
| Historical GEX auth breaks public access | Confirm with Principal Architect whether GEX should be public |

## 10. Dependencies

### From Phase 10.1 (must preserve)
- Alembic as sole schema management
- `Config.attributes` engine sharing
- `User`/`UserSession` models
- `get_or_create_user_from_upstox()` function
- Session hashing (SHA-256)
- Auth path DDL removal

### External
- PostgreSQL in production (Railway) — already available
- No new infrastructure dependencies

## 11. Sequencing

```
Phase 10.2A (Security & Correctness)
  ├── 1. get_current_user() dependency
  ├── 2. historical_gex authentication
  ├── 3. user.id isolation in paper/gex/annotations
  └── 4. create_session_record() fix

Phase 10.2B (Token Persistence)
  ├── 5. Alembic migration (broker_token_encrypted + indexes)
  ├── 6. Token encryption layer
  ├── 7. DB persistence in token_store
  └── 8. Remove get_any_token()

Phase 10.2C (Session Lifecycle)
  ├── 9. Session cleanup (startup + background)
  └── 10. Suspension → revocation

Phase 10.2D (Schema Cleanup)
  ├── 11. Composite indexes to Alembic
  └── 12. Duplicate WAL fix
```

## 12. Acceptance Criteria

- [ ] All `historical_gex` endpoints require authentication
- [ ] `user.id` is used for ownership isolation (not `session_id`)
- [ ] Broker tokens are encrypted at rest in database
- [ ] Sessions survive server restart (for new sessions)
- [ ] Suspended users have all sessions revoked
- [ ] Expired sessions are cleaned up automatically
- [ ] Composite indexes are in Alembic baseline
- [ ] No duplicate WAL listener
- [ ] All Phase 10.1A/B tests continue to pass
- [ ] New tests cover all Phase 10.2 changes
- [ ] No production database modifications without migration

---

_This document is a design proposal. Implementation requires Principal Architect approval._
