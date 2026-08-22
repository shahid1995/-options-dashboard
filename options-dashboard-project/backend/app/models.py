from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaperAccount(Base):
    """Per-user simulated account (starting capital) backing the journal."""

    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    starting_capital: Mapped[float] = mapped_column(Float, default=500000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Trade(Base):
    """A paper trade: one strategy execution, made up of one or more legs.

    Phase 5.0: the authoritative execution layer lives in
    ``StrategyExecution`` / ``PaperOrder`` / ``Position`` /
    ``PaperTransaction``; this table remains the user-facing JOURNAL record
    (account stats, trade log). Every journal record created by the
    authoritative engine carries the same ``strategy_execution_id`` as its
    execution so journal and portfolio stay reconcilable, and
    ``client_order_id`` guards against duplicate journal writes on retries.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    strategy_tag: Mapped[str] = mapped_column(String(64), default="Custom")
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | closed
    # Net entry money flow in rupees (negative = net credit received, e.g. a
    # short vertical spread; positive = net debit paid, e.g. a long spread).
    entry_net: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    # Phase 5.0 linkage to the authoritative execution layer (nullable so the
    # legacy journal path keeps working unchanged; columns added to existing
    # databases by ``db.init_db``'s ensure_column migration).
    strategy_execution_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    legs: Mapped[list["Leg"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan", order_by="Leg.id"
    )


class Leg(Base):
    """One option leg of a paper trade."""

    __tablename__ = "legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    expiration_date: Mapped[str] = mapped_column(String(10))
    strike_price: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(8))  # call | put
    action: Mapped[str] = mapped_column(String(8))  # buy | sell
    premium: Mapped[float] = mapped_column(Float)  # simulated premium per unit
    quantity: Mapped[int] = mapped_column(Integer)  # number of lots
    lot_size: Mapped[int] = mapped_column(Integer)  # contracts per lot
    entry_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    trade: Mapped[Trade] = relationship(back_populates="legs")


# ---- Phase 5.0: server-authoritative paper trading domain ----------------
#
# The backend is the single source of truth for orders, fills, positions,
# cash and P&L. The four tables below are the authoritative layer; the
# legacy ``Trade``/``Leg`` journal rows are written by the same engine (and
# carry the same ``strategy_execution_id``) so the journal UI keeps working.
# Quantities are LOTS everywhere; rupee exposure scales by lot_size.


class StrategyExecution(Base):
    """One strategy execution: a grouped multi-leg paper trade.

    ``client_order_id`` is the idempotency key at the execution boundary:
    the unique per-user constraint means a retried request can never create
    a second execution, a second set of orders, double-counted cash or
    duplicate journal records.

    ``status`` uses the execution states PENDING / FILLED / PARTIAL /
    FAILED / CANCELLED. The current engine pre-validates everything (market
    gate, chain data, prices) before writing, so it executes atomically:
    a successful request is FILLED with every order filled; any failure
    writes nothing (no misleading "fully executed" results).
    """

    __tablename__ = "strategy_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    execution_id: Mapped[str] = mapped_column(String(40), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64))
    strategy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy_tag: Mapped[str] = mapped_column(String(64), default="Custom")
    symbol: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(12), default="PENDING")
    # Net entry money flow in rupees — same convention as ``Trade.entry_net``:
    # positive = net debit paid, negative = net credit received.
    entry_net: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    # Phase 6.10: V2 execution audit trail (JSON in Text for SQLite compat)
    execution_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 7.0: trade annotations
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of strings
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "client_order_id", name="uq_execution_client_order"),)


class PaperOrder(Base):
    """One paper order (one leg of an entry, or one exit fill).

    Status lifecycle: PENDING → FILLED / PARTIALLY_FILLED / CANCELLED /
    REJECTED. The current engine fills atomically (PENDING → FILLED), but the
    full state model and transition validator exist so future async/partial
    fills cannot violate the lifecycle.

    ``client_order_id`` is the per-order idempotency key (unique per user);
    exits reuse it so duplicate exit requests return the original result.
    """

    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64))
    execution_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # entry (part of a strategy execution) | exit (closes a position)
    kind: Mapped[str] = mapped_column(String(8), default="entry")
    symbol: Mapped[str] = mapped_column(String(16))
    expiry: Mapped[str] = mapped_column(String(10))
    strike: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(8))  # call | put
    action: Mapped[str] = mapped_column(String(8))  # buy | sell (fill direction)
    quantity: Mapped[int] = mapped_column(Integer)  # lots
    lot_size: Mapped[int] = mapped_column(Integer)  # contracts per lot
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)  # lots filled
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_source: Mapped[str] = mapped_column(String(16), default="market")
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)  # exits only
    rejected_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    journal_leg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # legacy Leg row
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (UniqueConstraint("user_id", "client_order_id", name="uq_order_client_order"),)


class Position(Base):
    """Netted paper position for one tradable instrument.

    Identity: user + symbol + expiry + strike + option_type (unique).
    ``net_quantity`` is signed LOTS: BUY = +, SELL = −. Same-direction fills
    update the weighted-average entry price; opposite-direction fills realize
    P&L against that average. A zero net quantity marks the position CLOSED
    but keeps the record queryable (history is never silently overwritten).
    """

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    expiry: Mapped[str] = mapped_column(String(10))
    strike: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(8))  # call | put
    net_quantity: Mapped[int] = mapped_column(Integer, default=0)  # signed lots
    average_entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    lot_size: Mapped[int] = mapped_column(Integer, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)  # rupees
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | closed
    strategy_execution_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "symbol", "expiry", "strike", "option_type", name="uq_position_instrument"
        ),
    )


class PaperTransaction(Base):
    """Auditable cash-ledger record for every cash-affecting paper execution.

    ``amount`` is the signed rupee change applied to available cash
    (buy pays out = negative, sell receives = positive). Available cash is
    derived as ``starting_capital + SUM(amount)`` — the ledger is the only
    writer, so cash can always be reconciled to recorded transactions.
    """

    __tablename__ = "paper_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    execution_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(20))  # ENTRY_DEBIT | ENTRY_CREDIT | EXIT_DEBIT | EXIT_CREDIT
    amount: Mapped[float] = mapped_column(Float)  # signed rupees applied to cash
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class StrategyLegExposure(Base):
    """Per-execution strategy-leg attribution (Phase 6.5.0.1).

    The netted ``Position`` remains the AUTHORITATIVE portfolio exposure
    (one row per instrument, signed ``net_quantity``). Because multiple
    executions can trade the same instrument, the position alone cannot
    answer "how much of WHICH execution's leg is still open" — this table
    preserves exactly that attribution so future strategy-scoped exits can
    target BUY CE / SELL CE / BUY PE / SELL PE / individual legs without
    guessing.

    One row per FILLED entry ``PaperOrder`` (unique per ``order_id``).
    ``action`` is the strategy-leg action as executed — NEVER derived from
    ``Position.net_quantity``. ``original_quantity`` / ``remaining_quantity``
    are LOTS.

    Reconciliation invariant: for every position, the signed sum of its
    exposures' remaining_quantity (buy = +, sell = −) equals the position's
    net_quantity. Exits reduce the position's dominant side (long →
    buy-action legs, short → sell-action legs) deterministically FIFO so the
    invariant holds; when it cannot be maintained, exits fail safely or
    leave attribution untouched — the position engine is authoritative
    either way. No LTP / average entry price / realized P&L / cash / margin
    is duplicated here — those stay owned by the execution / position /
    accounting layer.
    """

    __tablename__ = "strategy_leg_exposures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    execution_id: Mapped[str] = mapped_column(String(40), index=True)
    position_id: Mapped[int] = mapped_column(Integer, index=True)  # netted positions.id
    order_id: Mapped[int] = mapped_column(Integer)  # source entry PaperOrder.id
    symbol: Mapped[str] = mapped_column(String(16))
    expiry: Mapped[str] = mapped_column(String(10))
    strike: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(8))  # call | put
    action: Mapped[str] = mapped_column(String(8))  # buy | sell (strategy leg action)
    original_quantity: Mapped[int] = mapped_column(Integer)  # lots
    remaining_quantity: Mapped[int] = mapped_column(Integer)  # lots still attributed open
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "order_id", name="uq_exposure_source_order"),
    )


class ExitExposureAllocation(Base):
    """Junction table: maps exit orders to the exposure reductions they caused.

    One exit can reduce multiple exposures (FIFO spanning exposures).
    One exposure can be reduced by multiple partial exits.
    This is a many-to-many relationship.

    ``exit_order_id`` → PaperOrder (exit, kind='exit')
    ``exposure_id``   → StrategyLegExposure (the entry exposure reduced)
    ``quantity``      → lots removed from the exposure by this exit

    Written in the SAME transaction as the exit fill by
    ``apply_exit_allocations()``.  Historical exits (before Phase 7.2A)
    have no allocation rows — analytics falls back to the legacy dict
    lookup for those.
    """

    __tablename__ = "exit_exposure_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    exit_order_id: Mapped[int] = mapped_column(Integer, index=True)
    exposure_id: Mapped[int] = mapped_column(Integer, index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BulkExitRecord(Base):
    """Idempotency record for ONE bulk exit operation (Phase 5.2).

    Bulk exits (EXIT STRATEGY / EXIT ALL) are atomic operations that can
    close many positions at once. The same ``client_order_id`` is never
    executed twice: the FIRST result is stored here (positions, groups,
    totals) and every replay returns the ORIGINAL result with
    ``duplicated=True`` — no second exit orders, no double cash-ledger
    entries, no duplicate journal records.

    ``scope`` is STRATEGY (one strategy execution) or ACCOUNT (every open
    position of the user).
    """

    __tablename__ = "bulk_exit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(12))  # STRATEGY | ACCOUNT
    strategy_execution_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(12))  # SUCCESS | NO_POSITIONS | FAILED | PARTIAL
    requested_count: Mapped[int] = mapped_column(Integer, default=0)
    exited_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    total_realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    cash_change: Mapped[float] = mapped_column(Float, default=0.0)
    positions_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of position outcomes
    groups_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of group outcomes
    errors_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of error strings
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("user_id", "client_order_id", name="uq_bulk_exit_client_order"),)


class StrategyTemplate(Base):
    """A user-created reusable strategy template (Phase 6.7).

    Stores the named leg configuration so the user can save, edit, duplicate,
    and re-use custom strategies without re-building them from scratch.

    ``user_id`` enforces strict ownership — one user can never see or modify
    another user's templates. Editing, renaming, duplicating or deleting a
    template NEVER affects historical executions, positions, exposures,
    orders, journal or P&L because there is NO foreign key from
    ``StrategyExecution`` to ``StrategyTemplate`` — the template is a
    reusable blueprint, not a live reference.
    """

    __tablename__ = "strategy_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    symbol: Mapped[str] = mapped_column(String(16), default="NIFTY")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    legs: Mapped[list["StrategyTemplateLeg"]] = relationship(
        back_populates="template", cascade="all, delete-orphan", order_by="StrategyTemplateLeg.position"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_template_user_name"),
    )


class StrategyTemplateLeg(Base):
    """One leg of a user-created strategy template (Phase 6.7 / 6.8B).

    Each leg stores the strike/expiry definition for a strategy leg.

    V1 (Phase 6.7 — fixed-leg templates):
        ``strike_mode = "fixed"``, ``strike`` is the absolute strike.
        ``expiry_mode = "fixed"``, ``expiry`` is the YYYY-MM-DD date.
        ``formula_version = 1``.

    V2 (Phase 6.8B — dynamic formula templates):
        ``strike_mode`` selects the strike resolution algorithm.
        ``expiry_mode`` selects the expiry resolution algorithm.
        ``formula_version = 2``.

    ``strike`` and ``expiry`` remain stored even for V2 legs — they hold
    the last-resolved or preview value and serve as backward-compatible
    display fields, but they are NOT authoritative formula input when
    ``strike_mode != "fixed"`` or ``expiry_mode != "fixed"``.

    ``price`` is informational only — never used for execution; the
    authoritative fill price is resolved from the live option chain at
    execution time.
    """

    __tablename__ = "strategy_template_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("strategy_templates.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)  # ordering
    action: Mapped[str] = mapped_column(String(8))  # buy | sell
    option_type: Mapped[str] = mapped_column(String(8))  # call | put
    strike: Mapped[float] = mapped_column(Float)  # fixed strike (V1) or last-resolved (V2)
    expiry: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD (V1) or last-resolved (V2)
    quantity: Mapped[int] = mapped_column(Integer, default=1)  # lots
    lot_size: Mapped[int] = mapped_column(Integer, default=50)  # contracts per lot
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # informational only
    # Phase 6.8B: dynamic formula fields
    strike_mode: Mapped[str] = mapped_column(String(20), default="fixed")  # fixed | atm | atm_offset_steps | atm_offset | spot_offset | delta
    strike_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)  # atm_offset_steps: integer step offset
    strike_offset_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # percentage offset (reserved for future use)
    target_delta: Mapped[float | None] = mapped_column(Float, nullable=True)  # delta mode: target delta value
    expiry_mode: Mapped[str] = mapped_column(String(20), default="fixed")  # fixed | current_week | next_week | monthly | dte_range
    expiry_dte_min: Mapped[int | None] = mapped_column(Integer, nullable=True)  # dte_range mode: minimum days-to-expiry
    expiry_dte_max: Mapped[int | None] = mapped_column(Integer, nullable=True)  # dte_range mode: maximum days-to-expiry
    formula_version: Mapped[int] = mapped_column(Integer, default=1)  # 1 = legacy fixed, 2 = dynamic formula
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    template: Mapped["StrategyTemplate"] = relationship(back_populates="legs")


class GexSnapshot(Base):
    """One stored GEX snapshot (Phase 7.3 data foundation).

    Persists the complete GEX state at one instant so that historical ΔGEX,
    migration, and decomposition can be computed without re-fetching the
    chain.  Every field that was used to compute GEX is preserved so the
    calculation is reproducible.

    ``spot``, ``call_gex``, ``put_gex``, ``net_gex`` are chain-level totals.
    ``strike_data`` is a JSON array containing per-strike broker-observed
    gamma, OI, IV and the resulting GEX — enough to reconstruct canonical
    chain rows and reproduce the exact GEX calculation.

    ``expiry_data`` is a JSON array of per-expiry totals.
    ``methodology_metadata`` records the formula, sign convention, and
    unit contract used at capture time.
    """

    __tablename__ = "gex_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Identity
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    expiry: Mapped[str] = mapped_column(String(10))
    # Market state at capture
    spot: Mapped[float] = mapped_column(Float)
    # Methodology
    methodology: Mapped[str] = mapped_column(String(32), default="GEX_STANDARD_V1")
    sign_convention: Mapped[str] = mapped_column(String(32), default="NAIVE_DEALER_CONVENTION")
    # Chain-level totals (computed at capture time)
    call_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_gex: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Data quality
    availability_status: Mapped[str] = mapped_column(String(16))  # available|partial|unavailable|invalid
    valid_strike_count: Mapped[int] = mapped_column(Integer, default=0)
    total_strike_count: Mapped[int] = mapped_column(Integer, default=0)
    # Capture metadata
    chain_age_ms: Mapped[float | None] = mapped_column(Float, nullable=True)  # ms since broker quote
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # Strike-level detail (JSON for SQLite compat)
    strike_data: Mapped[str] = mapped_column(Text, default="[]")
    # Expiry-level detail (JSON)
    expiry_data: Mapped[str] = mapped_column(Text, default="[]")
    # Methodology metadata (JSON)
    methodology_metadata: Mapped[str] = mapped_column(Text, default="{}")


class IVObservation(Base):
    """One stored implied-volatility observation (Phase 4.1 data foundation).

    Nothing records observations yet — the collection job is deliberately NOT
    implemented in Phase 4.1 (no uncontrolled database growth). This table and
    the service in ``app/services/iv_history.py`` are the persistence
    interfaces a FUTURE collector will use, and it must honour the
    configurable sampling interval / retention in ``app/config.py``.

    ``iv`` is stored as a CANONICAL DECIMAL FRACTION (0.1824 = 18.24%) — the
    exact unit contract used by the frontend calculation layer. Never store
    the raw broker percent here.
    """

    __tablename__ = "iv_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    expiry: Mapped[str] = mapped_column(String(10))
    strike: Mapped[float] = mapped_column(Float)
    option_type: Mapped[str] = mapped_column(String(8))  # call | put
    iv: Mapped[float] = mapped_column(Float)  # canonical decimal (0.1824 = 18.24%)
    spot: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="upstox")
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
