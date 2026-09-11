# StrikeNova Production Auth Handoff Review

**Date:** 2026-09-11

## Result

**BLOCKED** — the reported auth handoff fix is not present in the authoritative GitHub candidate used by the public production deployment.

## Evidence

### Public production deployment

- Vercel project: `options-dashboard`
- Deployment: `dpl_4tqQyqpGRQS41kf2RBCpZY8HirfZ`
- Candidate: `cedea111dd400e72c4a57a468d6d994417a1cc6f`
- State: READY
- This deployment is cleanly associated with commit `cedea11`.

### Authenticated application deployment

The separate Vercel project `frontend` now has a READY production deployment:

- Deployment: `dpl_FptThoh7VxXpwdYHj5ri65EVpfJr`
- Candidate metadata SHA: `cedea111dd400e72c4a57a468d6d994417a1cc6f`
- Aliases include `frontend-zeta-gray-75.vercel.app`
- Vercel metadata reports `gitDirty: 1`.

The `gitDirty: 1` flag indicates that the deployment was created from a working tree containing changes not represented by the Git commit SHA.

## Source verification

At GitHub commit `cedea111dd400e72c4a57a468d6d994417a1cc6f`:

`frontend/components/public/AuthModal.js` still redirects with `router.push("/dashboard")` after successful authentication.

`frontend/components/public/PublicLayout.js` still redirects with `router.push(redirectPath || "/dashboard")` after Google authentication.

The commit does not contain `NEXT_PUBLIC_APP_URL` usage in these handoff paths.

Therefore the claimed `window.location.assign(APP_URL + "/dashboard#session_id=...")` change is not part of the authoritative GitHub candidate.

## Backend evidence

Railway production service:

`options-dashboard-production-fb47.up.railway.app`

A real `POST /auth/google/state` request returned HTTP 200, proving that the public deployment can reach the production backend for the Google login initialization stage.

## Root cause

The public site and authenticated app are correctly separated into different Vercel projects, but the public-site production code still performs same-origin `/dashboard` navigation. The authenticated dashboard lives in the separate `frontend` project.

## Required correction

1. Commit the auth handoff change to GitHub.
2. Introduce/use `NEXT_PUBLIC_APP_URL` on the public deployment.
3. Route successful email and Google authentication to:
   `https://frontend-zeta-gray-75.vercel.app/dashboard#session_id=...`
4. Keep the fragment-based session transfer.
5. Do not merge the Vercel projects.
6. Do not deploy the public-site-only candidate to the authenticated `frontend` project as a replacement for the core app.
7. Redeploy the corrected public candidate from the clean committed tree.
8. Browser-verify end-to-end login.

## Release state

- Public website: deployed
- Authenticated application: deployed
- Public-to-app auth handoff: **BLOCKED**
- V1.2 release acceptance: **HOLD until auth handoff is committed and re-verified**
