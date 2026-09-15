# Day 13 — Streaming Lifecycle, Recovery & Stale-Data Hardening

**Status:** IN PROGRESS (authorized 2026-09-03)
**Baseline:** `bf3ea26` (Day 12 final — Data Quality Gate PASS)
**Branch:** `feat/strikenova-day1-security`

## Objective

Build the **source-neutral streaming lifecycle boundary** required by the
Blueprint: a lifecycle manager that governs connect / disconnect / reconnect /
bounded exponential backoff / resubscription / liveness / stale detection /
sequence tracking / gap recovery / intentional shutdown / auth failure for any
streaming source, emitting canonical Day-9 observations with provenance, and
lifecycle/recovery metadata that the Day-12 quality layer can consume.

## Existing streaming components (inspection findings)

- `app/services/upstox_market_feed.py` (Phase 8C): `UpstoxMarketFeed` wraps the
  official `upstox_client.MarketDataStreamerV3` SDK (transport + protobuf).
  It owns its own `FeedState` enum (DISCONNECTED … AUTH_FAILED, ERROR,
  STOPPING), SDK-level auto-reconnect with exponential backoff + 25% jitter,
  stale thresholds (10s tick / 15s chain / 30s GEX), tick state per
  instrument, chain reconstruction to the legacy `transform_chain()` dict, and
  callback isolation. It does NOT produce Day-9 canonical observations, does
  NOT track sequences (Upstox V3 feed messages carry no per-message sequence
  numbers — only `currentTs` exchange timestamps), and its reconnect policy is
  hard-coded broker-specific.
- `app/market_data/contracts.py` (Day 9): canonical `MarketObservation` already
  has `sequence_id: int | None` — sequence tracking slots into the existing
  contract without any schema/model change.
- `app/market_data/gateway.py` (Day 11): canonical boundary guards + data-mode
  semantics; the gateway stays REST/orchestration — the streaming lifecycle is
  a separate layer above sources.
- `app/market_data/quality.py` (Day 12): deterministic `MarketDataQualityEngine`
  over canonical observations with explicit `reference_time`. Already has
  `STALE_OBSERVATION` / `CONTINUITY_BREAK` issue codes; no new quality code is
  required. Lifecycle metadata (stale / gap / recovery) is exposed as a
  separate `StreamQualityContext` so consumers can refuse to act on
  degraded streams without conflating lifecycle state with quality scoring.
- `app/brokers/domain/errors.py`: `BrokerError` + `BrokerErrorCode` taxonomy.
  Day 13 reuses `INVALID_MARKET_DATA`, `AUTH_REQUIRED`, `RATE_LIMITED`,
  `NETWORK_ERROR`, `SOURCE_UNAVAILABLE`, `UPSTREAM_ERROR` — **no new error
  class/code** (no repository evidence for one).

## Reuse vs replacement decision

**REUSE.** The lifecycle manager is a NEW source-neutral layer
(`app/market_data/streaming.py`). The Upstox transport (SDK), token handling,
tick state and chain reconstruction in `UpstoxMarketFeed` are reused via a thin
`UpstoxStreamingSource` bridge (`app/brokers/adapters/upstox/streaming_source.py`)
that implements the source-neutral `StreamingSource` protocol. No competing
streaming architecture is created; the feed is not rewritten.

**Interplay note:** the feed's SDK-level auto-reconnect continues to operate at
the transport layer (socket liveness). The lifecycle manager owns the
source-neutral policy surface: source-level disconnect → bounded backoff →
`resubscribe()` (exact subscription set) → recovery. For Upstox,
`resubscribe()` re-invokes `feed.connect()` with the preserved subscription
set, which the feed guards against double-connect.

**Sequence continuity:** Upstox does NOT expose per-message sequence numbers.
`UpstoxStreamingSource.supports_sequence = False` and the limitation is
documented — sequence numbers are never invented. The lifecycle manager's
`SequenceTracker` is exercised by sources that DO expose sequence metadata
(future dataset/streaming sources), with duplicate / out-of-order / gap /
recovery semantics fully tested.

## New interfaces

- `StreamingSource` (Protocol, broker-neutral): `source_id`, `supports_sequence`,
  `connect()`, `disconnect()`, `subscribe(instruments)`, `resubscribe()`,
  observation/error handler registration, `liveness_seconds()`.
- `StreamingLifecycleManager`: `start(instruments)`, `stop()`, `heartbeat()`,
  `state`, `status()` → `StreamStatus`, `quality_context()` →
  `StreamQualityContext`, observation + lifecycle event handler registration,
  deterministic backoff (`BackoffPolicy` + injectable RNG/clock), canonical
  observation guard, sequence tracking via `SequenceTracker`.
- `LifecycleEvent` (structured, credential-free), `StreamLifecycleState`,
  `SequenceState`, `SequenceEvent` (OK / DUPLICATE / OUT_OF_ORDER / GAP /
  UNSUPPORTED).

## State machine

```
DISCONNECTED → CONNECTING → CONNECTED → SUBSCRIBING → LIVE
                                                         │
LIVE/SUBSCRIBING → RECONNECTING (transient failure, backoff) → CONNECTING
LIVE → STALE (no activity > stale_after_seconds; never fabricated)
LIVE/STALE → RECOVERY (unresolved sequence gap; data may flow but is flagged)
RECOVERY → LIVE (gap resolved / recovery marker)
any → AUTH_FAILED (401/unauthorized; NO endless reconnect)
any → ERROR (reconnect budget exhausted / unrecoverable source failure)
any → STOPPED (intentional shutdown; NEVER reconnects)
```

Rules enforced by tests: intentional shutdown never reconnects; auth failure
does not endlessly reconnect; an unresolved gap is never reported as healthy
continuous data; stale state never emits observations.

## Failure/recovery semantics

- Transient disconnect → `RECONNECTING` with bounded exponential backoff
  (base × 2^attempt, capped at max, jitter ≤ configured fraction, default 25%,
  deterministic with injected RNG).
- Max attempts exhausted → `ERROR` (no silent retry).
- Successful reconnect → attempt counter reset, `resubscribe()` restores the
  exact instrument set → `LIVE`.
- Source errors are classified via the source's `classify_error()` hook into
  the existing `BrokerErrorCode` taxonomy; credentials never appear in events,
  status, or repr.

## Test strategy

- Fake `StreamingSource` (deterministic, scripted connect/disconnect/errors,
  no network) drives the lifecycle tests: state machine, reconnect + backoff
  bounds + jitter bound, max-attempts, resubscribe-set preservation,
  intentional shutdown, auth failure, stale detection, sequence duplicate /
  out-of-order / gap / recovery, canonical guard, no-token leakage.
- `UpstoxStreamingSource` bridge tests: tick → canonical `QuoteObservation`
  mapping (LTP/OI/volume/bid/ask preserved, missing → None, no fabricated
  zeros, market vs received timestamps distinct, `BROKER_LIVE` mode, source
  `UPSTOX`, provenance present), `supports_sequence=False`, connect/disconnect
  delegation, 401 → `AUTH_REQUIRED`, token never in repr/status.
- Day 12 integration: `quality_context()` metadata is separate from
  `MarketDataQualityEngine.evaluate()` output; quality remains authoritative.

## Explicitly OUT OF SCOPE

- No Greeks/IV/GEX/intelligence/flow/opportunity/strategy/risk engines.
- No order execution, no live trading enablement.
- No historical ingestion, no Redis/Kafka/microservices, no DB persistence for
  streaming state (Alembic untouched — NO migrations).
- No refactor of existing WebSocket consumers (chains router, GEX services,
  frontend) — the legacy chain-dict path is unchanged.
- No production deployment / PostgreSQL cutover / merge.
- Day 14+ NOT started.