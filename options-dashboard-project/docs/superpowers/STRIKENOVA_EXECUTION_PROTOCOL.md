# StrikeNova Execution Protocol

## Operating Principles

1. **TDD First:** Every implementation change starts with a failing test that demonstrates the required behavior.
2. **Smallest Coherent Change:** Implement the minimum change that satisfies the test and the Blueprint.
3. **Gate Enforcement:** A failed gate keeps that day open. The calendar does not override correctness.
4. **Evidence Required:** Every gate pass requires fresh, demonstrable evidence — not historical claims.
5. **Scope Discipline:** Work only within the current day's scope. Do not advance without a PASS.
6. **No Production Mutation:** Implementation agents do not deploy, merge to production, rotate production secrets, or cut over databases without explicit human authorization.

## Daily Operating Loop

1. Read the relevant Blueprint sections and this day's objective.
2. Inspect current code before changing it.
3. Identify the smallest testable task boundary.
4. Write the failing test(s) first.
5. Implement the minimum change that satisfies the test and Blueprint.
6. Run focused tests.
7. Run the relevant backend/frontend regression suite.
8. Inspect the diff for scope creep and architectural drift.
9. Record verification evidence and unresolved risks.
10. Commit the day's coherent work.
11. Evaluate the day's exit gate.
12. Only after a PASS does the next day become active.

## Recovery Rule

If a test, migration, broker contract, quant invariant, security check, or production-readiness gate fails, stop advancing the sequence and diagnose the root cause before continuing. Do not stack later work on an unstable foundation.

## Change Control

- Do not insert unrelated features into the current day's scope.
- If a Blueprint defect is discovered, stop, document, propose correction, and obtain approval before continuing.
- Record unrelated improvements as backlog items.

## Status Tracking

- The execution status tracker (`STRIKENOVA_IMPLEMENTATION_STATUS.md`) is mandatory execution evidence.
- Each day records: milestone, commit, tests, verification result, blockers.
- Gate evidence must be fresh — do not claim PASS based on historical test runs.
