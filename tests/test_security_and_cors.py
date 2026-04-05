import pytest

from app.backend.core.config import Settings


TEST_DB_URL = "postgresql+asyncpg://localhost:5432/news_mvp"


def test_settings_generates_dev_secret_when_missing() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="dev",
        DATABASE_URL=TEST_DB_URL,
        JWT_SECRET_KEY="",
    )

    assert settings.JWT_SECRET_KEY.startswith("dev-")
    assert len(settings.JWT_SECRET_KEY) > 20


def test_settings_rejects_weak_secret_in_production() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            DATABASE_URL=TEST_DB_URL,
            JWT_SECRET_KEY="change_me_super_secret",
        )


def test_wildcard_origins_imply_credentials_disabled() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="dev",
        DATABASE_URL=TEST_DB_URL,
        JWT_SECRET_KEY="x" * 32,
        CORS_ALLOW_ORIGINS="*",
    )

    assert settings.cors_allow_origins == ["*"]
    allow_credentials = "*" not in settings.cors_allow_origins
    assert allow_credentials is False
