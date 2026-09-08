# Day 39 Task 2 — RED (failing) idempotent ingestion tests
# Must fail before any ingestion service exists.
from app.broker_sync import BrokerSyncEvent, BrokerEventType, BrokerEventSourceMode, CanonicalOrderState, OrderFacts, FillFacts

def test_ingestion_service_exists_and_is_callable():
    from app.broker_sync import ingest_canonical_event
    assert callable(ingest_canonical_event)
