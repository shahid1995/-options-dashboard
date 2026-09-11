"""Day41 Phase 5 — FPv2 canonical serialization + Lane-A projection (Day40.4 §6, Day40.6 §4).

FPv2 is the Task3 observation content fingerprint — an input to the CEID
derivation.  It MUST be byte-identical across implementations (Invariant W):
the published vectors V1–V13 are embedded as fixtures in the test suite.

FPv2-A is the Lane-A (order-observation) fingerprint: the canonical semantic
projection Π_A, exactly (Day40.6 §4.3):

    Π_A = (event_type, status, quantity, filled_quantity, pending_quantity,
           average_price, price, trigger_price, status_message,
           exchange_order_id, exchange_timestamp)

Serializer rules (normative):
- keys and string values NFC-normalized; null/absent keys omitted; "" preserved
- quantities via Decimal with integral check (non-integral → error, fail-closed)
- prices via Decimal with trailing-zero stripping (fractional legal, honest)
- timestamps → UTC, RFC 3339 millisecond-truncated
- JSON with sorted keys, ensure_ascii, no whitespace separators; SHA256 hex
- NO binary floating point anywhere in normalization (Decimal/string only)
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional


class FingerprintError(ValueError):
    """Raised when a value cannot be canonically serialized (fail-closed)."""


# Canonical FPv2 field sets -------------------------------------------------

FPV2_NUMERIC_QUANTITY_FIELDS = frozenset({
    "total_quantity", "filled_quantity", "cancelled_quantity",
})
FPV2_NUMERIC_PRICE_FIELDS = frozenset({"average_price"})
FPV2_TIMESTAMP_FIELDS = frozenset({"event_timestamp"})

# Lane-A canonical semantic projection Π_A (Day40.6 §4.3) — the fingerprinted
# field set for order observations.  Everything else is excluded (audit-only,
# correlation-only, or static-per-order attributes covered by the drift guard).
LANE_A_PROJECTED_FIELDS = (
    "event_type",
    "status",
    "quantity",
    "filled_quantity",
    "pending_quantity",
    "average_price",
    "price",
    "trigger_price",
    "status_message",
    "exchange_order_id",
    "exchange_timestamp",
)

# Fields whose canonical form is a quantity vs price (for Π_A serialization)
_LANE_A_QUANTITY_FIELDS = frozenset({"quantity", "filled_quantity", "pending_quantity"})
_LANE_A_PRICE_FIELDS = frozenset({"average_price", "price", "trigger_price"})

# Known order-update payload fields OUTSIDE Π_A, with their classification
# (Day40.6 §4.2).  Used by the drift guard to decide whether an excluded field
# carries a value that is plausible-and-static vs unexpected/material.
_LANE_A_EXCLUDED_FIELDS: dict[str, str] = {
    # audit-only content
    "disclosed_quantity": "audit_only",
    "tag": "audit_only",
    "status_message_raw": "audit_only",
    # correlation-only identifiers
    "order_request_id": "correlation_only",
    "order_ref_id": "correlation_only",
    # lane routing
    "update_type": "routing",
    # static-per-order attributes (drift-guarded, not fingerprinted)
    "exchange": "static_attribute",
    "product": "static_attribute",
    "order_type": "static_attribute",
    "transaction_type": "static_attribute",
    "validity": "static_attribute",
    "variety": "static_attribute",
    "instrument_token": "static_attribute",
    "instrument_key": "static_attribute",
    "trading_symbol": "static_attribute",
    "tradingsymbol": "static_attribute",   # deprecated alias
    "parent_order_id": "static_attribute",
    "is_amo": "static_attribute",
    "order_timestamp": "static_attribute",
    "placed_by": "static_attribute",
    "user_id": "static_attribute",
    "userId": "static_attribute",          # deprecated alias
    "order_id": "identity",                # D1 component, not content
}

# Values that mean "field absent/empty" for drift-guard purposes.
_DRIFT_NEUTRAL_VALUES = frozenset({"", None})


# ---------------------------------------------------------------------------
# Decimal canonicalization
# ---------------------------------------------------------------------------

def canonical_quantity(value: Any) -> str:
    """Quantity rule: Decimal, integral check, strip fraction, -0 → 0."""
    d = _to_decimal(value)
    if d != d.to_integral_value():
        raise FingerprintError(f"non-integral quantity not representable: {value}")
    return _decimal_to_str(d)


def canonical_price(value: Any) -> str:
    """Price rule: Decimal, trailing zeros stripped, fraction preserved honestly."""
    return _decimal_to_str(_to_decimal(value))


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, bool):
        raise FingerprintError("boolean is not a numeric value")
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        # Binary floats are NOT normalized (Day41 Phase 5 requirement) — the
        # safe path is the exact string/Decimal.  Accepting floats risks
        # binary artifacts (0.1 → 0.1000000000000000055511151231257827); we
        # convert through repr to keep determinism within one runtime, but
        # canonical input MUST be string/Decimal for cross-implementation work.
        d = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            d = Decimal(value)
        except InvalidOperation as exc:
            raise FingerprintError(f"invalid decimal: {value!r}") from exc
    else:
        raise FingerprintError(f"unsupported numeric type: {type(value).__name__}")
    if not d.is_finite():
        raise FingerprintError("non-finite decimal")
    return d


def _decimal_to_str(d: Decimal) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", "", "-"):
        s = "0"
    return s


# ---------------------------------------------------------------------------
# Timestamp canonicalization
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_timestamp(value: Any) -> str:
    """Timestamp rule: parse ISO-8601 → UTC → RFC 3339 ms-truncated."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            raise FingerprintError("naive timestamp (timezone-aware required)")
        ms = dt.microsecond // 1000  # truncate, never round
        dt = dt.replace(microsecond=0) + timedelta(milliseconds=ms)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"
    if isinstance(value, str):
        m = _ISO_RE.match(value.strip())
        if not m:
            raise FingerprintError(f"unparseable timestamp: {value!r}")
        y, mo, d, h, mi, s, frac, off = m.groups()
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s),
                      tzinfo=timezone.utc if off in (None, "Z") else None)
        if off not in (None, "Z"):
            sign = 1 if off[0] == "+" else -1
            dt = dt - sign * timedelta(hours=int(off[1:3]), minutes=int(off[-2:]))
        ms = int((frac or "0")[:3].ljust(3, "0"))
        dt = dt.replace(microsecond=0) + timedelta(milliseconds=ms)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"
    raise FingerprintError(f"unsupported timestamp type: {type(value).__name__}")


# ---------------------------------------------------------------------------
# Core serializer
# ---------------------------------------------------------------------------

def _serialize_field(key: str, value: Any) -> Any:
    nfc_key = unicodedata.normalize("NFC", key)
    if value is None:
        return None  # null ≡ absent: caller omits
    if isinstance(value, bool):
        return value
    if key in FPV2_NUMERIC_QUANTITY_FIELDS or key in _LANE_A_QUANTITY_FIELDS:
        return canonical_quantity(value)
    if key in FPV2_NUMERIC_PRICE_FIELDS or key in _LANE_A_PRICE_FIELDS:
        return canonical_price(value)
    if key in FPV2_TIMESTAMP_FIELDS or key == "exchange_timestamp":
        return canonical_timestamp(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    raise FingerprintError(f"unsupported value type for {key!r}: {type(value).__name__}")


def fpv2_canonical_bytes(fields: Mapping[str, Any]) -> bytes:
    """Canonical JSON bytes for an FPv2 field map (sorted NFC keys, ASCII)."""
    obj: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue  # null ≡ absent
        serialized = _serialize_field(key, value)
        if serialized is None:
            continue
        obj[unicodedata.normalize("NFC", key)] = serialized
    txt = json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return txt.encode("utf-8")


def fpv2_digest(fields: Mapping[str, Any]) -> str:
    """FPv2 content fingerprint: SHA256 over the canonical bytes (lowercase hex)."""
    return hashlib.sha256(fpv2_canonical_bytes(fields)).hexdigest()


# ---------------------------------------------------------------------------
# Lane A: projection + fingerprint + drift guard
# ---------------------------------------------------------------------------

def lane_a_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract Π_A from a provider order-update payload (Day40.6 §4.3)."""
    projection: dict[str, Any] = {}
    for field in LANE_A_PROJECTED_FIELDS:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and value == "" and field != "status_message"):
            # '' is preserved for status_message (semantic), omitted elsewhere
            if field == "status_message" and value == "":
                projection[field] = ""
            continue
        projection[field] = value
    return projection


def lane_a_fingerprint(payload: Mapping[str, Any]) -> str:
    """FPv2-A = FPv2 digest over Π_A exactly."""
    return fpv2_digest(lane_a_projection(payload))


def drift_guard(
    payload: Mapping[str, Any],
    baseline_attributes: Mapping[str, Any],
) -> Optional[str]:
    """Day40.6 §4.3 drift guard — fail-closed on unexpected/material change.

    Compares every non-Π_A payload field against the order's first-seen
    attribute baseline.  Returns None when safe to dedup; returns a reason
    string when the observation must be QUARANTINED/CLASSIFICATION_FAILED.

    Rules:
    - unknown (unclassified) fields with non-neutral values ⇒ drift
    - static-attribute fields differing from baseline (beyond appearing for
      the first time) ⇒ drift
    - audit-only/correlation fields are exempt (raw evidence retains them)
    """
    for key, value in payload.items():
        classification = _LANE_A_EXCLUDED_FIELDS.get(key)
        if key in LANE_A_PROJECTED_FIELDS:
            continue  # Π_A change is a fingerprint change, not drift
        if classification is None:
            # Undocumented/newly-appearing field (e.g. guid): drift when
            # it carries a meaningful value.
            if value not in _DRIFT_NEUTRAL_VALUES:
                return f"undocumented field {key!r} appeared with value {value!r}"
            continue
        if classification == "static_attribute":
            if key not in baseline_attributes:
                # First sighting is recorded, not drift — but only for
                # neutral defaults (e.g. exchange_order_id starts "").
                if value not in _DRIFT_NEUTRAL_VALUES:
                    baseline_attributes[key] = value
                continue
            baseline_value = baseline_attributes[key]
            if value != baseline_value and not (
                baseline_value in _DRIFT_NEUTRAL_VALUES and value not in _DRIFT_NEUTRAL_VALUES
            ):
                # A truly static field changed ⇒ material provider drift.
                return (
                    f"static field {key!r} changed from {baseline_value!r} to {value!r}"
                )
            # First non-neutral sighting after neutral default: adopt it.
            if baseline_value in _DRIFT_NEUTRAL_VALUES and value not in _DRIFT_NEUTRAL_VALUES:
                baseline_attributes[key] = value
        # audit_only / correlation_only / routing / identity: exempt
    return None
