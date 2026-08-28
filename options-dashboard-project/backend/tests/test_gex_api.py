"""Phase 7.6 — GEX snapshot API endpoint tests.

Tests cover:
  - Snapshot creation (POST)
  - Snapshot querying (GET list, GET latest, GET count)
  - Authentication
  - Idempotency / duplicate handling
  - Malformed snapshots
  - Timestamp ordering
  - Retention / query behavior
"""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, engine
from app.services import token_store
from tests.test_helpers import create_test_identity

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_snapshot(overrides=None):
    """Create a valid GEX snapshot payload."""
    base = {
        "symbol": "NIFTY",
        "expiry": "2026-08-28",
        "spot": 25500.0,
        "methodology": "GEX_STANDARD_V1",
        "signConvention": "NAIVE_DEALER_CONVENTION",
        "callGex": 125000000.0,
        "putGex": -98000000.0,
        "netGex": 27000000.0,
        "availabilityStatus": "available",
        "validStrikeCount": 20,
        "totalStrikeCount": 20,
        "chainAgeMs": 1200.0,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "strikeData": [
            {
                "strike": 25500,
                "callGamma": 0.002, "callOi": 1000, "callIv": 0.18,
                "callGex": 125000000.0,
                "putGamma": 0.003, "putOi": 800, "putIv": 0.20,
                "putGex": -98000000.0, "netGex": 27000000.0,
            }
        ],
        "expiryData": [
            {
                "expiry": "2026-08-28",
                "callGex": 125000000.0, "putGex": -98000000.0, "netGex": 27000000.0,
                "availabilityStatus": "available", "validStrikeCount": 20, "totalStrikeCount": 20,
            }
        ],
        "methodologyMetadata": {
            "gexVersion": "GEX_STANDARD_V1",
            "formula": "gamma * oi * spot^2 * 0.01",
            "oiUnit": "contracts",
            "signConvention": "NAIVE_DEALER_CONVENTION",
            "callSign": 1, "putSign": -1, "lotSizeFactorApplied": False,
        },
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    token_store.clear_token()
    yield
    Base.metadata.drop_all(bind=engine)
    token_store.clear_token()


def _auth():
    """Create a new session and return auth headers."""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        sid, uid = create_test_identity(db, "fake-token")
        db.commit()
    finally:
        db.close()
    return {"X-Session-Id": sid}


# ---------------------------------------------------------------------------
# POST /gex/snapshots
# ---------------------------------------------------------------------------

class TestCreateSnapshot:
    def test_create_valid_snapshot(self):
        resp = client.post("/gex/snapshots", json=_make_snapshot(), headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["id"] is not None
        assert data["duplicate"] is False

    def test_create_returns_id(self):
        resp = client.post("/gex/snapshots", json=_make_snapshot(), headers=_auth())
        assert resp.json()["id"] > 0

    def test_create_stores_all_fields(self):
        hdrs = _auth()
        resp = client.post("/gex/snapshots", json=_make_snapshot(), headers=hdrs)
        latest = client.get("/gex/snapshots/latest?symbol=NIFTY", headers=hdrs).json()
        assert latest is not None
        assert latest["symbol"] == "NIFTY"
        assert latest["spot"] == 25500.0
        assert latest["callGex"] == 125000000.0
        assert latest["netGex"] == 27000000.0
        assert len(latest["strikeData"]) == 1

    def test_create_without_auth(self):
        resp = client.post("/gex/snapshots", json=_make_snapshot())
        assert resp.status_code == 401

    def test_create_with_invalid_data(self):
        resp = client.post("/gex/snapshots", json={"symbol": ""}, headers=_auth())
        assert resp.status_code in (400, 422)

    def test_create_null_gex_values(self):
        snap = _make_snapshot({"callGex": None, "putGex": None, "netGex": None})
        resp = client.post("/gex/snapshots", json=snap, headers=_auth())
        assert resp.status_code == 200

    def test_create_with_sweep_data(self):
        snap = _make_snapshot({
            "sweepData": {
                "gammaFlipSpot": 25400.0,
                "gammaFlipDistancePct": 0.39,
                "gammaFlipDirection": "below",
                "callWallStrikes": [25600, 25700],
                "putWallStrikes": [25300, 25200],
                "sweepStatus": "available",
            }
        })
        hdrs = _auth()
        resp = client.post("/gex/snapshots", json=snap, headers=hdrs)
        assert resp.status_code == 200
        latest = client.get("/gex/snapshots/latest?symbol=NIFTY", headers=hdrs).json()
        assert latest["sweepData"] is not None
        assert latest["sweepData"]["gammaFlipSpot"] == 25400.0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_duplicate_within_60s_returns_existing(self):
        sid = _auth()["X-Session-Id"]
        hdrs = {"X-Session-Id": sid}
        snap = _make_snapshot({"capturedAt": "2026-08-22T09:00:00Z"})
        resp1 = client.post("/gex/snapshots", json=snap, headers=hdrs)
        id1 = resp1.json()["id"]
        resp2 = client.post("/gex/snapshots", json=snap, headers=hdrs)
        assert resp2.json()["duplicate"] is True
        assert resp2.json()["id"] == id1

    def test_different_timestamp_not_duplicate(self):
        s1 = _make_snapshot({"capturedAt": "2026-08-22T09:00:00Z"})
        s2 = _make_snapshot({"capturedAt": "2026-08-22T09:05:00Z"})
        r1 = client.post("/gex/snapshots", json=s1, headers=_auth())
        r2 = client.post("/gex/snapshots", json=s2, headers=_auth())
        assert r1.json()["duplicate"] is False
        assert r2.json()["duplicate"] is False
        assert r1.json()["id"] != r2.json()["id"]

    def test_different_symbol_not_duplicate(self):
        s1 = _make_snapshot({"symbol": "NIFTY", "capturedAt": "2026-08-22T09:00:00Z"})
        s2 = _make_snapshot({"symbol": "BANKNIFTY", "capturedAt": "2026-08-22T09:00:00Z"})
        r1 = client.post("/gex/snapshots", json=s1, headers=_auth())
        r2 = client.post("/gex/snapshots", json=s2, headers=_auth())
        assert r1.json()["duplicate"] is False
        assert r2.json()["duplicate"] is False


# ---------------------------------------------------------------------------
# GET /gex/snapshots
# ---------------------------------------------------------------------------

class TestListSnapshots:
    def test_empty_list(self):
        resp = client.get("/gex/snapshots?symbol=NIFTY", headers=_auth())
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_oldest_first(self):
        hdrs = _auth()
        for i in range(3):
            snap = _make_snapshot({
                "capturedAt": f"2026-08-22T09:0{i}:00Z",
                "netGex": 1000 * (i + 1),
            })
            client.post("/gex/snapshots", json=snap, headers=hdrs)

        resp = client.get("/gex/snapshots?symbol=NIFTY", headers=hdrs)
        snaps = resp.json()["snapshots"]
        assert len(snaps) == 3
        assert snaps[0]["capturedAt"] < snaps[1]["capturedAt"]

    def test_list_with_limit(self):
        hdrs = _auth()
        for i in range(5):
            snap = _make_snapshot({"capturedAt": f"2026-08-22T09:0{i}:00Z"})
            client.post("/gex/snapshots", json=snap, headers=hdrs)

        resp = client.get("/gex/snapshots?symbol=NIFTY&limit=2", headers=hdrs)
        assert resp.json()["count"] == 2

    def test_list_with_expiry_filter(self):
        hdrs = _auth()
        s1 = _make_snapshot({"expiry": "2026-08-28", "capturedAt": "2026-08-22T09:00:00Z"})
        s2 = _make_snapshot({"expiry": "2026-09-04", "capturedAt": "2026-08-22T09:00:00Z"})
        client.post("/gex/snapshots", json=s1, headers=hdrs)
        client.post("/gex/snapshots", json=s2, headers=hdrs)

        resp = client.get("/gex/snapshots?symbol=NIFTY&expiry=2026-08-28", headers=hdrs)
        assert resp.json()["count"] == 1
        assert resp.json()["snapshots"][0]["expiry"] == "2026-08-28"

    def test_list_with_since_filter(self):
        hdrs = _auth()
        s1 = _make_snapshot({"capturedAt": "2026-08-22T08:00:00Z"})
        s2 = _make_snapshot({"capturedAt": "2026-08-22T10:00:00Z"})
        client.post("/gex/snapshots", json=s1, headers=hdrs)
        client.post("/gex/snapshots", json=s2, headers=hdrs)

        resp = client.get("/gex/snapshots?symbol=NIFTY&since=2026-08-22T09:00:00Z", headers=hdrs)
        assert resp.json()["count"] == 1

    def test_list_without_auth(self):
        resp = client.get("/gex/snapshots?symbol=NIFTY")
        assert resp.status_code == 401

    def test_list_invalid_since(self):
        resp = client.get("/gex/snapshots?symbol=NIFTY&since=not-a-date", headers=_auth())
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /gex/snapshots/latest
# ---------------------------------------------------------------------------

class TestLatestSnapshot:
    def test_latest_empty(self):
        resp = client.get("/gex/snapshots/latest?symbol=NIFTY", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() is None

    def test_latest_returns_most_recent(self):
        hdrs = _auth()
        s1 = _make_snapshot({"capturedAt": "2026-08-22T09:00:00Z", "netGex": 1000})
        s2 = _make_snapshot({"capturedAt": "2026-08-22T09:05:00Z", "netGex": 2000})
        client.post("/gex/snapshots", json=s1, headers=hdrs)
        client.post("/gex/snapshots", json=s2, headers=hdrs)

        resp = client.get("/gex/snapshots/latest?symbol=NIFTY", headers=hdrs)
        assert resp.json()["netGex"] == 2000

    def test_latest_without_auth(self):
        resp = client.get("/gex/snapshots/latest?symbol=NIFTY")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /gex/snapshots/count
# ---------------------------------------------------------------------------

class TestSnapshotCount:
    def test_count_empty(self):
        resp = client.get("/gex/snapshots/count", headers=_auth())
        assert resp.json()["count"] == 0

    def test_count_after_inserts(self):
        hdrs = _auth()
        for i in range(3):
            snap = _make_snapshot({"capturedAt": f"2026-08-22T09:0{i}:00Z"})
            client.post("/gex/snapshots", json=snap, headers=hdrs)
        resp = client.get("/gex/snapshots/count?symbol=NIFTY", headers=hdrs)
        assert resp.json()["count"] == 3


# ---------------------------------------------------------------------------
# Malformed snapshots
# ---------------------------------------------------------------------------

class TestMalformedSnapshots:
    def test_missing_spot(self):
        snap = _make_snapshot()
        del snap["spot"]
        resp = client.post("/gex/snapshots", json=snap, headers=_auth())
        assert resp.status_code in (400, 422)

    def test_invalid_spot(self):
        resp = client.post("/gex/snapshots", json=_make_snapshot({"spot": -100}), headers=_auth())
        assert resp.status_code == 400

    def test_empty_body(self):
        resp = client.post("/gex/snapshots", json={}, headers=_auth())
        assert resp.status_code in (400, 422)
