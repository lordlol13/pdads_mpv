import secrets

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "AI News Feed MVP"
    APP_ENV: str = "dev"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/news_mvp"

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # AI / external APIs
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_REVIEW_ENABLED: bool = False
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    DEEPSEEK_API_KEY: str = ""
    NEWS_API_KEY: str = ""
    GOOGLE_CSE_API_KEY: str = ""
    GOOGLE_CSE_ID: str = ""

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    AUTH_VERIFICATION_CODE_TTL_MINUTES: int = 10
    AUTH_VERIFICATION_MAX_ATTEMPTS: int = 5
    AUTH_DEBUG_RETURN_CODE: bool = True

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@pdads.local"
    SMTP_USE_TLS: bool = True

    CORS_ALLOW_ORIGINS: str = (
        "http://127.0.0.1:3000,http://localhost:3000,"
        "http://127.0.0.1:3001,http://localhost:3001,"
        "http://127.0.0.1:5173,http://localhost:5173,"
        "http://127.0.0.1:8000,http://localhost:8000"
    )

    PIPELINE_MAX_ATTEMPTS: int = 1
    PIPELINE_TARGET_SCORE: float = 8.0
    PIPELINE_MIN_SCORE: float = 7.0
    PIPELINE_MAX_REWRITE_ROUNDS: int = 2
    SCHEDULER_INTERVAL_MINUTES: int = 15
    SCHEDULER_CLEANUP_INTERVAL_HOURS: int = 24
    NEWS_FETCH_BATCH_SIZE: int = 20
    NEWS_MAX_AGE_DAYS: int = 7
    NEWS_PRIORITY_MAX_AGE_HOURS: int = 24
    AI_PRODUCT_RETENTION_DAYS: int = 7
    PIPELINE_TEXT_MIN_WORDS: int = 170
    PIPELINE_TEXT_MAX_WORDS: int = 0
    PIPELINE_TEXT_MAX_CHARS: int = 0

    YOUTUBE_API_KEY: str = ""
    YOUTUBE_REGION_CODE: str = "UZ"
    VIDEO_TEMPLATE_URLS: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @staticmethod
    def _normalize_database_url(url: str) -> str:
        value = (url or "").strip()
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://"):]
        if value.startswith("postgresql+psycopg2://"):
            return "postgresql+asyncpg://" + value[len("postgresql+psycopg2://"):]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://"):]
        return value

    @property
    def cors_allow_origins(self) -> list[str]:
        values = [item.strip() for item in self.CORS_ALLOW_ORIGINS.split(",") if item.strip()]
        return values or ["http://127.0.0.1:8000"]

    @model_validator(mode="after")
    def _normalize_runtime_urls(self) -> "Settings":
        self.DATABASE_URL = self._normalize_database_url(self.DATABASE_URL)
        return self

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        env = (self.APP_ENV or "dev").strip().lower()
        weak_values = {"", "change_me_super_secret", "changeme", "secret"}

        if env in {"prod", "production", "stage", "staging"}:
            jwt_secret = (self.JWT_SECRET_KEY or "").strip()
            if jwt_secret in weak_values or len(jwt_secret) < 32:
                raise ValueError("JWT_SECRET_KEY must be set to a strong value in production/staging")

        if not (self.JWT_SECRET_KEY or "").strip():
            # Dev-only fallback to prevent shipping predictable secrets.
            self.JWT_SECRET_KEY = f"dev-{secrets.token_urlsafe(32)}"

        return self


settings = Settings()