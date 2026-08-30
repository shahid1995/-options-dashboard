import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db import init_db, SessionLocal
from app.routers import annotations, auth, candles, chains, gex, historical_gex, live_gex, paper, resolve, templates

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background GEX capture loop (Phase 8B)
# ---------------------------------------------------------------------------
#
# When GEX_CAPTURE_ENABLED is True and GEX_USER_ID is configured, a background
# asyncio task periodically:
#   1. Fetches the option chain from the specified user's authorized Upstox session
#   2. Computes GEX via LiveGexService
#   3. Persists a snapshot to gex_snapshots
#   4. Prunes snapshots older than the retention period
#
# Architecture: customer Analytics Tokens are user-scoped, not platform credentials.
# GEX_CAPTURE_ENABLED + GEX_USER_ID explicitly enables capture for one user.
# GEX_HISTORY_ENABLED controls UI display of historical GEX (separate concern).
#
# The loop:
#   - One background task, started on app startup
#   - Cleanly cancelled on shutdown
#   - Exceptions are logged and do not kill the loop
#   - No global mutable state; each iteration is independent
# ---------------------------------------------------------------------------

_capture_task = None
_stop_event = asyncio.Event()


async def _gex_capture_loop(user_id: str | None = None):
    """Background loop: capture GEX snapshots at the configured interval.

    Resilience features:
    - Single failed capture never kills the loop
    - Repeated failures trigger exponential backoff (up to 5x interval)
    - DB sessions are always closed even on unexpected errors
    - Structured logging for observability
    - Backoff resets after a successful capture
    """
    import time as _time
    from app.services.token_store import get_token, get_all_session_ids
    from app.services.gex_capture import GexCaptureService, run_retention_cleanup
    from app.services.live_gex import LiveGexService

    interval = getattr(settings, "GEX_HISTORY_SAMPLE_SECONDS", 60)
    capture_service = GexCaptureService()
    gex_service = LiveGexService()
    consecutive_failures = 0
    max_backoff_multiplier = 5

    logger.info(
        "GEX capture loop started",
        extra={"event": "gex.capture_loop.started", "interval_seconds": interval},
    )

    # Wait for initial interval before first capture (let app fully start)
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=interval)
        logger.info("GEX capture loop stopped (pre-start)")
        return
    except asyncio.TimeoutError:
        pass

    while not _stop_event.is_set():
        cycle_start = _time.time()
        try:
            # Fetch chain from the customer's authorized broker
            from app.brokers.adapters.upstox.mapper import UPSTOX_INSTRUMENT_KEYS as INSTRUMENT_KEYS
            from app.brokers.domain.enums import BROKER_ID_UPSTOX
            from app.brokers.gateway import gateway

            # Token priority (user-scoped — never platform-wide):
            # 1. Analytics Token via explicit connection (1-year, read-only)
            # 2. OAuth session token (daily expiry, fallback)
            # 3. Skip if no token available
            connection_id = _find_default_connection_id(user_id) if user_id else None
            token = _get_analytics_token_for_gex(user_id, connection_id=connection_id) if user_id and connection_id else None
            token_source = "analytics"
            current_session_id = None
            if not token:
                token, current_session_id = _get_oauth_token_for_gex(user_id) if user_id else (None, None)
                token_source = "oauth"

            if not token:
                logger.debug("GEX capture skipped: no available token")
                await _interruptible_sleep(interval)
                continue

            symbol = "NIFTY"
            if symbol not in INSTRUMENT_KEYS:
                await _interruptible_sleep(interval)
                continue

            adapter = gateway.create(BROKER_ID_UPSTOX, access_token=token)

            # Get available expiries
            try:
                contracts = await adapter.get_option_contracts(symbol)
                expiries = contracts.get("expiries", [])
                if not expiries:
                    logger.debug("GEX capture skipped: no expiries available")
                    await _interruptible_sleep(interval)
                    continue
                expiry_date = expiries[0]
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "GEX capture skipped: failed to get expiries",
                    extra={"event": "gex.capture_loop.failed", "error": str(exc), "consecutive_failures": consecutive_failures},
                )
                await _interruptible_sleep(interval)
                continue

            # Fetch chain
            try:
                chain = await adapter.get_option_chain(symbol, expiry_date)
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "GEX capture skipped: chain fetch failed",
                    extra={"event": "gex.capture_loop.failed", "symbol": symbol, "error": str(exc), "consecutive_failures": consecutive_failures},
                )
                await _interruptible_sleep(interval)
                continue

            # Capture and persist — DB session in try/finally for guaranteed cleanup
            db = SessionLocal()
            try:
                # owner_id is always the StrikeNova user ID (user-scoped GEX).
                # Both Analytics Token and OAuth captures are owned by the user.
                owner_id = user_id
                result = capture_service.capture_once(db, chain, expiry=expiry_date, symbol=symbol, owner_id=owner_id)
                status = result.get("status")

                if status == "captured":
                    consecutive_failures = 0  # Reset backoff on success
                    logger.info(
                        "Background GEX snapshot captured",
                        extra={
                            "event": "gex.capture_loop.completed",
                            "symbol": symbol,
                            "expiry": expiry_date,
                            "net_gex": result.get("net_gex"),
                            "snapshot_id": result.get("snapshot_id"),
                            "duration_ms": round((_time.time() - cycle_start) * 1000, 0),
                        },
                    )
                else:
                    consecutive_failures += 1
                    logger.debug(
                        "GEX capture not successful",
                        extra={"event": "gex.capture_loop.skipped", "status": status, "reason": result.get("reason")},
                    )

                # Retention cleanup — always safe and idempotent
                run_retention_cleanup(db)

            finally:
                try:
                    db.close()
                except Exception:
                    pass

        except asyncio.CancelledError:
            break
        except Exception as exc:
            consecutive_failures += 1
            logger.error(
                "GEX capture loop error",
                extra={"event": "gex.capture_loop.error", "error": str(exc), "consecutive_failures": consecutive_failures},
                exc_info=True,
            )

        # Apply backoff on repeated failures
        effective_interval = interval
        if consecutive_failures > 0:
            backoff_multiplier = min(consecutive_failures, max_backoff_multiplier)
            effective_interval = interval * backoff_multiplier

        await _interruptible_sleep(effective_interval)

    logger.info("GEX capture loop stopped")


def _find_default_connection_id(user_id: str) -> str | None:
    """Find the user's default UPSTOX connection with active data.

    Returns the connection_id for the user's explicitly-default connection,
    or None if no default connection exists. Does NOT fall back to
    arbitrary connection selection — GEX requires explicit authorization.
    """
    try:
        from app.db import SessionLocal
        from app.identity import BrokerConnection

        db = SessionLocal()
        try:
            conn = (
                db.query(BrokerConnection)
                .filter(
                    BrokerConnection.user_id == user_id,
                    BrokerConnection.status == "connected",
                    BrokerConnection.broker == "UPSTOX",
                    BrokerConnection.data_status == "active",
                    BrokerConnection.broker_analytics_token_encrypted.isnot(None),
                    BrokerConnection.is_default == True,
                )
                .first()
            )
            return conn.id if conn else None
        finally:
            db.close()
    except Exception:
        return None


def _get_analytics_token_for_gex(user_id: str, *, connection_id: str) -> str | None:
    """Find an Analytics Token for a specific user's connection for GEX.

    Requires explicit connection_id — GEX never silently selects a connection.
    Resolves exactly the specified user-owned BrokerConnection.
    """
    try:
        from app.db import SessionLocal
        from app.identity import get_analytics_token

        db = SessionLocal()
        try:
            return get_analytics_token(db, user_id, "UPSTOX", connection_id=connection_id)
        finally:
            db.close()
    except Exception:
        logger.warning("Failed to get Analytics Token for GEX capture")
        return None


def _get_oauth_token_for_gex(user_id: str) -> tuple[str | None, str | None]:
    """Fallback: find an active OAuth session token for a specific user.

    OAuth tokens expire daily at 3:30 AM IST.
    Returns (token, session_hash) or (None, None).
    Only resolves tokens belonging to the specified user.

    Uses resolve_broker_token_by_session_hash() to avoid the double-hashing
    bug of passing session_hash to get_token() which expects plaintext.
    """
    from app.db import SessionLocal
    from app.identity import UserSession, resolve_broker_token_by_session_hash
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        session = (
            db.query(UserSession)
            .filter(
                UserSession.user_id == user_id,
                UserSession.expires_at > now,
                UserSession.revoked_at.is_(None),
            )
            .order_by(UserSession.created_at.desc())
            .first()
        )
        if session is None:
            return None, None
        # Use the dedicated hash-based resolver instead of get_token(hash)
        token = resolve_broker_token_by_session_hash(session.session_hash)
        return token, session.session_hash
    finally:
        db.close()


async def _interruptible_sleep(seconds: float):
    """Sleep that can be interrupted by the stop event."""
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _capture_task
    init_db()

    # Phase 10.2B-3: Verify DB token health at startup.
    # Tokens survive restarts via get_token() DB fallback (memory miss -> DB -> decrypt -> cache).
    # No in-memory rehydration: DB stores session_hash, not plaintext session_id.
    try:
        from app.services.token_store import startup_db_check
        count = startup_db_check()
        logger.info("DB token health check: %d active tokens", count)
    except Exception:
        logger.warning("DB token health check failed (non-critical)")

    # Start background GEX capture if explicitly enabled.
    # GEX_CAPTURE_ENABLED controls the background loop (separate from GEX_HISTORY_ENABLED which controls UI).
    # GEX_USER_ID must be configured when capture is enabled.
    gex_capture_enabled = getattr(settings, "GEX_CAPTURE_ENABLED", False)
    gex_user_id = getattr(settings, "GEX_USER_ID", "") or None
    if gex_capture_enabled and gex_user_id:
        _stop_event.clear()
        _capture_task = asyncio.create_task(_gex_capture_loop(gex_user_id))
        logger.info("Background GEX capture task started", extra={"user_id": bool(gex_user_id)})
    elif gex_capture_enabled and not gex_user_id:
        logger.warning("GEX_CAPTURE_ENABLED but GEX_USER_ID not set — capture disabled")

    yield

    # Shutdown: stop the capture loop
    if _capture_task is not None and not _capture_task.done():
        _stop_event.set()
        try:
            await asyncio.wait_for(_capture_task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _capture_task.cancel()
        logger.info("Background GEX capture task stopped")

    # Cleanup rate limiter stale entries
    from app.services.rate_limiter import rate_limiter
    rate_limiter.cleanup()


app = FastAPI(title="Options Dashboard API", lifespan=lifespan, docs_url="/docs" if getattr(settings, "DEBUG", False) else None)

# CORS: production uses explicitly configured origins; development allows localhost
# FRONTEND_URL supports comma-separated origins for Vercel preview deployments.
# ADDITIONAL_CORS_ORIGINS provides extra origins (e.g. preview branches).
_cors_origins: list[str] = []
for _origin_source in [
    getattr(settings, "FRONTEND_URL", ""),
    getattr(settings, "ADDITIONAL_CORS_ORIGINS", ""),
]:
    if _origin_source:
        _cors_origins.extend(
            o.strip() for o in _origin_source.split(",") if o.strip()
        )
if getattr(settings, "ALLOW_LOCALHOST_CORS", False):
    _cors_origins.append("http://localhost:3000")
# Deduplicate while preserving order
_cors_origins = list(dict.fromkeys(_cors_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Session-Id"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chains.router, prefix="/chains", tags=["chains"])
app.include_router(paper.router, prefix="/paper", tags=["paper"])
app.include_router(templates.router, prefix="/paper", tags=["templates"])
app.include_router(resolve.router, prefix="/paper", tags=["resolve"])
app.include_router(gex.router, prefix="/gex", tags=["gex"])
app.include_router(historical_gex.router, prefix="/gex", tags=["gex-history"])
app.include_router(annotations.router, tags=["annotations"])
app.include_router(candles.router, prefix="/candles", tags=["candles"])
app.include_router(live_gex.router, prefix="/gex", tags=["gex-live"])


@app.get("/health")
def health():
    """Liveness check — is the process alive?"""
    return {"status": "ok"}


@app.get("/readiness")
def readiness():
    """Readiness check — can the app serve production traffic?"""
    import time
    from app.db import engine
    from sqlalchemy import text

    checks = {}
    all_ok = True

    # Database check
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        all_ok = False

    # Token store check
    try:
        from app.services.token_store import get_session_count
        checks["token_store"] = "ok"
        checks["active_sessions"] = get_session_count()
    except Exception as e:
        checks["token_store"] = f"error: {type(e).__name__}"
        all_ok = False

    status_code = 200 if all_ok else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
        status_code=status_code,
    )
