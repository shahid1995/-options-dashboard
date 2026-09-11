# StrikeNova — Production Auth Handoff Correction

## Mission

Fix the public-site → authenticated-app login handoff and deploy only from a clean, committed GitHub revision.

## Root cause

The accepted public-site candidate `cedea111dd400e72c4a57a468d6d994417a1cc6f` still uses same-origin Next navigation to `/dashboard` in `AuthModal.js` and `PublicLayout.js`. The authenticated routes actually belong to the separate Vercel `frontend` project.

A prior agent run reported a handoff fix but deployed it to the `frontend` project with `gitDirty=1`; those changes are not represented by the GitHub commit. Therefore the public production site does not yet contain the fix.

## Required architecture

```text
Public site
  Vercel project: options-dashboard
  https://options-dashboard-sigma-coral.vercel.app
          |
          | authentication API calls
          v
Railway backend
  https://options-dashboard-production-fb47.up.railway.app
          |
          | session_id
          v
Authenticated app
  Vercel project: frontend
  https://frontend-zeta-gray-75.vercel.app
          |
          v
  /dashboard, /paper, /portfolio, /positions, /orders,
  /strategies, /activity, /settings
```

Do not merge these projects.

## Acceptance candidate before correction

`cedea111dd400e72c4a57a468d6d994417a1cc6f`

## Required source changes

### `frontend/components/public/AuthModal.js`

After successful email login/registration, redirect to the authenticated app using a configurable origin:

`NEXT_PUBLIC_APP_URL`

Target:

`<APP_URL>/dashboard#session_id=<session_id>`

Use browser navigation (`window.location.assign` or equivalent) because the destination is cross-origin. Do not use `router.push('/dashboard')` for this handoff.

Do not put the session ID in a query parameter.

### `frontend/components/public/PublicLayout.js`

After successful Google OAuth callback handling, redirect to:

`<APP_URL>/<validated-path>#session_id=<session_id>`

Use browser navigation for the cross-origin handoff.

Preserve the existing nonce/state validation and token URL scrubbing.

Do not weaken OAuth security.

## Configuration

Configure public Vercel build-time environment:

`NEXT_PUBLIC_APP_URL=https://frontend-zeta-gray-75.vercel.app`

Do not hard-code the production app URL in source.

Do not commit secrets.

Do not change unrelated environment variables.

## Session requirements

The authenticated app already consumes `#session_id=...` via `captureSessionFromUrl()`.

Preserve that contract.

Never use `?session_id=...`.

Never expose broker credentials or access tokens in URLs.

## Redirect security

Preserve/implement validated internal redirect paths only.

Do not allow arbitrary external redirect URLs.

Default destination remains `/dashboard`.

## Backend/CORS

Verify Railway production CORS permits the required public and authenticated-app origins as appropriate.

Do not use wildcard `*` with credentials.

Do not change backend code unless verification proves a configuration change is needed.

## Tests

Add focused regression tests covering:

1. Email login success → cross-origin `/dashboard#session_id=...`.
2. Registration + auto-login → same handoff.
3. Google callback success → same handoff.
4. Session ID stays in fragment, never query string.
5. `NEXT_PUBLIC_APP_URL` is consumed.
6. No hard-coded production app origin in auth components.
7. Existing signed state/nonce validation remains intact.
8. Failed authentication stays on the public site.
9. Redirect paths cannot become arbitrary external URLs.

## Verification

Run fresh:

- complete frontend test suite;
- production build;
- all 7 public routes;
- all 9 authenticated routes;
- browser email-login flow;
- browser Google-login flow where environment permits;
- session-fragment handoff verification;
- Railway backend logs;
- CORS verification;
- console error check.

Target URLs:

Public:
`https://options-dashboard-sigma-coral.vercel.app`

Authenticated app:
`https://frontend-zeta-gray-75.vercel.app/dashboard`

## Deployment rules

1. Commit the source changes to GitHub first.
2. Ensure working tree is clean.
3. Verify exact commit SHA.
4. Deploy only the public `options-dashboard` Vercel project with that committed revision.
5. Do not deploy the public site candidate to the `frontend` authenticated-app project.
6. The authenticated-app project must remain available and unchanged except for deployment verification.
7. Never report success from a dirty deployment.

## Protected scope

Do not modify:

- backend/FastAPI business logic;
- database/schema/migrations;
- broker integrations;
- trading/execution logic;
- financial calculations;
- market-data architecture;
- authenticated application business logic;
- Signal Field UX;
- public page designs.

A backend configuration-only origin update is allowed only if verified necessary.

## Recommended commit

`fix(auth): route public login into authenticated app`

## Required final report

```text
AUTH HANDOFF CORRECTION: PASS / BLOCKED

Code commit:
Parent:
Branch:
Working tree:

NEXT_PUBLIC_APP_URL:

Public Vercel project:
Authenticated Vercel project:
Backend:

Email login:
Google login:
Session transfer:
Dashboard redirect:
CORS:

Tests:
Build:
Public routes:
Authenticated routes:
Browser verification:
Console errors:

Production deployment ID:
Production URL:
Production commit SHA:

Code changes:
Backend changes:
Database changes:
OAuth security changes:

Deployment: COMPLETED / NOT PERFORMED
```

## STOP

After the clean commit is pushed and production verification passes, stop. Do not begin another redesign or modify the two-project architecture.
