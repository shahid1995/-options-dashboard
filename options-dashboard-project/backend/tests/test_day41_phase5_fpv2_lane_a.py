"""Day41 Phase 5 — FPv2 byte-level vectors + Lane-A projection/drift tests.

V1–V13 are the published shared vectors (Day40.4 §6) — byte-identical
reproduction of canonical bytes and digests is REQUIRED (Invariant W).
Π_A / drift-guard tests implement Day40.6 §4.3.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.broker_sync.fingerprint import (
    FingerprintError,
    LANE_A_PROJECTED_FIELDS,
    canonical_price,
    canonical_quantity,
    canonical_timestamp,
    drift_guard,
    fpv2_canonical_bytes,
    fpv2_digest,
    lane_a_fingerprint,
    lane_a_projection,
)

# ---------------------------------------------------------------------------
# V1–V13: published vectors (canonical bytes + digest)
# ---------------------------------------------------------------------------

def _check(vector_key: str, fields: dict, expected_bytes: str, expected_digest: str) -> None:
    b = fpv2_canonical_bytes(fields).decode("utf-8")
    assert b == expected_bytes, f"{vector_key}: bytes {b!r} != {expected_bytes!r}"
    assert fpv2_digest(fields) == expected_digest, f"{vector_key}: digest mismatch"


def test_V1_integer_quantity_equivalence() -> None:
    _check("V1", {"filled_quantity": "20"},
           '{"filled_quantity":"20"}',
           "414f7729adf5105661c4fa05efe999e3fc81957c14858b132d24e0fbb09683bb")
    # All four spellings collapse to one digest
    assert fpv2_digest({"filled_quantity": "20.0"}) == fpv2_digest({"filled_quantity": "20"})
    assert fpv2_digest({"filled_quantity": "20.00"}) == fpv2_digest({"filled_quantity": "20"})
    assert fpv2_digest({"filled_quantity": 20}) == fpv2_digest({"filled_quantity": "20"})


def test_V2_price_integral_equivalence() -> None:
    _check("V2", {"average_price": "100"},
           '{"average_price":"100"}',
           "d12b30fc1bc36633df131df31111a49e17c0b31f136e96c87387c5fac09e5de5")
    assert fpv2_digest({"average_price": "100.0"}) == fpv2_digest({"average_price": "100"})
    assert fpv2_digest({"average_price": "100.00"}) == fpv2_digest({"average_price": "100"})
    assert fpv2_digest({"average_price": 100}) == fpv2_digest({"average_price": "100"})


def test_V3_price_0_10() -> None:
    _check("V3", {"average_price": "0.10"},
           '{"average_price":"0.1"}',
           "69de99a626dea86f8eefcb0a4b0a602ae466b6143d60287d94ded3ed31f66bb5")


def test_V4_price_100_100() -> None:
    _check("V4", {"average_price": "100.100"},
           '{"average_price":"100.1"}',
           "9ca751a858e253d1826f6808a5592fd96241a5698bc0fb3537ae6db09b427f6e")


def test_V5_null() -> None:
    _check("V5", {"reject_reason": None}, "{}",
           "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a")


def test_V6_absent() -> None:
    _check("V6", {}, "{}",
           "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a")
    assert fpv2_digest({"reject_reason": None}) == fpv2_digest({})  # V5 ≡ V6


def test_V7_empty_string() -> None:
    _check("V7", {"reject_reason": ""},
           '{"reject_reason":""}',
           "b8c789135e4fba4060491bff5848482d03a581355181b6f1862ca2b735ffa515")
    assert fpv2_digest({"reject_reason": ""}) != fpv2_digest({})  # V7 ≠ V5


def test_V8_unicode_nfc_nfd() -> None:
    _check("V8", {"tag": "I\u0303"},
           '{"tag":"\\u0128"}',
           "cc886e0b90341419be5ded03c2a9425ed70de2510484a083ab72f30edab41c17")
    assert fpv2_digest({"tag": "\u0128"}) == fpv2_digest({"tag": "I\u0303"})


def test_V9_timestamp_six_digit_fraction() -> None:
    _check("V9", {"event_timestamp": "2026-09-10T13:25:13.123456Z"},
           '{"event_timestamp":"2026-09-10T13:25:13.123Z"}',
           "61a6ad850b4d0a54339b6fefec9f335494dfae99061ac068388a6d42bb7c2fa2")
    # Four equivalent spellings collapse
    base = fpv2_digest({"event_timestamp": "2026-09-10T13:25:13.123456Z"})
    assert fpv2_digest({"event_timestamp": "2026-09-10T13:25:13.123Z"}) == base
    assert fpv2_digest({"event_timestamp": "2026-09-10T13:25:13.123456+00:00"}) == base
    assert fpv2_digest({"event_timestamp": "2026-09-10T18:55:13.123+05:30"}) == base


def test_V10_timestamp_no_fraction_is_different_instant() -> None:
    _check("V10", {"event_timestamp": "2026-09-10T13:25:13Z"},
           '{"event_timestamp":"2026-09-10T13:25:13.000Z"}',
           "08382c3aa66efecef40f359bfc7176cf10c1e811a1ddd07fb4b039a609564ce9")


def test_V11_negative_zero() -> None:
    _check("V11", {"filled_quantity": "-0"},
           '{"filled_quantity":"0"}',
           "92d9bedc7075ffd69b424658076bdc2fc444b7cfd5b7a775ee57021d8ccbe0bd")
    assert fpv2_digest({"filled_quantity": "0"}) == fpv2_digest({"filled_quantity": "-0"})


def test_V12_large_integer() -> None:
    _check("V12", {"total_quantity": "123456789012345678901234567890"},
           '{"total_quantity":"123456789012345678901234567890"}',
           "b37ad8f9c024e7c85a781c31c37d46ccb29b0eca40bf9b8ff296d377a3603983")


def test_V13_composed_full_observation() -> None:
    fields = {
        "tenant_id": "tenant-1", "broker": "UPSTOX",
        "provider_order_id": "240108010445130", "event_type": "FULL_FILL",
        "provider_status": "complete", "total_quantity": "100",
        "filled_quantity": "100.00", "average_price": "570.950",
        "reject_reason": None, "trade_id": "",
        "event_timestamp": "2026-09-10T13:25:13.123456Z",
    }
    expected_bytes = (
        '{"average_price":"570.95","broker":"UPSTOX","event_timestamp":"2026-09-10T13:25:13.123Z",'
        '"event_type":"FULL_FILL","filled_quantity":"100","provider_order_id":"240108010445130",'
        '"provider_status":"complete","tenant_id":"tenant-1","total_quantity":"100","trade_id":""}'
    )
    expected_digest = "bdca679d564b097e557f3869229e72a2a2701bca5d5b55e6ec1dc54d81bdcdcd"
    b = fpv2_canonical_bytes(fields).decode("utf-8")
    assert b == expected_bytes
    assert fpv2_digest(fields) == expected_digest


def test_non_integral_quantity_fails_closed() -> None:
    with pytest.raises(FingerprintError, match="non-integral quantity"):
        fpv2_digest({"filled_quantity": "20.5"})


def test_key_order_independence() -> None:
    a = fpv2_digest({"status": "open", "quantity": "100"})
    b = fpv2_digest({"quantity": "100", "status": "open"})
    assert a == b


def test_no_binary_float_artifacts() -> None:
    """0.1 as a float must not leak binary artifacts into the digest."""
    # Decimal('0.1') vs repr-round-tripped float 0.1 agree — but the canonical
    # rule is string/Decimal input; the digest of string "0.1" is the reference.
    assert canonical_price("0.1") == "0.1"
    assert canonical_price(0.1) == "0.1"  # repr path stays deterministic


# ---------------------------------------------------------------------------
# Π_A projection + Lane-A fingerprint
# ---------------------------------------------------------------------------

def _order_payload(**overrides) -> dict:
    payload = {
        "update_type": "order",
        "exchange": "NSE",
        "instrument_token": "NSE_EQ|INE848E01016",
        "trading_symbol": "NHPC-EQ",
        "product": "D",
        "order_type": "LIMIT",
        "average_price": 0,
        "price": 100.5,
        "trigger_price": 0,
        "quantity": 100,
        "disclosed_quantity": 0,
        "pending_quantity": 100,
        "transaction_type": "BUY",
        "order_ref_id": "57744821658411",
        "exchange_order_id": "",
        "validity": "DAY",
        "status": "open",
        "is_amo": False,
        "variety": "SIMPLE",
        "tag": None,
        "exchange_timestamp": "2026-09-10T13:25:13.123456Z",
        "status_message": "",
        "order_id": "240221025997024",
        "order_request_id": "1",
        "order_timestamp": "2026-09-10 13:25:13",
        "filled_quantity": 0,
        "placed_by": "UCC1",
        "status_message_raw": None,
    }
    payload.update(overrides)
    return payload


def test_lane_a_projection_contains_exactly_pi_a_fields() -> None:
    proj = lane_a_projection(_order_payload())
    # exchange_order_id is "" in this payload → omitted (only status_message ""
    # is semantically preserved); event_type is absent from the raw payload.
    assert set(proj.keys()) == {
        "status", "quantity", "filled_quantity", "pending_quantity",
        "average_price", "price", "trigger_price", "status_message",
        "exchange_timestamp",
    }
    assert set(proj.keys()) <= set(LANE_A_PROJECTED_FIELDS)


def test_lane_a_projection_excludes_audit_and_static_fields() -> None:
    proj = lane_a_projection(_order_payload())
    for excluded in ("tag", "order_request_id", "order_ref_id", "disclosed_quantity",
                     "status_message_raw", "product", "validity", "placed_by"):
        assert excluded not in proj


def test_lane_a_fingerprint_changes_on_projected_field_change() -> None:
    base = lane_a_fingerprint(_order_payload())
    assert lane_a_fingerprint(_order_payload(pending_quantity=50)) != base      # case 90
    assert lane_a_fingerprint(_order_payload(price=101.0)) != base              # case 91
    assert lane_a_fingerprint(_order_payload(trigger_price=99.0)) != base       # case 92
    assert lane_a_fingerprint(_order_payload(status_message="rms rejected")) != base  # case 95
    assert lane_a_fingerprint(_order_payload(exchange_order_id="1300000025660919")) != base


def test_lane_a_fingerprint_ignores_audit_only_changes() -> None:
    base = lane_a_fingerprint(_order_payload())
    assert lane_a_fingerprint(_order_payload(tag="new-tag")) == base            # case 93
    assert lane_a_fingerprint(_order_payload(order_request_id="2")) == base     # case 94
    assert lane_a_fingerprint(_order_payload(disclosed_quantity=10)) == base


def test_lane_a_fingerprint_quantity_normalization() -> None:
    assert lane_a_fingerprint(_order_payload(quantity=100)) == \
           lane_a_fingerprint(_order_payload(quantity="100"))


def test_lane_a_empty_status_message_is_semantic() -> None:
    """'' status_message is preserved (distinct from absent) in Π_A."""
    proj = lane_a_projection(_order_payload(status_message=""))
    assert proj["status_message"] == ""


# ---------------------------------------------------------------------------
# Drift guard
# ---------------------------------------------------------------------------

def test_drift_guard_allows_static_stability() -> None:
    payload = _order_payload()
    baseline: dict = {}
    assert drift_guard(payload, baseline) is None
    # Second identical observation still safe
    assert drift_guard(payload, baseline) is None


def test_drift_guard_flags_static_field_change() -> None:
    baseline: dict = {}
    assert drift_guard(_order_payload(), baseline) is None
    changed = _order_payload(product="I")  # product is static per order
    reason = drift_guard(changed, baseline)
    assert reason is not None and "static field" in reason


def test_drift_guard_flags_undocumented_field() -> None:
    baseline: dict = {}
    assert drift_guard(_order_payload(), baseline) is None
    with_guid = _order_payload(guid="abc-123")  # undocumented in field table
    reason = drift_guard(with_guid, baseline)
    assert reason is not None and "undocumented field" in reason


def test_drift_guard_tolerates_neutral_undocumented_fields() -> None:
    baseline: dict = {}
    assert drift_guard(_order_payload(guid=None), baseline) is None


def test_drift_guard_first_sighting_then_change_of_static_field() -> None:
    """A static non-Π_A attribute (validity) establishes its baseline on the
    first observation; any later deviation is drift; return-to-baseline is
    safe.  (exchange_order_id is Π_A — its changes are fingerprint changes,
    not drift.)"""
    baseline: dict = {}
    assert drift_guard(_order_payload(), baseline) is None          # baseline: DAY
    assert baseline.get("validity") == "DAY"
    reason = drift_guard(_order_payload(validity="IOC"), baseline)  # deviation
    assert reason is not None and "static field" in reason
    assert drift_guard(_order_payload(), baseline) is None          # back to baseline


def test_drift_guard_audit_only_changes_exempt() -> None:
    baseline: dict = {}
    assert drift_guard(_order_payload(), baseline) is None
    assert drift_guard(_order_payload(tag="x", order_request_id="3"), baseline) is None
