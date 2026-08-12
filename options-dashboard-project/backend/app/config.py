from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    UPSTOX_API_KEY: str
    UPSTOX_API_SECRET: str
    UPSTOX_REDIRECT_URI: str
    FRONTEND_URL: str = "http://localhost:3000"

    class Config:
        env_file = ".env"


settings = Settings()
