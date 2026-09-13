"""Live staging smoke suite (backend/tests/staging_smoke/).

Verifies the deployed staging stack end-to-end:

    Vercel staging -> Render staging -> CockroachDB Cloud staging

Run ONLY with STAGING_SMOKE=1 (see docs/architecture/STAGING_SMOKE_TEST.md):

    STAGING_SMOKE=1 python -m pytest tests/staging_smoke -v

Safety rules enforced by this suite:
* synthetic runtime-generated credentials only (never stored, never printed)
* session IDs masked in all output
* CRDB DSN read from a local 0600 file, never printed
* no production system is ever contacted
"""
