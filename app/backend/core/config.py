import secrets
import re

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "AI News Feed MVP"
    APP_ENV: str = "dev"
    DEBUG: bool = True

    # Server port (Railway sets PORT env var)
    PORT: int = 8000

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/news_mvp"

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # AI / external APIs
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_REVIEW_ENABLED: bool = False
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "gpt-4o-mini"
    # Optional heavy model defaults and safety guard: do NOT enable heavy model in
    # production unless `LLM_ENABLE_HEAVY_MODEL=true` is explicitly set in env.
    OPENAI_MODEL_DEFAULT_HEAVY: str = "gpt-4o-mini"
    LLM_ENABLE_HEAVY_MODEL: bool = False
    INTERNAL_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    DEEPSEEK_API_KEY: str = ""
    NEWS_API_KEY: str = ""
    GOOGLE_CSE_API_KEY: str = ""
    GOOGLE_CSE_ID: str = ""

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    SESSION_SECRET_KEY: str = ""

    OAUTH_FRONTEND_SUCCESS_URL: str = "http://localhost:5173"
    OAUTH_FRONTEND_ERROR_URL: str = "http://localhost:5173"

    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    MICROSOFT_OAUTH_CLIENT_ID: str = ""
    MICROSOFT_OAUTH_CLIENT_SECRET: str = ""
    APPLE_OAUTH_CLIENT_ID: str = ""
    APPLE_OAUTH_CLIENT_SECRET: str = ""

    AUTH_VERIFICATION_CODE_TTL_MINUTES: int = 10
    AUTH_VERIFICATION_MAX_ATTEMPTS: int = 5
    AUTH_DEBUG_RETURN_CODE: bool = True

    SMTP_HOST: str = ""
    # Railway UI sometimes sets empty string for "cleared" variables; tolerate it.
    SMTP_PORT: int | str = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@pdads.local"
    SMTP_USE_TLS: bool | str = True
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "onboarding@resend.dev"

    PASSWORD_RESET_CODE_TTL_MINUTES: int = 15
    PASSWORD_RESET_MAX_ATTEMPTS: int = 5

    CORS_ALLOW_ORIGINS: str = (
        "http://127.0.0.1:3000,http://localhost:3000,"
        "http://127.0.0.1:3001,http://localhost:3001,"
        "http://127.0.0.1:3002,http://localhost:3002,"
        "http://127.0.0.1:5173,http://localhost:5173,"
        "http://127.0.0.1:8000,http://localhost:8000,"
        "https://pdads-mpv.vercel.app,https://pdadsmpv-production.up.railway.app"
    )
    CORS_ALLOW_ORIGIN_REGEX: str = ""
    TRUSTED_HOSTS: str = "*"

    PIPELINE_MAX_ATTEMPTS: int = 1
    PIPELINE_TARGET_SCORE: float = 8.0
    PIPELINE_MIN_SCORE: float = 6.0  # Lowered for testing
    PIPELINE_MAX_REWRITE_ROUNDS: int = 1  # DEBUG: 1 round for speed
    SCHEDULER_INTERVAL_MINUTES: int = 15
    SCHEDULER_CLEANUP_INTERVAL_HOURS: int = 24
    NEWS_FETCH_BATCH_SIZE: int = 20
    NEWS_MAX_AGE_DAYS: int = 7
    NEWS_PRIORITY_MAX_AGE_HOURS: int = 24
    AI_PRODUCT_RETENTION_DAYS: int = 4
    RAW_NEWS_RETENTION_DAYS: int = 4
    PIPELINE_TEXT_MIN_WORDS: int = 200
    PIPELINE_TEXT_MAX_WORDS: int = 250
    PIPELINE_TEXT_MAX_CHARS: int = 0

    # Force editorial language for generated articles (set to 'uz', 'ru', or 'en').
    # Empty string disables forcing and lets the system detect language from source.
    EDITORIAL_FORCE_LANGUAGE: str = "uz"

    EMBEDDING_DIMENSION: int = 256
    RECOMMENDER_USER_HISTORY_LIMIT: int = 20
    RECOMMENDER_SIMILARITY_WINDOW_MULTIPLIER: int = 4
    RECOMMENDER_SIMILARITY_WEIGHT: float = 1.0
    RECOMMENDER_ENGAGEMENT_WEIGHT: float = 0.45
    RECOMMENDER_FRESHNESS_WEIGHT: float = 0.2

    # API Resilience & Retry Strategy
    API_RETRY_MAX_ATTEMPTS: int = 1  # DEBUG: no retries for speed
    API_RETRY_BASE_DELAY_SECONDS: int = 1
    API_RETRY_MAX_DELAY_SECONDS: int = 10

    # Rate Limiting
    NEWS_API_RATE_LIMIT_PER_MINUTE: int = 20
    NEWS_API_RATE_LIMIT_PER_DAY: int = 500
    LLM_RATE_LIMIT_PER_MINUTE: int = 5
    LLM_RATE_LIMIT_PER_HOUR: int = 200

    # Caching TTL
    CACHE_LLM_RESULTS_TTL_HOURS: int = 24
    CACHE_NEWS_RESULTS_TTL_HOURS: int = 6
    CACHE_EMBEDDINGS_TTL_HOURS: int = 168  # 1 week

    # Fallback & Degradation
    LLM_FALLBACK_ENABLED: bool = True
    LLM_FALLBACK_MODEL: str = "deepseek"
    LLM_FALLBACK_RETURN_CACHED: bool = True
    NEWS_API_FALLBACK_TO_RSS: bool = True

    # Concurrency controls
    LLM_CONCURRENCY: int = 2

    # Celery tuning (can be overridden via env)
    CELERY_WORKER_CONCURRENCY: int = 2
    CELERY_PREFETCH_MULTIPLIER: int = 1
    CELERY_MAX_TASKS_PER_CHILD: int = 100
    CELERY_TASK_TIME_LIMIT: int = 300

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
        raw = (self.CORS_ALLOW_ORIGINS or "").strip()
        # Accept comma/semicolon/newline separated values from hosting dashboards.
        parts = re.split(r"[,;\r\n]+", raw)
        values: list[str] = []
        for part in parts:
            item = (part or "").strip()
            if not item:
                continue
            # Normalize common dashboard inputs: remove surrounding quotes.
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1].strip()
            # Normalize common dashboard inputs: remove trailing slashes.
            item = item.rstrip("/")
            values.append(item)
        return values or ["http://127.0.0.1:8000"]

    @property
    def trusted_hosts(self) -> list[str]:
        raw = (self.TRUSTED_HOSTS or "").strip()
        parts = re.split(r"[,;\r\n]+", raw)
        values = [item.strip() for item in parts if item and item.strip()]
        return values or ["*"]

    @model_validator(mode="after")
    def _normalize_runtime_urls(self) -> "Settings":
        self.DATABASE_URL = self._normalize_database_url(self.DATABASE_URL)
        return self

    @model_validator(mode="after")
    def _coerce_ports(self) -> "Settings":
        if isinstance(self.SMTP_PORT, str):
            raw = self.SMTP_PORT.strip()
            if not raw:
                self.SMTP_PORT = 587
            else:
                self.SMTP_PORT = int(raw)
        return self

    @model_validator(mode="after")
    def _coerce_bools(self) -> "Settings":
        # Some hosting dashboards set empty string for cleared vars.
        # Accept textual boolean input and coerce to actual bool here.
        if isinstance(self.SMTP_USE_TLS, str):
            raw = self.SMTP_USE_TLS.strip()
            if not raw:
                # default to True when unspecified
                self.SMTP_USE_TLS = True
            else:
                val = raw.lower()
                if val in {"false", "0", "no", "off"}:
                    self.SMTP_USE_TLS = False
                elif val in {"true", "1", "yes", "on"}:
                    self.SMTP_USE_TLS = True
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

        if not (self.SESSION_SECRET_KEY or "").strip():
            self.SESSION_SECRET_KEY = f"session-{secrets.token_urlsafe(32)}"

        return self


settings = Settings()
