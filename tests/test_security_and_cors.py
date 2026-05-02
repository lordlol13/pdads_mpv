import pytest

from app.backend.core.config import Settings


TEST_DB_URL = "postgresql+asyncpg://localhost:5432/news_mvp"


def test_settings_requires_jwt_secret_key() -> None:
    """JWT_SECRET_KEY is required - no auto-generation allowed."""
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY is required"):
        Settings(
            _env_file=None,
            APP_ENV="dev",
            DATABASE_URL=TEST_DB_URL,
            JWT_SECRET_KEY="",
            SESSION_SECRET_KEY="test-session-secret-key-123456789012345678901234",
        )


def test_settings_rejects_weak_secret_in_production() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            DATABASE_URL=TEST_DB_URL,
            JWT_SECRET_KEY="change_me_super_secret",
            SESSION_SECRET_KEY="x" * 32,
        )


def test_wildcard_origins_imply_credentials_disabled() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="dev",
        DATABASE_URL=TEST_DB_URL,
        JWT_SECRET_KEY="x" * 32,
        SESSION_SECRET_KEY="y" * 32,
        CORS_ALLOW_ORIGINS="*",
    )

    assert settings.cors_allow_origins == ["*"]
    allow_credentials = "*" not in settings.cors_allow_origins
    assert allow_credentials is False


def test_settings_requires_session_secret_key() -> None:
    """SESSION_SECRET_KEY is required - no auto-generation allowed."""
    with pytest.raises(RuntimeError, match="SESSION_SECRET_KEY is required"):
        Settings(
            _env_file=None,
            APP_ENV="dev",
            DATABASE_URL=TEST_DB_URL,
            JWT_SECRET_KEY="x" * 32,
            SESSION_SECRET_KEY="",
        )
