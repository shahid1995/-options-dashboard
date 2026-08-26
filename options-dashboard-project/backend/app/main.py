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
# When GEX_HISTORY_ENABLED is True, a background asyncio task periodically:
#   1. Fetches the option chain from the customer's authorized Upstox session
#   2. Computes GEX via LiveGexService
#   3. Persists a snapshot to gex_snapshots
#   4. Prunes snapshots older than the retention period
#
# The loop is designed for the current single-user architecture:
#   - One background task, started on app startup
#   - Cleanly cancelled on shutdown
#   - Exceptions are logged and do not kill the loop
#   - No global mutable state; each iteration is independent
# ---------------------------------------------------------------------------

_capture_task = None
_stop_event = asyncio.Event()


async def _gex_capture_loop():
    """Background loop: capture GEX snapshots at the configured interval."""
    from app.services.token_store import get_any_token
    from app.services.gex_capture import GexCaptureService, run_retention_cleanup
    from app.services.live_gex import LiveGexService

    interval = getattr(settings, "GEX_HISTORY_SAMPLE_SECONDS", 60)
    capture_service = GexCaptureService()
    gex_service = LiveGexService()

    logger.info(
        "GEX capture loop started",
        extra={"interval_seconds": interval, "enabled": settings.GEX_HISTORY_ENABLED},
    )

    # Wait for initial interval before first capture (let app fully start)
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=interval)
        logger.info("GEX capture loop stopped (pre-start)")
        return
    except asyncio.TimeoutError:
        pass

    while not _stop_event.is_set():
        try:
            # Get the current broker token (single-user: first active session)
            token = get_any_token()
            if token is None:
                # No active session — skip this cycle
                logger.debug("GEX capture skipped: no active broker session")
                await _interruptible_sleep(interval)
                continue

            # Fetch chain from the customer's authorized broker
            from app.brokers.adapters.upstox.mapper import UPSTOX_INSTRUMENT_KEYS as INSTRUMENT_KEYS
            from app.brokers.domain.enums import BROKER_ID_UPSTOX
            from app.brokers.gateway import gateway

            # Default to NIFTY with nearest expiry — in production this would
            # be configurable per-user; for single-user MVP we capture NIFTY.
            symbol = "NIFTY"
            if symbol not in INSTRUMENT_KEYS:
                await _interruptible_sleep(interval)
                continue

            adapter = gateway.create(BROKER_ID_UPSTOX, access_token=token)

            # Get available expiries to find the nearest one
            try:
                from app.brokers.domain.errors import BrokerError
                contracts = await adapter.get_option_contracts(symbol)
                expiries = contracts.get("expiries", [])
                if not expiries:
                    logger.debug("GEX capture skipped: no expiries available")
                    await _interruptible_sleep(interval)
                    continue
                expiry_date = expiries[0]  # nearest expiry
            except Exception as exc:
                logger.warning(
                    "GEX capture skipped: failed to get expiries",
                    extra={"error": str(exc)},
                )
                await _interruptible_sleep(interval)
                continue

            # Fetch chain
            try:
                chain = await adapter.get_option_chain(symbol, expiry_date)
            except Exception as exc:
                logger.warning(
                    "GEX capture skipped: chain fetch failed",
                    extra={"symbol": symbol, "expiry": expiry_date, "error": str(exc)},
                )
                await _interruptible_sleep(interval)
                continue

            # Capture and persist
            db = SessionLocal()
            try:
                result = capture_service.capture_once(db, chain, expiry=expiry_date, symbol=symbol)
                if result.get("status") == "captured":
                    logger.info(
                        "Background GEX snapshot captured",
                        extra={
                            "symbol": symbol,
                            "expiry": expiry_date,
                            "net_gex": result.get("net_gex"),
                            "snapshot_id": result.get("snapshot_id"),
                        },
                    )

                # Periodic retention cleanup (every 10 captures)
                # Simplified: always run; prune_gex_snapshots is fast and idempotent
                run_retention_cleanup(db)

            finally:
                db.close()

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(
                "GEX capture loop error",
                extra={"error": str(exc)},
                exc_info=True,
            )

        # Wait for next interval (interruptible)
        await _interruptible_sleep(interval)

    logger.info("GEX capture loop stopped")


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

    # Start background GEX capture if enabled
    if getattr(settings, "GEX_HISTORY_ENABLED", False):
        _stop_event.clear()
        _capture_task = asyncio.create_task(_gex_capture_loop())
        logger.info("Background GEX capture task started")

    yield

    # Shutdown: stop the capture loop
    if _capture_task is not None and not _capture_task.done():
        _stop_event.set()
        try:
            await asyncio.wait_for(_capture_task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _capture_task.cancel()
        logger.info("Background GEX capture task stopped")


app = FastAPI(title="Options Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
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
    return {"status": "ok"}
