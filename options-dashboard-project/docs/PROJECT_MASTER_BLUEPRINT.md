# Options Dashboard — Project Master Blueprint

_Last updated: 2026-08-16_

## 1. Product vision

Build a professional options-trading research and paper-trading platform focused initially on Indian index options. The platform should let a user connect an authorized broker/data account, build and analyze multi-leg option strategies, paper trade them, monitor positions, study performance, and later backtest, scan, automate, and share strategies.

The product is currently **paper trading only**. No real-money execution is part of the current scope.

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

Future abstraction:

```text
BrokerAdapter
├── Upstox
├── Zerodha
├── Angel One
├── Dhan
├── Fyers
└── other supported brokers
```

The strategy/calculation layer should not depend on a specific broker.

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

## 10. Planned product roadmap

### Phase 0 — Repository audit
Completed.

### Phase 0.5 — Strategy/calculation architecture refactor
Completed and verified.

### Phase 1 — Strategy Builder 2.0
Completed and verified.

### Phase 1.1 — Risk metrics correction
Completed and verified.

### Phase 2 — Professional Payoff & Risk Engine
Current / next implementation phase.

Goals:
- theoretical payoff independent of visible chain limits
- analytical tail handling
- exact finite max profit/loss for same-expiry strategies
- underlying lower bound S >= 0
- exact theoretical breakevens
- separate theoretical payoff from chart/display grid
- mixed-quantity ratio handling
- explicit multi-expiry analytical limitations
- clean calculation warnings/state

### Phase 3 — Scenario & Time Analysis
Planned:
- spot price scenarios
- time-to-expiry scenarios
- IV scenarios
- combined scenarios
- current/theoretical P&L analysis

### Phase 4 — Advanced Greeks / IV analytics
Planned:
- improved Greeks presentation
- IV metrics
- strategy-level Greek analysis
- volatility relationships

### Phase 5 — Paper trading / portfolio upgrade
Planned:
- stronger server-authoritative positions/orders
- portfolio analytics
- more robust trade lifecycle

### Phase 6 — Capital & margin analysis
Planned:
- required capital
- margin estimates
- return on capital
- funds/margin summary

### Phase 7 — Strategy journal & performance analytics
Planned:
- trade journal
- win rate
- profit factor
- drawdown
- strategy performance
- filters and comparisons

### Phase 8 — Backtesting
Planned:
- historical strategy execution
- entry/exit logic
- trade statistics
- historical replay

### Phase 9 — Strategy scanner
Planned:
- generate candidate strategies
- calculate risk/reward
- rank/filter candidates

### Phase 10 — Custom trading terminal/dashboard
Planned.

### Phase 11 — Automation / alerts
Planned.

### Phase 12 — Multi-broker architecture
Planned.

### Phase 13 — Community
Planned:
- strategy sharing
- profiles
- follows
- comments
- leaderboards
- challenges

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

As of 2026-08-16:

- Phase 0: complete
- Phase 0.5: complete
- Phase 1: complete
- Phase 1.1: complete
- Phase 2: prompt prepared; implementation is the current next step

The latest known main-branch implementation commit before Phase 2 is:

`3c0430b924ae97cb37e73f279a2337b63e32a393`

## 14. Current key limitations / future work

- Payoff/risk engine must be upgraded so theoretical results do not depend on visible option-chain boundaries.
- Multi-expiry strategies need explicit analytical-mode handling until a time-value model exists.
- Margin/capital is not yet a full engine.
- Persistent server-authoritative portfolio state is a future improvement.
- Multi-broker support is future work.
- Community features must be designed carefully around market-data licensing/redistribution constraints.

## 15. Permanent project constraint

The platform should remain useful without paid/trial-only dependencies wherever reasonably possible. Any recommendation involving a third-party hosted service, market-data provider, broker API, infrastructure or SaaS must be checked for current pricing/terms before becoming a core architectural dependency.
