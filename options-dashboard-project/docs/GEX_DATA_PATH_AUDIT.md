# GEX Data-Path Audit

_Last audited: 2026-08-22_

## Purpose

This document records the current production data path relevant to Gamma Exposure (GEX) before any GEX implementation code is added.

## Current option-chain path

```text
Frontend / WebSocket or HTTP
        |
        v
backend/app/routers/chains.py
        |
        v
Broker Gateway
        |
        v
UpstoxAdapter.get_option_chain()
        |
        v
Upstox raw option-chain API
        |
        v
mapper.transform_chain()
        |
        v
Canonical chain:
  symbol
  expiry_date
  underlying_spot_price
  chain[]
    strike
    call { ltp, oi, chg_oi, volume, quote_timestamp, iv, delta, theta, gamma, vega, pop }
    put  { ltp, oi, chg_oi, volume, quote_timestamp, iv, delta, theta, gamma, vega, pop }
        |
        v
Frontend analytics / dashboard
```

## Confirmed inputs already available

### Underlying spot

`transform_chain()` exposes `underlying_spot_price` at the canonical chain level.

### Strike

Each canonical chain row exposes `strike`.

### Open interest

Each call and put leg exposes `oi`. The mapper also derives `chg_oi` when both current and previous OI are present.

### Gamma

Each call and put leg exposes live `gamma` from the broker's `option_greeks` payload.

### Expiry

The canonical chain exposes `expiry_date`. The existing broker adapter also exposes expiry discovery through `get_option_contracts()`.

### Other useful GEX context

The same chain already provides IV, delta, theta, vega, volume, LTP and quote timestamps, which can later be used for GEX regime research and cross-factor analytics without creating a second market-data pipeline.

## Existing Greek architecture

The frontend Greek analytics domain already treats live broker Greeks and model Greeks as separate sources and has an explicit canonical unit contract. Live gamma is defined as change in delta per one underlying point per unit. GEX must not modify or duplicate this Greek normalization layer.

GEX should consume the canonical market-chain gamma/OI data as a separate market-structure analytics domain.

## Important gap: authoritative lot size

The current broker instrument identity deliberately leaves `lot_size` unset when the platform does not have an authoritative value. The mapper does contain a lots-to-contracts helper for order/margin workflows, but GEX must not infer or hard-code lot size from that order helper.

Therefore, **authoritative lot size resolution is a prerequisite for production GEX**.

The GEX implementation must:

1. Resolve lot size from an authoritative contract/instrument source.
2. Associate it with the specific underlying/contract context and effective date where necessary.
3. Never silently substitute a stale or guessed lot size.
4. Return an explicit unavailable/invalid status when lot size cannot be resolved.

This is especially important because Indian index derivative lot sizes can change over time.

## GEX calculation boundary

The first implementation should be a pure backend/domain calculation service, conceptually:

```text
Canonical Option Chain
        +
Underlying Spot
        +
Authoritative Lot Size
        +
GEX Methodology
        |
        v
GEX Engine
        |
        +-- per-strike CE GEX
        +-- per-strike PE GEX
        +-- per-strike Net GEX
        +-- expiry totals
        +-- chain totals
        +-- data-quality status
```

The GEX engine must not call Upstox directly. It should receive canonical data and remain broker-neutral.

## Recommended first formula contract

For a 1% underlying move, the standard dollar/rupee exposure form is:

`GEX_i = gamma_i × OI_i × spot² × 0.01`

**Note:** No lot-size multiplier. `market_data.oi` from Upstox reports open interest in number of contracts, not lots. See GEX_V1_0_SPEC.md §11.1 for the complete evidence chain.

For the initial inferred dealer-position convention:

- Call GEX contribution: positive
- Put GEX contribution: negative

The convention must be stored as methodology metadata because OI does not directly reveal whether dealers are long or short gamma.

The project must never label this inferred quantity as an observed dealer position.

## Data-quality rules

GEX must distinguish:

- `available` — all required inputs present and valid
- `partial` — some option rows can be calculated but others cannot
- `unavailable` — required chain-level inputs are missing
- `invalid` — an input violates the calculation contract

Missing gamma/OI/spot/lot size must not be converted to zero.

## Do not change in Phase 7.1 foundation

The following existing boundaries should remain untouched:

- Upstox adapter contract
- broker gateway
- raw broker payload handling
- existing chain router behavior
- existing live/model Greek analytics
- paper execution
- strategy execution
- capital/margin calculations

## Proposed integration point

The preferred production boundary is:

```text
UpstoxAdapter
    |
    v
transform_chain()
    |
    v
Canonical Option Chain
    |
    +---------------------> Existing UI / Greek Analytics
    |
    +---------------------> GEX Analytics Service
                                      |
                                      v
                              GEX Snapshot / Profile
```

This avoids duplicating broker requests and avoids coupling GEX to Upstox-specific payload names.

## Historical roadmap

The current WebSocket chain path pushes a canonical chain approximately every three seconds. That is sufficient for live GEX calculation but does not by itself provide durable historical GEX.

A later phase should persist GEX snapshots with at least:

- timestamp
- symbol
- expiry
- spot
- methodology
- lot size
- CE GEX
- PE GEX
- Net GEX
- per-strike GEX contributions
- data-quality status

Historical analytics such as ΔGEX, GEX velocity, migration, percentile and anomaly detection must be built on these snapshots rather than reconstructed from current OI.

## Phase 7.1 implementation scope

The first coding phase should implement only:

1. Pure GEX calculation functions.
2. Explicit input/output schemas.
3. Authoritative lot-size resolution boundary.
4. CE/PE/Net GEX by strike.
5. Expiry and chain totals.
6. Data-quality/status handling.
7. Comprehensive deterministic tests with hand-calculated fixtures.
8. No UI changes yet.
9. No Gamma Flip yet.
10. No Strategy Builder integration yet.
11. No trading signal generated from GEX.

## Audit conclusion

The current project already exposes the core live market inputs required for GEX: spot, strike, expiry, OI and broker gamma. The correct architectural insertion point is a broker-neutral GEX analytics layer immediately downstream of canonical option-chain normalization.

The only major prerequisite identified by this audit is **authoritative lot-size resolution**. Once that is solved, Phase 7.1 can be implemented without creating another market-data pipeline or altering the existing Greek architecture.
