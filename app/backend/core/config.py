from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "AI News Feed MVP"
    APP_ENV: str = "dev"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/news_mvp"

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # AI / external APIs
    GEMINI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    NEWS_API_KEY: str = ""   # <-- add this

    JWT_SECRET_KEY: str = "change_me_super_secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    PIPELINE_MAX_ATTEMPTS: int = 1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"   # <-- optional safety: ignore unknown env vars
    )


settings = Settings()