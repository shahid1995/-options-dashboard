# Day 37 — Domain Event Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a typed, immutable, tenant-aware, in-process domain-event foundation inside the modular monolith without introducing distributed infrastructure or execution behavior.

**Architecture:** Add a small pure domain-events package containing an immutable event envelope, publisher abstraction, in-process event bus, handler contract/registry, and handler-scoped idempotency semantics. Domain producers depend on the publishing abstraction; consumers register typed handlers; no database event store is introduced on Day 37 because durable lifecycle/audit storage and replay belong to Day 38.

**Tech Stack:** Python, existing backend domain conventions, pytest, standard-library typing/dataclasses/serialization primitives only unless an already-approved project dependency is required by existing conventions.

**Spec:** `options-dashboard-project/docs/superpowers/specs/2026-09-05-strikenova-day37-domain-events-design.md` (use the approved Day 37 design in the repository; if the exact spec path differs, locate the approved Day 37 design before implementation and do not invent a replacement scope).

## Global Constraints

- Day 37 is an in-process domain-event foundation only.
- Events must be typed, immutable, versioned, tenant-aware, and auditable by identity/timestamp/aggregate context.
- Event timestamps are caller-supplied; domain code must not read the wall clock.
- Event IDs are caller-supplied; domain code must not generate randomness/UUIDs.
- Handler idempotency is scoped by `event_id + handler identity`, not by `event_id` alone.
- Tenant context must never be dropped or inferred from ambient/global state.
- Publishers depend on abstractions; domains must not depend on the concrete event bus.
- Handler failures must be isolated and observable to the publisher/bus; one handler must not silently suppress another handler's execution.
- Unknown event types must fail deterministically at the routing boundary rather than being silently coerced.
- No Kafka, Redis Streams, RabbitMQ, Celery, distributed event bus, background worker, or external messaging infrastructure.
- No database event store, event-sourcing implementation, replay engine, or lifecycle/audit persistence on Day 37.
- No trade lifecycle, order request, broker response, fill, position-sync, Upstox integration, execution gate, frontend event, notification, AI/ML, or historical-data ingestion behavior.
- No changes to Day 33 central-risk semantics or Day 35 portfolio-intelligence semantics.
- No production deployment, production DB changes, merge, or live execution.
- TDD is mandatory; every behavioral change must have a failing test before implementation.

---

## File Structure

**Create:**
- `options-dashboard-project/backend/app/domain_events/__init__.py` — public package surface; export only the approved domain-event contracts and in-process bus/publisher interfaces.
- `options-dashboard-project/backend/app/domain_events/contracts.py` — immutable event envelope and serialization/type contracts.
- `options-dashboard-project/backend/app/domain_events/handler.py` — typed handler protocol/contract and stable handler identity rules.
- `options-dashboard-project/backend/app/domain_events/idempotency.py` — in-process handler-scoped duplicate-delivery guard.
- `options-dashboard-project/backend/app/domain_events/bus.py` — in-process typed event routing and handler invocation.
- `options-dashboard-project/backend/app/domain_events/publisher.py` — publishing abstraction used by domain producers.
- `options-dashboard-project/backend/tests/test_day37_domain_events.py` — focused TDD suite.

**Do not modify existing business-domain modules unless a concrete, test-backed integration point is required to demonstrate the publishing abstraction. Prefer keeping Day 37 entirely additive.**

---

### Task 1: Establish the immutable typed event envelope

**Files:**
- Create: `backend/app/domain_events/contracts.py`
- Create: `backend/tests/test_day37_domain_events.py`

**Interfaces:**
- Produce `DomainEvent` with at least: `event_id`, `event_type`, `aggregate_type`, `aggregate_id`, `occurred_at`, `tenant_id`, `event_version`, `payload`, and `metadata`.
- `DomainEvent` is immutable after construction.
- `event_type` identifies the typed event contract; `event_version` supports explicit schema evolution.
- `occurred_at` is supplied by the caller and must be timezone-aware.
- Tenant and aggregate identity are explicit fields, never ambient.

- [ ] **Step 1: Write failing tests** for construction, required identity fields, timezone-aware timestamp, immutability, tenant preservation, event-version preservation, and payload/metadata serialization.
- [ ] **Step 2: Run the focused tests** and verify they fail for the missing contract.
- [ ] **Step 3: Implement the minimal frozen contract** using project-compatible standard-library primitives; reject invalid timestamps/empty identity fields deterministically.
- [ ] **Step 4: Run the focused tests** and verify they pass.
- [ ] **Step 5: Add deterministic serialization tests** proving equivalent inputs produce equivalent serialized representations and no runtime object identity leaks into serialization.
- [ ] **Step 6: Commit** with a focused message such as `feat: add immutable domain event envelope`.

---

### Task 2: Define handler and publisher boundaries

**Files:**
- Create: `backend/app/domain_events/handler.py`
- Create: `backend/app/domain_events/publisher.py`
- Modify: `backend/app/domain_events/contracts.py` only if Task 2 reveals a contract-level type requirement.
- Test: `backend/tests/test_day37_domain_events.py`

**Interfaces:**
- `DomainEventHandler` consumes one `DomainEvent` and exposes a stable handler identity.
- `EventPublisher` exposes `publish(event: DomainEvent) -> None` (or the project's established equivalent if repository conventions require an awaitable API; do not introduce async solely for speculation).
- Domain producers depend on `EventPublisher`, never on `EventBus` internals.

- [ ] **Step 1: Write failing tests** proving a publisher abstraction can be supplied to a domain producer without importing the concrete bus.
- [ ] **Step 2: Run the focused boundary tests** and verify failure.
- [ ] **Step 3: Implement minimal protocols/interfaces** with no routing or persistence logic.
- [ ] **Step 4: Add tests for stable handler identity** and rejection of ambiguous/empty handler identities.
- [ ] **Step 5: Run focused tests** and verify pass.
- [ ] **Step 6: Commit** with a focused message such as `feat: define domain event boundaries`.

---

### Task 3: Implement handler-scoped idempotency

**Files:**
- Create: `backend/app/domain_events/idempotency.py`
- Test: `backend/tests/test_day37_domain_events.py`

**Interfaces:**
- Provide an in-process idempotency component keyed by `(event_id, handler_id)`.
- Duplicate delivery of the same event to the same handler is suppressed deterministically.
- The same event delivered to two different handlers is independently eligible for processing.
- Idempotency state is process-local only; it is not presented as durable exactly-once delivery.

- [ ] **Step 1: Write failing tests** for first delivery, duplicate same-handler delivery, same event/different-handler delivery, and independent event IDs.
- [ ] **Step 2: Run tests** and verify failure.
- [ ] **Step 3: Implement the smallest in-memory guard** with deterministic behavior.
- [ ] **Step 4: Add a test proving handler identity participates in the key.**
- [ ] **Step 5: Run tests** and verify pass.
- [ ] **Step 6: Commit** with a focused message such as `feat: add handler scoped event idempotency`.

---

### Task 4: Implement the in-process typed event bus

**Files:**
- Create: `backend/app/domain_events/bus.py`
- Test: `backend/tests/test_day37_domain_events.py`

**Interfaces:**
- `EventBus` implements the `EventPublisher` boundary.
- Provide `subscribe(event_type, handler)` and `publish(event)` semantics.
- Routing is by explicit event type; registration order must be deterministic.
- Multiple handlers may consume the same event type.
- Duplicate delivery is filtered per `(event_id, handler_id)`.
- A handler failure is surfaced deterministically and must not silently convert to success.

- [ ] **Step 1: Write failing tests** for typed routing, multiple handlers, deterministic order, unknown event type, duplicate delivery, tenant preservation, and handler failure.
- [ ] **Step 2: Run tests** and verify failure.
- [ ] **Step 3: Implement the minimal in-process registry and dispatch path.**
- [ ] **Step 4: Add tests proving an event routed to handler A does not invoke unrelated handler B and that a duplicate event does not execute handler A twice.**
- [ ] **Step 5: Add a failure-path test** proving handler exceptions are explicit and do not become false publish success.
- [ ] **Step 6: Run focused tests and the relevant existing backend test subset.**
- [ ] **Step 7: Commit** with a focused message such as `feat: add in process domain event bus`.

---

### Task 5: Define public package surface and circular-coupling safeguards

**Files:**
- Create: `backend/app/domain_events/__init__.py`
- Test: `backend/tests/test_day37_domain_events.py`

**Interfaces:**
- Public imports expose only the stable event contract, publisher boundary, handler contract, and bus entrypoint needed by future domains.
- Internal implementation modules remain replaceable.

- [ ] **Step 1: Write failing import-boundary tests** that import the public API and verify no concrete business domain is imported transitively.
- [ ] **Step 2: Run tests** and verify failure where appropriate.
- [ ] **Step 3: Implement the narrow public API.**
- [ ] **Step 4: Add static/source inspection tests or repository-approved checks for forbidden imports/circular coupling.**
- [ ] **Step 5: Run focused tests and import checks.**
- [ ] **Step 6: Commit** with a focused message such as `feat: expose domain event public api`.

---

### Task 6: Complete invariant and regression verification

**Files:**
- Test: `backend/tests/test_day37_domain_events.py`
- Modify: only Day 37 files if defects are discovered.

**Interfaces:**
- Verify the complete Day 37 acceptance gate without adding later-day lifecycle semantics.

- [ ] **Step 1: Add/complete tests** covering at minimum: immutable envelope; typed routing; event version; aggregate identity; tenant isolation/preservation; caller-supplied timestamp; deterministic ordering; multiple handlers; duplicate delivery; handler-scoped idempotency; handler failure; unknown type; serialization; public API; and no database/network/broker dependency.
- [ ] **Step 2: Run focused Day 37 suite** with `pytest backend/tests/test_day37_domain_events.py -q` (adjust only for the repository's established test invocation/path conventions).
- [ ] **Step 3: Run the relevant regression suite** covering prior approved intelligence/risk/portfolio boundaries; do not replace the full-suite run with only focused tests.
- [ ] **Step 4: Perform source inspection** for wall-clock calls, UUID/random generation, database/network imports, broker imports, distributed messaging dependencies, and forbidden Day38+ behavior.
- [ ] **Step 5: Review the final diff** and confirm only approved Day 37 files/scope changed.
- [ ] **Step 6: Record test counts, invariant evidence, and scope audit in the implementation report/status tracker according to repository convention.**
- [ ] **Step 7: Commit the final Day 37 evidence/status update separately from functional implementation where repository practice permits.**

---

## Day 37 Acceptance Gate

Day 37 passes only if all are true:

1. A typed immutable event envelope exists with event ID, type, aggregate identity, caller-supplied timestamp, tenant context, version, payload, and metadata.
2. Event serialization is deterministic and version-aware.
3. Publishing is an abstraction; domain producers do not depend on concrete bus internals.
4. The bus is in-process only and routes deterministically by event type.
5. Multiple handlers are supported without cross-handler state coupling.
6. Idempotency is explicitly handler-scoped by event ID plus handler identity.
7. Tenant context is preserved end-to-end; no ambient tenant inference exists.
8. Handler failures are explicit and cannot silently report successful handling.
9. Unknown event types are handled deterministically rather than coerced or ignored.
10. No wall-clock, UUID/randomness, DB, network, broker, distributed bus, or external worker dependency exists in the domain-event foundation.
11. No trade/order/fill/position lifecycle semantics have leaked in from Day 38+.
12. Existing approved Days 19–36 semantics remain unchanged.
13. Focused tests and required regression tests pass with fresh evidence.
14. The implementation agent does not deploy, merge, alter production infrastructure, or begin Day 38.

**Stop condition:** If any acceptance-gate item fails, stop at Day 37, diagnose/remediate, and do not advance to Day 38 until the independent project-control review returns 🟢 APPROVED.
