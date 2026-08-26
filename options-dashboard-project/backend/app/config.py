from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    UPSTOX_API_KEY: str
    UPSTOX_API_SECRET: str
    UPSTOX_REDIRECT_URI: str
    FRONTEND_URL: str = "http://localhost:3000"
    # Phase 9C: CORS — set ALLOW_LOCALHOST_CORS=True only in development
    ALLOW_LOCALHOST_CORS: bool = False
    DEBUG: bool = False
    # Paper trading journal database. Defaults to a local SQLite file; point at
    # a PostgreSQL URL (e.g. a Railway Postgres DATABASE_URL) for durable,
    # shared production storage.
    DATABASE_URL: str | None = None
    # Historical IV foundation (Phase 4.1): the persistence model and
    # repository exist, but collection is DISABLED by default. A future phase
    # that turns it on must honour these bounds to avoid uncontrolled
    # database growth (sampling interval, retention, per-key caps).
    IV_HISTORY_ENABLED: bool = False
    IV_HISTORY_SAMPLE_SECONDS: int = 300
    IV_HISTORY_RETENTION_DAYS: int = 90
    # Historical GEX snapshots (Phase 7.3): persistence model and repository.
    # Collection is DISABLED by default.  A future phase that enables it must
    # honour these bounds to avoid uncontrolled database growth.
    GEX_HISTORY_ENABLED: bool = False
    GEX_HISTORY_SAMPLE_SECONDS: int = 60   # 1-minute live GEX snapshot interval
    GEX_HISTORY_RETENTION_DAYS: int = 90   # matches IV history retention
    # Historical NIFTY candles (Phase 7.7 research)
    CANDLE_RETENTION_DAYS: int = 365
    CANDLE_INTERVAL: str = "3min"
    CANDLE_BACKFILL_ENABLED: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
