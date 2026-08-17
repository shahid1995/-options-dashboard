#!/usr/bin/env bash
# Local-only preview bootstrap (Phase 5.2 manual testing).
#
# Starts the FastAPI backend on :8000 against LOCAL SQLite (DATABASE_URL is
# forced to the local file so the preview can NEVER touch the production
# database), then the Next.js dev server on ${PORT:-3000} pointed at the
# sandbox backend proxy instead of the production Railway API baked into
# next.config.js. The backend binds 0.0.0.0 so the sandbox proxy can reach
# it, and FRONTEND_URL matches the preview origin so CORS allows the browser.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WS="a824e7d6-6c6c-449e-9cec-fd5b8e0f8ea7"
BACKEND_PUBLIC_URL="https://8000-$WS.daytonaproxy01.net"
FRONTEND_PUBLIC_URL="https://3000-$WS.daytonaproxy01.net"

# Backend: local SQLite only. Upstox settings are required by Settings() at
# import; prefer real values injected by the platform (Freebuff API Keys) and
# fall back to local-dev placeholders (same approach as the test suite) so
# the app boots. Real broker endpoints stay unusable without real keys.
(
  cd "$ROOT/backend"
  export DATABASE_URL="sqlite:///./paper_journal.db"
  export FRONTEND_URL="$FRONTEND_PUBLIC_URL"
  export UPSTOX_API_KEY="${UPSTOX_API_KEY:-local-dev-placeholder-key}"
  export UPSTOX_API_SECRET="${UPSTOX_API_SECRET:-local-dev-placeholder-secret}"
  export UPSTOX_REDIRECT_URI="${UPSTOX_REDIRECT_URI:-http://localhost:8000/auth/callback}"
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    >> /tmp/backend-uvicorn.log 2>&1 &
  echo "backend pid: $!"
)

sleep 2

# Frontend: override the production Railway fallback in next.config.js.
cd "$ROOT/frontend"
export NEXT_PUBLIC_API_URL="$BACKEND_PUBLIC_URL"
exec npm run dev -- -H 0.0.0.0 -p "${PORT:-3000}"
