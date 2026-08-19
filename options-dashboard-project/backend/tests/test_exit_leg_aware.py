"""Tests for Phase 6.6.5 — Leg-Aware Exit Execution + Exit Preview.

Proves:
- exit_position() uses exit_side when provided (not derived from net_quantity)
- maintain_exposure_on_exit() targets specific exposure when target_exposure_id given
- BUY CE → SELL CE, SELL CE → BUY CE, BUY PE → SELL PE, SELL PE → BUY PE
- Shared-instrument strategy isolation (Strategy A vs B)
- Preview endpoint returns targets without mutation
- Stale target protection
- Idempotency replay
- Quantity safety
- Authentication/user isolation
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Position, StrategyExecution, StrategyLegExposure, PaperOrder, PaperAccount,
)
from app.services import token_store
from app.services.leg_exposure import (
    maintain_exposure_on_exit, exposures_for_position, reconcile_position_exposures,
)
from app.services.paper_execution import (
    exit_position, ExitRequestIn, PaperExecutionError,
    execute_strategy, round_option_price,
)

LOT = 65
EXPIRY = "2026-08-21"


@pytest.fixture()
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


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _login():
    yield
    token_store.clear_token()


@pytest.fixture()
def logged_in(client):
    return token_store.set_token("tok-exit-test")


HDR = lambda tok: {"X-Session-Id": tok}


# ---- Helpers ----

def _account(db, user_id):
    acc = PaperAccount(user_id=user_id, starting_capital=500000)
    db.add(acc)
    db.flush()
    return acc


def _position(db, user_id, symbol="NIFTY", expiry=EXPIRY, strike=25000.0,
              option_type="call", net_quantity=2, lot_size=LOT,
              average_entry_price=150.0, status="open", strategy_execution_id=None):
    pos = Position(
        user_id=user_id, symbol=symbol, expiry=expiry, strike=strike,
        option_type=option_type, net_quantity=net_quantity, lot_size=lot_size,
        average_entry_price=average_entry_price, realized_pnl=0.0,
        status=status, strategy_execution_id=strategy_execution_id,
    )
    db.add(pos)
    db.flush()
    return pos


def _execution(db, user_id, execution_id="exec-1", strategy_tag="Bull Call"):
    se = StrategyExecution(
        user_id=user_id, execution_id=execution_id,
        client_order_id=f"coid-{execution_id}",
        strategy_tag=strategy_tag, symbol="NIFTY", status="FILLED",
        entry_net=0.0,
    )
    db.add(se)
    db.flush()
    return se


_exp_counter = {"n": 0}

def _exposure(db, user_id, execution_id, position_id, order_id=None,
              symbol="NIFTY", expiry=EXPIRY, strike=25000.0,
              option_type="call", action="buy", original_quantity=2,
              remaining_quantity=2, status="open"):
    _exp_counter["n"] += 1
    if order_id is None:
        order_id = _exp_counter["n"]
    exp = StrategyLegExposure(
        user_id=user_id, execution_id=execution_id, position_id=position_id,
        order_id=order_id or 0, symbol=symbol, expiry=expiry, strike=strike,
        option_type=option_type, action=action,
        original_quantity=original_quantity,
        remaining_quantity=remaining_quantity, status=status,
    )
    db.add(exp)
    db.flush()
    return exp


def _exit_request(client_order_id="exit-test-001", quantity=None):
    return ExitRequestIn(client_order_id=client_order_id, quantity=quantity)


# ===================================================================
# TEST GROUP 1: Leg-aware exit_side override
# ===================================================================

def test_exit_position_uses_exit_side_over_net_quantity(db_session, logged_in):
    """exit_position() uses exit_side parameter when provided."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2)  # LONG position

    # Exit with exit_side="sell" (matching LONG position — same as auto-derived)
    result = exit_position(
        uid, pos.id, _exit_request("exit-sell-001"), db_session,
        fill_price=180.0, exit_side="sell",
    )
    assert result.order.action == "sell"
    assert result.order.filled_quantity == 2

    # Verify position is closed
    db_session.refresh(pos)
    assert pos.net_quantity == 0
    assert pos.status == "closed"


def test_exit_position_with_buy_side_on_long_position(db_session, logged_in):
    """exit_position() with exit_side='buy' on a LONG position — forces BUY."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2)  # LONG

    # Exit with exit_side="buy" — this is for exiting a SELL exposure
    # on a net-long position. The fill should be a BUY.
    result = exit_position(
        uid, pos.id, _exit_request("exit-buy-001"), db_session,
        fill_price=180.0, exit_side="buy",
    )
    assert result.order.action == "buy"
    assert result.order.filled_quantity == 2


def test_exit_position_fallback_to_net_quantity_when_no_exit_side(db_session, logged_in):
    """When exit_side is None, falls back to net_quantity derivation."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2)  # LONG

    result = exit_position(
        uid, pos.id, _exit_request("exit-auto-001"), db_session,
        fill_price=180.0,  # no exit_side
    )
    assert result.order.action == "sell"  # derived from LONG position


# ===================================================================
# TEST GROUP 2: Targeted exposure allocation
# ===================================================================

def test_maintain_exposure_targeted_specific_exposure(db_session, logged_in):
    """maintain_exposure_on_exit with target_exposure_id reduces THAT exposure."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=7)
    exp_a = _exposure(db_session, uid, "exec-a", pos.id, remaining_quantity=2, action="buy")
    exp_b = _exposure(db_session, uid, "exec-b", pos.id, remaining_quantity=5, action="buy")

    now = datetime.now(timezone.utc)
    result = maintain_exposure_on_exit(
        db_session, uid, pos, prior_net_quantity=7, quantity=5, now=now,
        target_exposure_id=exp_b.id,
    )
    assert result is True

    db_session.refresh(exp_a)
    db_session.refresh(exp_b)
    assert exp_a.remaining_quantity == 2  # untouched
    assert exp_b.remaining_quantity == 0  # reduced
    assert exp_b.status == "closed"


def test_maintain_exposure_fallback_fifo_when_no_target(db_session, logged_in):
    """Without target_exposure_id, FIFO across dominant side is used."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=7)
    exp_a = _exposure(db_session, uid, "exec-a", pos.id, remaining_quantity=2, action="buy")
    exp_b = _exposure(db_session, uid, "exec-b", pos.id, remaining_quantity=5, action="buy")

    now = datetime.now(timezone.utc)
    result = maintain_exposure_on_exit(
        db_session, uid, pos, prior_net_quantity=7, quantity=5, now=now,
    )
    assert result is True

    db_session.refresh(exp_a)
    db_session.refresh(exp_b)
    # FIFO: A first (id=lower), then B
    assert exp_a.remaining_quantity == 0  # FIFO reduced first
    assert exp_a.status == "closed"
    assert exp_b.remaining_quantity == 2


# ===================================================================
# TEST GROUP 3: Shared-instrument strategy isolation
# ===================================================================

def test_shared_instrument_exit_strategy_b_only(db_session, logged_in):
    """Strategy A and B share same instrument. Exit B leaves A untouched."""
    uid = logged_in
    _account(db_session, uid)
    se_a = _execution(db_session, uid, "exec-a", "Strategy A")
    se_b = _execution(db_session, uid, "exec-b", "Strategy B")
    pos = _position(db_session, uid, net_quantity=7, strategy_execution_id="exec-a")
    exp_a = _exposure(db_session, uid, "exec-a", pos.id, remaining_quantity=2, action="buy")
    exp_b = _exposure(db_session, uid, "exec-b", pos.id, remaining_quantity=5, action="buy")

    # Exit Strategy B / BUY CE / ALL
    result = exit_position(
        uid, pos.id, _exit_request("exit-strat-b-001", quantity=5), db_session,
        fill_price=180.0, exit_side="sell", target_exposure_id=exp_b.id,
    )
    assert result.order.action == "sell"
    assert result.order.filled_quantity == 5

    db_session.refresh(exp_a)
    db_session.refresh(exp_b)
    db_session.refresh(pos)

    assert exp_a.remaining_quantity == 2  # untouched
    assert exp_a.status == "open"
    assert exp_b.remaining_quantity == 0
    assert exp_b.status == "closed"
    assert pos.net_quantity == 2  # 7 - 5 = 2


def test_shared_instrument_exit_sell_exposure_on_net_long(db_session, logged_in):
    """SELL CE exposure on a net-long position. Exit should use BUY."""
    uid = logged_in
    _account(db_session, uid)
    se_a = _execution(db_session, uid, "exec-a", "Strategy A")
    se_b = _execution(db_session, uid, "exec-b", "Strategy B")
    # A: BUY CE × 2, B: SELL CE × 1 → Net: +1
    pos = _position(db_session, uid, net_quantity=1, strategy_execution_id="exec-a")
    exp_a = _exposure(db_session, uid, "exec-a", pos.id, remaining_quantity=2, action="buy")
    exp_b = _exposure(db_session, uid, "exec-b", pos.id, remaining_quantity=1, action="sell")

    # Exit Strategy B / SELL CE / ALL
    # SELL exposure → BUY exit
    result = exit_position(
        uid, pos.id, _exit_request("exit-sell-exp-001", quantity=1), db_session,
        fill_price=180.0, exit_side="buy", target_exposure_id=exp_b.id,
    )
    assert result.order.action == "buy"  # BUY to exit SELL exposure

    db_session.refresh(exp_a)
    db_session.refresh(exp_b)
    db_session.refresh(pos)

    assert exp_a.remaining_quantity == 2  # untouched
    assert exp_b.remaining_quantity == 0
    assert exp_b.status == "closed"
    assert pos.net_quantity == 2  # +1 - (-1) = +2


# ===================================================================
# TEST GROUP 4: BUY/SELL × CE/PE matrix
# ===================================================================

def test_buy_ce_to_sell_ce(db_session, logged_in):
    """BUY CE exposure exits via SELL CE."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2, option_type="call")
    exp = _exposure(db_session, uid, "exec-1", pos.id, option_type="call", action="buy")

    result = exit_position(
        uid, pos.id, _exit_request("buy-ce-001", quantity=2), db_session,
        fill_price=180.0, exit_side="sell", target_exposure_id=exp.id,
    )
    assert result.order.action == "sell"
    assert result.order.option_type == "call"
    db_session.refresh(exp)
    assert exp.remaining_quantity == 0


def test_sell_ce_to_buy_ce(db_session, logged_in):
    """SELL CE exposure exits via BUY CE."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=-2, option_type="call")
    exp = _exposure(db_session, uid, "exec-1", pos.id, option_type="call", action="sell")

    result = exit_position(
        uid, pos.id, _exit_request("sell-ce-001", quantity=2), db_session,
        fill_price=180.0, exit_side="buy", target_exposure_id=exp.id,
    )
    assert result.order.action == "buy"
    assert result.order.option_type == "call"
    db_session.refresh(exp)
    assert exp.remaining_quantity == 0


def test_buy_pe_to_sell_pe(db_session, logged_in):
    """BUY PE exposure exits via SELL PE."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2, option_type="put", strike=24900.0)
    exp = _exposure(db_session, uid, "exec-1", pos.id, option_type="put", action="buy",
                    strike=24900.0)

    result = exit_position(
        uid, pos.id, _exit_request("buy-pe-001", quantity=2), db_session,
        fill_price=150.0, exit_side="sell", target_exposure_id=exp.id,
    )
    assert result.order.action == "sell"
    assert result.order.option_type == "put"
    db_session.refresh(exp)
    assert exp.remaining_quantity == 0


def test_sell_pe_to_buy_pe(db_session, logged_in):
    """SELL PE exposure exits via BUY PE."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=-2, option_type="put", strike=24900.0)
    exp = _exposure(db_session, uid, "exec-1", pos.id, option_type="put", action="sell",
                    strike=24900.0)

    result = exit_position(
        uid, pos.id, _exit_request("sell-pe-001", quantity=2), db_session,
        fill_price=150.0, exit_side="buy", target_exposure_id=exp.id,
    )
    assert result.order.action == "buy"
    assert result.order.option_type == "put"
    db_session.refresh(exp)
    assert exp.remaining_quantity == 0


# ===================================================================
# TEST GROUP 5: Preview endpoint
# ===================================================================

def test_preview_returns_targets_without_mutation(client, logged_in, db_session):
    """POST /paper/exit-intent/preview resolves targets without mutating state."""
    uid = logged_in
    _account(db_session, uid)
    se = _execution(db_session, uid, "exec-prev")
    pos = _position(db_session, uid, net_quantity=2, strategy_execution_id="exec-prev")
    exp = _exposure(db_session, uid, "exec-prev", pos.id, remaining_quantity=2)
    db_session.commit()

    resp = client.post("/paper/exit-intent/preview", headers=HDR(logged_in), json={
        "client_order_id": "preview-test-001",
        "scope": "POSITION",
        "position_id": pos.id,
        "option_type": "CALL",
        "action": "BUY",
        "quantity_mode": "ALL",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "PREVIEW"
    assert len(data["targets"]) == 1
    target = data["targets"][0]
    assert target["position_id"] == pos.id
    assert target["source_action"] == "buy"
    assert target["exit_side"] == "sell"
    assert target["quantity"] == 2
    assert target["remaining_quantity"] == 2
    assert target["strategy_leg_exposure_id"] == exp.id

    # Verify NO mutation occurred
    db_session.refresh(pos)
    assert pos.net_quantity == 2  # unchanged
    assert pos.status == "open"


def test_preview_no_matching_targets(client, logged_in, db_session):
    """Preview returns NO_MATCHING_TARGETS when selector matches nothing."""
    uid = logged_in
    resp = client.post("/paper/exit-intent/preview", headers=HDR(logged_in), json={
        "client_order_id": "preview-empty-001",
        "scope": "STRATEGY",
        "strategy_execution_id": "nonexistent",
        "quantity_mode": "ALL",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("NO_MATCHING_TARGETS", "REJECTED")
    assert len(data["targets"]) == 0


def test_preview_rejects_unauthenticated(client, db_session):
    """Preview requires authentication."""
    resp = client.post("/paper/exit-intent/preview", json={
        "client_order_id": "preview-unauth-001",
        "scope": "PORTFOLIO",
        "quantity_mode": "ALL",
    })
    assert resp.status_code == 401


def test_preview_strategy_scope(client, logged_in, db_session):
    """Preview with STRATEGY scope resolves correct exposures."""
    uid = logged_in
    _account(db_session, uid)
    se = _execution(db_session, uid, "exec-s1", "Iron Condor")
    pos = _position(db_session, uid, net_quantity=2, strategy_execution_id="exec-s1")
    exp = _exposure(db_session, uid, "exec-s1", pos.id, remaining_quantity=2)
    db_session.commit()

    resp = client.post("/paper/exit-intent/preview", headers=HDR(logged_in), json={
        "client_order_id": "preview-strat-001",
        "scope": "STRATEGY",
        "strategy_execution_id": "exec-s1",
        "quantity_mode": "ALL",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "PREVIEW"
    assert len(data["targets"]) == 1
    assert data["targets"][0]["strategy_execution_id"] == "exec-s1"


# ===================================================================
# TEST GROUP 6: Idempotency
# ===================================================================

def test_idempotent_exit_replay(db_session, logged_in):
    """Retrying the same client_order_id returns original result."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2)
    exp = _exposure(db_session, uid, "exec-1", pos.id, remaining_quantity=2)

    r1 = exit_position(
        uid, pos.id, _exit_request("idem-001", quantity=2), db_session,
        fill_price=180.0, exit_side="sell", target_exposure_id=exp.id,
    )
    assert r1.duplicated is False

    # Replay
    r2 = exit_position(
        uid, pos.id, _exit_request("idem-001", quantity=2), db_session,
        fill_price=200.0,  # different price — should be ignored
    )
    assert r2.duplicated is True
    assert r2.order.fill_price == r1.order.fill_price  # original preserved


# ===================================================================
# TEST GROUP 7: Quantity safety
# ===================================================================

def test_excess_quantity_rejected(db_session, logged_in):
    """Quantity exceeding remaining is rejected."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2)
    exp = _exposure(db_session, uid, "exec-1", pos.id, remaining_quantity=2)

    with pytest.raises(PaperExecutionError) as exc_info:
        exit_position(
            uid, pos.id, _exit_request("qty-exceed-001", quantity=5), db_session,
            fill_price=180.0, exit_side="sell", target_exposure_id=exp.id,
        )
    assert exc_info.value.code == "INSUFFICIENT_POSITION"


def test_zero_quantity_rejected_via_schema(db_session, logged_in):
    """Zero quantity is rejected at the Pydantic schema level."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ExitRequestIn(client_order_id="qty-zero-001", quantity=0)


def test_partial_exit_preserves_remaining(db_session, logged_in):
    """Partial exit reduces quantity correctly."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=3)
    exp = _exposure(db_session, uid, "exec-1", pos.id, remaining_quantity=3)

    result = exit_position(
        uid, pos.id, _exit_request("partial-001", quantity=1), db_session,
        fill_price=180.0, exit_side="sell", target_exposure_id=exp.id,
    )
    assert result.order.filled_quantity == 1

    db_session.refresh(pos)
    db_session.refresh(exp)
    assert pos.net_quantity == 2
    assert exp.remaining_quantity == 2
    assert exp.status == "open"


# ===================================================================
# TEST GROUP 8: Stale target protection
# ===================================================================

def test_exit_closed_position_rejected(db_session, logged_in):
    """Exiting a closed position is rejected."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=0, status="closed")

    with pytest.raises(PaperExecutionError) as exc_info:
        exit_position(
            uid, pos.id, _exit_request("stale-001"), db_session,
            fill_price=180.0, exit_side="sell",
        )
    assert exc_info.value.code == "INSUFFICIENT_POSITION"


def test_targeted_exposure_not_found(db_session, logged_in):
    """Targeting a non-existent exposure returns False (best-effort)."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2)
    now = datetime.now(timezone.utc)

    result = maintain_exposure_on_exit(
        db_session, uid, pos, prior_net_quantity=2, quantity=2, now=now,
        target_exposure_id=99999,
    )
    assert result is False  # best-effort: exposure not found


# ===================================================================
# TEST GROUP 9: User isolation
# ===================================================================

def test_user_isolation_exit(db_session, logged_in):
    """User cannot exit another user's position."""
    uid = logged_in
    other_uid = "user-other-exit"
    pos = _position(db_session, other_uid, net_quantity=2)

    with pytest.raises(PaperExecutionError) as exc_info:
        exit_position(
            uid, pos.id, _exit_request("isolation-001"), db_session,
            fill_price=180.0, exit_side="sell",
        )
    assert exc_info.value.code == "POSITION_NOT_FOUND"


# ===================================================================
# TEST GROUP 10: Paper order records correct side
# ===================================================================

def test_paper_order_records_exit_side(db_session, logged_in):
    """PaperOrder records the exit_side, not the net quantity derived side."""
    uid = logged_in
    pos = _position(db_session, uid, net_quantity=2)  # LONG
    exp = _exposure(db_session, uid, "exec-1", pos.id, remaining_quantity=2)

    result = exit_position(
        uid, pos.id, _exit_request("order-side-001", quantity=2), db_session,
        fill_price=180.0, exit_side="sell", target_exposure_id=exp.id,
    )
    # PaperOrder should record "sell" (the exit_side)
    assert result.order.action == "sell"
    assert result.order.kind == "exit"


# ===================================================================
# TEST GROUP 11: Preview warns about no market price
# ===================================================================

def test_preview_includes_warning_about_market_price(client, logged_in, db_session):
    """Preview warns that market prices will be resolved at execution time."""
    uid = logged_in
    _account(db_session, uid)
    se = _execution(db_session, uid, "exec-warn")
    pos = _position(db_session, uid, net_quantity=2, strategy_execution_id="exec-warn")
    _exposure(db_session, uid, "exec-warn", pos.id, remaining_quantity=2)
    db_session.commit()

    resp = client.post("/paper/exit-intent/preview", headers=HDR(logged_in), json={
        "client_order_id": "preview-warn-001",
        "scope": "POSITION",
        "position_id": pos.id,
        "quantity_mode": "ALL",
    })
    data = resp.json()
    assert any("market prices" in w.lower() or "market" in w.lower() for w in data["warnings"])
