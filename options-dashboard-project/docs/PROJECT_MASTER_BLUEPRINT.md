# Options Dashboard — Project Master Blueprint

_Last updated: 2026-08-21_

## 1. Product vision

Build a professional options-trading dashboard and trading terminal initially focused on Indian index options.

The platform must be architected for:

- **PAPER execution** — simulated trading with no real broker orders
- **LIVE broker execution** — future real-money execution through the broker-neutral BrokerGateway and broker-specific adapters

Paper mode is an execution environment. Live mode is another execution environment. The same trading concepts (orders, positions, portfolio, P&L, strategies, journal, risk controls) work in both modes.

**Every trading feature must be designed for eventual LIVE broker execution first.** PAPER is a safe execution backend that performs the equivalent workflow without sending an order to the broker.

LIVE execution is currently **DISABLED**. No real broker orders are placed in the current version.

## 2. Core principles

- GitHub is the source of truth for code.
- This blueprint is the source of truth for product and architecture decisions.
- Free-for-life constraint: prefer open-source, self-hostable, genuinely free ongoing tooling; avoid trial/credit-dependent core services and unnecessary vendor lock-in.
- User-specific broker/data access must respect broker, exchange, and applicable SEBI/data-sharing terms. Do not centrally redistribute broker market data unless explicitly permitted.
- Broker client secrets remain backend-only; customer authorization should use the broker's supported OAuth/authorization flow.
- Financial calculations must live in reusable domain modules, not UI components.
- Backend/database should become the authoritative source for persistent trading state as the platform matures.
- Every important financial rule must have automated tests.
- Build incrementally; one controlled milestone at a time.

## 3. Current technology

- Frontend: Next.js 14 / React 18.
- Backend: Python/FastAPI-style backend.
- Current broker/data integration: Upstox.
- Current charting: Recharts.
- Current frontend tests: Vitest.
- Deployment currently uses environment configuration (including Upstox application credentials) in the backend environment.

## 4. Current architecture

### Frontend domains

`frontend/lib/strategy/`
- `strategy.js`
- `strategyUtils.js`
- `strategyValidation.js`
- `strategyIdentity.js`

`frontend/lib/calculations/`
- `payoff.js`
- `risk.js`
- `greeks.js`
- `strategyCalculator.js`

### Current application areas

- Strategy Builder / Paper Trading page
- Market/option-chain data
- Strategy templates
- Payoff chart
- Basic Greeks
- Paper positions and P&L
- Order history / journal
- Market-hours protection

### Backend domains

- Authentication/session handling
- Upstox integration
- Paper trading API
- Market status service
- Journal/database models and services

## 5. Canonical strategy model

A Strategy is the reusable domain object that future modules consume.

Conceptually:

```text
Strategy
- id
- name
- underlying
- primaryExpiry
- legs[]
- source
- status
- createdAt
- updatedAt
```

A StrategyLeg conceptually contains:

```text
- id
- type: call | put
- action: buy | sell
- strike
- expiry
- qty (lots)
- price (premium)
- optional metadata such as hedge
```

The same Strategy definition should eventually be reusable by:

```text
Strategy Builder
    ↓
Payoff / Risk
    ↓
Greeks
    ↓
Scenario Engine
    ↓
Paper Trading
    ↓
Journal / Analytics
    ↓
Backtesting
    ↓
Scanner
```

## 6. Financial calculation rules

### Max loss / max profit

- Long Call: max loss = premium paid; max profit = unlimited.
- Long Put: max loss = premium paid; max profit = theoretically finite based on underlying lower bound of 0.
- Naked Short Call: max loss = unlimited; max profit = premium received.
- Naked Short Put: max loss = potentially finite based on underlying price >= 0; max profit = premium received.
- Defined-risk spreads and combinations must be derived from their actual legs, quantities, strikes, premiums, lot size, multiplier and payoff structure.
- Never classify a position as unlimited merely because it contains a short leg. Net exposure/tail behavior matters.

### Premium flow

Positive net premium flow = debit.
Negative net premium flow = credit.

`premiumOutlay` is the premium paid on long legs. It is NOT the same thing as required margin/capital.

### Reward / Risk

For defined-risk positions:

`Reward/Risk = Max Profit / Absolute Max Loss`

If profit or loss is structurally unlimited, do not fabricate a finite ratio. Use a clean internal flag/null representation and let the UI display `Unlimited` or `N/A`.

### Premium ROI

`Premium ROI = Max Profit / Net Debit × 100`

Only meaningful when max profit is finite and net debit > 0.

Do not call this Return on Capital.

A future capital/margin engine will provide a separate capital-based metric.

## 7. Market-hours / paper trading rules

- Market OPEN: new paper orders allowed.
- Market CLOSED: new paper orders blocked.
- Market UNKNOWN/unverifiable: block orders.
- Final market validation must occur immediately before execution.
- Backend/server-side market gate remains the final authority.
- Existing positions remain viewable after market close.
- Market-close rejection must not create a false paper fill.
- Double-click/duplicate execution must be prevented.

## 8. Broker/data architecture direction

Long-term direction is **Bring Your Own Broker / user-authorized broker connections**.

Current baseline:

```text
Platform's broker application credentials
        ↓
Backend-only environment/secrets
        ↓
Broker OAuth / authorization
        ↓
Customer-specific access token
        ↓
Broker adapter
        ↓
User-specific market/data context
```

Implemented foundation (Phase 6.5.0.2 — see below):

```text
Application (strategy / risk / Greeks / IV / capital / portfolio /
Exit Intent / StrategyLegExposure — all broker-independent)
        ↓
BrokerGateway (app/brokers/gateway.py — one controlled selection point)
        ↓
BrokerAdapter (app/brokers/domain/protocols.py — canonical contract)
        ├── UpstoxAdapter (app/brokers/adapters/upstox — Adapter #1, IMPLEMENTED)
        ├── Zerodha (future milestone)
        ├── Angel One (future milestone)
        ├── Dhan (future milestone)
        ├── Fyers (future milestone)
        └── other supported brokers (future)
```

Phase 6.5.0.2 — Broker-Neutral Connectivity Foundation (implemented,
tested; pulled forward from the former Phase 12 plan because future Phase
6.5 execution work needs a broker boundary):

- Canonical broker-neutral domain contracts (``app/brokers/domain/``):
  enums, error taxonomy (``BrokerError`` / ``BrokerErrorCode``), canonical
  instrument identity (broker keys stay in per-broker mappings), canonical
  order request/result (multi broker-order-id capable), a capability model
  that distinguishes SUPPORTED vs AVAILABLE vs ACCOUNT_DISABLED (never a
  bare boolean), and the ``BrokerAdapter`` protocol.
- ``BrokerGateway`` / ``BrokerRegistry``: broker selection happens in ONE
  controlled location; unknown brokers fail safely with BROKER_UNKNOWN.
- ``UpstoxAdapter`` (Adapter #1): the existing read-only Upstox integration
  (profile, funds, margin, market status, option chain, option contracts)
  now runs behind the adapter/gateway; Upstox-specific concepts
  (instrument keys, transaction types, product codes, HTTP status/error
  strings, token handling, V3 payload field names) stay inside the adapter
  package and the raw client (``app/services/upstox.py``).
- Upstox V3 ORDER preparation: the canonical order contract, payload
  builder and response mapper exist and are tested, but NO live broker
  execution is wired — order methods raise CAPABILITY_UNSUPPORTED.
- Native-slicing safety by construction: one canonical ``execution_policy``
  (AUTO / BROKER_NATIVE / PLATFORM_MANAGED / DISABLED) plus a multi-id
  ``BrokerOrderResult`` — platform chunking and broker-native slicing can
  never both apply to one order.

Guarantees:

- The strategy/calculation layer does not depend on a specific broker.
- Paper trading remains fully broker-independent — a user can paper trade
  without any connected broker. Paper execution is NOT live execution.
- Credentials stay backend-only; adapters never log, repr or return
  tokens; frontend-facing diagnostics never receive credentials.
- A second broker (Zerodha, ...) is a LATER milestone and will register a
  new adapter in the registry without changing domain code.

## 9. Dashboard / terminal direction

A future custom **Trading Terminal / Dashboard** is a major product module, separate from the Strategy Lab.

Planned dashboard capabilities include:

- market overview
- underlying / expiry selector
- option chain
- CE/PE LTP
- OI and OI change
- volume
- IV
- Delta/Gamma/Theta/Vega
- India VIX where available/legally appropriate
- strength / call-put analytics
- signals
- paper order panel
- positions / P&L
- alerts
- configurable widgets/layout

The dashboard must consume shared market-data and calculation services. It must not implement its own financial logic.

## 10. Implementation roadmap — current state

| Phase | Status |
|---|---|
| Phase 0 — Repository audit | ✅ Complete |
| Phase 0.5 — Strategy/calculation refactor | ✅ Complete |
| Phase 1 — Strategy Builder 2.0 | ✅ Complete |
| Phase 1.1 — Risk metrics correction | ✅ Complete |
| Phase 2 — Professional Payoff & Risk Engine | ✅ Complete |
| Phase 2.1 — Multi-expiry chain handling | ✅ Complete |
| Phase 3 — Scenario & Time Analysis | ✅ Complete |
| Phase 4.0 — Greek Foundation & Live-vs-Model Analytics | ✅ Complete |
| Phase 4.1 — IV Analytics | ✅ Complete |
| Phase 4.2 — Generic Greek/IV Analytics & Statistical Condition Engine | ✅ Complete |
| Phase 5.0 — Paper Trading & Portfolio Foundation | ✅ Complete |
| Phase 5.1 — Portfolio & Journal Analytics | ✅ Complete |
| Phase 5.2 — Bulk Paper Position Exit & Exit-All Safety | ✅ Complete |
| Phase 5.2.1 — Active Positions UX, Strategy Filtering, Market Session Awareness | ✅ Complete |
| Phase 6.0 — Capital & Margin Foundation | ✅ Complete |
| Phase 6.1 — Broker Margin Integration (Upstox) | ✅ Complete |
| Phase 6.2 — Analytical Margin Model | ✅ Complete |
| Phase 6.3 — Capital Efficiency & Return Metrics | ✅ Complete |
| Phase 6.4 — Capital Allocation / Portfolio Risk Controls | ✅ Complete |
| Phase 6.4.1 — Broker Profile & Connection Diagnostics | ✅ Complete |
| Phase 6.5.0 — Exit Intent / Selector Foundation | ✅ Complete |
| Phase 6.5.0.1 — Strategy Leg Attribution Architecture | ✅ Complete |
| Phase 6.5.0.2 — Broker-Neutral Connectivity Foundation | ✅ Complete |
| Phase 6.5.0.3 — Execution Intent + Execution Router | ✅ Complete |
| Phase 6.8 — Dynamic Template Resolution Architecture | ✅ Complete |
| Phase 6.9 — Dynamic Template Execution Safety Bridge | ✅ Complete |
| Phase 6.10 — Template Execution Audit Trail and Retry Safety | ✅ Complete |
| Phase 6.11 — Production Deployment Readiness / CORS Correction | 🔄 In Progress |
| Phase 7 — Journal & performance analytics | ⏳ Planned |
| Phase 8 — Backtesting | ⏳ Planned |
| Phase 9 — Strategy scanner | ⏳ Planned |
| Phase 10 — Custom trading terminal/dashboard | ⏳ Planned |
| Phase 11 — Automation / alerts | ⏳ Planned |
| Phase 12 — Multi-broker expansion | ⏳ Planned (foundation in 6.5.0.2) |
| Phase 13 — Community | ⏳ Planned |

### Current verified checkpoint

`391b8f06a7ec5691a6c9eb824ea06320d6ea83e5` — Phase 6.10: Template Execution Audit Trail and Retry Safety.

Tests: 995 backend + 946 frontend. Production build: PASS.

## 11. Development workflow with FreeBuff

The collaboration workflow is:

```text
User requirement
    ↓
ChatGPT: inspect repository + design architecture
    ↓
ChatGPT: write exact FreeBuff implementation prompt
    ↓
FreeBuff: implement one milestone
    ↓
GitHub main / commit
    ↓
User manual testing
    ↓
ChatGPT: inspect actual GitHub changes
    ↓
Approve / corrective prompt
    ↓
Next milestone
```

Rules:

- Do not ask FreeBuff to build the whole platform in one prompt.
- One prompt = one controlled milestone.
- Always inspect current GitHub state before a major new phase.
- Do not start the next phase until the previous one is reviewed and verified.
- FreeBuff completion reports should be shared for review, but GitHub code is the final source of truth.

## 12. Testing policy

Every financial calculation change must include tests.

Important regression cases include:

- Long Call
- Long Put
- Naked Short Call
- Naked Short Put
- Bull Call Spread
- Bear Put Spread
- Bull Put Spread
- Bear Call Spread
- Straddle / Strangle
- Iron Condor / Iron Butterfly
- Butterfly / Condor
- Ratio spreads
- asymmetric quantities
- lot-size scaling
- underlying boundary S=0
- price exactly at strike
- prices between strikes
- prices outside visible chain range

## 13. Current project state

As of 2026-08-21:

All phases through 6.10 are complete and verified. Phase 6.11 (CORS correction + deployment readiness) is in progress.

Latest verified commit: `391b8f06a7ec5691a6c9eb824ea06320d6ea83e5`

### Current architecture summary

- **Frontend:** Next.js 14 / React 18
- **Backend:** FastAPI (Python 3.12+) / SQLAlchemy 2.0
- **Database:** SQLite (development) / PostgreSQL (production)
- **Authentication:** Upstox OAuth 2.0 (single-user MVP)
- **Real-time:** WebSocket (FastAPI native) with HTTP fallback
- **Paper execution:** Server-authoritative
- **Execution boundary:** ExecutionIntent → ExecutionRouter → Paper Execution Engine
- **Position attribution:** StrategyLegExposure (per-execution, per-leg remaining)
- **Template execution:** preview → confirmation → server resolution → validation → audit metadata
- **Idempotency:** clientOrderId-based at both execution and exit boundaries
- **LIVE execution:** DISABLED — Paper is the safe execution environment
- **Deployment target:** Railway backend + PostgreSQL / Vercel frontend

### Key architectural features completed

- Dynamic V2 template resolution with formula-driven strike/expiry resolution
- Server-authoritative resolution during execution (never trusts client values)
- Execution audit trail (formula, preview, confirmed, execution resolution)
- Deterministic/retry-safe client identity with server-side idempotency
- One-strike-step tolerance with confirmation-based material-change protection
- Broker-neutral domain architecture (BrokerGateway → BrokerAdapter → UpstoxAdapter)

## 14. Current key limitations / future work

- Execution-time quote_timestamp is not currently captured (blocked by protected `resolve_market_prices()` interface)
- broker_data.spot_price may be null at the template router level
- Single-user MVP — multi-user architecture not yet implemented
- Live execution is disabled — requires full broker order placement pipeline
- Community features must be designed carefully around market-data licensing/redistribution constraints
- Persistent audit trail could be extended to all execution types (not just V2 template)
- No automated database backup in production
- No rate limiting on API endpoints

## 15. Permanent project constraint

The platform should remain useful without paid/trial-only dependencies wherever reasonably possible. Any recommendation involving a third-party hosted service, market-data provider, broker API, infrastructure or SaaS must be checked for current pricing/terms before becoming a core architectural dependency.
