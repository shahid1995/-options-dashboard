# StrikeNova Day 3 Security Hardening Audit — 2026-09-02

## Status

**OPEN — security gate not yet passed.**

No production deployment, Railway change, production database cutover, or merge was performed.

## Verified controls

- Repository-root GitHub Actions workflows are active.
- Full-history Gitleaks secret scan passes on the current branch.
- Repository secret hygiene was hardened in Day 1/Day 2.
- Runtime Python dependency audit is enforced in CI.
- Frontend production dependency audit is enforced in CI.
- Root `.gitignore` covers `.env.*` while preserving `.env.example`.

## Findings

### SEC-01 — OAuth login/callback still contain legacy platform-credential fallback

**Severity: High / P0 before production broker onboarding.**

`backend/app/routers/auth.py` still contains backward-compatibility fallback behavior that can use platform-level Upstox credentials when per-user credentials are unavailable. The approved StrikeNova architecture is authenticated-first BYOB: broker OAuth must be bound to an authenticated StrikeNova user and use that user's broker credential set.

Required remediation:

1. Require an authenticated StrikeNova session before `/auth/login` can start broker OAuth.
2. Reject OAuth callback state that is not bound to an authenticated session.
3. Resolve the broker connection/user from the bound StrikeNova session rather than creating a new StrikeNova identity from the broker profile.
4. Remove platform-level broker credential fallback from the production BYOB path.
5. Add regression tests for anonymous login rejection, unbound callback rejection, and cross-user state rejection.

### SEC-02 — Frontend dependency baseline upgrade needs compatibility work

The existing Next.js 14.2.35 line is unsupported by the current Next.js support policy and the security audit identifies high-severity advisories affecting that dependency range. Next.js 15.5.25 was selected as the maintenance-LTS upgrade target.

React 19 is required for the Next.js 15 App Router upgrade. The first generated dependency update exposed a peer-dependency conflict with Recharts 2.12.7. Recharts 3.10.1 is the current stable target and must be upgraded together with React 19.

Required verification after the Recharts upgrade:

- `npm ci`
- Vitest suite
- Next.js production build
- Browser smoke verification
- Visual verification of chart-heavy pages
- npm production dependency audit

### SEC-03 — CI action runtime warnings

GitHub Actions currently warns that the `checkout@v4` and `setup-node@v4` actions target Node 20 and are being forced onto Node 24 by the hosted runner. This is not currently blocking, but action modernization should be completed during CI/CD hardening rather than mixed into the current security fix.

## Day 3 exit criteria

Day 3 cannot be marked PASS until SEC-01 is remediated and the frontend security baseline passes the complete CI/build/browser verification chain.

## Non-goals for Day 3

- No production deployment.
- No Railway production configuration changes.
- No PostgreSQL production cutover.
- No live broker execution changes.
- No broad architectural refactor.
