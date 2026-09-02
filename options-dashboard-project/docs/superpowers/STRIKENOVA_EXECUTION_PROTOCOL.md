# StrikeNova Execution Protocol

## Purpose

Prevent implementation drift between the **StrikeNova Architecture Blueprint master plan** and the **implementation status ledger**.

### Required files

1. **Master plan** — `docs/superpowers/plans/2026-09-02-strikenova-architecture-blueprint-v1-master-implementation-plan.md`
2. **Status ledger** — `docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`
3. **CI enforcement** — `.github/workflows/strikenova-status-gate.yml`

The master plan defines **what/why/order/gates**. The status ledger defines **what has actually happened/evidence/state**. Never use the status ledger as a replacement for reading the master plan.

## Mandatory work loop

At the beginning of every implementation batch:

1. Read the master plan.
2. Read the status ledger.
3. Identify the active Day and its exact objective/tasks/gate.
4. Inspect current code and recent commits.
5. Work only inside the active day's scope unless an explicit architectural change is approved.
6. Use TDD: failing test → minimal implementation → focused pass → regression pass.
7. Inspect the final diff for scope creep.
8. Update the status ledger with evidence.
9. Commit the coherent implementation and status update together whenever practical.
10. Evaluate the day's gate.
11. **Do not start the next day unless the current gate is PASS.**

## Mandatory milestone rule

A milestone is not complete because:

- code was written;
- tests were written;
- a commit exists;
- a PR is open;
- a deployment succeeded; or
- the calendar moved to the next day.

It is complete only when the master-plan gate is satisfied and the status ledger records verifiable evidence.

## CI enforcement

The repository status gate is intentionally simple:

- implementation changes in backend/frontend/migrations/config/workflow areas require a status-ledger change;
- a change to the master plan requires a status-ledger change;
- the status ledger's recorded master-plan blob SHA must match the checked-out master plan;
- the workflow fails rather than silently allowing the implementation to proceed without status synchronization.

This is a **guardrail**, not an automatic status generator. Humans/agents must still write accurate evidence; CI cannot truthfully decide whether a milestone passed.

## Agent handoff rule

If a work session is interrupted, the next agent/session must start from:

1. master plan;
2. status ledger;
3. current branch/PR state;
4. latest status entry;
5. active day's gate and blockers.

Do not infer progress from chat history alone.

## Production safety

The protocol does not authorize:

- production deployment;
- production PostgreSQL cutover;
- merging draft PRs;
- live broker execution;
- destructive data changes.

Those remain separately approval-gated.
