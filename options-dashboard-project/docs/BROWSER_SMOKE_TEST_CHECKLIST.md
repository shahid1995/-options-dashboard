# Browser Smoke Test Checklist — Staging

**Date:** 2026-08-31
**Staging URL:** `https://staging-backend.up.railway.app`
**Status:** BROWSER AUTOMATION UNAVAILABLE — Manual testing required

---

## HTTP/API Verification (Completed)

| Endpoint | HTTP Status | Expected | Result |
|----------|-------------|----------|--------|
| `GET /health` | 200 | 200 | ✅ |
| `GET /auth/status` | 403 | 403 (requires auth) | ✅ |
| `GET /auth/google/state` | 403 | 403 (requires auth) | ✅ |
| `GET /gex/snapshots` | 403 | 403 (requires auth) | ✅ |
| `GET /paper/trades` | 403 | 403 (requires auth) | ✅ |
| `GET /portfolio` | 403 | 403 (requires auth) | ✅ |
| `GET /docs` | 403 | 403 (requires auth) | ✅ |
| `OPTIONS /health` (CORS) | 200 | CORS headers present | ✅ |

### CORS Headers Verified

```
access-control-allow-credentials: true
access-control-allow-origin: http://localhost:3000
vary: Origin
```

---

## Manual Browser Checklist (PENDING)

The following must be verified manually in a real browser:

| # | Test | URL | Expected | Status |
|---|------|-----|----------|--------|
| 1 | Landing page | `https://staging-backend.up.railway.app` | Login form visible | ⏳ PENDING |
| 2 | Google login | Click "Continue with Google" | OAuth flow initiates | ⏳ PENDING |
| 3 | Dashboard | After login | Dashboard loads with data | ⏳ PENDING |
| 4 | GEX view | Navigate to GEX | 60 synthetic snapshots visible | ⏳ PENDING |
| 5 | Paper trading | Navigate to paper trading | 20 paper accounts visible | ⏳ PENDING |
| 6 | Portfolio | Navigate to portfolio | Portfolio data loads | ⏳ PENDING |
| 7 | Settings | Navigate to settings | User settings accessible | ⏳ PENDING |
| 8 | Logout | Click logout | Session terminated | ⏳ PENDING |
| 9 | Re-login | Login again | Session restored | ⏳ PENDING |
| 10 | Console errors | Open DevTools | No JavaScript errors | ⏳ PENDING |
| 11 | Network failures | Check Network tab | No failed requests | ⏳ PENDING |
| 12 | WebSocket | Check WS connections | Connection established | ⏳ PENDING |

---

## Notes

- Browser automation is not available in this environment (Railway free plan).
- All API-level verification has been completed.
- The staging backend correctly requires authentication for all non-health endpoints.
- CORS is configured for `http://localhost:3000`.
- No console errors can be verified without a real browser session.
- **This checklist is NOT a substitute for actual browser testing.**
