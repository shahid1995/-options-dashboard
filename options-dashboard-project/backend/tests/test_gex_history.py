"""Tests for the Phase 7.3 GEX-snapshot persistence repository."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.services import gex_history


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _snap(**overrides):
    """One valid GEX snapshot with sensible defaults."""
    base = {
        "symbol": "NIFTY",
        "expiry": "2026-08-28",
        "spot": 25512.0,
        "methodology": "GEX_STANDARD_V1",
        "signConvention": "NAIVE_DEALER_CONVENTION",
        "callGex": 125000000.0,
        "putGex": -98000000.0,
        "netGex": 27000000.0,
        "availabilityStatus": "available",
        "validStrikeCount": 20,
        "totalStrikeCount": 20,
        "chainAgeMs": 1200.0,
        "capturedAt": "2026-08-22T09:00:00+00:00",
        "strikeData": [
            {
                "strike": 25500,
                "callGamma": 0.0025,
                "callOi": 5000,
                "callIv": 0.1824,
                "callGex": 79687500.0,
                "putGamma": 0.0022,
                "putOi": 4500,
                "putIv": 0.1910,
                "putGex": -56430937.5,
                "netGex": 23256562.5,
                "status": "available",
            }
        ],
        "expiryData": [
            {
                "expiry": "2026-08-28",
                "callGex": 125000000.0,
                "putGex": -98000000.0,
                "netGex": 27000000.0,
                "availabilityStatus": "available",
                "validStrikeCount": 20,
                "totalStrikeCount": 20,
            }
        ],
        "methodologyMetadata": {
            "gexVersion": "GEX_STANDARD_V1",
            "formula": "gamma * oi * spot^2 * 0.01",
            "oiUnit": "contracts",
        },
    }
    base.update(overrides)
    return base


# ---- Record + query roundtrip ------------------------------------------------


def test_record_and_query_roundtrip(db_session):
    assert gex_history.record_gex_snapshot(db_session, _snap()) == 1
    rows = gex_history.get_gex_snapshots(db_session, "NIFTY")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NIFTY"
    assert rows[0]["spot"] == 25512.0
    assert rows[0]["callGex"] == 125000000.0
    assert rows[0]["putGex"] == -98000000.0
    assert rows[0]["netGex"] == 27000000.0
    assert rows[0]["availabilityStatus"] == "available"
    assert rows[0]["expiry"] == "2026-08-28"
    assert len(rows[0]["strikeData"]) == 1
    assert rows[0]["strikeData"][0]["strike"] == 25500
    assert rows[0]["strikeData"][0]["callGamma"] == 0.0025
    assert rows[0]["strikeData"][0]["callOi"] == 5000
    assert rows[0]["strikeData"][0]["callIv"] == 0.1824
    assert len(rows[0]["expiryData"]) == 1
    assert rows[0]["methodologyMetadata"]["formula"] == "gamma * oi * spot^2 * 0.01"
    assert rows[0]["methodologyMetadata"]["oiUnit"] == "contracts"


# ---- Query filters -----------------------------------------------------------


def test_query_filters_by_expiry(db_session):
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:00:00+00:00"))
    gex_history.record_gex_snapshot(
        db_session, _snap(expiry="2026-09-04", capturedAt="2026-08-22T09:05:00+00:00")
    )
    assert len(gex_history.get_gex_snapshots(db_session, "NIFTY")) == 2
    near = gex_history.get_gex_snapshots(db_session, "NIFTY", expiry="2026-08-28")
    assert len(near) == 1 and near[0]["expiry"] == "2026-08-28"


def test_query_returns_oldest_first(db_session):
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:10:00+00:00"))
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:00:00+00:00"))
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:05:00+00:00"))
    rows = gex_history.get_gex_snapshots(db_session, "NIFTY")
    times = [r["capturedAt"] for r in rows]
    assert times == sorted(times)


def test_query_since_filter(db_session):
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:00:00+00:00"))
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:10:00+00:00"))
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:20:00+00:00"))
    since = datetime.fromisoformat("2026-08-22T09:05:00+00:00")
    rows = gex_history.get_gex_snapshots(db_session, "NIFTY", since=since)
    assert len(rows) == 2
    # SQLite strips timezone; compare as naive datetimes
    naive_since = since.replace(tzinfo=None)
    assert all(
        datetime.fromisoformat(r["capturedAt"]).replace(tzinfo=None) >= naive_since
        for r in rows
    )


def test_query_limit(db_session):
    for i in range(5):
        gex_history.record_gex_snapshot(
            db_session, _snap(capturedAt=f"2026-08-22T09:0{i}:00+00:00")
        )
    rows = gex_history.get_gex_snapshots(db_session, "NIFTY", limit=3)
    assert len(rows) == 3


# ---- Invalid inputs are skipped ---------------------------------------------


def test_invalid_spot_skipped(db_session):
    n = gex_history.record_gex_snapshot(db_session, _snap(spot=0))
    assert n == 0
    n = gex_history.record_gex_snapshot(db_session, _snap(spot=-100))
    assert n == 0
    n = gex_history.record_gex_snapshot(db_session, _snap(spot=None))
    assert n == 0


def test_invalid_status_skipped(db_session):
    n = gex_history.record_gex_snapshot(db_session, _snap(availabilityStatus="bogus"))
    assert n == 0
    assert gex_history.count_gex_snapshots(db_session, "NIFTY") == 0


def test_missing_symbol_skipped(db_session):
    n = gex_history.record_gex_snapshot(db_session, _snap(symbol=""))
    assert n == 0


def test_missing_expiry_skipped(db_session):
    n = gex_history.record_gex_snapshot(db_session, _snap(expiry=None))
    assert n == 0


def test_empty_input_records_nothing(db_session):
    assert gex_history.record_gex_snapshot(db_session, {}) == 0
    assert gex_history.record_gex_snapshot(db_session, None) == 0
    assert gex_history.count_gex_snapshots(db_session, "NIFTY") == 0


def test_null_gex_values_are_stored_as_null(db_session):
    gex_history.record_gex_snapshot(
        db_session,
        _snap(callGex=None, putGex=None, netGex=None, availabilityStatus="unavailable"),
    )
    rows = gex_history.get_gex_snapshots(db_session, "NIFTY")
    assert len(rows) == 1
    assert rows[0]["callGex"] is None
    assert rows[0]["putGex"] is None
    assert rows[0]["netGex"] is None


# ---- Prune -------------------------------------------------------------------


def test_prune_removes_old_snapshots_only(db_session):
    now = datetime.now(timezone.utc)
    gex_history.record_gex_snapshot(
        db_session, _snap(capturedAt=(now - timedelta(days=200)).isoformat())
    )
    gex_history.record_gex_snapshot(
        db_session, _snap(capturedAt=(now - timedelta(days=10)).isoformat())
    )
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt=now.isoformat()))
    assert gex_history.prune_gex_snapshots(db_session, retention_days=90) == 1
    rows = gex_history.get_gex_snapshots(db_session, "NIFTY")
    assert len(rows) == 2


# ---- Count -------------------------------------------------------------------


def test_count_gex_snapshots(db_session):
    assert gex_history.count_gex_snapshots(db_session, "NIFTY") == 0
    gex_history.record_gex_snapshot(db_session, _snap())
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:05:00+00:00"))
    assert gex_history.count_gex_snapshots(db_session, "NIFTY") == 2
    assert gex_history.count_gex_snapshots(db_session, "BANKNIFTY") == 0


# ---- Latest snapshot ---------------------------------------------------------


def test_latest_snapshot(db_session):
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:00:00+00:00"))
    gex_history.record_gex_snapshot(db_session, _snap(capturedAt="2026-08-22T09:10:00+00:00"))
    latest = gex_history.get_latest_snapshot(db_session, "NIFTY")
    assert latest is not None
    # SQLite stores naive datetimes (no timezone offset)
    assert latest["capturedAt"].startswith("2026-08-22T09:10:00")


def test_latest_snapshot_empty(db_session):
    assert gex_history.get_latest_snapshot(db_session, "NIFTY") is None


# ---- Multi-symbol isolation --------------------------------------------------


def test_multi_symbol_isolation(db_session):
    gex_history.record_gex_snapshot(db_session, _snap(symbol="NIFTY"))
    gex_history.record_gex_snapshot(db_session, _snap(symbol="BANKNIFTY"))
    assert len(gex_history.get_gex_snapshots(db_session, "NIFTY")) == 1
    assert len(gex_history.get_gex_snapshots(db_session, "BANKNIFTY")) == 1
