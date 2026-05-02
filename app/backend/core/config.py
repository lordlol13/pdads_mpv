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
    APP_ENV: str = "production"
    DEBUG: bool = False

    # Server port (Railway sets PORT env var)
    PORT: int = 8000

    # Railway provides DATABASE_URL - must be set in environment
    DATABASE_URL: str = ""

    # Railway provides REDIS_URL - must be set in environment
    REDIS_URL: str = ""
    # Celery uses same Redis as configured by Railway
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    # AI / external APIs
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_REVIEW_ENABLED: bool = False
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"  # FIX - Use proper embedding model, not chat model
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

    # Frontend OAuth redirect URLs - Railway production defaults
    OAUTH_FRONTEND_SUCCESS_URL: str = "https://pdads-mpv.vercel.app"
    OAUTH_FRONTEND_ERROR_URL: str = "https://pdads-mpv.vercel.app"

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

    # Production CORS - Railway/Vercel origins
    CORS_ALLOW_ORIGINS: str = (
        "https://pdads-mpv.vercel.app,"
        "https://pdadsmpv-production.up.railway.app"
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
    GLOBAL_LLM_CONCURRENCY: int = 3  # Distributed limit across all workers (Redis-based)

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
        # Production fallback - don't use localhost
        return values or ["https://pdadsmpv-production.up.railway.app"]

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
    def _set_celery_urls(self) -> "Settings":
        # If Celery URLs not set, use REDIS_URL (Railway provides this)
        redis_url = (self.REDIS_URL or "").strip()
        if redis_url:
            if not (self.CELERY_BROKER_URL or "").strip():
                self.CELERY_BROKER_URL = redis_url
            if not (self.CELERY_RESULT_BACKEND or "").strip():
                # Use database 1 for result backend (separate from broker)
                if redis_url.endswith("/0"):
                    self.CELERY_RESULT_BACKEND = redis_url[:-2] + "/1"
                else:
                    self.CELERY_RESULT_BACKEND = redis_url
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
    def _validate_required_env(self) -> "Settings":
        """Validate critical environment variables are set."""
        env = (self.APP_ENV or "dev").strip().lower()
        is_production = env in {"prod", "production", "stage", "staging"}

        # DATABASE_URL is always required
        if not (self.DATABASE_URL or "").strip():
            raise RuntimeError("DATABASE_URL is required - set it in Railway environment variables")

        # REDIS_URL is required for production (Celery/tasks)
        if is_production and not (self.REDIS_URL or "").strip():
            raise RuntimeError("REDIS_URL is required in production - set it in Railway environment variables")

        return self

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        env = (self.APP_ENV or "dev").strip().lower()
        weak_values = {"", "change_me_super_secret", "changeme", "secret"}
        is_production = env in {"prod", "production", "stage", "staging"}

        # JWT_SECRET_KEY validation - REQUIRED for all environments
        jwt_secret = (self.JWT_SECRET_KEY or "").strip()
        if not jwt_secret:
            raise RuntimeError("JWT_SECRET_KEY is required - set it in environment variables")
        if is_production and (jwt_secret in weak_values or len(jwt_secret) < 32):
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters and not a weak/default value in production/staging")

        # SESSION_SECRET_KEY validation - REQUIRED for all environments
        session_secret = (self.SESSION_SECRET_KEY or "").strip()
        if not session_secret:
            raise RuntimeError("SESSION_SECRET_KEY is required - set it in environment variables")
        if is_production and (session_secret in weak_values or len(session_secret) < 32):
            raise ValueError("SESSION_SECRET_KEY must be at least 32 characters and not a weak/default value in production/staging")

        return self


settings = Settings()

# Production startup logging
print(f"[STARTUP] APP_ENV: {settings.APP_ENV}")
print(f"[STARTUP] DEBUG: {settings.DEBUG}")
print(f"[STARTUP] DATABASE_URL: {settings.DATABASE_URL[:50]}..." if settings.DATABASE_URL else "[STARTUP] DATABASE_URL: NOT SET!")
print(f"[STARTUP] REDIS_URL: {settings.REDIS_URL[:30]}..." if settings.REDIS_URL else "[STARTUP] REDIS_URL: NOT SET!")
print(f"[STARTUP] CELERY_BROKER_URL: {settings.CELERY_BROKER_URL[:30]}..." if settings.CELERY_BROKER_URL else "[STARTUP] CELERY_BROKER_URL: NOT SET!")
print(f"[STARTUP] JWT configured: {bool(settings.JWT_SECRET_KEY)} (length: {len(settings.JWT_SECRET_KEY or '')})")
print(f"[STARTUP] SESSION_SECRET configured: {bool(settings.SESSION_SECRET_KEY)} (length: {len(settings.SESSION_SECRET_KEY or '')})")
