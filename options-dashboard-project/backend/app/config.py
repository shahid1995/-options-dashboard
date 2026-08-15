from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    UPSTOX_API_KEY: str
    UPSTOX_API_SECRET: str
    UPSTOX_REDIRECT_URI: str
    FRONTEND_URL: str = "http://localhost:3000"
    # Paper trading journal database. Defaults to a local SQLite file; point at
    # a PostgreSQL URL (e.g. a Railway Postgres DATABASE_URL) for durable,
    # shared production storage.
    DATABASE_URL: str | None = None

    class Config:
        env_file = ".env"


settings = Settings()
