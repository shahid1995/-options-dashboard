# Changelog

All notable changes to the StrikeNova control-document set at the repository
root. Application-level release history lives with the code and the status
tracker (`options-dashboard-project/docs/superpowers/STRIKENOVA_IMPLEMENTATION_STATUS.md`).

Format: date — change — reference.

---

## 2026-09-19 — Real Brevo delivery verified on staging (Issue #67)

- Configured the staging Render service (`strikenova-api-staging`) with
  `EMAIL_PROVIDER=brevo` and the Brevo transactional configuration (API key in
  the Render secret store only; never printed, committed, or logged) and
  deployed commit `546307d` (deploy `dep-damommnf3r2c73ap40jg`).
- Verified real mailbox delivery end-to-end on staging: registration
  verification, password reset (with full session revocation and a link-free
  security notification), and email-change confirmation to the NEW address
  (with link-free notification); all links resolved to
  `EMAIL_BASE_URL` verification pages and all single-use tokens rejected
  replay (400). Evidence: ADR-012.
- Status effect: real mailbox/email-delivery verification moves from Pending
  to **Verified (2026-09-19, staging)**. The final Phase 10.2
  release/security gate remains **pending** (ADR-011/ADR-012).

---

## 2026-09-18 — Brevo transactional-email adapter (Issue #65)

- Added `BrevoEmailSender` behind the provider-neutral `EmailSender`
  boundary (`backend/app/services/email.py`): Brevo `smtp/email` endpoint,
  `api-key` header, `sender` object, `[{"email"}]` recipients,
  `htmlContent`/`textContent`. No vendor SDK in the auth flow; account
  security code remains Brevo-unaware.
- Provider selection is now explicit: `EMAIL_PROVIDER=inmemory|brevo`
  (default `inmemory`; the deterministic test sender never performs network
  calls). Selecting `brevo` without `BREVO_API_KEY` fails fast — never a
  silent fallback. `BREVO_API_URL` defaults to the Brevo endpoint.
- Hardened the transport: the deterministic capture mirror now runs only for
  the in-memory sender, so production provider message contents (which
  contain verification/reset links) are never persisted in memory or the
  database; credentials/tokens/URLs are never logged.
- Status effect: transactional email provider integration is **implemented
  in code**; real mailbox/email-delivery verification and the final Phase
  10.2 release/security gate remain **pending** (ADR-011).

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

## 2026-09-16 — Phase 10.2 auth/account-security design approved (context)

Approved design and execution plan for Phase 10.2 (auth & account security)
landed under `options-dashboard-project/docs/superpowers/` (spec + plan dated
2026-09-16). The phase is **not** uniformly complete — see
[`DECISIONS.md`](DECISIONS.md) ADR-011 for the standing status record:

- identity/session hardening — completed;
- token/OAuth-state work — completed;
- account-auth implementation — substantially implemented;
- secure browser session transport — completed by PR #62 (Issue #61),
  merged 2026-09-18 at `aa70629`;
- transactional email provider integration — implemented and live
  (**Brevo** adapter, Issue #65);
- real mailbox/email-delivery verification — **verified 2026-09-19 on
  staging (Issue #67, ADR-012)**;
- final end-to-end Phase 10.2 release/security gate — pending.

  *(2026-09-19 update, Issue #67: the two delivery-related items above were
  completed and verified on staging; see the 2026-09-19 entry.)*

PR #62 completed only the secure browser-session transport/reconciliation
work associated with Issue #61 — not the entire Phase 10.2 execution plan.
Recorded here 2026-09-18 with the control set.

---

Earlier governance (pre-2026-09-18): project-control conventions existed on
`main` only as `PROJECT-CONTROL.md` (not on this branch). The document set
above is their successor and single home; do not fork it.
