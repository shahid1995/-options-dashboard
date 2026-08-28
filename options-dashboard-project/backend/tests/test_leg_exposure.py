"""Phase 6.5.0.1 tests — strategy-leg attribution (StrategyLegExposure).

Covers the phase matrix: one strategy / one leg, one strategy / multiple
legs, multiple strategies / same instrument, BUY + SELL same instrument,
CE + PE, partial exit, repeated partial exits, reversal, same strategy
multiple executions, user isolation, journal attribution (strategy-scoped
journal closes), position-capacity reconciliation, deterministic
allocation, insufficient current capacity, idempotent state updates, the
conservative startup backfill, and mixed legacy + new attribution.
"""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Leg,
    PaperOrder,
    Position,
    StrategyExecution,
    StrategyLegExposure,
    Trade,
)
from app.services import token_store
from tests.test_helpers import create_test_identity
from app.services.leg_exposure import (
    LegExposureError,
    allocate_exit,
    backfill_all_exposures,
    backfill_exposures,
    maintain_exposure_on_exit,
    reconcile_position_exposures,
)

LOT = 65
EXPIRY = "2026-08-27"

DEFAULT_CHAIN = {
    EXPIRY: {
        24350: {"call": 125.25, "put": 90.0},
        25000: {"call": 200.0, "put": 80.0},
        25100: {"call": 80.0, "put": 210.0},
    },
}


def chain_payload(expiry: str, quotes: dict) -> dict:
    data = []
    for strike, sides in quotes.items():
        item = {"strike_price": strike, "underlying_spot_price": 24000.0}
        item["call_options"] = {"market_data": {"ltp": sides["call"]}, "option_greeks": {}}
        item["put_options"] = {"market_data": {"ltp": sides["put"]}, "option_greeks": {}}
        data.append(item)
    return {"data": data}


@pytest.fixture(autouse=True)
def market_open_gate():
    status = SimpleNamespace(
        status="open",
        source="test",
        trade_date="2026-08-14",
        checked_at="2026-08-14T10:00:00+05:30",
        message="test market status: open",
        error=None,
    )
    with patch("app.routers.paper.get_market_status", new=AsyncMock(return_value=status)):
        yield


@pytest.fixture(autouse=True)
def chain_mock():
    async def fake(token, instrument_key, expiry):
        return chain_payload(expiry, DEFAULT_CHAIN.get(expiry, {}))

    with patch("app.services.upstox.get_option_chain", new=AsyncMock(side_effect=fake)):
        yield


@pytest.fixture
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


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def logged_in(client, db_session):
    session_id, user_id = create_test_identity(db_session, "tok-leg-exposure")
    db_session._test_user_id = user_id
    return session_id


# ---- helpers ----------------------------------------------------------------


def headers(session_id):
    return {"X-Session-Id": session_id}


def leg_payload(strike, option_type, action, quantity):
    return {
        "symbol": "NIFTY",
        "expiration_date": EXPIRY,
        "strike_price": strike,
        "option_type": option_type,
        "action": action,
        "quantity": quantity,
        "lot_size": LOT,
    }


def exec_payload(client_order_id, strategy_tag, legs):
    return {
        "client_order_id": client_order_id,
        "symbol": "NIFTY",
        "strategy_tag": strategy_tag,
        "starting_capital": 500000,
        "legs": legs,
    }


def execute(client, session_id, payload):
    return client.post("/paper/executions", headers=headers(session_id), json=payload)


def exit_position(client, session_id, position_id, payload):
    return client.post(
        f"/paper/positions/{position_id}/exit", headers=headers(session_id), json=payload
    )


def exposures(db_session):
    return db_session.query(StrategyLegExposure).order_by(StrategyLegExposure.id).all()


def position_for(db_session, strike, option_type="call"):
    return db_session.query(Position).filter_by(strike=strike, option_type=option_type).one()


def utcnow():
    return datetime.now(timezone.utc)


# ---- one strategy / one leg -------------------------------------------------


def test_one_strategy_one_leg_creates_exposure(client, logged_in, db_session):
    execute(client, logged_in, exec_payload("exec-1-1", "Long Call", [leg_payload(24350, "call", "buy", 2)]))
    pos = position_for(db_session, 24350)
    rows = exposures(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == db_session._test_user_id
    assert row.position_id == pos.id
    assert row.execution_id == pos.strategy_execution_id
    assert row.action == "buy"
    assert row.option_type == "call"
    assert row.original_quantity == 2
    assert row.remaining_quantity == 2
    assert row.status == "open"
    assert row.symbol == "NIFTY" and row.expiry == EXPIRY and row.strike == 24350
    # Never derived from the position sign — action is the executed leg action.
    assert row.action != ("sell" if pos.net_quantity > 0 else "buy")


# ---- one strategy / multiple legs -------------------------------------------


def test_one_strategy_multiple_legs_ce_and_pe(client, logged_in, db_session):
    execute(
        client,
        logged_in,
        exec_payload("exec-1-multi", "Mixed", [
            leg_payload(25000, "call", "buy", 1),
            leg_payload(25100, "put", "sell", 2),
        ]),
    )
    rows = exposures(db_session)
    assert len(rows) == 2
    by_key = {(r.option_type, r.action): r for r in rows}
    assert set(by_key) == {("call", "buy"), ("put", "sell")}
    assert by_key[("call", "buy")].remaining_quantity == 1
    assert by_key[("put", "sell")].remaining_quantity == 2


# ---- multiple strategies / same instrument (BUY + SELL) ---------------------


def test_buy_and_sell_same_instrument_preserve_both_executions(client, logged_in, db_session):
    execute(client, logged_in, exec_payload("exec-a-buy", "Strat A", [leg_payload(25000, "call", "buy", 2)]))
    execute(client, logged_in, exec_payload("exec-b-sell", "Strat B", [leg_payload(25000, "call", "sell", 1)]))
    pos = position_for(db_session, 25000)
    # Netted position: +2 −1 = +1 (single authoritative row).
    assert pos.net_quantity == 1
    rows = exposures(db_session)
    assert len(rows) == 2
    by_action = {r.action: r for r in rows}
    assert by_action["buy"].remaining_quantity == 2
    assert by_action["sell"].remaining_quantity == 1
    assert by_action["sell"].execution_id != by_action["buy"].execution_id
    # The exposure ledger reconciles to the netted position: 2 − 1 = 1.
    assert reconcile_position_exposures(pos, rows)["status"] == "OK"


# ---- partial exit / repeated partial exits ----------------------------------


def test_partial_exit_reduces_exposure(client, logged_in, db_session):
    execute(client, logged_in, exec_payload("exec-partial", "Long Call", [leg_payload(24350, "call", "buy", 5)]))
    pos = position_for(db_session, 24350)
    exit_position(client, logged_in, pos.id, {"client_order_id": "exit-partial-1", "quantity": 2})
    row = exposures(db_session)[0]
    assert row.remaining_quantity == 3
    assert row.status == "open"
    assert position_for(db_session, 24350).net_quantity == 3


def test_repeated_partial_exits_close_exposure_at_zero(client, logged_in, db_session):
    execute(client, logged_in, exec_payload("exec-repeat", "Long Call", [leg_payload(24350, "call", "buy", 5)]))
    pos = position_for(db_session, 24350)
    for idx, qty in enumerate((2, 2, 1)):
        resp = exit_position(client, logged_in, pos.id, {
            "client_order_id": f"exit-repeat-{idx}", "quantity": qty,
        })
        assert resp.status_code == 200
    row = exposures(db_session)[0]
    assert row.remaining_quantity == 0
    assert row.status == "closed"
    assert position_for(db_session, 24350).status == "closed"


# ---- reversal ---------------------------------------------------------------


def test_reversal_allocates_to_dominant_side(client, logged_in, db_session):
    # A: BUY 1 @ 100 → net +1. B: SELL 3 @ 120 → net −2 (reversal).
    execute(client, logged_in, exec_payload("exec-rev-a", "Strat A", [leg_payload(24350, "call", "buy", 1)]))
    execute(client, logged_in, exec_payload("exec-rev-b", "Strat B", [leg_payload(24350, "call", "sell", 3)]))
    pos = position_for(db_session, 24350)
    assert pos.net_quantity == -2
    assert pos.average_entry_price == 125.25  # static test chain — no price move
    rows = {r.action: r for r in exposures(db_session)}
    assert rows["buy"].remaining_quantity == 1  # A's long, netted away, preserved
    assert rows["sell"].remaining_quantity == 3

    # Full exit (BUY 2): reduces the DOMINANT side (short → sell legs), FIFO.
    resp = exit_position(client, logged_in, pos.id, {"client_order_id": "exit-rev-full", "quantity": 2})
    assert resp.status_code == 200
    assert position_for(db_session, 24350).net_quantity == 0
    assert position_for(db_session, 24350).status == "closed"
    rows = {r.action: r for r in exposures(db_session)}
    # B's short 3 → 1; A's long 1 stays. Signed sum 1 − 1 = 0 == net.
    assert rows["sell"].remaining_quantity == 1
    assert rows["sell"].status == "open"
    assert rows["buy"].remaining_quantity == 1
    pos = position_for(db_session, 24350)
    assert reconcile_position_exposures(pos, exposures(db_session))["status"] == "OK"


# ---- same strategy, multiple executions -------------------------------------


def test_same_strategy_multiple_executions_keep_separate_exposures(client, logged_in, db_session):
    execute(client, logged_in, exec_payload("exec-same-1", "Iron Condor", [leg_payload(24350, "call", "buy", 1)]))
    execute(client, logged_in, exec_payload("exec-same-2", "Iron Condor", [leg_payload(24350, "call", "buy", 1)]))
    pos = position_for(db_session, 24350)
    assert pos.net_quantity == 2
    rows = exposures(db_session)
    assert len(rows) == 2
    assert len({r.execution_id for r in rows}) == 2  # two distinct executions
    assert all(r.remaining_quantity == 1 for r in rows)
    assert reconcile_position_exposures(pos, rows)["status"] == "OK"


# ---- user isolation ---------------------------------------------------------


def test_user_isolation_exposures_untouched(client, logged_in, db_session):
    other = "tok-other-user"
    now = utcnow()
    other_pos = Position(
        user_id=other, symbol="NIFTY", expiry=EXPIRY, strike=25000,
        option_type="call", net_quantity=3, average_entry_price=100.0,
        lot_size=LOT, realized_pnl=0.0, status="open",
        strategy_execution_id="exec-other", opened_at=now,
    )
    db_session.add(other_pos)
    db_session.flush()
    db_session.add(StrategyLegExposure(
        user_id=other, execution_id="exec-other", position_id=other_pos.id,
        order_id=999001, symbol="NIFTY", expiry=EXPIRY, strike=25000,
        option_type="call", action="buy", original_quantity=3,
        remaining_quantity=3, status="open", created_at=now, updated_at=now,
    ))
    db_session.commit()

    execute(client, logged_in, exec_payload("exec-iso-a", "Strat A", [leg_payload(25000, "call", "buy", 2)]))
    execute(client, logged_in, exec_payload("exec-iso-b", "Strat B", [leg_payload(25000, "call", "sell", 1)]))
    pos = db_session.query(Position).filter_by(user_id=db_session._test_user_id, strike=25000, option_type="call").one()
    exit_position(client, logged_in, pos.id, {"client_order_id": "exit-iso", "quantity": 1})

    # Other user's exposure is byte-for-byte untouched.
    others = db_session.query(StrategyLegExposure).filter_by(user_id=other).all()
    assert len(others) == 1
    assert others[0].remaining_quantity == 3
    assert others[0].status == "open"
    mine = db_session.query(StrategyLegExposure).filter_by(user_id=db_session._test_user_id).all()
    assert len(mine) == 2
    # Only the logged-in user's dominant-side exposure was reduced.
    assert {r.action for r in mine} == {"buy", "sell"}
    assert next(r for r in mine if r.action == "buy").remaining_quantity == 1
    assert next(r for r in mine if r.action == "sell").remaining_quantity == 1


# ---- journal attribution (Phase 6.5.0.1 regression) -------------------------


def test_journal_close_is_scoped_to_positions_own_execution(client, logged_in, db_session):
    # A: BUY 25000 CE 1 (journal leg A). B: BUY 25000 CE 3 (journal leg B).
    # Netted position +4 is owned by A. Exiting 2 lots must only close A's
    # journal leg — B's leg belongs to a different execution.
    execute(client, logged_in, exec_payload("exec-jrnl-a", "Strat A", [leg_payload(25000, "call", "buy", 1)]))
    execute(client, logged_in, exec_payload("exec-jrnl-b", "Strat B", [leg_payload(25000, "call", "buy", 3)]))
    pos = position_for(db_session, 25000)
    assert pos.strategy_execution_id is not None
    assert pos.net_quantity == 4

    exit_position(client, logged_in, pos.id, {"client_order_id": "exit-jrnl", "quantity": 2})

    leg_a, leg_b = db_session.query(Leg).order_by(Leg.id).all()
    assert leg_a.quantity == 1 and leg_b.quantity == 3
    # A's leg is closed (its execution owns the position); B's leg is NOT
    # closed by an exit of a different strategy's position.
    assert leg_a.exit_at is not None
    assert leg_b.exit_at is None


def test_journal_close_still_closes_same_execution_legs(client, logged_in, db_session):
    execute(client, logged_in, exec_payload("exec-jrnl-same", "Long Call", [leg_payload(24350, "call", "buy", 1)]))
    pos = position_for(db_session, 24350)
    exit_position(client, logged_in, pos.id, {"client_order_id": "exit-jrnl-same", "quantity": 1})
    leg = db_session.query(Leg).one()
    assert leg.exit_at is not None
    trade = db_session.query(Trade).one()
    assert trade.status == "closed"


# ---- position-capacity reconciliation (pure) --------------------------------


def _exposure(id_, action, remaining, status="open"):
    return SimpleNamespace(
        id=id_, action=action, remaining_quantity=remaining,
        status=status, execution_id="x", user_id="u",
    )


def _position(net):
    return SimpleNamespace(id=1, net_quantity=net)


def test_reconcile_ok_and_mismatch():
    pos = _position(1)
    assert reconcile_position_exposures(pos, [
        _exposure(1, "buy", 2), _exposure(2, "sell", 1),
    ])["status"] == "OK"
    assert reconcile_position_exposures(pos, [
        _exposure(1, "buy", 2),
    ])["status"] == "MISMATCH"
    assert reconcile_position_exposures(_position(-2), [
        _exposure(1, "buy", 1), _exposure(2, "sell", 3),
    ])["status"] == "OK"


def test_allocate_exit_deterministic_fifo():
    allocs = allocate_exit(
        [_exposure(2, "buy", 2), _exposure(1, "buy", 2)], prior_net_quantity=4, quantity=3
    )
    # FIFO by id regardless of input order.
    assert [(a.id, take) for a, take in allocs] == [(1, 2), (2, 1)]


def test_allocate_exit_reduces_dominant_side_only():
    allocs = allocate_exit(
        [_exposure(1, "buy", 2), _exposure(2, "sell", 1)], prior_net_quantity=1, quantity=1
    )
    assert [(a.id, take) for a, take in allocs] == [(1, 1)]  # long → buy side
    allocs = allocate_exit(
        [_exposure(1, "buy", 2), _exposure(2, "sell", 3)], prior_net_quantity=-2, quantity=2
    )
    assert [(a.id, take) for a, take in allocs] == [(2, 2)]  # short → sell side


def test_allocate_exit_rejects_quantity_beyond_position_capacity():
    with pytest.raises(LegExposureError) as exc:
        allocate_exit(
            [_exposure(1, "buy", 2), _exposure(2, "sell", 1)],
            prior_net_quantity=1, quantity=2,
        )
    assert exc.value.code == "INSUFFICIENT_POSITION_CAPACITY"
    with pytest.raises(LegExposureError) as exc:
        allocate_exit([_exposure(1, "buy", 0)], prior_net_quantity=0, quantity=1)
    assert exc.value.code == "INSUFFICIENT_POSITION_CAPACITY"


def test_allocate_exit_rejects_uncovered_attribution():
    # Stale/corrupt ledger: dominant side can only cover 1 of 2 lots.
    with pytest.raises(LegExposureError) as exc:
        allocate_exit(
            [_exposure(1, "buy", 1), _exposure(2, "sell", 1)],
            prior_net_quantity=2, quantity=2,
        )
    assert exc.value.code == "INSUFFICIENT_EXPOSURE_CAPACITY"


def test_allocate_exit_rejects_zero_quantity():
    with pytest.raises(LegExposureError) as exc:
        allocate_exit([_exposure(1, "buy", 1)], prior_net_quantity=1, quantity=0)
    assert exc.value.code == "INVALID_QUANTITY"


# ---- insufficient current capacity through the endpoint ---------------------


def test_endpoint_cannot_exit_beyond_position_capacity(client, logged_in, db_session):
    execute(client, logged_in, exec_payload("exec-cap-a", "Strat A", [leg_payload(25000, "call", "buy", 2)]))
    execute(client, logged_in, exec_payload("exec-cap-b", "Strat B", [leg_payload(25000, "call", "sell", 1)]))
    pos = position_for(db_session, 25000)  # net +1
    resp = exit_position(client, logged_in, pos.id, {"client_order_id": "exit-cap", "quantity": 2})
    assert resp.status_code == 400
    assert "only 1 lot" in resp.json()["detail"].lower()
    # Nothing changed: attribution intact, position intact.
    assert position_for(db_session, 25000).net_quantity == 1
    assert all(r.remaining_quantity == r.original_quantity for r in exposures(db_session))


# ---- idempotent state updates -----------------------------------------------


def test_duplicate_execution_never_duplicates_exposures(client, logged_in, db_session):
    payload = exec_payload("exec-idem", "Long Call", [leg_payload(24350, "call", "buy", 2)])
    first = execute(client, logged_in, payload)
    second = execute(client, logged_in, payload)
    assert first.json()["duplicated"] is False
    assert second.json()["duplicated"] is True
    rows = exposures(db_session)
    assert len(rows) == 1
    assert rows[0].remaining_quantity == 2
    assert db_session.query(PaperOrder).count() == 1


def test_duplicate_exit_never_double_decrements_exposures(client, logged_in, db_session):
    execute(client, logged_in, exec_payload("exec-idem-exit", "Long Call", [leg_payload(24350, "call", "buy", 3)]))
    pos = position_for(db_session, 24350)
    payload = {"client_order_id": "exit-idem", "quantity": 1}
    first = exit_position(client, logged_in, pos.id, payload)
    second = exit_position(client, logged_in, pos.id, payload)
    assert first.status_code == 200 and first.json()["duplicated"] is False
    assert second.status_code == 200 and second.json()["duplicated"] is True
    row = exposures(db_session)[0]
    assert row.remaining_quantity == 2
    assert position_for(db_session, 24350).net_quantity == 2


# ---- mixed legacy + new attribution (safe skip, never blocks) ---------------


def test_mixed_legacy_and_new_exposure_never_blocks_exit(client, logged_in, db_session):
    now = utcnow()
    db_session.add(Position(
        user_id=db_session._test_user_id, symbol="NIFTY", expiry=EXPIRY, strike=25100,
        option_type="call", net_quantity=1, average_entry_price=50.0,
        lot_size=LOT, realized_pnl=0.0, status="open",
        strategy_execution_id="legacy-exec", opened_at=now,
    ))
    db_session.commit()
    # A NEW execution adds attribution on top of legacy quantity: net +2,
    # exposure ledger (1) no longer equals net (2) — cannot reconcile.
    execute(client, logged_in, exec_payload("exec-mixed", "Strat New", [leg_payload(25100, "call", "buy", 1)]))
    pos = position_for(db_session, 25100)
    assert pos.net_quantity == 2
    assert reconcile_position_exposures(pos, exposures(db_session))["status"] == "MISMATCH"
    # Attribution maintenance skips on an unreconciled ledger — it never
    # guesses — and it never blocks the authoritative exit.
    assert maintain_exposure_on_exit(db_session, logged_in, pos, 2, 1, now) is False

    resp = exit_position(client, logged_in, pos.id, {"client_order_id": "exit-mixed", "quantity": 1})
    assert resp.status_code == 200
    assert position_for(db_session, 25100).net_quantity == 1
    assert exposures(db_session)[0].remaining_quantity == 1  # untouched


# ---- conservative startup backfill ------------------------------------------


def _seed_legacy_position(db_session, user_id, strike, net, exec_id, seed_orders=True, exit_order=False, extra_exec=None):
    now = utcnow()
    pos = Position(
        user_id=user_id, symbol="NIFTY", expiry=EXPIRY, strike=strike,
        option_type="call", net_quantity=net, average_entry_price=100.0,
        lot_size=LOT, realized_pnl=0.0, status="open" if net else "closed",
        strategy_execution_id=exec_id, opened_at=now,
    )
    db_session.add(pos)
    db_session.flush()
    if seed_orders:
        db_session.add(PaperOrder(
            user_id=user_id, client_order_id=f"legacy-{exec_id}-0", execution_id=exec_id,
            position_id=pos.id, kind="entry", symbol="NIFTY", expiry=EXPIRY,
            strike=strike, option_type="call", action="buy" if net > 0 else "sell",
            quantity=abs(net), lot_size=LOT, status="FILLED", filled_quantity=abs(net),
            fill_price=100.0,
        ))
    if extra_exec:
        # A SECOND execution also traded this instrument (same netted position).
        db_session.add(PaperOrder(
            user_id=user_id, client_order_id=f"legacy-{extra_exec}-0", execution_id=extra_exec,
            position_id=pos.id, kind="entry", symbol="NIFTY", expiry=EXPIRY,
            strike=strike, option_type="call", action="buy" if net > 0 else "sell",
            quantity=abs(net), lot_size=LOT, status="FILLED", filled_quantity=abs(net),
            fill_price=100.0,
        ))
    if exit_order:
        db_session.add(PaperOrder(
            user_id=user_id, client_order_id=f"legacy-{exec_id}-exit", execution_id=exec_id,
            position_id=pos.id, kind="exit", symbol="NIFTY", expiry=EXPIRY,
            strike=strike, option_type="call", action="sell" if net > 0 else "buy",
            quantity=1, lot_size=LOT, status="FILLED", filled_quantity=1,
            fill_price=100.0,
        ))
    db_session.commit()
    return pos


def test_backfill_creates_rows_for_unambiguous_execution(db_session):
    _seed_legacy_position(db_session, "u1", 24350, 3, "legacy-a")
    created = backfill_exposures(db_session, "u1")
    assert created == 1
    row = db_session.query(StrategyLegExposure).one()
    assert row.execution_id == "legacy-a"
    assert row.remaining_quantity == 3
    assert row.action == "buy"
    assert reconcile_position_exposures(position_for(db_session, 24350), [row])["status"] == "OK"


def test_backfill_skips_shared_instrument_and_exited_instrument(db_session):
    # Shared instrument: the position is owned by legacy-a but legacy-b ALSO
    # has FILLED entry orders on the same instrument → per-execution
    # remaining quantities are unknowable → skipped.
    _seed_legacy_position(db_session, "u1", 24350, 1, "legacy-a", extra_exec="legacy-b")
    # Instrument with a past exit → remaining unknowable.
    _seed_legacy_position(db_session, "u1", 25100, 2, "legacy-c", exit_order=True)
    created = backfill_exposures(db_session, "u1")
    assert created == 0
    assert db_session.query(StrategyLegExposure).count() == 0


def test_backfill_is_idempotent_and_user_scoped(db_session):
    _seed_legacy_position(db_session, "u1", 24350, 3, "legacy-a")
    _seed_legacy_position(db_session, "u2", 25000, 2, "legacy-b")
    assert backfill_all_exposures(db_session) == 2
    assert backfill_all_exposures(db_session) == 0  # idempotent
    assert db_session.query(StrategyLegExposure).count() == 2
    assert {e.user_id for e in exposures(db_session)} == {"u1", "u2"}
    for row in exposures(db_session):
        pos = db_session.get(Position, row.position_id)
        assert reconcile_position_exposures(pos, [row])["status"] == "OK"


# ---- execution grouping sanity ----------------------------------------------


def test_exposures_tie_to_execution_grouping(client, logged_in, db_session):
    seagull = exec_payload("exec-group", "Long Seagull", [
        leg_payload(24350, "call", "buy", 1),
        leg_payload(25000, "call", "sell", 1),
        leg_payload(25100, "put", "sell", 1),
    ])
    resp = execute(client, logged_in, seagull)
    exec_id = resp.json()["execution_id"]
    rows = db_session.query(StrategyLegExposure).filter_by(execution_id=exec_id).all()
    assert len(rows) == 3
    assert {(r.option_type, r.action) for r in rows} == {
        ("call", "buy"), ("call", "sell"), ("put", "sell"),
    }
    executions = db_session.query(StrategyExecution).all()
    assert len(executions) == 1
