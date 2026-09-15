"""FYERS staging diagnostics — masked, user-scoped, read-only.

Purpose (staging identity-validation task): after a live FYERS OAuth
consent, report JUST enough to confirm the adapter wiring and the exact
customer identity field — and to exercise the FYERS read-only surface
(profile, funds, positions, holdings, tradebook, quote, option contracts)
against the real staging account.

Security contract (mirrors ``app.services.broker_profile``):

- Credentials NEVER cross this boundary: no access token, refresh token,
  app id, app secret, appIdHash or PIN is accepted from, or returned to,
  any caller. The adapter is built server-side from the caller's OWN
  encrypted BYOB credentials (``resolve_user_credentials``) plus the
  CURRENT session's broker token (never resurrected from other sessions).
- The caller can only ever see THEIR OWN connection (session → user_id →
  that user's FYERS connection row); another user's connection 404s.
- Profile-derived data is masked: the customer identity appears only
  MASKED; only its FIELD NAME and the profile key NAMES are verbatim.
  No email value, PAN, PIN or DOB is ever included.
- Broker failures map to canonical ``BrokerErrorCode`` names — no raw
  provider payloads, no stack traces.

Read-only by construction: no order endpoints are reachable from here,
and nothing creates sessions, tokens or connections.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.brokers.domain.errors import BrokerError
from app.brokers.gateway import gateway
from app.identity import BrokerConnection
from app.identity import resolve_user_credentials
from app.routers.deps import AuthenticatedUser, CurrentUser, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fyers", tags=["fyers-diagnostics"])

# App-id suffix → generation hint (FYERS -200 compliant vs legacy/-100).
_APP_TYPE_HINTS = {
    "-200": "compliant_trading_candidate",
    "-100": "legacy_data_only",
    "-40": "legacy_data_only",
}

# Capability names reported verbatim from the adapter's matrix.
_REPORTED_CAPABILITIES = (
    "profile",
    "funds",
    "positions",
    "holdings",
    "quotes",
    "option_chain",
    "option_contracts",
    "trades",
    "market_status",
    "orders",
    "websocket_market_data",
    "websocket_order_events",
    "margin",
)


def _mask(value: str | None) -> str | None:
    """Mask an identifier: keep first 2 + last 2 chars only."""
    if not value:
        return None
    text = str(value).strip()
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"


def _require_fyers_connection(db: Session, user_id: str) -> BrokerConnection:
    """The caller's own FYERS connection, or 404 (no enumeration)."""
    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == "FYERS",
        )
        .order_by(BrokerConnection.created_at.desc())
        .first()
    )
    if conn is None:
        raise HTTPException(
            status_code=404,
            detail="No FYERS connection for this user. Connect FYERS first.",
        )
    return conn


class FyersDiagnosticsOut(BaseModel):
    ok: bool
    connection_id: str | None = None
    connection_status: str | None = None
    broker_account_id_masked: str | None = None
    identity: dict | None = None
    capabilities: dict | None = None
    reads: dict | None = None
    error: str | None = None


@router.get("/diagnostics", response_model=FyersDiagnosticsOut)
async def fyers_diagnostics(
    user: AuthenticatedUser = Depends(CurrentUser()),
    db: Session = Depends(get_db),
) -> FyersDiagnosticsOut:
    """Masked FYERS connection + read-only capability report (own data only)."""
    conn = _require_fyers_connection(db, user.user_id)
    out = FyersDiagnosticsOut(ok=True, connection_id=conn.id)
    out.connection_status = conn.status
    out.broker_account_id_masked = _mask(conn.broker_account_id)

    try:
        credentials = resolve_user_credentials(user.user_id, "FYERS", db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    app_id = str(credentials.get("api_key") or "")
    out.capabilities = {
        "app_id_suffix_reported": app_id[-4:] if len(app_id) >= 4 else None,
        "app_type_hint": _APP_TYPE_HINTS.get(app_id[-4:], "unknown"),
        "note": (
            "app-id suffix is a HINT only — the authoritative capability "
            "comes from the FYERS app configuration and live probes"
        ),
    }

    # The CURRENT session's FYERS token (never resurrected from other
    # sessions); None means "consent not completed in this session" —
    # the profile probe then reports AUTH_REQUIRED instead of failing.
    access_token = user.access_token
    adapter = gateway.create("FYERS", access_token=access_token, **credentials)

    # ---- 1) Profile + masked identity extraction -------------------------
    profile: dict | None = None
    try:
        profile = await adapter.get_profile()
        identity_field = None
        identity_masked = None
        profile_keys: list[str] = []
        app_permit = None
        try:
            from app.brokers.adapters.fyers.profile import diagnose_profile_identity

            report = diagnose_profile_identity(profile)
            identity_field = report.get("selected_field")
            identity_masked = report.get("identity_masked")
            profile_keys = report.get("profile_keys", [])
        except Exception:
            logger.exception("FYERS identity diagnostic failed (non-fatal)")
        data = profile.get("data") if isinstance(profile, dict) else None
        if isinstance(data, dict):
            app_permit = data.get("app_permit") or data.get("appattribution")
        out.identity = {
            "ok": True,
            "identity_field": identity_field,
            "identity_masked": identity_masked,
            "profile_keys": profile_keys,
            "app_type_signal": app_permit,
        }
    except BrokerError as exc:
        out.identity = {"ok": False, "error": exc.code.value}

    # ---- 2) Capability matrix as the adapter computes it -----------------
    try:
        caps = adapter.get_capabilities(profile)
        out.capabilities.update(
            {name: caps.state(name).value for name in _REPORTED_CAPABILITIES}
        )
    except BrokerError as exc:
        out.capabilities["error"] = exc.code.value

    # ---- 3) Read-only surface probes (never orders) ----------------------
    async def _probe(name: str, coro) -> dict:
        try:
            result = await coro
        except BrokerError as exc:
            return {"ok": False, "error": exc.code.value}
        except Exception:
            logger.exception("FYERS diagnostics probe %s failed", name)
            return {"ok": False, "error": "UNEXPECTED_ERROR"}
        if isinstance(result, dict):
            return {"ok": True, "keys": sorted(str(k) for k in result.keys())[:12]}
        if isinstance(result, list):
            return {"ok": True, "rows": len(result)}
        return {"ok": True}

    async def _probe_quote_and_chain() -> dict:
        quote_out: dict = {}
        try:
            instrument = adapter.resolve_instrument("NIFTY")
            obs = await adapter.get_quote(instrument)
            quote_out = {
                "ok": True,
                "ltp_present": obs.quote.ltp is not None,
                "symbol": obs.instrument.symbol,
                "source": obs.source,
            }
        except BrokerError as exc:
            quote_out = {"ok": False, "error": exc.code.value}
        except Exception:
            logger.exception("FYERS diagnostics quote probe failed")
            quote_out = {"ok": False, "error": "UNEXPECTED_ERROR"}

        chain_out: dict = {}
        try:
            contracts = await adapter.get_option_contracts("NIFTY")
            shape = (
                {"rows": len(contracts)}
                if isinstance(contracts, list)
                else {"keys": sorted(str(k) for k in contracts.keys())[:12]}
                if isinstance(contracts, dict)
                else {"shape": type(contracts).__name__}
            )
            chain_out = {"ok": True, **shape}
        except BrokerError as exc:
            chain_out = {"ok": False, "error": exc.code.value}
        except Exception:
            logger.exception("FYERS diagnostics chain probe failed")
            chain_out = {"ok": False, "error": "UNEXPECTED_ERROR"}
        return {"quote": quote_out, "option_contracts": chain_out}

    funds, positions, holdings, trades, qc = await asyncio.gather(
        _probe("funds", adapter.get_funds()),
        _probe("positions", adapter.get_positions()),
        _probe("holdings", adapter.get_holdings()),
        _probe("tradebook", adapter.get_tradebook()),
        _probe_quote_and_chain(),
    )
    out.reads = {
        "funds": funds,
        "positions": positions,
        "holdings": holdings,
        "tradebook": trades,
        **qc,
    }

    if conn.broker_account_id == "pending":
        out.error = (
            "Connection is still 'pending' — no completed FYERS OAuth on "
            "record for this user yet."
        )
    return out
