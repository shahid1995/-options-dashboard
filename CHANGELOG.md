# Changelog

All notable changes to the StrikeNova control-document set at the repository
root. Application-level release history lives with the code and the status
tracker (`options-dashboard-project/docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`).

Format: date — change — reference.

---

## 2026-09-18 — Introduced the canonical control-document set (Issue #63)

- Added the eleven canonical control documents at the repository root:
  `AI.md` (entry point + runtime topology), `PROJECT-CONTROL.md` (authority
  model, workflow, board, contracts), `AGENTS.md` (agent operating rules +
  anti-context-drift), `CONTEXT.md`, `INVARIANTS.md`, `DECISIONS.md`,
  `ARCHITECTURE.md`, `SECURITY.md`, `DATA.md`, `TESTING.md`, `CHANGELOG.md`.
- Synchronized from `main`'s project-control system (imported without merging
  `main` history) and reconciled against the active feature branch.
- Runtime topology recorded as current truth: **Vercel (frontend) → Render
  (backend) → CockroachDB (production database)**; Railway explicitly marked
  historical (ADR-004).
- Security model recorded to match the merged Issue #61 state: cookie-only
  HttpOnly `strikenova_session` browser transport; BYOB/platform separation;
  401/403 vs transient (5xx/network) auth-failure semantics (ADR-007).
- References: Issue #63; branch `fix/63-sync-control-docs`; base
  `aa70629a7969c309bbd4caaa6f97c05e561ecb81` (merge of PR #62).

## 2026-09-16 — Auth/account-security design approved (context)

Approved design and execution plan for the secure session transport landed
under `options-dashboard-project/docs/superpowers/` (spec + plan dated
2026-09-16); implementation completed by PR #62 (Issue #61), merged
2026-09-18 at `aa70629`. Recorded here 2026-09-18 with the control set.

---

Earlier governance (pre-2026-09-18): project-control conventions existed on
`main` only as `PROJECT-CONTROL.md` (not on this branch). The document set
above is their successor and single home; do not fork it.
