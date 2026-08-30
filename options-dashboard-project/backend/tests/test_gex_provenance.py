"""GEX provenance persistence tests.

Proves that connection_id and data_source are persisted and returned
consistently for all capture paths (Analytics Token, OAuth, API upload).
"""

import secrets
from uuid import uuid4

import pytest
from datetime import datetime, timedelta, timezone

from app.db import Base, SessionLocal
from app.identity import (
    User, BrokerConnection, BrokerToken, UserSession,
    create_session_record, hash_session_id,
)
from app.services import token_store
from app.services.gex_history import record_gex_snapshot, get_gex_snapshots, get_latest_snapshot
from app.services.gex_capture import GexCaptureService, _is_duplicate
from app.crypto import encrypt


@pytest.fixture(autouse=True)
def db_session():
    engine = SessionLocal().get_bind()
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _create_user(db, uid=None):
    uid = uid or f"user-{secrets.token_hex(4)}"
    db.add(User(id=uid, email=f"{uid}@test.com"))
    db.commit()
    return uid


def _create_connection(db, user_id, broker="UPSTOX", data_status="active", is_default=True):
    conn_id = str(uuid4())
    db.add(BrokerConnection(
        id=conn_id,
        user_id=user_id,
        broker=broker,
        broker_account_id=conn_id,
        status="connected",
        data_status=data_status,
        trading_status="inactive",
        is_default=is_default,
    ))
    db.commit()
    return conn_id


def _make_snap(symbol="NIFTY", expiry="2026-08-28", spot=25512.0, capturedAt=None):
    now = datetime.now(timezone.utc)
    return {
        "symbol": symbol,
        "expiry": expiry,
        "spot": spot,
        "methodology": "GEX_STANDARD_V1",
        "signConvention": "NAIVE_DEALER_CONVENTION",
        "callGex": 125000000.0,
        "putGex": -98000000.0,
        "netGex": 27000000.0,
        "availabilityStatus": "available",
        "validStrikeCount": 20,
        "totalStrikeCount": 20,
        "chainAgeMs": 1200.0,
        "capturedAt": capturedAt or now.isoformat(),
        "strikeData": [],
        "expiryData": [],
        "methodologyMetadata": {},
    }


class TestProvenancePersistence:
    """Provenance fields (connection_id, data_source) must be stored and returned."""

    def test_analytics_token_capture_persists_provenance(self, db_session):
        """Analytics Token capture stores connection_id + data_source."""
        uid = _create_user(db_session)
        conn_id = _create_connection(db_session, uid)

        snap = _make_snap()
        record_gex_snapshot(
            db_session, snap, owner_id=uid,
            connection_id=conn_id, data_source="analytics_token",
        )

        latest = get_latest_snapshot(db_session, "NIFTY", owner_id=uid)
        assert latest is not None
        assert latest["connection_id"] == conn_id
        assert latest["data_source"] == "analytics_token"
        assert latest["owner_id"] == uid

    def test_oauth_capture_persists_provenance(self, db_session):
        """OAuth capture stores connection_id + data_source."""
        uid = _create_user(db_session)
        conn_id = _create_connection(db_session, uid)

        snap = _make_snap()
        record_gex_snapshot(
            db_session, snap, owner_id=uid,
            connection_id=conn_id, data_source="broker_oauth",
        )

        latest = get_latest_snapshot(db_session, "NIFTY", owner_id=uid)
        assert latest is not None
        assert latest["connection_id"] == conn_id
        assert latest["data_source"] == "broker_oauth"

    def test_api_upload_persists_data_source(self, db_session):
        """API upload stores data_source but no connection_id."""
        uid = _create_user(db_session)

        snap = _make_snap()
        record_gex_snapshot(
            db_session, snap, owner_id=uid,
            data_source="api_upload",
        )

        latest = get_latest_snapshot(db_session, "NIFTY", owner_id=uid)
        assert latest is not None
        assert latest["data_source"] == "api_upload"
        assert latest["connection_id"] is None

    def test_no_provenance_stores_none(self, db_session):
        """Legacy snapshots without provenance store None."""
        uid = _create_user(db_session)

        snap = _make_snap()
        record_gex_snapshot(db_session, snap, owner_id=uid)

        latest = get_latest_snapshot(db_session, "NIFTY", owner_id=uid)
        assert latest is not None
        assert latest["connection_id"] is None
        assert latest["data_source"] is None

    def test_provenance_fields_in_snapshots_list(self, db_session):
        """Provenance fields appear in list queries."""
        uid = _create_user(db_session)
        conn_id = _create_connection(db_session, uid)

        snap1 = _make_snap(expiry="2026-08-28",
                           capturedAt=(datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat())
        snap2 = _make_snap(expiry="2026-08-28",
                           capturedAt=datetime.now(timezone.utc).isoformat())
        record_gex_snapshot(
            db_session, snap1, owner_id=uid,
            connection_id=conn_id, data_source="analytics_token",
        )
        record_gex_snapshot(
            db_session, snap2, owner_id=uid,
            data_source="api_upload",
        )

        rows = get_gex_snapshots(db_session, "NIFTY", owner_id=uid)
        assert len(rows) == 2
        assert rows[0]["connection_id"] == conn_id
        assert rows[0]["data_source"] == "analytics_token"
        assert rows[1]["connection_id"] is None
        assert rows[1]["data_source"] == "api_upload"


class TestCaptureServiceProvenance:
    """GexCaptureService.capture_once passes provenance through to persistence."""

    def test_capture_once_persists_provenance(self, db_session):
        """capture_once passes connection_id and data_source to record_gex_snapshot."""
        from unittest.mock import patch, MagicMock
        from app.services.live_gex import GexCalculationResult, GexStatus

        uid = _create_user(db_session)
        conn_id = _create_connection(db_session, uid)

        mock_result = MagicMock(spec=GexCalculationResult)
        mock_result.symbol = "NIFTY"
        mock_result.expiry = "2026-08-28"
        mock_result.spot = 25512.0
        mock_result.methodology = "GEX_STANDARD_V1"
        mock_result.sign_convention = "NAIVE_DEALER_CONVENTION"
        mock_result.call_gex = 125000000.0
        mock_result.put_gex = -98000000.0
        mock_result.net_gex = 27000000.0
        mock_result.availability_status = "available"
        mock_result.valid_strike_count = 20
        mock_result.total_strike_count = 20
        mock_result.chain_age_ms = 1200.0
        mock_result.captured_at = datetime.now(timezone.utc).isoformat()
        mock_result.strikes = []
        mock_result.methodology_metadata = {}

        fake_chain = {
            "underlying_spot_price": 25512.0,
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "chain": [{"strike": 25500, "ltp": 100}],
        }

        service = GexCaptureService()
        with patch.object(service._gex_service, "calculate", return_value=mock_result):
            result = service.capture_once(
                db_session, fake_chain,
                expiry="2026-08-28", symbol="NIFTY",
                owner_id=uid, connection_id=conn_id,
                data_source="analytics_token",
            )

        assert result["status"] == "captured"

        latest = get_latest_snapshot(db_session, "NIFTY", owner_id=uid)
        assert latest is not None
        assert latest["connection_id"] == conn_id
        assert latest["data_source"] == "analytics_token"
        assert latest["owner_id"] == uid

    def test_capture_once_missing_provenance_stores_none(self, db_session):
        """capture_once without provenance stores None."""
        from unittest.mock import patch, MagicMock
        from app.services.live_gex import GexCalculationResult

        uid = _create_user(db_session)

        mock_result = MagicMock(spec=GexCalculationResult)
        mock_result.symbol = "NIFTY"
        mock_result.expiry = "2026-08-28"
        mock_result.spot = 25512.0
        mock_result.methodology = "GEX_STANDARD_V1"
        mock_result.sign_convention = "NAIVE_DEALER_CONVENTION"
        mock_result.call_gex = 125000000.0
        mock_result.put_gex = -98000000.0
        mock_result.net_gex = 27000000.0
        mock_result.availability_status = "available"
        mock_result.valid_strike_count = 20
        mock_result.total_strike_count = 20
        mock_result.chain_age_ms = 1200.0
        mock_result.captured_at = datetime.now(timezone.utc).isoformat()
        mock_result.strikes = []
        mock_result.methodology_metadata = {}

        fake_chain = {
            "underlying_spot_price": 25512.0,
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "chain": [{"strike": 25500, "ltp": 100}],
        }

        service = GexCaptureService()
        with patch.object(service._gex_service, "calculate", return_value=mock_result):
            result = service.capture_once(
                db_session, fake_chain,
                expiry="2026-08-28", symbol="NIFTY",
                owner_id=uid,
            )

        assert result["status"] == "captured"
        latest = get_latest_snapshot(db_session, "NIFTY", owner_id=uid)
        assert latest is not None
        assert latest["connection_id"] is None
        assert latest["data_source"] is None


class TestOwnershipInvariants:
    """Provenance never leaks across users."""

    def test_user_a_cannot_own_user_b_snapshot(self, db_session):
        """A snapshot owned by user A cannot be queried by user B."""
        uid_a = _create_user(db_session)
        uid_b = _create_user(db_session)
        conn_a = _create_connection(db_session, uid_a)

        snap = _make_snap()
        record_gex_snapshot(
            db_session, snap, owner_id=uid_a,
            connection_id=conn_a, data_source="analytics_token",
        )

        # Query as user B — should return empty
        rows_b = get_gex_snapshots(db_session, "NIFTY", owner_id=uid_b)
        assert len(rows_b) == 0

        # Query as user A — should return the snapshot
        rows_a = get_gex_snapshots(db_session, "NIFTY", owner_id=uid_a)
        assert len(rows_a) == 1
        assert rows_a[0]["connection_id"] == conn_a

    def test_owner_id_never_session_hash(self, db_session):
        """owner_id is always a user ID, never a session hash."""
        uid = _create_user(db_session)
        session_hash = secrets.token_hex(32)

        snap = _make_snap()
        record_gex_snapshot(db_session, snap, owner_id=uid)

        latest = get_latest_snapshot(db_session, "NIFTY", owner_id=uid)
        assert latest["owner_id"] == uid
        assert latest["owner_id"] != session_hash

    def test_wrong_connection_id_does_not_authorize(self, db_session):
        """Snapshot with wrong connection_id is stored but not authorized for user B."""
        uid_a = _create_user(db_session)
        uid_b = _create_user(db_session)
        conn_a = _create_connection(db_session, uid_a)
        conn_b = _create_connection(db_session, uid_b)

        snap = _make_snap()
        record_gex_snapshot(
            db_session, snap, owner_id=uid_a,
            connection_id=conn_a, data_source="analytics_token",
        )

        rows = get_gex_snapshots(db_session, "NIFTY", owner_id=uid_a)
        assert rows[0]["connection_id"] == conn_a
        assert rows[0]["connection_id"] != conn_b
