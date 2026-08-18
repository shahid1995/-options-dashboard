"""Phase 6.4.1 — broker profile & connection diagnostics tests.

Covers the backend matrix from the phase spec:

1. successful profile response        9.  secret fields never returned
2. profile field mapping              10. user isolation
3. missing optional fields            11. cache hit
4. auth failure                       12. cache expiry
5. token expired                      13. manual refresh bypass
6. rate limit                         14. broker error normalization
7. broker unavailable
8. malformed response
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services import broker_profile, token_store
from app.services.broker_profile import (
    BROKER_AUTH_REQUIRED,
    BROKER_BAD_RESPONSE,
    BROKER_MAINTENANCE,
    BROKER_NETWORK_ERROR,
    BROKER_PROFILE_UNAVAILABLE,
    BROKER_RATE_LIMITED,
    BROKER_TOKEN_EXPIRED,
    BrokerProfileCache,
    FORBIDDEN_FIELDS,
    get_broker_profile_summary,
    normalize_profile,
)


# ---- Fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_profile_cache():
    """Each test starts with an empty module-level profile cache so cached
    entries from an earlier test can never leak into a later one."""
    broker_profile._PROFILE_CACHE.clear()
    yield
    broker_profile._PROFILE_CACHE.clear()


@pytest.fixture
def client():
    from app.main import app

    yield TestClient(app)


@pytest.fixture
def logged_in(client):
    return token_store.set_token("tok-xyz")


def headers(session_id):
    return {"X-Session-Id": session_id}


def profile_body(**overrides):
    data = {
        "email": "shahid@example.com",
        "exchanges": ["NSE", "NFO", "BSE", "CDS"],
        "products": ["D", "I"],
        "broker": "UPSTOX",
        "user_id": "UCC12345",
        "user_name": "Shahid Ahmed",
        "order_types": ["MARKET", "LIMIT", "SL", "SL-M"],
        "user_type": "individual",
        "poa": True,
        "ddpi": False,
        "is_active": True,
    }
    data.update(overrides)
    return {"status": "success", "data": data}


def upstox_error(status_code, message="boom"):
    from app.services.upstox import UpstoxError

    return UpstoxError(status_code, message)


def make_fetcher(body):
    async def _f(access_token):
        if isinstance(body, Exception):
            raise body
        return body

    return _f


# ---- Pure normalization -------------------------------------------------------


def test_normalize_profile_maps_all_fields():
    profile = normalize_profile(profile_body()["data"])
    assert profile["user_name"] == "Shahid Ahmed"
    assert profile["email"] == "shahid@example.com"
    assert profile["user_id"] == "UCC12345"
    assert profile["broker"] == "UPSTOX"
    assert profile["user_type"] == "individual"
    assert profile["is_active"] is True
    assert profile["exchanges"] == ["NSE", "NFO", "BSE", "CDS"]
    assert profile["products"] == ["D", "I"]
    assert profile["order_types"] == ["MARKET", "LIMIT", "SL", "SL-M"]
    assert profile["poa"] is True
    assert profile["ddpi"] is False


def test_normalize_profile_missing_optional_fields_are_null():
    # account_type is NOT reported by Upstox — must stay None, never fabricated.
    profile = normalize_profile({"user_id": "UCC12345", "user_name": "A"})
    assert profile["email"] is None
    assert profile["account_type"] is None
    assert profile["user_type"] is None
    assert profile["is_active"] is None
    assert profile["exchanges"] is None
    assert profile["products"] is None
    assert profile["order_types"] is None
    assert profile["poa"] is None
    assert profile["ddpi"] is None


def test_normalize_profile_never_carries_credentials():
    profile = normalize_profile(
        {"user_id": "UCC12345", "access_token": "tok", "refresh_token": "ref", "api_secret": "sec"}
    )
    for field in FORBIDDEN_FIELDS:
        assert field not in profile


def test_secret_regression_guard_raises_on_forbidden_key():
    from app.services.broker_profile import BrokerProfileError

    with pytest.raises(BrokerProfileError):
        broker_profile.assert_no_secrets({"access_token": "tok"})


# ---- Service: successful profile ----------------------------------------------


async def test_successful_profile_response():
    summary = await get_broker_profile_summary("user-1", "tok", profile_fetcher=make_fetcher(profile_body()))
    assert summary["status"] == "available"
    assert summary["source"] == "BROKER_REPORTED"
    assert summary["broker"] == "UPSTOX"
    assert summary["error"] is None
    assert summary["cached"] is False
    assert summary["generated_at"] is not None
    assert summary["profile"]["user_name"] == "Shahid Ahmed"
    assert summary["profile"]["user_id"] == "UCC12345"


async def test_profile_field_mapping_full_payload():
    summary = await get_broker_profile_summary("user-1", "tok", profile_fetcher=make_fetcher(profile_body()))
    profile = summary["profile"]
    assert profile == {
        "user_name": "Shahid Ahmed",
        "email": "shahid@example.com",
        "user_id": "UCC12345",
        "broker": "UPSTOX",
        "user_type": "individual",
        "account_type": None,
        "is_active": True,
        "exchanges": ["NSE", "NFO", "BSE", "CDS"],
        "products": ["D", "I"],
        "order_types": ["MARKET", "LIMIT", "SL", "SL-M"],
        "poa": True,
        "ddpi": False,
    }


async def test_missing_optional_fields_stay_null_in_service():
    body = profile_body(email=None, user_type=None, poa=None, exchanges="not-a-list")
    summary = await get_broker_profile_summary("user-1", "tok", profile_fetcher=make_fetcher(body))
    assert summary["status"] == "available"
    assert summary["profile"]["email"] is None
    assert summary["profile"]["user_type"] is None
    assert summary["profile"]["poa"] is None
    assert summary["profile"]["exchanges"] is None  # non-list → None, never fabricated


async def test_secret_fields_never_returned_in_service_response():
    body = profile_body()
    body["data"]["access_token"] = "super-secret-token"
    body["data"]["client_secret"] = "super-secret"
    summary = await get_broker_profile_summary("user-1", "tok", profile_fetcher=make_fetcher(body))
    assert summary["status"] == "available"
    serialized = str(summary)
    for field in FORBIDDEN_FIELDS:
        assert field not in summary["profile"]
    assert "super-secret" not in serialized


# ---- Service: failures --------------------------------------------------------


async def test_token_expired_maps_to_structured_code():
    summary = await get_broker_profile_summary(
        "user-1", "tok", profile_fetcher=make_fetcher(upstox_error(401))
    )
    assert summary["status"] == "unavailable"
    assert summary["profile"] is None
    assert summary["error"] == BROKER_TOKEN_EXPIRED
    assert summary["message"]


async def test_rate_limit_maps_to_structured_code():
    summary = await get_broker_profile_summary(
        "user-1", "tok", profile_fetcher=make_fetcher(upstox_error(429))
    )
    assert summary["error"] == BROKER_RATE_LIMITED


async def test_maintenance_maps_to_structured_code():
    summary = await get_broker_profile_summary(
        "user-1", "tok", profile_fetcher=make_fetcher(upstox_error(423))
    )
    assert summary["error"] == BROKER_MAINTENANCE


async def test_broker_unavailable_generic_maps_to_profile_unavailable():
    summary = await get_broker_profile_summary(
        "user-1", "tok", profile_fetcher=make_fetcher(upstox_error(500))
    )
    assert summary["error"] == BROKER_PROFILE_UNAVAILABLE


async def test_network_error_maps_to_structured_code():
    summary = await get_broker_profile_summary(
        "user-1", "tok", profile_fetcher=make_fetcher(upstox_error(502, "Could not reach Upstox: timeout"))
    )
    assert summary["error"] == BROKER_NETWORK_ERROR


async def test_malformed_response_is_broker_bad_response():
    summary = await get_broker_profile_summary(
        "user-1", "tok", profile_fetcher=make_fetcher({"status": "success"})  # no data
    )
    assert summary["status"] == "unavailable"
    assert summary["error"] == BROKER_BAD_RESPONSE
    assert summary["profile"] is None


async def test_no_access_token_is_auth_required():
    summary = await get_broker_profile_summary("user-1", None)
    assert summary["status"] == "unavailable"
    assert summary["error"] == BROKER_AUTH_REQUIRED


async def test_broker_error_normalization_never_exposes_raw_message():
    summary = await get_broker_profile_summary(
        "user-1", "tok", profile_fetcher=make_fetcher(upstox_error(500, "INTERNAL SECRET DETAIL"))
    )
    assert "SECRET DETAIL" not in str(summary)


# ---- Cache: user isolation / TTL / refresh ------------------------------------


def test_cache_hit_serves_same_user_without_refetch():
    cache = BrokerProfileCache()
    calls = {"n": 0}

    async def counting_fetcher(access_token):
        calls["n"] += 1
        return profile_body()

    async def run():
        first = await get_broker_profile_summary(
            "user-1", "tok", profile_fetcher=counting_fetcher, cache=cache
        )
        second = await get_broker_profile_summary(
            "user-1", "tok", profile_fetcher=counting_fetcher, cache=cache
        )
        return first, second

    import asyncio

    first, second = asyncio.run(run())
    assert calls["n"] == 1  # second call served from cache
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["profile"]["user_id"] == "UCC12345"


def test_cache_is_user_scoped():
    cache = BrokerProfileCache()
    calls = {"n": 0}

    async def counting_fetcher(access_token):
        calls["n"] += 1
        return profile_body(user_id=f"UCC-{access_token}")

    async def run():
        await get_broker_profile_summary("user-a", "tok-a", profile_fetcher=counting_fetcher, cache=cache)
        await get_broker_profile_summary("user-a", "tok-a", profile_fetcher=counting_fetcher, cache=cache)
        # user-b must never see user-a's cached profile.
        await get_broker_profile_summary("user-b", "tok-b", profile_fetcher=counting_fetcher, cache=cache)

    import asyncio

    asyncio.run(run())
    assert calls["n"] == 2  # user-a cached once, user-b fetched fresh


def test_cache_expiry_refetches():
    start = datetime(2026, 8, 18, 10, 0, 0, tzinfo=timezone.utc)
    now = [start]

    def fake_now():
        return now[0]

    cache = BrokerProfileCache(now=fake_now)
    calls = {"n": 0}

    async def counting_fetcher(access_token):
        calls["n"] += 1
        return profile_body()

    async def run():
        await get_broker_profile_summary("user-1", "tok", profile_fetcher=counting_fetcher, cache=cache, now=fake_now)
        now[0] = start + timedelta(seconds=broker_profile.PROFILE_TTL_SECONDS + 1)
        await get_broker_profile_summary("user-1", "tok", profile_fetcher=counting_fetcher, cache=cache, now=fake_now)

    import asyncio

    asyncio.run(run())
    assert calls["n"] == 2  # TTL expired → refetched


def test_manual_refresh_bypasses_cache():
    cache = BrokerProfileCache()
    calls = {"n": 0}

    async def counting_fetcher(access_token):
        calls["n"] += 1
        return profile_body()

    async def run():
        await get_broker_profile_summary("user-1", "tok", profile_fetcher=counting_fetcher, cache=cache)
        await get_broker_profile_summary("user-1", "tok", profile_fetcher=counting_fetcher, cache=cache, refresh=True)

    import asyncio

    asyncio.run(run())
    assert calls["n"] == 2  # refresh bypassed the cached entry


# ---- Endpoint: GET /paper/broker/profile --------------------------------------


def test_endpoint_requires_login(client):
    resp = client.get("/paper/broker/profile")
    assert resp.status_code == 401


def test_endpoint_returns_normalized_profile(client, logged_in):
    with patch(
        "app.services.upstox.get_broker_profile",
        new=AsyncMock(return_value=profile_body()),
    ):
        resp = client.get("/paper/broker/profile", headers=headers(logged_in))

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "available"
    assert body["source"] == "BROKER_REPORTED"
    assert body["broker"] == "UPSTOX"
    assert body["profile"]["user_name"] == "Shahid Ahmed"
    assert body["profile"]["user_id"] == "UCC12345"
    assert body["profile"]["account_type"] is None
    assert body["error"] is None


def test_endpoint_never_returns_secrets(client, logged_in):
    body = profile_body()
    body["data"]["access_token"] = "leaked-token"
    body["data"]["client_secret"] = "leaked-secret"
    with patch("app.services.upstox.get_broker_profile", new=AsyncMock(return_value=body)):
        resp = client.get("/paper/broker/profile", headers=headers(logged_in))

    assert resp.status_code == 200
    payload = str(resp.json())
    assert "leaked-token" not in payload
    assert "leaked-secret" not in payload
    for field in FORBIDDEN_FIELDS:
        assert field not in payload


def test_endpoint_user_isolation(client, logged_in):
    session_a = logged_in

    with patch(
        "app.services.upstox.get_broker_profile",
        new=AsyncMock(side_effect=lambda tok: profile_body(user_id=f"UCC-{tok}")),
    ):
        body_a = client.get("/paper/broker/profile", headers=headers(session_a)).json()
        # The token store is single-session: switching the active session
        # must NOT leak user A's cached profile to user B.
        session_b = token_store.set_token("tok-other")
        body_b = client.get("/paper/broker/profile", headers=headers(session_b)).json()

    assert body_a["profile"]["user_id"] == "UCC-tok-xyz"
    assert body_b["profile"]["user_id"] == "UCC-tok-other"
    # Same endpoint must not cross-contaminate cached profiles.
    assert body_a["profile"]["user_id"] != body_b["profile"]["user_id"]


def test_endpoint_cached_response_marks_cached_flag(client, logged_in):
    with patch(
        "app.services.upstox.get_broker_profile",
        new=AsyncMock(return_value=profile_body()),
    ):
        first = client.get("/paper/broker/profile", headers=headers(logged_in)).json()
        second = client.get("/paper/broker/profile", headers=headers(logged_in)).json()

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["generated_at"] == second["generated_at"]  # same verified-at time


def test_endpoint_refresh_bypasses_cache(client, logged_in):
    with patch(
        "app.services.upstox.get_broker_profile",
        new=AsyncMock(return_value=profile_body()),
    ):
        first = client.get("/paper/broker/profile", headers=headers(logged_in)).json()
        refreshed = client.get(
            "/paper/broker/profile", headers=headers(logged_in), params={"refresh": "true"}
        ).json()

    assert first["cached"] is False
    assert refreshed["cached"] is False  # manual refresh re-fetched from the broker
    assert refreshed["generated_at"] != first["generated_at"]


def test_endpoint_token_expired_returns_unavailable_contract(client, logged_in):
    with patch(
        "app.services.upstox.get_broker_profile",
        new=AsyncMock(side_effect=upstox_error(401)),
    ):
        resp = client.get("/paper/broker/profile", headers=headers(logged_in))

    assert resp.status_code == 200  # structured contract, never a crash
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["profile"] is None
    assert body["error"] == BROKER_TOKEN_EXPIRED
    assert body["message"]


def test_endpoint_rate_limited_returns_structured_error(client, logged_in):
    with patch(
        "app.services.upstox.get_broker_profile",
        new=AsyncMock(side_effect=upstox_error(429)),
    ):
        resp = client.get("/paper/broker/profile", headers=headers(logged_in))

    assert resp.status_code == 200
    assert resp.json()["error"] == BROKER_RATE_LIMITED
