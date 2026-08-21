"""Phase 7.1 — Trade Detail + Strategy Detail Drill-Down tests."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import PaperOrder, Position, StrategyExecution
from app.services import token_store
from fastapi.testclient import TestClient


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def logged_in(client):
    return token_store.set_token("tok-phase71")


_strike_counter = 25000


def _create_execution(db_session, user_id, exec_id, strategy_tag="Bull Call Spread",
                       status="FILLED", realized_pnl=50.0, is_open=False):
    """Helper to create a strategy execution with positions and orders.

    Each execution gets a unique strike to avoid Position unique-constraint violations.
    """
    global _strike_counter
    _strike_counter += 1
    strike = float(_strike_counter)

    ex = StrategyExecution(
        user_id=user_id,
        execution_id=exec_id,
        client_order_id=f"client-{exec_id}",
        strategy_tag=strategy_tag,
        symbol="NIFTY",
        status=status,
        entry_net=100.0,
        realized_pnl=realized_pnl if not is_open else None,
        entry_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        exit_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc) if not is_open else None,
        tags='["test-tag"]' if not is_open else None,
        notes="Test note" if not is_open else None,
    )
    db_session.add(ex)
    db_session.flush()

    pos_status = "closed" if not is_open else "open"
    pos = Position(
        user_id=user_id,
        symbol="NIFTY",
        expiry="2026-08-07",
        strike=strike,
        option_type="call",
        net_quantity=0 if not is_open else 1,
        average_entry_price=100.0,
        lot_size=50,
        realized_pnl=realized_pnl if not is_open else 0.0,
        status=pos_status,
        strategy_execution_id=exec_id,
        opened_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc) if not is_open else None,
    )
    db_session.add(pos)

    entry_order = PaperOrder(
        user_id=user_id,
        client_order_id=f"entry-{exec_id}",
        execution_id=exec_id,
        kind="entry",
        symbol="NIFTY",
        expiry="2026-08-07",
        strike=strike,
        option_type="call",
        action="buy",
        quantity=1,
        lot_size=50,
        status="FILLED",
        filled_quantity=1,
        fill_price=100.0,
    )
    db_session.add(entry_order)

    if not is_open:
        exit_order = PaperOrder(
            user_id=user_id,
            client_order_id=f"exit-{exec_id}",
            execution_id=exec_id,
            kind="exit",
            symbol="NIFTY",
            expiry="2026-08-07",
            strike=strike,
            option_type="call",
            action="sell",
            quantity=1,
            lot_size=50,
            status="FILLED",
            filled_quantity=1,
            fill_price=101.0,
            realized_pnl=realized_pnl,
        )
        db_session.add(exit_order)

    db_session.commit()
    return exec_id


# ---- Trade Detail Tests ----


class TestTradeDetail:
    def test_retrieve_own_execution(self, client, logged_in, db_session):
        exec_id = _create_execution(db_session, logged_in, "td-001")
        resp = client.get(f"/paper/analytics/trades/{exec_id}", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_id"] == exec_id
        assert data["strategy"] == "Bull Call Spread"
        assert data["symbol"] == "NIFTY"
        assert data["result"] == "WIN"
        assert data["realized_pnl"] == 50.0
        assert len(data["legs"]) == 1
        assert data["legs"][0]["action"] == "buy"
        assert data["legs"][0]["entry_price"] == 100.0
        assert data["legs"][0]["exit_price"] == 101.0

    def test_unauthenticated(self, client, db_session):
        exec_id = _create_execution(db_session, "anyone", "td-002")
        resp = client.get(f"/paper/analytics/trades/{exec_id}")
        assert resp.status_code == 401

    def test_nonexistent_execution(self, client, logged_in):
        resp = client.get("/paper/analytics/trades/nonexistent", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 404

    def test_another_user_execution(self, client, db_session):
        """User A's execution is not visible to User B."""
        user_a = token_store.set_token("user-a-td")
        user_b = token_store.set_token("user-b-td")
        exec_id = _create_execution(db_session, user_a, "td-003")
        resp = client.get(f"/paper/analytics/trades/{exec_id}", headers={"X-Session-Id": user_b})
        assert resp.status_code == 404

    def test_tags_and_notes_returned(self, client, logged_in, db_session):
        exec_id = _create_execution(db_session, logged_in, "td-004")
        resp = client.get(f"/paper/analytics/trades/{exec_id}", headers={"X-Session-Id": logged_in})
        data = resp.json()
        assert data["tags"] == ["test-tag"]
        assert data["notes"] == "Test note"

    def test_open_execution(self, client, logged_in, db_session):
        exec_id = _create_execution(db_session, logged_in, "td-005", is_open=True)
        resp = client.get(f"/paper/analytics/trades/{exec_id}", headers={"X-Session-Id": logged_in})
        data = resp.json()
        assert data["result"] == "OPEN"
        assert data["status"] == "FILLED"
        assert data["exit_at"] is None

    def test_breakeven_classification(self, client, logged_in, db_session):
        exec_id = _create_execution(db_session, logged_in, "td-006", realized_pnl=0.0)
        resp = client.get(f"/paper/analytics/trades/{exec_id}", headers={"X-Session-Id": logged_in})
        assert resp.json()["result"] == "BREAKEVEN"

    def test_loss_classification(self, client, logged_in, db_session):
        exec_id = _create_execution(db_session, logged_in, "td-007", realized_pnl=-30.0)
        resp = client.get(f"/paper/analytics/trades/{exec_id}", headers={"X-Session-Id": logged_in})
        assert resp.json()["result"] == "LOSS"

    def test_execution_metadata(self, client, logged_in, db_session):
        import json
        exec_id = _create_execution(db_session, logged_in, "td-008")
        # Manually set metadata
        ex = db_session.query(StrategyExecution).filter_by(execution_id=exec_id).first()
        ex.execution_metadata = json.dumps({"formula_version": 2, "preview": {}})
        db_session.commit()
        resp = client.get(f"/paper/analytics/trades/{exec_id}", headers={"X-Session-Id": logged_in})
        assert resp.json()["execution_metadata"]["formula_version"] == 2

    def test_duration_calculated(self, client, logged_in, db_session):
        exec_id = _create_execution(db_session, logged_in, "td-009")
        resp = client.get(f"/paper/analytics/trades/{exec_id}", headers={"X-Session-Id": logged_in})
        data = resp.json()
        assert data["duration_seconds"] is not None
        assert data["duration_seconds"] > 0
        assert data["duration_label"] is not None


# ---- Strategy Detail Tests ----


class TestStrategyDetail:
    def test_retrieve_own_strategy(self, client, logged_in, db_session):
        _create_execution(db_session, logged_in, "sd-001", strategy_tag="Iron Condor")
        _create_execution(db_session, logged_in, "sd-002", strategy_tag="Iron Condor",
                         realized_pnl=-20.0)
        resp = client.get("/paper/analytics/strategies/Iron Condor", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "Iron Condor"
        assert data["total_executions"] == 2
        assert data["closed_executions"] == 2
        assert data["winning_trades"] == 1
        assert data["losing_trades"] == 1
        assert data["net_realized_pnl"] == 30.0
        assert len(data["trades"]) == 2

    def test_unauthenticated(self, client, db_session):
        resp = client.get("/paper/analytics/strategies/Custom")
        assert resp.status_code == 401

    def test_nonexistent_strategy(self, client, logged_in):
        resp = client.get("/paper/analytics/strategies/NonExistent", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 404

    def test_another_user_strategy_isolated(self, client, db_session):
        """User A's strategy is not visible to User B."""
        user_a = token_store.set_token("user-a-sd")
        user_b = token_store.set_token("user-b-sd")
        _create_execution(db_session, user_a, "sd-003", strategy_tag="MyStrategy")
        resp = client.get("/paper/analytics/strategies/MyStrategy", headers={"X-Session-Id": user_b})
        assert resp.status_code == 404

    def test_strategy_metrics_correct(self, client, logged_in, db_session):
        _create_execution(db_session, logged_in, "sd-004", strategy_tag="Bear Spread", realized_pnl=100.0)
        _create_execution(db_session, logged_in, "sd-005", strategy_tag="Bear Spread", realized_pnl=-40.0)
        _create_execution(db_session, logged_in, "sd-006", strategy_tag="Bear Spread", realized_pnl=0.0)
        resp = client.get("/paper/analytics/strategies/Bear Spread", headers={"X-Session-Id": logged_in})
        data = resp.json()
        assert data["win_rate"] is not None
        assert data["profit_factor"] is not None
        assert data["expectancy"] is not None
        assert data["average_winner"] == 100.0
        assert data["average_loser"] == -40.0
        assert data["largest_winner"] == 100.0
        assert data["largest_loser"] == -40.0
        assert data["breakeven_trades"] == 1

    def test_open_executions_counted(self, client, logged_in, db_session):
        _create_execution(db_session, logged_in, "sd-007", strategy_tag="Open Strat", is_open=True)
        _create_execution(db_session, logged_in, "sd-008", strategy_tag="Open Strat",
                         realized_pnl=25.0)
        resp = client.get("/paper/analytics/strategies/Open Strat", headers={"X-Session-Id": logged_in})
        data = resp.json()
        assert data["open_executions"] == 1
        assert data["closed_executions"] == 1
        assert data["total_executions"] == 2

    def test_trade_list_includes_tags(self, client, logged_in, db_session):
        _create_execution(db_session, logged_in, "sd-009", strategy_tag="Tagged Strat")
        resp = client.get("/paper/analytics/strategies/Tagged Strat", headers={"X-Session-Id": logged_in})
        trades = resp.json()["trades"]
        assert len(trades) == 1
        assert trades[0]["tags"] == ["test-tag"]

    def test_empty_strategy_after_clearing(self, client, logged_in, db_session):
        """Strategy with no executions returns 404."""
        resp = client.get("/paper/analytics/strategies/Empty", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 404


class TestBackwardCompatibility:
    def test_analytics_still_works(self, client, logged_in, db_session):
        _create_execution(db_session, logged_in, "bc-001")
        resp = client.get("/paper/analytics", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 200
        data = resp.json()
        assert "journal" in data
        assert "performance" in data
        assert "equity_curve" in data
        assert "strategies" in data

    def test_legacy_journal_still_works(self, client, logged_in):
        resp = client.get("/paper/journal", headers={"X-Session-Id": logged_in})
        assert resp.status_code == 200
        assert "account" in resp.json()
        assert "trades" in resp.json()
