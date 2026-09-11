"""Day41 Phase 3/4 — Durable raw-ingress models (Day40.6 §1/§2).

The raw observation is the durable record of a received provider payload.
Its lifecycle is TWO-PHASE (Day40.6 §1):

  Phase 1 — RAW INGEST COMMIT: a dedicated transaction whose ONLY write is
  the BrokerRawObservation row.  Committed before any parsing, normalization,
  classification, Task2 work, or projection.  Downstream failure can never
  roll the raw evidence back (Invariants AB/AC).

  Phase 2 — PROCESSING: separate transaction(s).  Failures are recorded ON
  the raw row (processing_status/last_error) without ever touching
  raw_payload.  Recovery re-claims PENDING/FAILED/stale-IN_PROGRESS rows
  with FOR UPDATE SKIP LOCKED; reprocessing is idempotent by key.
"""
from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Statuses (Day40.6 §2)
# ---------------------------------------------------------------------------

class IngestionStatus(str, enum.Enum):
    """ingestion_status — how far the payload has been understood.

    RAW_RECEIVED: bytes committed, nothing parsed.
    RAW_NORMALIZED: parsed, mandatory fields + D1/FPv2 derived and recorded.
    RAW_CLASSIFIED: lane routed + delivery/economic dedup decided.
    CANONICALIZED: canonical event(s) emitted/authorized.
    NORMALIZATION_FAILED / CLASSIFICATION_FAILED: honest failure states.
    """

    RAW_RECEIVED = "RAW_RECEIVED"
    RAW_NORMALIZED = "RAW_NORMALIZED"
    RAW_CLASSIFIED = "RAW_CLASSIFIED"
    CANONICALIZED = "CANONICALIZED"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    CLASSIFICATION_FAILED = "CLASSIFICATION_FAILED"


class ProcessingStatus(str, enum.Enum):
    """processing_status — worker claim/effect lifecycle (Phase 2 only)."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


# Lease duration for stale IN_PROGRESS reclamation (Day40.6 §1-D).
DEFAULT_LEASE_SECONDS = 300


# ---------------------------------------------------------------------------
# Model — authoritative raw evidence, byte-preserving (Day40.6 §2)
# ---------------------------------------------------------------------------

class BrokerRawObservation(Base):
    """Durable raw provider payload — the source-of-truth evidence record.

    ``raw_payload`` is BYTEA (LargeBinary): the EXACT bytes received from the
    provider.  Parsed JSON (if any) is secondary and may be stored separately;
    it is never the authoritative representation (Day41 Phase 3 requirement).

    Immutable columns (never updated after Phase 1 commit): raw_observation_id,
    raw_payload, received_at, source_mode, tenant_id, broker, created_at.
    Mutable columns (Phase 2 only): d1, content_fingerprint, provider_order_id,
    provider_trade_id, ingestion_status, processing_status, attempt_count,
    last_error, processing_completed_at, lease_expires_at.
    """

    __tablename__ = "broker_raw_observation"

    raw_observation_id: Mapped[str] = mapped_column(
        String(36), primary_key=True  # UUID4 hex-with-dashes; portable across SQLite/PG
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(64), nullable=False)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False)

    # BYTEA: exact provider bytes.  NEVER derived from a parsed copy.
    raw_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # Class-labeled delivery evidence (A=provider-authoritative, B=system-local,
    # C=correlation-only) — Day40.6 §5.  JSON-encoded by the caller.
    delivery_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    provider_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    provider_trade_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    d1: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    content_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    ingestion_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=IngestionStatus.RAW_RECEIVED.value
    )
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProcessingStatus.PENDING.value
    )

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Worker lease (Day40.6 §1-D): stamped AT CLAIM TIME; a stale lease is one
    # whose expiry has passed.  Measuring the lease from ingest time would let
    # a worker actively processing an OLD observation have its row stolen
    # instantly — the lease must start when the claim starts.
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Non-unique lookup index — (d1, fp) is NEVER a uniqueness constraint
        # on raw observations (Day40.5 §5.2; fill lanes must never dedup here).
        Index("ix_broker_raw_observation_d1_fp", "tenant_id", "broker", "d1", "content_fingerprint"),
        Index("ix_broker_raw_observation_processing", "processing_status", "created_at"),
    )


# ---------------------------------------------------------------------------
# Phase 1 — raw ingest commit (the ONLY write of its transaction)
# ---------------------------------------------------------------------------

def commit_raw_observation(
    db: Session,
    *,
    tenant_id: str,
    broker: str,
    source_mode: str,
    raw_payload: bytes,
    received_at: datetime | None = None,
    delivery_evidence: Optional[Mapping[str, Any]] = None,
    provider_order_id: str | None = None,
    provider_trade_id: str | None = None,
) -> BrokerRawObservation:
    """Phase 1: durably commit the raw provider payload.

    Day40.6 §1-A: this function performs the raw INSERT and COMMITS in a
    dedicated transaction.  Callers MUST NOT wrap it in a larger transaction:
    the whole point is that downstream work begins only after this commit
    returns (Invariants AB/AC).

    Note: the caller owns the session's transaction policy for ordinary work;
    here we explicitly commit because Phase 1 is defined as its own atomic
    unit.  On any failure the session is rolled back and the exception
    propagates (nothing was accepted; the channel's redelivery re-ingests).
    """
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    if not isinstance(raw_payload, (bytes, bytearray)):
        raise TypeError("raw_payload must be bytes (byte-preserving evidence)")
    row = BrokerRawObservation(
        raw_observation_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        broker=broker,
        received_at=received_at,
        source_mode=source_mode,
        raw_payload=bytes(raw_payload),
        delivery_evidence=(
            _encode_delivery_evidence(delivery_evidence)
            if delivery_evidence is not None
            else None
        ),
        provider_order_id=provider_order_id,
        provider_trade_id=provider_trade_id,
        ingestion_status=IngestionStatus.RAW_RECEIVED.value,
        processing_status=ProcessingStatus.PENDING.value,
    )
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return row


def _encode_delivery_evidence(evidence: Mapping[str, Any]) -> str:
    """Persist delivery evidence with explicit class labels (Invariant AE).

    Expected shape: {"<source>": {"class": "A"|"B"|"C", "value": ...}, ...}
    Serialized as compact JSON; stored as text for SQLite/PG portability.
    """
    import json

    labeled: dict[str, Any] = {}
    for source, entry in evidence.items():
        if isinstance(entry, Mapping) and "class" in entry:
            labeled[source] = dict(entry)
        else:
            # Unlabeled evidence is recorded as class C (correlation only) —
            # never silently elevated to provider-authoritative.
            labeled[source] = {"class": "C", "value": entry}
    return json.dumps(labeled, sort_keys=True, separators=(",", ":"))


def get_delivery_evidence(row: BrokerRawObservation) -> dict[str, Any]:
    import json

    if not row.delivery_evidence:
        return {}
    return json.loads(row.delivery_evidence)


# ---------------------------------------------------------------------------
# Phase 2 — claim + recovery loop (FOR UPDATE SKIP LOCKED)
# ---------------------------------------------------------------------------

def claim_raw_observations(
    db: Session,
    *,
    limit: int = 50,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    worker_id: str = "worker",
) -> list[BrokerRawObservation]:
    """Claim up to ``limit`` raw observations for processing.

    Selects PENDING / FAILED rows plus IN_PROGRESS rows whose claim lease has
    expired (``lease_expires_at`` in the past — stale leases from crashed
    workers), locking them with ``FOR UPDATE SKIP LOCKED`` so concurrent
    workers never fight over a row.  On PostgreSQL this emits the real SKIP
    LOCKED clause; on SQLite (tests) the dialect omits it and the
    single-writer model makes it moot.

    The claim writes processing_status=IN_PROGRESS, increments attempt_count,
    and stamps lease_expires_at = now + lease_seconds, COMMITTED
    independently — a crash right after claim leaves only a stale lease,
    which a later claim reclaims (at-least-once).

    Returned rows are fully loaded and remain usable after the session ends
    (crash/replay): the claim commit is made with expire_on_commit disabled,
    so attributes are loaded and never require a session-bound refresh.
    """
    now = datetime.now(timezone.utc)

    def _claim_predicate():
        return BrokerRawObservation.processing_status.in_([
            ProcessingStatus.PENDING.value,
            ProcessingStatus.FAILED.value,
        ]) | (
            (BrokerRawObservation.processing_status == ProcessingStatus.IN_PROGRESS.value)
            & (BrokerRawObservation.processing_completed_at.is_(None))
            & (
                (BrokerRawObservation.lease_expires_at.is_(None))
                | (BrokerRawObservation.lease_expires_at < now)
            )
        )

    try:
        stmt = (
            select(BrokerRawObservation)
            .where(_claim_predicate())
            .order_by(BrokerRawObservation.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list(db.execute(stmt).scalars().all())
    except Exception:
        # Databases without FOR UPDATE support fall back to a plain read.
        stmt = (
            select(BrokerRawObservation)
            .where(_claim_predicate())
            .order_by(BrokerRawObservation.created_at.asc())
            .limit(limit)
        )
        rows = list(db.execute(stmt).scalars().all())

    for row in rows:
        row.processing_status = ProcessingStatus.IN_PROGRESS.value
        row.attempt_count = row.attempt_count + 1
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
    if rows:
        # Commit WITHOUT expiring: claimed rows stay loaded so they remain
        # readable even if the worker's session closes (crash/replay), and
        # callers' existing references to these rows stay valid.
        previous_expire = db.expire_on_commit
        db.expire_on_commit = False
        try:
            db.commit()
        finally:
            db.expire_on_commit = previous_expire
    return rows


def mark_processing_result(
    db: Session,
    row: BrokerRawObservation,
    *,
    ingestion_status: IngestionStatus | None = None,
    processing_status: ProcessingStatus | None = None,
    error: str | None = None,
    d1: str | None = None,
    content_fingerprint: str | None = None,
    provider_order_id: str | None = None,
    provider_trade_id: str | None = None,
) -> None:
    """Record a Phase-2 outcome ON the raw row (never touching raw_payload).

    ``row`` may be ATTACHED (same session) or DETACHED (claim_raw_observations
    returns detached rows — a worker may mark results after re-attaching to a
    new session, e.g. after a crash/replay).  merge() handles both and issues
    no writes beyond the explicit attribute changes below.
    """
    row = db.merge(row)
    if ingestion_status is not None:
        row.ingestion_status = ingestion_status.value
    if processing_status is not None:
        row.processing_status = processing_status.value
        # An outcome is recorded → the lease is no longer held.
        row.lease_expires_at = None
    if error is not None:
        row.last_error = error
    if d1 is not None:
        row.d1 = d1
    if content_fingerprint is not None:
        row.content_fingerprint = content_fingerprint
    if provider_order_id is not None:
        row.provider_order_id = provider_order_id
    if provider_trade_id is not None:
        row.provider_trade_id = provider_trade_id
    if processing_status in (ProcessingStatus.SUCCEEDED, ProcessingStatus.QUARANTINED):
        row.processing_completed_at = datetime.now(timezone.utc)
    db.commit()


def process_pending_observations(
    db: Session,
    processor: Callable[[Session, BrokerRawObservation], str],
    *,
    limit: int = 50,
    worker_id: str = "worker",
) -> list[tuple[str, str]]:
    """Recovery loop: claim then process, recording per-row outcomes.

    ``processor`` is a Phase-2 callable receiving (session, row); it records
    its own outcome on the row via mark_processing_result.  The loop reports
    the row's resulting processing_status in BOTH paths — success and
    exception (captured as FAILED + last_error; the raw payload is NEVER
    rewritten) — so outcomes share one coherent taxonomy.

    Returns [(raw_observation_id, processing_status), ...].
    """
    outcomes: list[tuple[str, str]] = []
    rows = claim_raw_observations(db, limit=limit, worker_id=worker_id)
    for row in rows:
        try:
            processor(db, row)
            outcomes.append((row.raw_observation_id, row.processing_status))
        except Exception as exc:  # noqa: BLE001 — recovery loop must survive any failure
            logger.warning(
                "raw observation %s processing failed: %s",
                row.raw_observation_id, exc,
            )
            mark_processing_result(
                db, row,
                processing_status=ProcessingStatus.FAILED,
                error=str(exc),
            )
            outcomes.append((row.raw_observation_id, row.processing_status))
    return outcomes
