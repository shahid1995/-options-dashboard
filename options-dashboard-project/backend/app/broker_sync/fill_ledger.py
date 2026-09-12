"""Day41 Phases 6/7/9 — Fill ledger + three-lane routing (Day40.5, Day40.6).

Architecture (Day40.5 §2/§5-6, Day40.6 §6):

  Lane A — order observations: broker_sync_observation delivery dedup on
           (tenant, broker, d1, content_fingerprint) — sound because Π_A is
           fully fingerprinted (Day40.6 §4.3).  Implemented at the payload
           router, not here.
  Lane B — trade_id-present fills: economic dedup by TRADE_ID identity.
  Lane C — trade_id-absent fills: NO dedup on (D1, FPv2).  Every payload
           becomes an immutable fill observation; equivalence unprovable ⇒
           AMBIGUOUS; no economic canonical fill until proven.

Identity upgrade (Day40.3 §4): the composite fill row is NEVER re-keyed.
Upgrades create distinct TRADE_ID fill rows + alias + lineage rows.

Edge contract (Day40.5 §5 / Day41 Phase 9):
- complete + filled_quantity < quantity  ⇒ INVALID_OBSERVATION (quarantined)
- open + filled_quantity > 0             ⇒ two explicit observations
  (order-state + economic fill candidate) — never an implicit synthetic fill

Day41.1 hardening (caller-owned transactions + atomic arbitration):
- NO helper in this module commits.  Helpers add/update/FLUSH only; the
  caller owns COMMIT/ROLLBACK so observation + fill + lineage + canonical
  authorization commit atomically (Phase-2 transaction contract).  The
  Phase-1 raw ingest commit (raw_ingress.commit_raw_observation) remains
  intentionally independent and is unchanged.
- Lane B first-applier arbitration is ATOMIC: the TRADE_ID fill row is
  created with ``INSERT … ON CONFLICT DO NOTHING RETURNING`` — the database
  itself decides whether THIS transaction created the fill.  Winner ⇒
  APPLIED; loser ⇒ DUPLICATE_FILL (same fingerprint) or CONFLICT (different
  fingerprint).  The "did we create it?" answer is never inferred from a
  follow-up read (that race is the Day41.1 Defect 1).
- Lane B duplicate/conflicting deliveries record a preserved observation
  (DUPLICATE with duplicate_of / CONFLICT) — evidence is never discarded
  (Invariants AA/AF, Day40.5 §5.4).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base


# ---------------------------------------------------------------------------
# Reconciliation states (Day40.2 §4.2 state machine)
# ---------------------------------------------------------------------------

class ReconciliationState(str, enum.Enum):
    PENDING = "PENDING"
    RECONCILED = "RECONCILED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"
    SUPERSEDED = "SUPERSEDED"
    DUPLICATE = "DUPLICATE"  # proven duplicate delivery (class-A evidence only)


class AliasState(str, enum.Enum):
    UNRESOLVED = "UNRESOLVED"
    AUTHORITATIVE = "AUTHORITATIVE"
    SPLIT = "SPLIT"
    CONTRADICTED = "CONTRADICTED"


class LineageOutcome(str, enum.Enum):
    UPGRADED = "UPGRADED"
    SPLIT = "SPLIT"
    NO_CANDIDATE = "NO_CANDIDATE"
    CONTRADICTED = "CONTRADICTED"
    DUPLICATE_DELIVERY = "DUPLICATE_DELIVERY"


class FillIdentityType(str, enum.Enum):
    COMPOSITE = "COMPOSITE"
    TRADE_ID = "TRADE_ID"


class ObservationClass(str, enum.Enum):
    """Why an observation exists — lane/edge-contract classification."""

    ORDER_STATE = "ORDER_STATE"          # Lane A order observation
    ECONOMIC_FILL = "ECONOMIC_FILL"      # Lane B/C fill observation
    INVALID_OBSERVATION = "INVALID_OBSERVATION"  # Day40.5 §5.1 quarantine


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BrokerFillLedgerObservation(Base):
    """Immutable raw fill/order observation derived from a raw ingest row.

    One row per NORMALIZED observation (not per delivery): multiple raw
    ingest rows may reference the same observation via replay, and one raw
    row may yield two observations (order-state + economic fill, Day40.5
    §5.2).  Content is immutable; only reconciliation_state/observed_count
    advance through the state machine.
    """

    __tablename__ = "broker_fill_ledger_observation"

    observation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    raw_observation_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=True  # provenance link to Phase-1 row
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_order_id: Mapped[str] = mapped_column(String(128), nullable=False)

    observation_class: Mapped[str] = mapped_column(String(32), nullable=False)
    d1: Mapped[str] = mapped_column(String(64), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    provider_trade_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    fill_eq_key: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    fill_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fill_price: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cumulative_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    provider_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    source_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    reconciliation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    # Day40.5 §5.4: a proven duplicate delivery points at the prior preserved
    # observation; the duplicate row itself is NEVER deleted (Invariant AF).
    duplicate_of: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    observed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        # NO (d1, fingerprint) uniqueness — raw observations are never
        # delivery-deduped at this layer (Day40.5 §5.2 / Invariant X).
        Index("ix_bfill_obs_lookup", "tenant_id", "broker", "provider_order_id", "d1"),
    )


class BrokerFillLedgerFill(Base):
    """Economic-fill identity row (Day40.3 §4.2).

    PK (tenant, order, fill_eq_key): TRADE_ID rows are authoritative;
    COMPOSITE rows are provisional quarantine scopes.  Row identity is
    immutable — the alias/lineage model moves identity, never this PK.
    """

    __tablename__ = "broker_fill_ledger_fill"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    fill_eq_key: Mapped[str] = mapped_column(String(160), primary_key=True)

    fill_identity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reconciliation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fill_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fill_price: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cumulative_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    observed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    frozen_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class BrokerFillIdentityAlias(Base):
    """Alias relation: provisional composite → authoritative trade_id.

    UNIQUE on (tenant, order, from_eq_key): the only mutable pointer in the
    upgrade model.  Every change appends a lineage row (Day40.3 §4.2).
    """

    __tablename__ = "broker_fill_identity_alias"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    from_eq_key: Mapped[str] = mapped_column(String(160), primary_key=True)

    to_eq_key: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    alias_state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_transition_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class BrokerFillIdentityLineage(Base):
    """Append-only lineage/audit: how observations mapped to fills."""

    __tablename__ = "broker_fill_identity_lineage"

    lineage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider_order_id: Mapped[str] = mapped_column(String(128), nullable=False)

    observation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    from_eq_key: Mapped[str] = mapped_column(String(160), nullable=False)
    to_eq_key: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)

    upgrade_trigger: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    evidence_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def composite_eq_key(tenant_id: str, provider_order_id: str, d1: str) -> str:
    """Provisional composite key (Day40.3 §4.2): FILLKEYv1 scope.

    Deterministic from the fill-class D1 — two distinct no-ID fills with
    identical attributes share this QUARANTINE scope (that is the point:
    ambiguity is per-content-collision, while raw observations stay distinct).
    """
    import hashlib

    return "FILLKEYv1:" + hashlib.sha256(
        "\x1f".join(("COMPOSITE", tenant_id, provider_order_id, d1)).encode("utf-8")
    ).hexdigest()[:32]


def trade_eq_key(provider_trade_id: str) -> str:
    return "T:" + provider_trade_id


# ---------------------------------------------------------------------------
# Lane C — record + equivalence evaluation (Phase 1 commit already done)
# ---------------------------------------------------------------------------

def record_fill_observation(
    db: Session,
    *,
    tenant_id: str,
    broker: str,
    provider_order_id: str,
    observation_class: ObservationClass,
    d1: str,
    content_fingerprint: str,
    source_mode: str,
    received_at: datetime,
    raw_observation_id: str | None = None,
    provider_trade_id: str | None = None,
    fill_quantity: int | None = None,
    fill_price: str | None = None,
    cumulative_after: int | None = None,
    provider_status: str | None = None,
    raw_payload_excerpt: str | None = None,
    initial_state: ReconciliationState = ReconciliationState.PENDING,
) -> BrokerFillLedgerObservation:
    """Insert ONE immutable observation row.  NEVER dedups on (D1, FPv2):
    two identical no-ID fills produce two rows (Invariant X/AA).

    Day41.1: flush (not commit) — the caller owns COMMIT/ROLLBACK so the
    observation, fill, lineage, and canonical authorization commit atomically
    in the caller's Phase-2 transaction.  The Phase-1 raw commit remains
    separate and independent (Invariants AB/AC).
    """
    row = BrokerFillLedgerObservation(
        observation_id=str(uuid.uuid4()),
        raw_observation_id=raw_observation_id,
        tenant_id=tenant_id,
        broker=broker,
        provider_order_id=provider_order_id,
        observation_class=observation_class.value,
        d1=d1,
        content_fingerprint=content_fingerprint,
        provider_trade_id=provider_trade_id,
        fill_eq_key=(
            trade_eq_key(provider_trade_id)
            if provider_trade_id
            else composite_eq_key(tenant_id, provider_order_id, d1)
        ),
        fill_quantity=fill_quantity,
        fill_price=fill_price,
        cumulative_after=cumulative_after,
        provider_status=provider_status,
        source_mode=source_mode,
        received_at=received_at,
        raw_payload_excerpt=raw_payload_excerpt,
        reconciliation_state=initial_state.value,
        observed_count=1,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Lane B — trade_id-present economic fills (Phase 6)
# ---------------------------------------------------------------------------

def apply_lane_b_fill(
    db: Session,
    *,
    tenant_id: str,
    broker: str,
    provider_order_id: str,
    provider_trade_id: str,
    d1: str,
    content_fingerprint: str,
    source_mode: str,
    received_at: datetime,
    raw_observation_id: str | None = None,
    fill_quantity: int | None = None,
    fill_price: str | None = None,
    cumulative_after: int | None = None,
    provider_status: str | None = None,
    raw_payload_excerpt: str | None = None,
) -> tuple[BrokerFillLedgerFill, str, BrokerFillLedgerObservation | None]:
    """Lane B: dedup by ECONOMIC identity (tenant, order, trade_id) — Day40.5 §3.B.

    The provider minted the trade_id, so it is authoritative economic-fill
    identity; delivery dedup is irrelevant here.

    Day41.1 atomic arbitration — NO application-level check-then-insert:
    the TRADE_ID fill row is created with ``INSERT … ON CONFLICT DO NOTHING
    RETURNING`` and the DATABASE tells this transaction whether it created
    the row (Defect-1 fix).  Two simultaneous first-sighting workers on the
    same (tenant, broker, order, trade_id) can never both observe "I
    created it": exactly one INSERT returns a row.

    Returns (fill_row, outcome, new_observation_row):
    - ("APPLIED", obs_row):          THIS transaction won the arbitration —
                                      it created the TRADE_ID fill row and
                                      the RECONCILED observation row.
    - ("DUPLICATE_FILL", dup_obs):    this transaction lost the race (or the
                                      fill pre-existed) and its fingerprint
                                      MATCHES the applied content.  A
                                      preserved DUPLICATE observation (with
                                      duplicate_of) records the replay —
                                      evidence is never discarded (Invariant
                                      AA/AF, Day40.5 §5.4); NO economic
                                      re-application occurs.
    - ("CONFLICT", conflict_obs):     lost/pre-existing + fingerprint
                                      DIFFERS ⇒ economic identity conflict;
                                      preserved observation + lineage, the
                                      applied fill is NEVER overwritten
                                      (Day40.3 §4.4).

    Invariant (audit §1): for economic identity
    (tenant, broker, provider_order_id, trade_id) exactly ONE worker is
    FIRST_APPLIER (APPLIED); every other concurrent delivery yields
    DUPLICATE_FILL or CONFLICT.  Two APPLIED results are impossible — the
    returned-row status comes from the insert arbitration, not from "a row
    exists after the upsert".

    Caller-owned transaction (Defect-3 fix): this function performs NO
    commit — wrap it in the caller's Phase-2 transaction (BEGIN → … →
    COMMIT) so fill + observation + lineage commit atomically or not at
    all.  On PostgreSQL the losing INSERT blocks only until the winning
    transaction commits/aborts (spec-faithful exactly-once), then
    re-classifies under a row lock.
    """
    key = trade_eq_key(provider_trade_id)

    # --- ATOMIC creation attempt (Day41.1 Defect-1 fix) -------------------
    # created is not None ⇔ THIS transaction inserted the row (winner).
    # created is None     ⇒ row already existed or a concurrent worker won.
    created = _upsert_trade_fill(
        db,
        tenant_id=tenant_id,
        provider_order_id=provider_order_id,
        fill_eq_key=key,
        fill_quantity=fill_quantity,
        fill_price=fill_price,
        cumulative_after=cumulative_after,
    )

    if created is None:
        # LOST the race (or row pre-existed): classify the loser under a row
        # lock.  On PostgreSQL, reaching this point after a DO-NOTHING insert
        # implies the conflicting transaction has committed, so its effects
        # (fill row + RECONCILED observation) are visible to this read.
        existing = db.execute(
            select(BrokerFillLedgerFill)
            .where(
                BrokerFillLedgerFill.tenant_id == tenant_id,
                BrokerFillLedgerFill.provider_order_id == provider_order_id,
                BrokerFillLedgerFill.fill_eq_key == key,
            )
            .with_for_update()
        ).scalar_one()
        prior_fp = _fill_fingerprint(db, existing)
        if prior_fp == content_fingerprint:
            # Same economic identity + same content ⇒ DUPLICATE_FILL.
            # Preserve the replay as a DUPLICATE observation (Day40.5 §5.4):
            # evidence retained, NO economic re-application, fill untouched.
            dup_obs = record_fill_observation(
                db,
                tenant_id=tenant_id,
                broker=broker,
                provider_order_id=provider_order_id,
                observation_class=ObservationClass.ECONOMIC_FILL,
                d1=d1,
                content_fingerprint=content_fingerprint,
                source_mode=source_mode,
                received_at=received_at,
                raw_observation_id=raw_observation_id,
                provider_trade_id=provider_trade_id,
                fill_quantity=fill_quantity,
                fill_price=fill_price,
                cumulative_after=cumulative_after,
                provider_status=provider_status,
                raw_payload_excerpt=raw_payload_excerpt,
                initial_state=ReconciliationState.DUPLICATE,
            )
            dup_obs.duplicate_of = _first_reconciled_observation_id(db, existing)
            _append_lineage(
                db,
                tenant_id=tenant_id,
                provider_order_id=provider_order_id,
                observation_id=dup_obs.observation_id,
                from_eq_key=key,
                outcome=LineageOutcome.DUPLICATE_DELIVERY,
                evidence_ref="duplicate delivery of already-applied economic fill",
                observed_at=received_at,
            )
            return existing, "DUPLICATE_FILL", dup_obs
        # Different content under the same economic identity → CONFLICT.
        # Quarantine: record the conflict observation (preserved), never
        # overwrite the applied fill row (Day40.3 §4.4 contradiction path).
        conflict_obs = record_fill_observation(
            db,
            tenant_id=tenant_id,
            broker=broker,
            provider_order_id=provider_order_id,
            observation_class=ObservationClass.ECONOMIC_FILL,
            d1=d1,
            content_fingerprint=content_fingerprint,
            source_mode=source_mode,
            received_at=received_at,
            raw_observation_id=raw_observation_id,
            provider_trade_id=provider_trade_id,
            fill_quantity=fill_quantity,
            fill_price=fill_price,
            cumulative_after=cumulative_after,
            provider_status=provider_status,
            raw_payload_excerpt=raw_payload_excerpt,
            initial_state=ReconciliationState.CONFLICT,
        )
        _append_lineage(
            db,
            tenant_id=tenant_id,
            provider_order_id=provider_order_id,
            observation_id=conflict_obs.observation_id,
            from_eq_key=key,
            outcome=LineageOutcome.CONTRADICTED,
            evidence_ref="same trade_id, different content fingerprint",
            observed_at=received_at,
        )
        existing.reconciliation_state = ReconciliationState.CONFLICT.value
        existing.updated_at = _utcnow()
        return existing, "CONFLICT", conflict_obs

    # --- WINNER: this transaction created the authoritative fill row ------
    obs = record_fill_observation(
        db,
        tenant_id=tenant_id,
        broker=broker,
        provider_order_id=provider_order_id,
        observation_class=ObservationClass.ECONOMIC_FILL,
        d1=d1,
        content_fingerprint=content_fingerprint,
        source_mode=source_mode,
        received_at=received_at,
        raw_observation_id=raw_observation_id,
        provider_trade_id=provider_trade_id,
        fill_quantity=fill_quantity,
        fill_price=fill_price,
        cumulative_after=cumulative_after,
        provider_status=provider_status,
        raw_payload_excerpt=raw_payload_excerpt,
        initial_state=ReconciliationState.RECONCILED,
    )
    return created, "APPLIED", obs


def _first_reconciled_observation_id(
    db: Session, fill_row: BrokerFillLedgerFill
) -> str | None:
    """observation_id of the fill's earliest RECONCILED observation (the
    duplicate_of target for Lane-B replay evidence), or None."""
    prior = db.execute(
        select(BrokerFillLedgerObservation)
        .where(
            BrokerFillLedgerObservation.tenant_id == fill_row.tenant_id,
            BrokerFillLedgerObservation.provider_order_id == fill_row.provider_order_id,
            BrokerFillLedgerObservation.fill_eq_key == fill_row.fill_eq_key,
            BrokerFillLedgerObservation.observation_class == ObservationClass.ECONOMIC_FILL.value,
            BrokerFillLedgerObservation.reconciliation_state == ReconciliationState.RECONCILED.value,
        )
        .order_by(BrokerFillLedgerObservation.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    return prior.observation_id if prior is not None else None

def _upsert_trade_fill(
    db: Session,
    *,
    tenant_id: str,
    provider_order_id: str,
    fill_eq_key: str,
    fill_quantity: int | None,
    fill_price: str | None,
    cumulative_after: int | None,
) -> BrokerFillLedgerFill | None:
    """ATOMIC first-applier arbitration for a TRADE_ID fill row (Day41.1).

    ``INSERT … ON CONFLICT DO NOTHING RETURNING``: the DATABASE decides —
    not a check-then-insert read — whether THIS transaction created the row:

    - a returned row  ⇒ this transaction is the FIRST APPLIER;
    - zero rows returned ⇒ a concurrent transaction owns the row (or it
      already existed); the caller must re-read (under its own lock) and
      classify the loser outcome (DUPLICATE_FILL / CONFLICT).

    Works on PostgreSQL (byte-identical semantics, real SKIP-LOCKED-era
    concurrency) and SQLite ≥ 3.35 (single-writer; tests).  Flush only —
    never commits (Day41.1 caller-owned transaction contract).
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values = dict(
        tenant_id=tenant_id,
        provider_order_id=provider_order_id,
        fill_eq_key=fill_eq_key,
        fill_identity_type=FillIdentityType.TRADE_ID.value,
        reconciliation_state=ReconciliationState.RECONCILED.value,
        fill_quantity=fill_quantity,
        fill_price=fill_price,
        cumulative_after=cumulative_after,
        observed_count=1,
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name in ("postgresql", "cockroachdb"):
        stmt = pg_insert(BrokerFillLedgerFill).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
        ).returning(BrokerFillLedgerFill.tenant_id)
    else:
        stmt = sqlite_insert(BrokerFillLedgerFill).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
        ).returning(BrokerFillLedgerFill.tenant_id)
    result = db.execute(stmt)
    created = result.first() is not None
    if created:
        # We created the row inside this unit of work; return the ORM
        # identity-mapped instance so callers can read/modify it naturally.
        return db.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.tenant_id == tenant_id,
                BrokerFillLedgerFill.provider_order_id == provider_order_id,
                BrokerFillLedgerFill.fill_eq_key == fill_eq_key,
            )
        ).scalar_one()
    return None  # LOST the race (or row pre-existed) — atomic loser signal


def _fill_fingerprint(db: Session, fill_row: BrokerFillLedgerFill) -> str | None:
    """The economic-content reference fingerprint: the earliest non-conflict
    observation bound to this fill identity."""
    prior = db.execute(
        select(BrokerFillLedgerObservation)
        .where(
            BrokerFillLedgerObservation.tenant_id == fill_row.tenant_id,
            BrokerFillLedgerObservation.provider_order_id == fill_row.provider_order_id,
            BrokerFillLedgerObservation.fill_eq_key == fill_row.fill_eq_key,
            BrokerFillLedgerObservation.observation_class == ObservationClass.ECONOMIC_FILL.value,
            BrokerFillLedgerObservation.reconciliation_state.in_([
                ReconciliationState.RECONCILED.value,
            ]),
        )
        .order_by(BrokerFillLedgerObservation.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    return prior.content_fingerprint if prior is not None else None


def evaluate_lane_c_equivalence(
    db: Session,
    observation: BrokerFillLedgerObservation,
    *,
    delivery_evidence: dict[str, Any] | None = None,
) -> str:
    """Lane C equivalence: delivery-evidence dedup, else AMBIGUOUS quarantine.

    Returns the resulting reconciliation_state value for the observation.

    Delivery dedup (Case A) requires admissible class-A delivery evidence
    (Day40.6 §5): a provider-authoritative delivery identifier.  System-local
    references (class B) suppress only re-ingest bookkeeping — they never
    prove two payloads are one provider delivery (Invariant Y).

    Without evidence: the observation is DISTINCT (never merged).  It joins
    its composite quarantine scope: the composite fill row (created under a
    FOR-UPDATE-serialized upsert) accumulates observed_count; state AMBIGUOUS;
    NO economic canonical fill (fail-closed).
    """
    provider_order_id = observation.provider_order_id
    composite_key = composite_eq_key(
        observation.tenant_id, provider_order_id, observation.d1
    )

    # --- Serialization on the observation row (Day41.1): re-read the
    # observation FOR UPDATE before any decision.  Two workers evaluating the
    # SAME observation concurrently cannot both pass the replay guard below —
    # the second blocks until the first commits, then sees the committed
    # state.  Lock order stays fixed: observation → composite (no cycles).
    # populate_existing forces the identity-mapped instance to refresh from
    # the locked read — without it a stale pre-lock snapshot (PENDING) would
    # defeat the guard.
    locked_observation = db.execute(
        select(BrokerFillLedgerObservation)
        .where(
            BrokerFillLedgerObservation.observation_id == observation.observation_id
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if locked_observation is not None:
        # Same PK ⇒ same identity-map instance when the caller's row was
        # session-attached; rebinding guarantees decisions use locked truth,
        # not a stale session snapshot (DetachedInstance callers rely on the
        # returned state string, the durable state lives on this instance).
        observation = locked_observation

    # --- Replay safety (Day41.1): an already-classified observation is a
    # no-op.  Reprocessing the same observation (stale-lease reclaim,
    # recovery replay) must NEVER re-run equivalence and re-increment the
    # composite scope — the recorded state is the durable truth.
    if observation.reconciliation_state in (
        ReconciliationState.AMBIGUOUS.value,
        ReconciliationState.DUPLICATE.value,
    ):
        return observation.reconciliation_state

    # --- Case A: proven duplicate delivery (class-A evidence only) ---
    # Day40.6 §5/§6: only provider-authoritative (class A) delivery identity
    # may prove two payloads are one provider delivery.  Upstox supplies no
    # such identity today, so this branch never fires on real Upstox traffic
    # (fail-closed); it exists for future providers and is exercised by tests
    # with synthetic class-A evidence.
    delivery_id = _class_a_delivery_value(delivery_evidence or {})
    if delivery_id is not None:
        prior = _find_prior_observation_with_delivery(
            db, observation, delivery_id
        )
        if prior is not None:
            observation.reconciliation_state = ReconciliationState.DUPLICATE.value
            observation.duplicate_of = prior.observation_id
            _append_lineage(
                db,
                tenant_id=observation.tenant_id,
                provider_order_id=provider_order_id,
                observation_id=observation.observation_id,
                from_eq_key=composite_key,
                outcome=LineageOutcome.DUPLICATE_DELIVERY,
                evidence_ref="class-A delivery identity matched prior observation",
                observed_at=observation.received_at,
            )
            # Day41.1: no commit — caller owns the Phase-2 transaction.
            return ReconciliationState.DUPLICATE.value

    # --- Case B: no admissible evidence ⇒ distinct observation, quarantine ---
    db.execute(
        _upsert_composite_fill_stmt(
            db,
            tenant_id=observation.tenant_id,
            provider_order_id=provider_order_id,
            fill_eq_key=composite_key,
            fill_quantity=observation.fill_quantity,
            fill_price=observation.fill_price,
            cumulative_after=observation.cumulative_after,
        )
    )
    # Day40.2 §4.3B: contention on the composite row is serialized by a
    # row lock (FOR UPDATE on PostgreSQL; SQLite single-writer ignores it)
    # so the observed_count increment cannot be lost.  populate_existing
    # refreshes any stale identity-map copy so the increment starts from the
    # committed value, never a session-local snapshot.
    composite_row = db.execute(
        select(BrokerFillLedgerFill)
        .where(
            BrokerFillLedgerFill.tenant_id == observation.tenant_id,
            BrokerFillLedgerFill.provider_order_id == provider_order_id,
            BrokerFillLedgerFill.fill_eq_key == composite_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    composite_row.observed_count = composite_row.observed_count + 1
    composite_row.reconciliation_state = ReconciliationState.AMBIGUOUS.value
    composite_row.fill_identity_type = FillIdentityType.COMPOSITE.value
    composite_row.updated_at = _utcnow()

    observation.reconciliation_state = ReconciliationState.AMBIGUOUS.value
    observation.observed_count = composite_row.observed_count
    _append_lineage(
        db,
        tenant_id=observation.tenant_id,
        provider_order_id=provider_order_id,
        observation_id=observation.observation_id,
        from_eq_key=composite_key,
        outcome=LineageOutcome.NO_CANDIDATE,
        evidence_ref="no admissible delivery evidence; composite quarantined",
        observed_at=observation.received_at,
    )
    # Day41.1: no commit — caller owns the Phase-2 transaction.
    return ReconciliationState.AMBIGUOUS.value


def _upsert_composite_fill_stmt(db: Session, *, tenant_id: str, provider_order_id: str,
                                fill_eq_key: str, fill_quantity: int | None,
                                fill_price: str | None, cumulative_after: int | None):
    """Dialect-portable upsert for the composite quarantine row.

    Dialect is chosen from the SESSION bind (not a module-global engine) so
    the dispatch is correct under test overrides and multi-engine hosting.
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values = dict(
        tenant_id=tenant_id,
        provider_order_id=provider_order_id,
        fill_eq_key=fill_eq_key,
        fill_identity_type=FillIdentityType.COMPOSITE.value,
        reconciliation_state=ReconciliationState.PENDING.value,
        fill_quantity=fill_quantity,
        fill_price=fill_price,
        cumulative_after=cumulative_after,
        observed_count=0,
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name in ("postgresql", "cockroachdb"):
        stmt = pg_insert(BrokerFillLedgerFill).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
        )
    else:
        stmt = sqlite_insert(BrokerFillLedgerFill).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "provider_order_id", "fill_eq_key"]
        )
    return stmt


def _append_lineage(
    db: Session,
    *,
    tenant_id: str,
    provider_order_id: str,
    observation_id: str | None,
    from_eq_key: str,
    outcome: LineageOutcome,
    observed_at: datetime,
    to_eq_key: str | None = None,
    upgrade_trigger: str | None = None,
    trade_ids: list[str] | None = None,
    evidence_ref: str | None = None,
) -> BrokerFillIdentityLineage:
    import json as _json

    row = BrokerFillIdentityLineage(
        lineage_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        provider_order_id=provider_order_id,
        observation_id=observation_id,
        from_eq_key=from_eq_key,
        to_eq_key=to_eq_key,
        upgrade_trigger=upgrade_trigger,
        outcome=outcome.value,
        trade_ids=_json.dumps(trade_ids) if trade_ids else None,
        evidence_ref=evidence_ref,
        observed_at=observed_at,
    )
    db.add(row)
    return row


def _class_a_delivery_value(evidence: dict[str, Any] | None) -> str | None:
    """Extract the provider-authoritative (class A) delivery identity value.

    Returns None when no class-A entry exists — the only outcome for current
    Upstox traffic (Day40.6 §6), which supplies no delivery identity at all.
    """
    for entry in (evidence or {}).values():
        if isinstance(entry, dict) and entry.get("class") == "A" and entry.get("value"):
            return str(entry["value"])
    return None


def _find_prior_observation_with_delivery(
    db: Session,
    observation: BrokerFillLedgerObservation,
    delivery_id: str,
) -> BrokerFillLedgerObservation | None:
    """Find a prior ECONOMIC_FILL observation whose raw row carries the same
    class-A delivery identity.  Delivery identity lives on the raw ingest row
    (Day40.6 §2); the match is evaluated in Python over the bounded candidate
    set (same tenant/broker/order/lane)."""
    candidates = db.execute(
        select(BrokerFillLedgerObservation)
        .where(
            BrokerFillLedgerObservation.tenant_id == observation.tenant_id,
            BrokerFillLedgerObservation.broker == observation.broker,
            BrokerFillLedgerObservation.provider_order_id == observation.provider_order_id,
            BrokerFillLedgerObservation.observation_id != observation.observation_id,
            BrokerFillLedgerObservation.observation_class == ObservationClass.ECONOMIC_FILL.value,
            BrokerFillLedgerObservation.duplicate_of.is_(None),
        )
        .order_by(BrokerFillLedgerObservation.created_at.asc())
    ).scalars().all()
    for prior in candidates:
        if not prior.raw_observation_id:
            continue
        from app.broker_sync.raw_ingress import BrokerRawObservation, get_delivery_evidence

        raw_row = db.execute(
            select(BrokerRawObservation).where(
                BrokerRawObservation.raw_observation_id == prior.raw_observation_id,
            )
        ).scalar_one_or_none()
        if raw_row is None:
            continue
        if _class_a_delivery_value(get_delivery_evidence(raw_row)) == delivery_id:
            return prior
    return None


# ---------------------------------------------------------------------------
# Alias upgrade — Day40.3 §4.3 (C → T1 / split / contradiction)
# ---------------------------------------------------------------------------

def upgrade_composite_to_trade(
    db: Session,
    *,
    tenant_id: str,
    provider_order_id: str,
    composite_key: str,
    trade_ids: list[str],
    trigger: str,
    observation_ids: list[str] | None = None,
    evidence_ref: str | None = None,
    trade_quantities: dict[str, int] | None = None,
) -> list[BrokerFillLedgerFill]:
    """Upgrade a composite quarantine scope to authoritative TRADE_ID fill rows.

    Exactly one trade_id ⇒ UPGRADED (alias AUTHORITATIVE, one fill row).
    Multiple trade_ids ⇒ SPLIT (alias SPLIT, one fill row per trade).

    SPLIT conservation: when ``trade_quantities`` supplies every trade's
    quantity and the composite carries cumulative_after, the sum MUST equal
    the cumulative — else CONTRADICTED.  When quantities are absent, rows are
    created with quantity None and the outcome is SPLIT: missing data never
    manufactures a contradiction (Day40.5 fail-closed principle).

    The composite fill row is frozen (SUPERSEDED + frozen_reason) — NEVER
    deleted, NEVER re-keyed.
    """
    alias = db.execute(
        select(BrokerFillIdentityAlias).where(
            BrokerFillIdentityAlias.tenant_id == tenant_id,
            BrokerFillIdentityAlias.provider_order_id == provider_order_id,
            BrokerFillIdentityAlias.from_eq_key == composite_key,
        )
    ).scalar_one_or_none()

    created_rows: list[BrokerFillLedgerFill] = []
    outcome: LineageOutcome
    alias_state: AliasState

    composite_row = db.execute(
        select(BrokerFillLedgerFill).where(
            BrokerFillLedgerFill.tenant_id == tenant_id,
            BrokerFillLedgerFill.provider_order_id == provider_order_id,
            BrokerFillLedgerFill.fill_eq_key == composite_key,
        )
    ).scalar_one_or_none()

    if len(trade_ids) == 1:
        outcome, alias_state = LineageOutcome.UPGRADED, AliasState.AUTHORITATIVE
        created_rows.append(_ensure_trade_fill_row(
            db, tenant_id, provider_order_id, trade_ids[0], composite_row,
            fill_quantity=(trade_quantities or {}).get(trade_ids[0]),
            allow_composite_quantity_fallback=True,
        ))
    else:
        # SPLIT: conservation is enforced ONLY when per-trade quantities are
        # supplied (absence of data is not a contradiction).  The ambiguous
        # composite's last-seen quantity is NEVER copied per-trade — it
        # describes one observation of unknown position among the split.
        outcome, alias_state = LineageOutcome.SPLIT, AliasState.SPLIT
        quantities = trade_quantities or {}
        for tid in trade_ids:
            created_rows.append(_ensure_trade_fill_row(
                db, tenant_id, provider_order_id, tid, composite_row,
                fill_quantity=quantities.get(tid),
                allow_composite_quantity_fallback=False,
            ))
        if (
            composite_row is not None
            and composite_row.cumulative_after is not None
            and trade_ids
            and all(tid in quantities for tid in trade_ids)
        ):
            total = sum(quantities[tid] for tid in trade_ids)
            if total != composite_row.cumulative_after:
                outcome, alias_state = LineageOutcome.CONTRADICTED, AliasState.CONTRADICTED

    if alias is None:
        alias = BrokerFillIdentityAlias(
            tenant_id=tenant_id,
            provider_order_id=provider_order_id,
            from_eq_key=composite_key,
            to_eq_key=(trade_eq_key(trade_ids[0]) if len(trade_ids) == 1 else None),
            alias_state=alias_state.value,
        )
        db.add(alias)
    else:
        alias.to_eq_key = (
            trade_eq_key(trade_ids[0]) if len(trade_ids) == 1 else alias.to_eq_key
        )
        alias.alias_state = alias_state.value
        alias.last_transition_at = _utcnow()

    if composite_row is not None:
        composite_row.reconciliation_state = ReconciliationState.SUPERSEDED.value
        composite_row.frozen_reason = "SUPERSEDED_BY_ALIAS"
        composite_row.updated_at = _utcnow()

    _append_lineage(
        db,
        tenant_id=tenant_id,
        provider_order_id=provider_order_id,
        observation_id=(observation_ids[0] if observation_ids else None),
        from_eq_key=composite_key,
        to_eq_key=(trade_ids[0] if len(trade_ids) == 1 else None),
        upgrade_trigger=trigger,
        outcome=outcome,
        trade_ids=trade_ids,
        evidence_ref=evidence_ref,
        observed_at=_utcnow(),
    )
    # Day41.1: no commit — caller owns the Phase-2 transaction.
    return created_rows


def _ensure_trade_fill_row(
    db: Session,
    tenant_id: str,
    provider_order_id: str,
    trade_id: str,
    composite_row: BrokerFillLedgerFill | None,
    *,
    fill_quantity: int | None = None,
    allow_composite_quantity_fallback: bool = False,
) -> BrokerFillLedgerFill:
    """Create (or idempotently return) the authoritative TRADE_ID fill row.

    Quantity precedence: explicit ``fill_quantity`` (from trade history)
    first; the composite snapshot quantity only as a fallback for the
    single-trade UPGRADE case (``allow_composite_quantity_fallback``); never
    invented for splits without quantities."""
    key = trade_eq_key(trade_id)
    row = db.execute(
        select(BrokerFillLedgerFill).where(
            BrokerFillLedgerFill.tenant_id == tenant_id,
            BrokerFillLedgerFill.provider_order_id == provider_order_id,
            BrokerFillLedgerFill.fill_eq_key == key,
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    effective_quantity = fill_quantity
    if (
        effective_quantity is None
        and allow_composite_quantity_fallback
        and composite_row is not None
        and composite_row.fill_quantity is not None
    ):
        effective_quantity = composite_row.fill_quantity
    row = BrokerFillLedgerFill(
        tenant_id=tenant_id,
        provider_order_id=provider_order_id,
        fill_eq_key=key,
        fill_identity_type=FillIdentityType.TRADE_ID.value,
        reconciliation_state=ReconciliationState.RECONCILED.value,
        fill_quantity=effective_quantity,
        fill_price=(composite_row.fill_price if composite_row else None),
        cumulative_after=(composite_row.cumulative_after if composite_row else None),
        observed_count=1,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Phase 9 — status/fill edge contract (Day40.5 §5)
# ---------------------------------------------------------------------------

def classify_order_payload_edge(
    *,
    provider_status: str,
    quantity: int | None,
    filled_quantity: int | None,
) -> tuple[ObservationClass, list[ObservationClass]]:
    """Day40.5 §5 edge rules — deterministic status/fill separation (Invariant V).

    Returns (primary_class, extra_classes).  Extra classes are additional
    EXPLICIT observations derived from the same payload (never implicit).

    - complete + filled < quantity ⇒ INVALID_OBSERVATION (quarantine; no
      silent reinterpretation as partial)
    - open + filled > 0 ⇒ ORDER_STATE + ECONOMIC_FILL (two distinct;
      Day41 Phase 9 enumerated case)
    - otherwise ⇒ ORDER_STATE (fill observation only from explicit fill-bearing
      field sets — never manufactured from absence of data).  Terminal
      complete snapshots carry fill totals in Π_A order state; authoritative
      per-fill rows come from Lane B trade history.
    """
    if provider_status == "complete" and quantity is not None and filled_quantity is not None \
            and filled_quantity < quantity:
        return ObservationClass.INVALID_OBSERVATION, []
    classes: list[ObservationClass] = [ObservationClass.ORDER_STATE]
    if provider_status == "open" and filled_quantity is not None and filled_quantity > 0:
        classes.append(ObservationClass.ECONOMIC_FILL)
    return classes[0], classes[1:]
