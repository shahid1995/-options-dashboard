"""Phase 6.4.1 — Broker profile & connection diagnostics (READ-ONLY).

A small domain service over the Upstox profile endpoint
(``GET /v2/user/profile``, ``app/services/upstox.py``). It answers ONE
question for the authenticated customer: "is the broker connection working,
and what safe account information does the broker report?"

Non-negotiable rules:

- Profile data is normalized to a SAFE contract. Only the fields the UI
  needs are returned — never the raw broker payload (it can carry the
  customer's identity fields) and never credentials (access_token,
  refresh_token, api_key, api_secret, client_secret, authorization codes).
- Missing optional profile fields are ``None`` — never fabricated. The
  Upstox profile response has no ``account_type`` field, so
  ``account_type`` stays ``None`` (never invented).
- Broker failures map to structured error codes (BROKER_TOKEN_EXPIRED,
  BROKER_RATE_LIMITED, BROKER_MAINTENANCE, BROKER_BAD_RESPONSE,
  BROKER_NETWORK_ERROR, BROKER_PROFILE_UNAVAILABLE, BROKER_AUTH_REQUIRED)
  with human-readable messages — no raw provider errors, no stack traces.
- Profile is cached briefly (TTL 300 s) with a USER-SCOPED key: user A's
  profile is never served to user B. A manual refresh bypasses the cache.
- No mutation, no trading logic, no market-data calls. This is a
  diagnostics/account-information feature only.

The endpoint contract (see ``app.schemas.BrokerProfileOut``)::

    {
        "status": "available" | "unavailable",
        "source": "BROKER_REPORTED",
        "broker": "UPSTOX",
        "profile": {normalized safe profile} | None,
        "generated_at": iso | None,
        "cached": bool,
        "error": structured code | None,
        "message": human-readable | None,
    }
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.upstox import UpstoxError

BROKER = "UPSTOX"
SOURCE_BROKER_REPORTED = "BROKER_REPORTED"
STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"

# ---- Structured broker diagnostics (§9) --------------------------------------

BROKER_AUTH_REQUIRED = "BROKER_AUTH_REQUIRED"
BROKER_TOKEN_EXPIRED = "BROKER_TOKEN_EXPIRED"
BROKER_RATE_LIMITED = "BROKER_RATE_LIMITED"
BROKER_PROFILE_UNAVAILABLE = "BROKER_PROFILE_UNAVAILABLE"
BROKER_BAD_RESPONSE = "BROKER_BAD_RESPONSE"
BROKER_MAINTENANCE = "BROKER_MAINTENANCE"
BROKER_NETWORK_ERROR = "BROKER_NETWORK_ERROR"

PROFILE_TTL_SECONDS = 300  # recommended profile TTL (§17) — not tick data

# Broker profile fields that are NEVER returned, even if a future broker
# payload ever included them (security regression guard).
FORBIDDEN_FIELDS = (
    "access_token",
    "refresh_token",
    "api_key",
    "api_secret",
    "client_secret",
    "client_id",
    "authorization_code",
    "auth_code",
    "password",
)


class BrokerProfileError(Exception):
    """A structured broker-profile failure (stable code + human message)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def classify_upstox_error(exc: UpstoxError) -> tuple[str, str]:
    """Map an Upstox profile failure to (structured code, human message).

    The message is written for the customer — the raw provider message is
    never passed through (no stack traces, no internal error text).
    """
    if exc.status_code in (401, 403):
        return (
            BROKER_TOKEN_EXPIRED,
            "Upstox session expired or unauthorized — reconnect your broker.",
        )
    if exc.status_code == 423:
        return (
            BROKER_MAINTENANCE,
            "Upstox is in its daily maintenance window — try again shortly.",
        )
    if exc.status_code == 429:
        return (
            BROKER_RATE_LIMITED,
            "Upstox rate limit reached — try again shortly.",
        )
    if exc.status_code == 502 and str(exc.message).startswith("Could not reach Upstox"):
        return (
            BROKER_NETWORK_ERROR,
            "Could not reach Upstox — check your network connection.",
        )
    return (
        BROKER_PROFILE_UNAVAILABLE,
        "Upstox profile temporarily unavailable. Try again in a few minutes.",
    )


# ---- Normalization ------------------------------------------------------------

def _optional_str(value):
    return value if isinstance(value, str) and value.strip() else None


def _optional_bool(value):
    return value if isinstance(value, bool) else None


def _optional_str_list(value):
    if not isinstance(value, list):
        return None
    items = [v for v in value if isinstance(v, str) and v.strip()]
    return items or None


def normalize_profile(data: dict | None) -> dict:
    """Normalize the Upstox profile payload ``data`` into the SAFE contract.

    Only the fields the UI needs are copied; anything else in the payload is
    dropped (never returned raw). Optional fields that the broker does not
    report become ``None`` — never fabricated. ``account_type`` is not part
    of the Upstox profile response, so it stays ``None`` unless a future
    broker payload reports it.
    """
    data = data or {}
    return {
        "user_name": _optional_str(data.get("user_name")),
        "email": _optional_str(data.get("email")),
        "user_id": _optional_str(data.get("user_id")),
        "broker": _optional_str(data.get("broker")) or BROKER,
        "user_type": _optional_str(data.get("user_type")),
        "account_type": _optional_str(data.get("account_type")),
        "is_active": _optional_bool(data.get("is_active")),
        "exchanges": _optional_str_list(data.get("exchanges")),
        "products": _optional_str_list(data.get("products")),
        "order_types": _optional_str_list(data.get("order_types")),
        "poa": _optional_bool(data.get("poa")),
        "ddpi": _optional_bool(data.get("ddpi")),
    }


def assert_no_secrets(payload: dict) -> None:
    """Security regression guard: the contract must never carry credentials.

    Checks top-level keys only (the profile dict is built by
    ``normalize_profile`` from an allow-list, so it cannot contain them).
    """
    for key in FORBIDDEN_FIELDS:
        if key in payload:
            raise BrokerProfileError(
                BROKER_BAD_RESPONSE, "Refusing to expose a credential field in the profile payload."
            )


# ---- Cache (§17/§18) ----------------------------------------------------------


class BrokerProfileCache:
    """Small TTL cache keyed by user id — one user's profile is never
    served to another user. Values expire after ``PROFILE_TTL_SECONDS`` and
    are never served stale."""

    def __init__(self, now=None):
        self._store: dict[str, dict] = {}
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get(self, key: str):
        item = self._store.get(key)
        if item is None:
            return None
        if item["expires_at"] <= self._now():
            del self._store[key]
            return None
        return item["value"]

    def set(self, key: str, value, ttl_seconds: int) -> None:
        self._store[key] = {"value": value, "expires_at": self._now() + timedelta(seconds=ttl_seconds)}

    def clear(self) -> None:
        self._store.clear()


# Module-level singleton so a profile fetched for one request is reused for
# the TTL by later requests of the SAME user (profile is not tick data).
_PROFILE_CACHE = BrokerProfileCache()


# ---- Service ------------------------------------------------------------------


def _unavailable_summary(code: str, message: str, cached: bool = False) -> dict:
    return {
        "status": STATUS_UNAVAILABLE,
        "source": SOURCE_BROKER_REPORTED,
        "broker": BROKER,
        "profile": None,
        "generated_at": None,
        "cached": cached,
        "error": code,
        "message": message,
    }


async def get_broker_profile_summary(
    user_id: str,
    access_token: str,
    profile_fetcher=None,
    cache: BrokerProfileCache | None = None,
    now=None,
    refresh: bool = False,
) -> dict:
    """Fetch (or serve from the user-scoped cache) the normalized profile.

    ``user_id`` scopes the cache AND the authorization semantics: this
    service only ever asks the broker with the token that authenticated that
    session. ``refresh=True`` bypasses the cache (manual refresh).

    Returns the full endpoint contract dict. Never raises: broker failures
    degrade to an ``unavailable`` result with a structured code.
    """
    fetcher = profile_fetcher or _default_fetcher
    cache_store = cache if cache is not None else _PROFILE_CACHE
    now_fn = now or (lambda: datetime.now(timezone.utc))
    generated_at = now_fn().isoformat()

    if not access_token:
        return _unavailable_summary(
            BROKER_AUTH_REQUIRED, "Broker login required — log in to Upstox first."
        )

    cache_key = f"profile:{user_id}"
    if not refresh:
        cached = cache_store.get(cache_key)
        if cached is not None:
            return {**cached, "cached": True}

    try:
        body = await fetcher(access_token)
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise BrokerProfileError(
                BROKER_BAD_RESPONSE, "Upstox profile response was unreadable."
            )
        profile = normalize_profile(body["data"])
        summary = {
            "status": STATUS_AVAILABLE,
            "source": SOURCE_BROKER_REPORTED,
            "broker": profile.get("broker") or BROKER,
            "profile": profile,
            "generated_at": generated_at,
            "cached": False,
            "error": None,
            "message": "Upstox profile retrieved.",
        }
        assert_no_secrets(summary)
    except UpstoxError as exc:
        code, message = classify_upstox_error(exc)
        summary = _unavailable_summary(code, message)
    except BrokerProfileError as exc:
        summary = _unavailable_summary(exc.code, exc.message)

    cache_store.set(cache_key, summary, PROFILE_TTL_SECONDS)
    return summary


async def _default_fetcher(access_token: str) -> dict:
    from app.services import upstox

    return await upstox.get_broker_profile(access_token)
