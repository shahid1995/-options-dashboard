# Options Dashboard (NIFTY, Upstox-powered)

Two folders:
- `backend/` — a Python API that logs into Upstox and serves option chain data.
- `frontend/` — the website you actually see, built with Next.js.

You don't need to run anything on your own computer. Follow the deployment
steps Claude gives you: upload this whole folder to GitHub, then connect
`backend/` to Railway and `frontend/` to Vercel, and set the environment
variables listed in `backend/.env.example` on Railway.

Full guide: ask Claude to walk you through "GitHub upload" and "Railway +
Vercel deployment" — this repo is built to drop straight into that flow.
