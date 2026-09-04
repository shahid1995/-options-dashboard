"""Day 35 — Normalization adapters (authoritative position rows -> inputs).

The pure analytics layer never touches a database or a broker.  These
adapters convert an AUTHORITATIVE position row into the pure
``PortfolioPosition`` input.  They are duck-typed attribute/dict readers —
no SQLAlchemy import, no session, no broker SDK — so they stay part of the
pure package while the caller (a service/repository outside this package)
supplies the rows.

Authority rules
---------------
* PAPER rows: the paper ``Position`` model's netted quantity (signed lots),
  average entry price and lot size are authoritative.  The adapter RE-STATES
  them; it never nets, prices, fills or invents anything.  Rows that are
  closed or carry zero net quantity are not positions and are rejected
  (``ValueError``) — nothing is fabricated for them.
* BROKER rows: the normalized broker row (``symbol``/``expiry``/``strike``/
  ``option_type``/``quantity``/``direction`` and optional ``lot_size``,
  ``market_value``, ``entry_price``) is authoritative broker-observed state.
  A broker row missing its quantity or direction cannot be normalized — the
  adapter raises instead of inventing a quantity.

Optional per-position evidence (per-unit Greeks, spot, current mark) is
caller-supplied via keyword arguments and passed through verbatim.
"""

from __future__ import annotations

from datetime import datetime

from app.market_data.contracts import Provenance, Side
from app.quant.scenarios import PositionDirection

from app.portfolio_intelligence.contracts import (
    GreekInput,
    PortfolioPosition,
    PositionSource,
)

_PAPER_PROVENANCE_MODE = "PAPER_LEDGER"
_BROKER_PROVENANCE_MODE = "BROKER_SNAPSHOT"


def _paper_provenance(tenant_id: str, reference_timestamp: datetime) -> Provenance:
    return Provenance(
        source="paper.position",
        collection_mode=_PAPER_PROVENANCE_MODE,
        received_at=reference_timestamp,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _broker_provenance(tenant_id: str, reference_timestamp: datetime) -> Provenance:
    return Provenance(
        source="broker.position",
        collection_mode=_BROKER_PROVENANCE_MODE,
        received_at=reference_timestamp,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _side_from_token(option_type) -> Side:
    token = str(option_type).strip().lower()
    if token in ("call", "ce"):
        return Side.CALL
    if token in ("put", "pe"):
        return Side.PUT
    raise ValueError(
        f"option_type must be 'call' or 'put', got {option_type!r}"
    )


def paper_position_to_input(
    row,
    *,
    tenant_id: str,
    reference_timestamp: datetime,
    greeks: GreekInput | None = None,
    spot: float | None = None,
    current_price: float | None = None,
) -> PortfolioPosition:
    """Normalize one authoritative paper ``Position`` row (duck-typed).

    ``row`` is any object exposing the paper engine's authoritative columns:
    ``user_id``, ``symbol``, ``expiry``, ``strike``, ``option_type``
    (call/put), ``net_quantity`` (signed lots), ``average_entry_price``,
    ``lot_size`` and ``status`` (open/closed).  The normalized quantity is
    ``abs(net_quantity)`` with the explicit direction preserved from the
    signed net — the paper engine's net is the ONLY sign authority.
    """
    if row is None:
        raise ValueError("A paper position row is required for normalization")
    if str(getattr(row, "status", "open")).lower() == "closed":
        raise ValueError("Closed paper positions carry nothing to normalize")
    net = getattr(row, "net_quantity", None)
    if net is None:
        raise ValueError(
            "Paper position row carries no net_quantity; a quantity is never "
            "invented."
        )
    net = int(net)
    if net == 0:
        raise ValueError(
            "A paper position with zero net quantity is not an open position."
        )
    direction = PositionDirection.LONG if net > 0 else PositionDirection.SHORT

    option_type = _side_from_token(getattr(row, "option_type"))
    expiry = str(getattr(row, "expiry"))
    strike = float(getattr(row, "strike"))
    symbol = str(getattr(row, "symbol")).upper()
    lot_size = getattr(row, "lot_size", None)
    entry_price = getattr(row, "average_entry_price", None)

    return PortfolioPosition(
        position_id=str(getattr(row, "id", f"{tenant_id}:{symbol}:{expiry}:{strike}:{option_type.value}")),
        tenant_id=tenant_id,
        source=PositionSource.PAPER,
        underlying=symbol,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        quantity=float(abs(net)),
        direction=direction,
        lot_size=int(lot_size) if lot_size is not None else None,
        entry_price=float(entry_price) if entry_price is not None else None,
        current_price=current_price,
        market_value=None,
        spot=spot,
        greeks=greeks,
        quality=None,
        provenance=_paper_provenance(tenant_id, reference_timestamp),
        reference_timestamp=reference_timestamp,
    )


def broker_position_to_input(
    row,
    *,
    tenant_id: str,
    reference_timestamp: datetime,
    greeks: GreekInput | None = None,
    spot: float | None = None,
    current_price: float | None = None,
) -> PortfolioPosition:
    """Normalize one authoritative broker-observed position row.

    ``row`` is the normalized broker position shape (a mapping or
    attribute object) produced by a broker adapter: ``symbol``, ``expiry``,
    ``strike``, ``option_type``, ``quantity`` (net broker quantity), and
    ``direction`` (LONG/SHORT), with optional ``lot_size``, ``market_value``,
    ``entry_price``.  The broker adapter maps raw broker payloads to this
    shape at the integration boundary — this function never contacts a broker
    and never infers a quantity or direction that the broker did not report.
    """
    if row is None:
        raise ValueError("A broker position row is required for normalization")

    def _get(key):
        if isinstance(row, dict):
            return row.get(key)
        return getattr(row, key, None)

    quantity = _get("quantity")
    direction_token = _get("direction")
    if quantity is None:
        raise ValueError(
            "Broker position row carries no observed quantity; broker "
            "quantities are never inferred."
        )
    quantity = float(quantity)
    if quantity <= 0:
        raise ValueError("Broker position quantity must be positive")
    if direction_token is None:
        raise ValueError(
            "Broker position row carries no direction; a direction is never "
            "inferred."
        )
    token = str(direction_token).strip().upper()
    if token not in ("LONG", "SHORT", "BUY", "SELL"):
        raise ValueError(
            f"Broker direction must be LONG/SHORT (or BUY/SELL), got "
            f"{direction_token!r}"
        )
    direction = (
        PositionDirection.LONG if token in ("LONG", "BUY")
        else PositionDirection.SHORT
    )

    option_type = _side_from_token(_get("option_type"))
    symbol = str(_get("symbol")).upper()
    lot_size = _get("lot_size")
    market_value = _get("market_value")
    entry_price = _get("entry_price")

    return PortfolioPosition(
        position_id=str(
            _get("position_id")
            or f"{tenant_id}:{symbol}:{_get('expiry')}:{_get('strike')}:{option_type.value}"
        ),
        tenant_id=tenant_id,
        source=PositionSource.BROKER,
        underlying=symbol,
        expiry=str(_get("expiry")),
        strike=float(_get("strike")),
        option_type=option_type,
        quantity=quantity,
        direction=direction,
        lot_size=int(lot_size) if lot_size is not None else None,
        entry_price=float(entry_price) if entry_price is not None else None,
        current_price=current_price,
        market_value=float(market_value) if market_value is not None else None,
        spot=spot,
        greeks=greeks,
        quality=None,
        provenance=_broker_provenance(tenant_id, reference_timestamp),
        reference_timestamp=reference_timestamp,
    )


__all__ = [
    "broker_position_to_input",
    "paper_position_to_input",
]
