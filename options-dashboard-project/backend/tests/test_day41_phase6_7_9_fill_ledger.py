"""Day41 Phases 6/7/9 — Three-lane routing + fill ledger + edge contract.

Verifies (Day40.5 §3/§5, Day40.6 §6, Day40.3 §4):
- Lane C: two identical no-ID fills NEVER collapse — two observation rows,
  one AMBIGUOUS composite (observed_count=2), no economic canonical fill
- Lane C: no delivery evidence ⇒ never DUPLICATE (fail-closed, Invariant Y)
- Lane C: class-A delivery evidence ⇒ DUPLICATE with duplicate_of pointer;
  BOTH rows preserved (Invariant AF/Z)
- Lane C: class-B (system-local) evidence is NOT duplicate proof
- Alias upgrade: composite → T1 (UPGRADED), PK never mutated, composite
  frozen SUPERSEDED (Invariant O)
- Alias split: composite → T1/T2 (SPLIT), cumulative conservation enforced;
  mismatch ⇒ CONTRADICTED
- Lane B: TRADE_ID dedup by economic identity; same content DUPLICATE_FILL;
  different content CONFLICT (preserved, never overwritten)
- Phase 9 edges: complete+short-fill ⇒ INVALID_OBSERVATION quarantine;
  open+filled>0 ⇒ two explicit observations; never a synthetic fill

Day41.1 correction pass:
- helpers NEVER commit — the caller owns COMMIT/ROLLBACK (Phase-2 contract);
  Lane-B duplicate/conflict deliveries record a PRESERVED observation
  (DUPLICATE with duplicate_of / CONFLICT) — evidence never discarded
- atomic first-applier arbitration via INSERT … ON CONFLICT DO NOTHING
  RETURNING is verified on real PostgreSQL in
  test_day41_phase10_postgres_concurrency.py
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.broker_sync.fill_ledger import (
    AliasState,
    LineageOutcome,
    ObservationClass,
    ReconciliationState,
    BrokerFillIdentityAlias,
    BrokerFillIdentityLineage,
    BrokerFillLedgerFill,
    BrokerFillLedgerObservation,
    apply_lane_b_fill,
    classify_order_payload_edge,
    composite_eq_key,
    evaluate_lane_c_equivalence,
    record_fill_observation,
    trade_eq_key,
    upgrade_composite_to_trade,
)

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

_RECEIVED_AT = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    from app.db import Base
    import app.models  # noqa: F401
    import app.broker_sync.models  # noqa: F401
    import app.broker_sync.raw_ingress  # noqa: F401
    import app.broker_sync.fill_ledger  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401

    Base.metadata.create_all(_engine)
    session = _TestSessionLocal()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(_engine)


def _record_no_id_fill(db, *, order="O1", d1="D1ABC", fp="FP1", qty=5):
    return record_fill_observation(
        db,
        tenant_id="tenant-1",
        broker="UPSTOX",
        provider_order_id=order,
        observation_class=ObservationClass.ECONOMIC_FILL,
        d1=d1,
        content_fingerprint=fp,
        source_mode="STREAM",
        received_at=_RECEIVED_AT,
        fill_quantity=qty,
        fill_price="100",
        raw_payload_excerpt=b'{"order_id":"O1"}'.decode(),
    )


# ---------------------------------------------------------------------------
# Lane C — no-ID fills
# ---------------------------------------------------------------------------

def test_lane_c_two_identical_no_id_fills_never_collapse(db) -> None:
    """Case 75/76: two genuinely distinct no-ID fills with identical
    observable attributes produce TWO observation rows and ONE AMBIGUOUS
    composite scope with observed_count=2 — never one merged row."""
    obs_a = _record_no_id_fill(db, d1="D1X", fp="FPX")
    obs_b = _record_no_id_fill(db, d1="D1X", fp="FPX")

    assert obs_a.observation_id != obs_b.observation_id
    state_a = evaluate_lane_c_equivalence(db, obs_a)
    state_b = evaluate_lane_c_equivalence(db, obs_b)

    assert state_a == ReconciliationState.AMBIGUOUS.value
    assert state_b == ReconciliationState.AMBIGUOUS.value

    rows = db.execute(select(BrokerFillLedgerObservation)).scalars().all()
    assert len(rows) == 2  # Invariant X: both preserved, no merge

    composite_key = composite_eq_key("tenant-1", "O1", "D1X")
    fill_row = db.execute(
        select(BrokerFillLedgerFill).where(
            BrokerFillLedgerFill.tenant_id == "tenant-1",
            BrokerFillLedgerFill.provider_order_id == "O1",
            BrokerFillLedgerFill.fill_eq_key == composite_key,
        )
    ).scalar_one()
    assert fill_row.fill_identity_type == "COMPOSITE"
    assert fill_row.reconciliation_state == ReconciliationState.AMBIGUOUS.value
    assert fill_row.observed_count == 2  # Case B must NOT become delivery_count=1


def test_lane_c_no_delivery_evidence_is_never_duplicate(db) -> None:
    """Case 84: without admissible delivery evidence the observation is
    AMBIGUOUS — never DUPLICATE (fail-closed, Invariant Y)."""
    obs = _record_no_id_fill(db, d1="D1N", fp="FPN")
    state = evaluate_lane_c_equivalence(db, obs, delivery_evidence={})
    assert state == ReconciliationState.AMBIGUOUS.value


def test_lane_c_class_b_local_cursor_is_not_duplicate_proof(db) -> None:
    """Invariant Y/AD: a system-local cursor (class B) proves only that we
    ingested a position before — it can NEVER classify a duplicate."""
    obs_a = _record_no_id_fill(db, d1="D1B", fp="FPB")
    evaluate_lane_c_equivalence(db, obs_a)
    obs_b = _record_no_id_fill(db, d1="D1B", fp="FPB")
    state = evaluate_lane_c_equivalence(
        db, obs_b,
        delivery_evidence={"recovery_cursor": {"class": "B", "value": "cursor-7"}},
    )
    assert state == ReconciliationState.AMBIGUOUS.value


def test_lane_c_class_a_evidence_proves_duplicate_but_preserves_both(db) -> None:
    """Case 74/83/99: with provider-authoritative (class A) delivery identity,
    the second delivery is DUPLICATE — with a duplicate_of pointer — and BOTH
    observation rows remain preserved (Invariant AF)."""
    from app.broker_sync.raw_ingress import (
        BrokerRawObservation,
        commit_raw_observation,
    )

    evidence = {"provider_delivery_id": {"class": "A", "value": "prov-dlv-1"}}

    # First delivery: durable raw commit → fill observation linked to it.
    raw_a = commit_raw_observation(
        db, tenant_id="tenant-1", broker="UPSTOX", source_mode="STREAM",
        raw_payload=b'{"raw":"a"}', received_at=_RECEIVED_AT,
        delivery_evidence=evidence,
    )
    obs_a = _record_no_id_fill(db, d1="D1A", fp="FPA")
    obs_a.raw_observation_id = raw_a.raw_observation_id
    db.commit()
    state_a = evaluate_lane_c_equivalence(db, obs_a, delivery_evidence=evidence)
    assert state_a == ReconciliationState.AMBIGUOUS.value  # first delivery: no prior

    # Second delivery: SAME class-A identity → proven duplicate.
    raw_b = commit_raw_observation(
        db, tenant_id="tenant-1", broker="UPSTOX", source_mode="STREAM",
        raw_payload=b'{"raw":"b"}', received_at=_RECEIVED_AT,
        delivery_evidence=evidence,
    )
    obs_b = _record_no_id_fill(db, d1="D1A", fp="FPA")
    obs_b.raw_observation_id = raw_b.raw_observation_id
    db.commit()
    state_b = evaluate_lane_c_equivalence(db, obs_b, delivery_evidence=evidence)
    assert state_b == ReconciliationState.DUPLICATE.value

    rows = db.execute(select(BrokerFillLedgerObservation)).scalars().all()
    assert len(rows) == 2  # both preserved (Invariant AF)
    dup_row = next(r for r in rows if r.observation_id == obs_b.observation_id)
    assert dup_row.duplicate_of == obs_a.observation_id
    assert db.execute(select(BrokerRawObservation)).scalars().all() != []


def test_lane_c_permanent_ambiguity_without_reconciliation(db) -> None:
    """Case 82: a no-ID fill never reconciled stays AMBIGUOUS — no economic
    canonical fill, evidence preserved."""
    obs = _record_no_id_fill(db, d1="D1P", fp="FPP")
    evaluate_lane_c_equivalence(db, obs)
    composite_key = composite_eq_key("tenant-1", "O1", "D1P")
    fill_row = db.execute(
        select(BrokerFillLedgerFill).where(
            BrokerFillLedgerFill.fill_eq_key == composite_key,
        )
    ).scalar_one()
    assert fill_row.reconciliation_state == ReconciliationState.AMBIGUOUS.value
    # No TRADE_ID row exists — fail-closed.
    trade_rows = db.execute(
        select(BrokerFillLedgerFill).where(
            BrokerFillLedgerFill.fill_identity_type == "TRADE_ID",
        )
    ).scalars().all()
    assert trade_rows == []


# ---------------------------------------------------------------------------
# Alias upgrade — C → T1 / split / contradiction
# ---------------------------------------------------------------------------

def test_alias_upgrade_composite_to_t1_pk_never_mutated(db) -> None:
    """Case 80: C → T1 upgrade.  The composite row is frozen SUPERSEDED with
    its ORIGINAL PK intact; a distinct TRADE_ID row carries the identity;
    the alias becomes AUTHORITATIVE; lineage records UPGRADED."""
    obs = _record_no_id_fill(db, d1="D1U", fp="FPU", qty=5)
    evaluate_lane_c_equivalence(db, obs)
    composite_key = composite_eq_key("tenant-1", "O1", "D1U")

    created = upgrade_composite_to_trade(
        db,
        tenant_id="tenant-1",
        provider_order_id="O1",
        composite_key=composite_key,
        trade_ids=["T1"],
        trigger="TRADE_HISTORY",
        observation_ids=[obs.observation_id],
    )
    assert len(created) == 1
    assert created[0].fill_eq_key == trade_eq_key("T1")
    assert created[0].fill_identity_type == "TRADE_ID"
    assert created[0].reconciliation_state == ReconciliationState.RECONCILED.value

    # Composite row STILL EXISTS with its original PK — never re-keyed.
    composite_row = db.execute(
        select(BrokerFillLedgerFill).where(
            BrokerFillLedgerFill.fill_eq_key == composite_key,
        )
    ).scalar_one()
    assert composite_row.reconciliation_state == ReconciliationState.SUPERSEDED.value
    assert composite_row.frozen_reason == "SUPERSEDED_BY_ALIAS"

    alias = db.execute(
        select(BrokerFillIdentityAlias).where(
            BrokerFillIdentityAlias.from_eq_key == composite_key,
        )
    ).scalar_one()
    assert alias.alias_state == AliasState.AUTHORITATIVE.value
    assert alias.to_eq_key == trade_eq_key("T1")

    lineage = db.execute(select(BrokerFillIdentityLineage)).scalars().all()
    outcomes = {l.outcome for l in lineage}
    assert LineageOutcome.UPGRADED.value in outcomes


def test_alias_split_composite_to_t1_t2(db) -> None:
    """Case 81: C → T1/T2 SPLIT with cumulative conservation holding."""
    obs = _record_no_id_fill(db, d1="D1S", fp="FPS", qty=5)
    # Composite carries cumulative_after=8; split 5+3 conserves.
    composite_key = composite_eq_key("tenant-1", "O1", "D1S")
    evaluate_lane_c_equivalence(db, obs)
    fill_row = db.execute(
        select(BrokerFillLedgerFill).where(BrokerFillLedgerFill.fill_eq_key == composite_key)
    ).scalar_one()
    fill_row.cumulative_after = 8
    db.commit()

    created = upgrade_composite_to_trade(
        db,
        tenant_id="tenant-1",
        provider_order_id="O1",
        composite_key=composite_key,
        trade_ids=["T1", "T2"],
        trigger="TRADE_HISTORY",
    )
    assert {r.fill_eq_key for r in created} == {trade_eq_key("T1"), trade_eq_key("T2")}
    alias = db.execute(
        select(BrokerFillIdentityAlias).where(
            BrokerFillIdentityAlias.from_eq_key == composite_key,
        )
    ).scalar_one()
    assert alias.alias_state == AliasState.SPLIT.value

    lineage = db.execute(select(BrokerFillIdentityLineage)).scalars().all()
    assert any(l.outcome == LineageOutcome.SPLIT.value for l in lineage)
    # Composite preserved.
    assert db.execute(
        select(BrokerFillLedgerFill).where(BrokerFillLedgerFill.fill_eq_key == composite_key)
    ).scalar_one() is not None


def test_alias_split_cumulative_contradiction(db) -> None:
    """Case 81-variant: split with explicit per-trade quantities whose sum
    contradicts the composite cumulative is recorded CONTRADICTED
    (Day40.3 §4 contradiction transition)."""
    obs = _record_no_id_fill(db, d1="D1C", fp="FPC", qty=5)
    composite_key = composite_eq_key("tenant-1", "O1", "D1C")
    evaluate_lane_c_equivalence(db, obs)
    fill_row = db.execute(
        select(BrokerFillLedgerFill).where(BrokerFillLedgerFill.fill_eq_key == composite_key)
    ).scalar_one()
    fill_row.cumulative_after = 100  # contradiction: 40+40 ≠ 100
    db.commit()

    created = upgrade_composite_to_trade(
        db,
        tenant_id="tenant-1",
        provider_order_id="O1",
        composite_key=composite_key,
        trade_ids=["T1", "T2"],
        trigger="TRADE_HISTORY",
        trade_quantities={"T1": 40, "T2": 40},
    )
    assert len(created) == 2  # rows still created (evidence preserved)
    lineage = db.execute(select(BrokerFillIdentityLineage)).scalars().all()
    assert any(l.outcome == LineageOutcome.CONTRADICTED.value for l in lineage)
    alias = db.execute(
        select(BrokerFillIdentityAlias).where(
            BrokerFillIdentityAlias.from_eq_key == composite_key,
        )
    ).scalar_one()
    assert alias.alias_state == AliasState.CONTRADICTED.value


def test_alias_split_without_quantities_is_split_not_contradiction(db) -> None:
    """Missing per-trade quantities never manufactures a contradiction:
    rows are created with quantity=None and the outcome is SPLIT."""
    obs = _record_no_id_fill(db, d1="D1Q", fp="FPQ", qty=5)
    composite_key = composite_eq_key("tenant-1", "O1", "D1Q")
    evaluate_lane_c_equivalence(db, obs)
    fill_row = db.execute(
        select(BrokerFillLedgerFill).where(BrokerFillLedgerFill.fill_eq_key == composite_key)
    ).scalar_one()
    fill_row.cumulative_after = 100
    db.commit()

    created = upgrade_composite_to_trade(
        db,
        tenant_id="tenant-1",
        provider_order_id="O1",
        composite_key=composite_key,
        trade_ids=["T1", "T2"],
        trigger="TRADE_HISTORY",
    )
    assert len(created) == 2
    assert all(r.fill_quantity is None for r in created)
    lineage = db.execute(select(BrokerFillIdentityLineage)).scalars().all()
    assert any(l.outcome == LineageOutcome.SPLIT.value for l in lineage)
    assert not any(l.outcome == LineageOutcome.CONTRADICTED.value for l in lineage)


# ---------------------------------------------------------------------------
# Lane B — trade_id-present fills
# ---------------------------------------------------------------------------

def test_lane_b_first_fill_applied(db) -> None:
    fill_row, outcome, obs = apply_lane_b_fill(
        db,
        tenant_id="tenant-1",
        broker="UPSTOX",
        provider_order_id="O1",
        provider_trade_id="T9",
        d1="D1T9",
        content_fingerprint="FPT9",
        source_mode="STREAM",
        received_at=_RECEIVED_AT,
        fill_quantity=5,
        fill_price="100",
    )
    assert outcome == "APPLIED"
    assert fill_row.fill_eq_key == trade_eq_key("T9")
    assert fill_row.fill_identity_type == "TRADE_ID"
    assert fill_row.reconciliation_state == ReconciliationState.RECONCILED.value
    assert obs is not None
    assert obs.observation_class == ObservationClass.ECONOMIC_FILL.value


def test_lane_b_same_trade_id_same_fingerprint_is_duplicate_fill(db) -> None:
    """Case 74-analog for Lane B: same economic identity + same content ⇒
    DUPLICATE_FILL.  Day41.1: the replay is recorded as a PRESERVED DUPLICATE
    observation (duplicate_of → the applied observation) — evidence is never
    discarded (Invariants AA/AF); the fill row is untouched."""
    first, outcome1, obs1 = apply_lane_b_fill(
        db, tenant_id="tenant-1", broker="UPSTOX", provider_order_id="O1",
        provider_trade_id="T9", d1="D1T9", content_fingerprint="FPT9",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    assert outcome1 == "APPLIED"
    fill_row, outcome2, obs2 = apply_lane_b_fill(
        db, tenant_id="tenant-1", broker="UPSTOX", provider_order_id="O1",
        provider_trade_id="T9", d1="D1T9-redelivery", content_fingerprint="FPT9",
        source_mode="RECOVERY", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    assert outcome2 == "DUPLICATE_FILL"
    # Day41.1: duplicate delivery keeps evidence — DUPLICATE observation row.
    assert obs2 is not None
    assert obs2.reconciliation_state == ReconciliationState.DUPLICATE.value
    assert obs2.duplicate_of == obs1.observation_id
    # Fill row identity unchanged (same PK row).
    assert fill_row.fill_eq_key == first.fill_eq_key
    assert fill_row.fill_quantity == 5  # not re-applied/overwritten
    obs_rows = db.execute(select(BrokerFillLedgerObservation)).scalars().all()
    assert len(obs_rows) == 2  # RECONCILED + preserved DUPLICATE
    assert {r.reconciliation_state for r in obs_rows} == {
        ReconciliationState.RECONCILED.value,
        ReconciliationState.DUPLICATE.value,
    }


def test_lane_b_same_trade_id_different_fingerprint_is_conflict(db) -> None:
    """Case: same TRADE_ID with different content ⇒ CONFLICT quarantine;
    the conflict observation is preserved; the applied fill row is never
    silently overwritten (Day40.3 §4.4)."""
    apply_lane_b_fill(
        db, tenant_id="tenant-1", broker="UPSTOX", provider_order_id="O1",
        provider_trade_id="T9", d1="D1T9", content_fingerprint="FPT9",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    fill_row, outcome, conflict_obs = apply_lane_b_fill(
        db, tenant_id="tenant-1", broker="UPSTOX", provider_order_id="O1",
        provider_trade_id="T9", d1="D1T9", content_fingerprint="FPT9-DIFFERENT",
        source_mode="RECOVERY", received_at=_RECEIVED_AT, fill_quantity=7,
    )
    assert outcome == "CONFLICT"
    assert conflict_obs is not None
    assert conflict_obs.reconciliation_state == ReconciliationState.CONFLICT.value
    # Applied row quantity NOT overwritten by the conflicting payload.
    assert fill_row.fill_quantity == 5
    lineage = db.execute(select(BrokerFillIdentityLineage)).scalars().all()
    assert any(l.outcome == LineageOutcome.CONTRADICTED.value for l in lineage)


def test_lane_b_concurrent_workers_same_trade_converge(db) -> None:
    """Case (Day40.6 §8.7): two workers applying the same trade_id converge
    on ONE fill row; the second is DUPLICATE_FILL (ON CONFLICT DO NOTHING)."""
    row1, outcome1, _ = apply_lane_b_fill(
        db, tenant_id="tenant-1", broker="UPSTOX", provider_order_id="O1",
        provider_trade_id="TC", d1="D1C1", content_fingerprint="FPC1",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    row2, outcome2, _ = apply_lane_b_fill(
        db, tenant_id="tenant-1", broker="UPSTOX", provider_order_id="O1",
        provider_trade_id="TC", d1="D1C1", content_fingerprint="FPC1",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    assert row1.fill_eq_key == row2.fill_eq_key
    assert outcome2 == "DUPLICATE_FILL"
    fills = db.execute(
        select(BrokerFillLedgerFill).where(BrokerFillLedgerFill.fill_identity_type == "TRADE_ID")
    ).scalars().all()
    assert len(fills) == 1


# ---------------------------------------------------------------------------
# Day41.1 — caller-owned transaction contract (helpers never commit)
# ---------------------------------------------------------------------------

def test_lane_b_rollback_discards_all_phase2_writes(db) -> None:
    """Day41.1 Defect-3: helpers never commit.  A caller ROLLBACK after a full
    Lane-B application (fill + observation + lineage) discards EVERY Phase-2
    write — no partial state.  (Phase-1 raw evidence is a separate committed
    transaction and is unaffected by design.)"""
    from app.broker_sync.fill_ledger import BrokerFillIdentityLineage

    apply_lane_b_fill(
        db, tenant_id="tenant-1", broker="UPSTOX", provider_order_id="O1",
        provider_trade_id="TRB", d1="D1RB", content_fingerprint="FPRB",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    db.rollback()  # caller-owned rollback of the entire Phase-2 unit

    assert db.execute(select(BrokerFillLedgerFill)).scalars().all() == []
    assert db.execute(select(BrokerFillLedgerObservation)).scalars().all() == []
    assert db.execute(select(BrokerFillIdentityLineage)).scalars().all() == []


def test_lane_b_explicit_commit_applies_atomically(db) -> None:
    """Day41.1: the CALLER's commit persists the whole Lane-B unit (fill +
    observation + lineage) — one atomic Phase-2 transaction."""
    _, outcome, obs = apply_lane_b_fill(
        db, tenant_id="tenant-1", broker="UPSTOX", provider_order_id="O1",
        provider_trade_id="TRC", d1="D1RC", content_fingerprint="FPRC",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=3,
    )
    assert outcome == "APPLIED"
    db.commit()

    fresh = db.execute(
        select(BrokerFillLedgerFill).where(
            BrokerFillLedgerFill.fill_eq_key == trade_eq_key("TRC"),
        )
    ).scalar_one()
    assert fresh.reconciliation_state == ReconciliationState.RECONCILED.value
    assert obs.reconciliation_state == ReconciliationState.RECONCILED.value
    assert db.execute(select(BrokerFillIdentityLineage)).scalars().all() == []


# ---------------------------------------------------------------------------
# Phase 9 — status/fill edge contract
# ---------------------------------------------------------------------------

def test_edge_complete_short_fill_is_invalid_observation(db) -> None:
    """Case 69: complete + filled_quantity < quantity ⇒ INVALID_OBSERVATION —
    never silently reinterpreted as partial."""
    primary, extra = classify_order_payload_edge(
        provider_status="complete", quantity=10, filled_quantity=6,
    )
    assert primary == ObservationClass.INVALID_OBSERVATION
    assert extra == []


def test_edge_open_with_fills_is_dual_observation(db) -> None:
    """Case 70: open + filled_quantity > 0 ⇒ ORDER_STATE + ECONOMIC_FILL as
    two EXPLICITLY distinct observations (never an implicit synthetic fill)."""
    primary, extra = classify_order_payload_edge(
        provider_status="open", quantity=10, filled_quantity=4,
    )
    assert primary == ObservationClass.ORDER_STATE
    assert extra == [ObservationClass.ECONOMIC_FILL]


def test_edge_open_without_fills_is_order_state_only(db) -> None:
    """No fill-bearing data ⇒ NO fill observation manufactured (Invariant V)."""
    primary, extra = classify_order_payload_edge(
        provider_status="open", quantity=10, filled_quantity=0,
    )
    assert primary == ObservationClass.ORDER_STATE
    assert extra == []


def test_edge_complete_full_fill_is_order_state_only(db) -> None:
    """complete + filled == quantity: the order-state observation carries the
    fill data; no extra composite fill observation is manufactured here —
    Lane B/C own economic fills from explicit fill-bearing payloads."""
    primary, extra = classify_order_payload_edge(
        provider_status="complete", quantity=10, filled_quantity=10,
    )
    assert primary == ObservationClass.ORDER_STATE
    assert extra == []


def test_edge_missing_quantity_data_never_manufactures_fill(db) -> None:
    """Absent quantity data ⇒ no INVALID quarantine, no synthetic fill."""
    primary, extra = classify_order_payload_edge(
        provider_status="complete", quantity=None, filled_quantity=None,
    )
    assert primary == ObservationClass.ORDER_STATE
    assert extra == []
