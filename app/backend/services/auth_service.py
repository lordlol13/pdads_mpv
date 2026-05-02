from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.config import settings
from app.backend.core.logging import ContextLogger
from app.backend.core.security import create_access_token, hash_password, verify_password
from app.backend.services.email_service import send_password_reset_code_async, send_verification_code_async
from app.backend.services.recommender_service import refresh_user_embedding


logger = ContextLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_naive() -> datetime:
    """Return UTC datetime without tzinfo for DB columns declared as TIMESTAMP."""
    return _utcnow().replace(tzinfo=None)


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item:
            continue

        dedupe_key = item.lower()
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        normalized.append(item)

    return normalized


def _to_utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        normalized = raw.replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    return None


def _parse_user_dict(row: Any) -> dict[str, Any]:
    """Normalize user row: interests as dict (JSONB, JSON text, or malformed)."""
    user_dict = dict(row) if hasattr(row, "keys") else row
    raw = user_dict.get("interests")
    if isinstance(raw, dict):
        user_dict["interests"] = dict(raw)
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else {}
            user_dict["interests"] = parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            user_dict["interests"] = {}
    else:
        user_dict["interests"] = {}
    return user_dict


def _hash_verification_code(verification_id: str, code: str) -> str:
    payload = f"{verification_id}:{code}:{settings.JWT_SECRET_KEY}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _ensure_password_reset_table(session: AsyncSession) -> None:
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS password_reset_requests (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        email TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        used_at TIMESTAMP NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
    create_email_index_sql = (
        "CREATE INDEX IF NOT EXISTS idx_password_reset_requests_email "
        "ON password_reset_requests (email)"
    )
    await session.execute(text(create_table_sql))
    await session.execute(text(create_email_index_sql))
    await session.commit()


async def _seed_user_feed_for_new_user(session: AsyncSession, *, user_id: int, topics: list[str]) -> int:
    normalized_topics = [value.lower() for value in _normalize_string_list(topics)]

    def _persona_matches(persona: str, topic: str) -> bool:
        if topic == "general":
            return persona == "general" or persona.startswith("general|")
        return persona == topic or persona.startswith(f"{topic}|")

    candidates_result = await session.execute(
        text(
            """
            SELECT id, ai_score, target_persona, raw_news_id
            FROM ai_news
            ORDER BY created_at DESC, id DESC
            LIMIT 300
            """
        )
    )
    candidates = [dict(row) for row in candidates_result.mappings().all()]

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    selected_raw_news_ids: set[int] = set()

    for row in candidates:
        ai_news_id = int(row.get("id") or 0)
        if not ai_news_id or ai_news_id in selected_ids:
            continue

        raw_news_id = int(row.get("raw_news_id") or 0)
        if raw_news_id and raw_news_id in selected_raw_news_ids:
            continue

        persona = str(row.get("target_persona") or "").strip().lower()
        if not persona:
            continue

        matched = False
        for topic in normalized_topics:
            if _persona_matches(persona, topic):
                matched = True
                break

        if not matched:
            continue

        selected_ids.add(ai_news_id)
        if raw_news_id:
            selected_raw_news_ids.add(raw_news_id)
        selected.append(
            {
                "ai_news_id": ai_news_id,
                "ai_score": float(row.get("ai_score") or 0.0),
            }
        )
        if len(selected) >= 40:
            break

    if not selected:
        selected_ids.clear()
        selected_raw_news_ids.clear()
        for row in candidates:
            ai_news_id = int(row.get("id") or 0)
            if not ai_news_id or ai_news_id in selected_ids:
                continue

            raw_news_id = int(row.get("raw_news_id") or 0)
            if raw_news_id and raw_news_id in selected_raw_news_ids:
                continue

            persona = str(row.get("target_persona") or "").strip().lower()
            if not persona or not _persona_matches(persona, "general"):
                continue

            selected_ids.add(ai_news_id)
            if raw_news_id:
                selected_raw_news_ids.add(raw_news_id)
            selected.append(
                {
                    "ai_news_id": ai_news_id,
                    "ai_score": float(row.get("ai_score") or 0.0),
                }
            )
            if len(selected) >= 12:
                break

    if not selected:
        selected_ids.clear()
        selected_raw_news_ids.clear()
        # Final cold-start fallback: give latest unique stories regardless of persona,
        # so a brand-new account never lands on an empty feed.
        for row in candidates:
            ai_news_id = int(row.get("id") or 0)
            if not ai_news_id or ai_news_id in selected_ids:
                continue

            raw_news_id = int(row.get("raw_news_id") or 0)
            if raw_news_id and raw_news_id in selected_raw_news_ids:
                continue

            selected_ids.add(ai_news_id)
            if raw_news_id:
                selected_raw_news_ids.add(raw_news_id)
            selected.append(
                {
                    "ai_news_id": ai_news_id,
                    "ai_score": float(row.get("ai_score") or 0.0),
                }
            )
            if len(selected) >= 16:
                break

    if not selected:
        return 0

    now_sql = "CURRENT_TIMESTAMP" if session.get_bind().dialect.name == "sqlite" else "NOW()"
    inserted = 0
    for item in selected:
        result = await session.execute(
            text(
                f"""
                INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
                SELECT :user_id, :ai_news_id, :ai_score, {now_sql}
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM user_feed uf
                    WHERE uf.user_id = :user_id
                      AND uf.ai_news_id = :ai_news_id
                )
                """
            ),
            {
                "user_id": user_id,
                "ai_news_id": item["ai_news_id"],
                "ai_score": item["ai_score"],
            },
        )
        inserted += int(getattr(result, "rowcount", 0) or 0)

    return inserted


async def _ensure_registration_table(session: AsyncSession) -> None:
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS registration_verifications (
        id TEXT PRIMARY KEY,
        username VARCHAR(100) NOT NULL,
        email TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        verification_code_hash TEXT NOT NULL,
        code_expires_at TIMESTAMP NOT NULL,
        is_verified BOOLEAN NOT NULL DEFAULT FALSE,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        consumed_at TIMESTAMP NULL
    )
    """
    create_email_index_sql = (
        "CREATE INDEX IF NOT EXISTS idx_registration_verifications_email "
        "ON registration_verifications (email)"
    )

    await session.execute(text(create_table_sql))
    await session.execute(text(create_email_index_sql))
    await session.commit()


async def check_username_exists(session: AsyncSession, username: str) -> bool:
    query = """
    SELECT 1
    FROM users
    WHERE LOWER(username) = LOWER(:username)
    LIMIT 1
    """
    result = await session.execute(text(query), {"username": username.strip()})
    return result.scalar_one_or_none() is not None


async def check_email_exists(session: AsyncSession, email: str) -> bool:
    query = """
    SELECT 1
    FROM users
    WHERE LOWER(email) = LOWER(:email)
    LIMIT 1
    """
    result = await session.execute(text(query), {"email": email.strip()})
    return result.scalar_one_or_none() is not None


async def _ensure_oauth_identities_table(session: AsyncSession) -> None:
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS oauth_identities (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        provider VARCHAR(32) NOT NULL,
        subject VARCHAR(255) NOT NULL,
        email TEXT NULL,
        display_name VARCHAR(255) NULL,
        avatar_url TEXT NULL,
        profile_json TEXT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_login_at TIMESTAMP NULL,
        CONSTRAINT uq_oauth_identities_provider_subject UNIQUE (provider, subject)
    )
    """
    create_user_index_sql = (
        "CREATE INDEX IF NOT EXISTS idx_oauth_identities_user_id "
        "ON oauth_identities (user_id)"
    )
    await session.execute(text(create_table_sql))
    await session.execute(text(create_user_index_sql))
    await session.commit()


def _normalize_oauth_email(provider: str, subject: str, email: str | None) -> str:
    value = (email or "").strip().lower()
    if value:
        return value
    digest = hashlib.sha256(f"{provider}:{subject}".encode("utf-8")).hexdigest()[:24]
    return f"{provider}-{digest}@oauth.local"


def _username_seed(display_name: str | None, email: str) -> str:
    if display_name and display_name.strip():
        raw = display_name.strip().lower()
    else:
        raw = email.split("@", 1)[0].strip().lower()

    cleaned = re.sub(r"[^a-z0-9_]+", "_", raw)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if len(cleaned) < 3:
        cleaned = f"user_{cleaned}" if cleaned else "user"
    return cleaned[:80]


async def _build_unique_username(session: AsyncSession, seed: str) -> str:
    base = seed[:80]
    if len(base) < 3:
        base = f"{base}_usr"[:80]

    if not await check_username_exists(session, base):
        return base

    for attempt in range(1, 5000):
        suffix = f"_{attempt}"
        candidate = f"{base[: max(3, 80 - len(suffix))]}{suffix}"
        if not await check_username_exists(session, candidate):
            return candidate

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate username")


async def _get_user_by_email(session: AsyncSession, email: str) -> dict[str, Any] | None:
    query = """
    SELECT
        id, username, email, location, interests, is_active, is_verified,
        country_code, region_code, created_at, updated_at
    FROM users
    WHERE LOWER(email) = LOWER(:email)
    ORDER BY id
    LIMIT 1
    """
    result = await session.execute(text(query), {"email": email.strip().lower()})
    row = result.mappings().first()
    return _parse_user_dict(row) if row else None


async def upsert_oauth_user(
    session: AsyncSession,
    *,
    provider: str,
    subject: str,
    email: str | None,
    display_name: str | None,
    avatar_url: str | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    await _ensure_oauth_identities_table(session)

    provider_clean = provider.strip().lower()
    subject_clean = subject.strip()
    if not provider_clean or not subject_clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth identity")

    email_clean = _normalize_oauth_email(provider_clean, subject_clean, email)
    display_name_clean = (display_name or "").strip() or None
    avatar_url_clean = (avatar_url or "").strip() or None
    profile_json = json.dumps(profile or {}, ensure_ascii=False)

    existing_identity_result = await session.execute(
        text(
            """
            SELECT
                u.id,
                u.username,
                u.email,
                u.location,
                u.interests,
                u.is_active,
                u.is_verified,
                u.country_code,
                u.region_code,
                u.created_at,
                u.updated_at
            FROM oauth_identities oi
            JOIN users u ON u.id = oi.user_id
            WHERE oi.provider = :provider
              AND oi.subject = :subject
            LIMIT 1
            """
        ),
        {"provider": provider_clean, "subject": subject_clean},
    )
    existing_user_row = existing_identity_result.mappings().first()

    if existing_user_row:
        await session.execute(
            text(
                """
                UPDATE oauth_identities
                SET email = :email,
                    display_name = :display_name,
                    avatar_url = :avatar_url,
                    profile_json = :profile_json,
                    updated_at = :updated_at,
                    last_login_at = :last_login_at
                WHERE provider = :provider
                  AND subject = :subject
                """
            ),
            {
                "email": email_clean,
                "display_name": display_name_clean,
                "avatar_url": avatar_url_clean,
                "profile_json": profile_json,
                "updated_at": _utcnow_naive(),
                "last_login_at": _utcnow_naive(),
                "provider": provider_clean,
                "subject": subject_clean,
            },
        )
        await session.commit()
        return _parse_user_dict(existing_user_row)

    user = await _get_user_by_email(session, email_clean)

    if user is None:
        username = await _build_unique_username(session, _username_seed(display_name_clean, email_clean))
        created = await session.execute(
            text(
                """
                INSERT INTO users (
                    username,
                    location,
                    interests,
                    created_at,
                    email,
                    password_hash,
                    is_active,
                    is_verified,
                    country_code,
                    region_code,
                    updated_at
                )
                VALUES (
                    :username,
                    NULL,
                    :interests,
                    CURRENT_TIMESTAMP,
                    :email,
                    :password_hash,
                    TRUE,
                    TRUE,
                    NULL,
                    NULL,
                    CURRENT_TIMESTAMP
                )
                RETURNING
                    id, username, email, location, interests, is_active, is_verified,
                    country_code, region_code, created_at, updated_at
                """
            ),
            {
                "username": username,
                "interests": "{}",
                "email": email_clean,
                "password_hash": hash_password(secrets.token_urlsafe(48)),
            },
        )
        row = created.mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create OAuth user")

        await session.commit()
        user = _parse_user_dict(row)

        try:
            from app.backend.core.celery_app import send_task_safe

            send_task_safe("recommender.refresh_user_embedding", args=(int(user["id"]),))
        except Exception:
            logger.exception("failed to enqueue background embedding for oauth user id=%s", user.get("id"))

    updated = await session.execute(
        text(
            """
            UPDATE oauth_identities
            SET user_id = :user_id,
                email = :email,
                display_name = :display_name,
                avatar_url = :avatar_url,
                profile_json = :profile_json,
                updated_at = :updated_at,
                last_login_at = :last_login_at
            WHERE provider = :provider
              AND subject = :subject
            """
        ),
        {
            "user_id": int(user["id"]),
            "email": email_clean,
            "display_name": display_name_clean,
            "avatar_url": avatar_url_clean,
            "profile_json": profile_json,
            "updated_at": _utcnow_naive(),
            "last_login_at": _utcnow_naive(),
            "provider": provider_clean,
            "subject": subject_clean,
        },
    )

    if int(getattr(updated, "rowcount", 0) or 0) == 0:
        await session.execute(
            text(
                """
                INSERT INTO oauth_identities (
                    user_id,
                    provider,
                    subject,
                    email,
                    display_name,
                    avatar_url,
                    profile_json,
                    created_at,
                    updated_at,
                    last_login_at
                )
                VALUES (
                    :user_id,
                    :provider,
                    :subject,
                    :email,
                    :display_name,
                    :avatar_url,
                    :profile_json,
                    :created_at,
                    :updated_at,
                    :last_login_at
                )
                """
            ),
            {
                "user_id": int(user["id"]),
                "provider": provider_clean,
                "subject": subject_clean,
                "email": email_clean,
                "display_name": display_name_clean,
                "avatar_url": avatar_url_clean,
                "profile_json": profile_json,
                "created_at": _utcnow_naive(),
                "updated_at": _utcnow_naive(),
                "last_login_at": _utcnow_naive(),
            },
        )

    await session.commit()
    return user


async def get_user_by_identifier(session: AsyncSession, identifier: str) -> dict[str, Any] | None:
    query = """
    SELECT
        id, username, email, location, interests, is_active, is_verified,
        country_code, region_code, created_at, updated_at, password_hash
    FROM users
    WHERE LOWER(username) = LOWER(:identifier) OR LOWER(email) = LOWER(:identifier)
    ORDER BY id
    LIMIT 1
    """
    result = await session.execute(text(query), {"identifier": identifier.strip()})
    row = result.mappings().first()
    return _parse_user_dict(row) if row else None


async def get_user_by_id(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    query = """
    SELECT
        id, username, email, location, interests, is_active, is_verified,
        country_code, region_code, created_at, updated_at
    FROM users
    WHERE id = :user_id
    LIMIT 1
    """
    result = await session.execute(text(query), {"user_id": user_id})
    row = result.mappings().first()
    return _parse_user_dict(row) if row else None


async def create_registration_verification(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
) -> dict[str, Any]:
    await _ensure_registration_table(session)

    username_clean = username.strip()
    email_clean = email.strip().lower()

    if await check_username_exists(session, username_clean):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    if await check_email_exists(session, email_clean):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    cleanup_query = """
    DELETE FROM registration_verifications
    WHERE LOWER(email) = LOWER(:email) OR LOWER(username) = LOWER(:username)
    """
    await session.execute(text(cleanup_query), {"email": email_clean, "username": username_clean})

    verification_id = str(uuid.uuid4())
    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = _hash_verification_code(verification_id, code)
    expires_at = _utcnow_naive() + timedelta(minutes=settings.AUTH_VERIFICATION_CODE_TTL_MINUTES)
    created_now = _utcnow_naive()

    insert_query = """
    INSERT INTO registration_verifications (
        id,
        username,
        email,
        password_hash,
        verification_code_hash,
        code_expires_at,
        is_verified,
        attempt_count,
        created_at,
        updated_at,
        consumed_at
    )
    VALUES (
        :id,
        :username,
        :email,
        :password_hash,
        :verification_code_hash,
        :code_expires_at,
        :is_verified,
        :attempt_count,
        :created_at,
        :updated_at,
        :consumed_at
    )
    """
    await session.execute(
        text(insert_query),
        {
            "id": verification_id,
            "username": username_clean,
            "email": email_clean,
            "password_hash": hash_password(password),
            "verification_code_hash": code_hash,
            "code_expires_at": expires_at,
            "is_verified": False,
            "attempt_count": 0,
            "created_at": created_now,
            "updated_at": created_now,
            "consumed_at": None,
        },
    )
    await session.commit()

    return {
        "verification_id": verification_id,
        "code": code,
        "expires_in_seconds": settings.AUTH_VERIFICATION_CODE_TTL_MINUTES * 60,
    }


async def verify_registration_code(session: AsyncSession, verification_id: str, code: str) -> dict[str, Any]:
    await _ensure_registration_table(session)

    query = """
    SELECT
        id,
        verification_code_hash,
        code_expires_at,
        is_verified,
        attempt_count,
        consumed_at
    FROM registration_verifications
    WHERE id = :verification_id
    LIMIT 1
    """
    result = await session.execute(text(query), {"verification_id": verification_id.strip()})
    row = result.mappings().first()

    if row is None or row.get("consumed_at") is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification session not found")

    if row.get("is_verified"):
        return {"verification_id": verification_id, "verified": True}

    expires_at = _to_utc_datetime(row.get("code_expires_at"))
    if expires_at is None or expires_at < _utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification code expired")

    expected_hash = str(row.get("verification_code_hash") or "")
    provided_hash = _hash_verification_code(verification_id, code.strip())

    if provided_hash != expected_hash:
        attempts = int(row.get("attempt_count") or 0) + 1
        await session.execute(
            text(
                """
                UPDATE registration_verifications
                SET attempt_count = :attempt_count,
                    updated_at = :updated_at
                WHERE id = :verification_id
                """
            ),
            {
                "attempt_count": attempts,
                "updated_at": _utcnow_naive(),
                "verification_id": verification_id,
            },
        )
        await session.commit()

        if attempts >= settings.AUTH_VERIFICATION_MAX_ATTEMPTS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many invalid code attempts")

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")

    await session.execute(
        text(
            """
            UPDATE registration_verifications
            SET is_verified = :is_verified,
                updated_at = :updated_at
            WHERE id = :verification_id
            """
        ),
        {
            "is_verified": True,
            "updated_at": _utcnow_naive(),
            "verification_id": verification_id,
        },
    )
    await session.commit()
    return {"verification_id": verification_id, "verified": True}


async def resend_registration_code(session: AsyncSession, verification_id: str) -> dict[str, Any]:
    await _ensure_registration_table(session)

    result = await session.execute(
        text(
            """
            SELECT id, email, consumed_at
            FROM registration_verifications
            WHERE id = :verification_id
            LIMIT 1
            """
        ),
        {"verification_id": verification_id.strip()},
    )
    row = result.mappings().first()

    if row is None or row.get("consumed_at") is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification session not found")

    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = _hash_verification_code(verification_id, code)
    expires_at = _utcnow_naive() + timedelta(minutes=settings.AUTH_VERIFICATION_CODE_TTL_MINUTES)

    await session.execute(
        text(
            """
            UPDATE registration_verifications
            SET verification_code_hash = :verification_code_hash,
                code_expires_at = :code_expires_at,
                is_verified = FALSE,
                attempt_count = 0,
                updated_at = :updated_at
            WHERE id = :verification_id
            """
        ),
        {
            "verification_code_hash": code_hash,
            "code_expires_at": expires_at,
            "updated_at": _utcnow_naive(),
            "verification_id": verification_id,
        },
    )
    await session.commit()

    email = str(row.get("email") or "").strip().lower()
    sent, provider_error = await send_verification_code_async(email, code)
    provider_error_str = None
    if provider_error:
        provider_error_str = (
            provider_error.get("message")
            or provider_error.get("error")
            or str(provider_error)
        )

    return {
        "verification_id": verification_id,
        "expires_in_seconds": settings.AUTH_VERIFICATION_CODE_TTL_MINUTES * 60,
        "sent": sent,
        "debug_code": code if settings.AUTH_DEBUG_RETURN_CODE else None,
        "provider_error": provider_error_str,
    }


async def complete_verified_registration(
    session: AsyncSession,
    *,
    verification_id: str,
    interests: list[str],
    custom_interests: list[str] | None,
    profession: str | None,
    country_code: str | None,
    country_name: str | None,
    city: str | None,
    region_code: str | None,
) -> dict[str, Any]:
    await _ensure_registration_table(session)

    load_query = """
    SELECT
        id,
        username,
        email,
        password_hash,
        code_expires_at,
        is_verified,
        consumed_at
    FROM registration_verifications
    WHERE id = :verification_id
    LIMIT 1
    """
    result = await session.execute(text(load_query), {"verification_id": verification_id.strip()})
    row = result.mappings().first()

    if row is None or row.get("consumed_at") is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification session not found")

    if not row.get("is_verified"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is not verified")

    expires_at = _to_utc_datetime(row.get("code_expires_at"))
    if expires_at is None or expires_at < _utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification session expired")

    username = str(row["username"]).strip()
    email = str(row["email"]).strip().lower()
    password_hash = str(row["password_hash"])

    if await check_username_exists(session, username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    if await check_email_exists(session, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    topics_clean = _normalize_string_list(interests)
    custom_clean = _normalize_string_list(custom_interests)
    all_topics = _normalize_string_list([*topics_clean, *custom_clean])
    if not all_topics:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one interest is required")

    city_clean = (city or "").strip() or None
    country_code_clean = (country_code or "").strip().upper() or None
    country_name_clean = (country_name or "").strip() or None
    region_code_clean = (region_code or "").strip() or None

    interests_payload: dict[str, Any] = {
        "topics": topics_clean,
        "custom_topics": custom_clean,
        "all_topics": all_topics,
    }
    profession_clean = (profession or "").strip()
    if profession_clean:
        interests_payload["profession"] = profession_clean
    if country_code_clean:
        interests_payload["country_code"] = country_code_clean
    if country_name_clean:
        interests_payload["country_name"] = country_name_clean
    if city_clean:
        interests_payload["city"] = city_clean

    insert_user_query = """
    INSERT INTO users (
        username, location, interests, created_at, email, password_hash,
        is_active, is_verified, country_code, region_code, updated_at
    )
    VALUES (
        :username, :location, :interests, CURRENT_TIMESTAMP, :email, :password_hash,
        TRUE, TRUE, :country_code, :region_code, CURRENT_TIMESTAMP
    )
    RETURNING
        id, username, email, location, interests, is_active, is_verified,
        country_code, region_code, created_at, updated_at
    """
    created = await session.execute(
        text(insert_user_query),
        {
            "username": username,
            "location": city_clean,
            "interests": json.dumps(interests_payload, ensure_ascii=False),
            "email": email,
            "password_hash": password_hash,
            "country_code": country_code_clean,
            "region_code": region_code_clean,
        },
    )

    await session.execute(
        text(
            """
            UPDATE registration_verifications
            SET consumed_at = :consumed_at,
                updated_at = :updated_at
            WHERE id = :verification_id
            """
        ),
        {
            "consumed_at": _utcnow_naive(),
            "updated_at": _utcnow_naive(),
            "verification_id": verification_id,
        },
    )

    new_user_row = created.mappings().first()
    if new_user_row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user")

    # Persist the new user and the registration consumption before performing
    # potentially-failing background tasks (seeding + embeddings). Doing so
    # ensures that failures in recommender/embedding logic do not cause the
    # whole transaction to be rolled back and lose the created user.
    await session.commit()

    try:
        await _seed_user_feed_for_new_user(
            session,
            user_id=int(new_user_row["id"]),
            topics=all_topics,
        )
    except Exception:
        logger.exception("failed to seed user_feed for new user id=%s", new_user_row.get("id"))

    try:
        from app.backend.core.celery_app import send_task_safe

        send_task_safe("recommender.refresh_user_embedding", args=(int(new_user_row["id"]),))
    except Exception:
        logger.exception("failed to enqueue background embedding for new user id=%s", new_user_row.get("id"))

    # No further commit required here; seeding/refresh may commit on their own.

    return _parse_user_dict(new_user_row)


async def register_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
    location: str | None = None,
    interests: dict[str, Any] | None = None,
    country_code: str | None = None,
    region_code: str | None = None,
) -> dict[str, Any]:
    existing = await get_user_by_identifier(session, username)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    existing_email = await get_user_by_identifier(session, email)
    if existing_email is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    password_hash = hash_password(password)
    interests_json = json.dumps(interests or {}, ensure_ascii=False)

    query = """
    INSERT INTO users (
        username, location, interests, created_at, email, password_hash,
        is_active, is_verified, country_code, region_code, updated_at
    )
    VALUES (
        :username, :location, :interests, CURRENT_TIMESTAMP, :email, :password_hash,
        TRUE, FALSE, :country_code, :region_code, CURRENT_TIMESTAMP
    )
    RETURNING
        id, username, email, location, interests, is_active, is_verified,
        country_code, region_code, created_at, updated_at
    """
    result = await session.execute(
        text(query),
        {
            "username": username,
            "location": location,
            "interests": interests_json,
            "email": email,
            "password_hash": password_hash,
            "country_code": country_code,
            "region_code": region_code,
        },
    )
    await session.commit()
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user")

    try:
        from app.backend.core.celery_app import send_task_safe

        send_task_safe("recommender.refresh_user_embedding", args=(int(row["id"]),))
    except Exception:
        logger.exception("failed to enqueue background embedding for registered user id=%s", row.get("id"))

    return _parse_user_dict(row)


async def authenticate_user(session: AsyncSession, identifier: str, password: str) -> dict[str, Any]:
    user = await get_user_by_identifier(session, identifier)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.get("password_hash") or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.get("is_active") is False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    return user


async def create_password_reset_request(session: AsyncSession, *, email: str) -> bool:
    await _ensure_password_reset_table(session)

    email_clean = email.strip().lower()
    user_query = """
    SELECT id, email
    FROM users
    WHERE LOWER(email) = LOWER(:email)
    LIMIT 1
    """
    result = await session.execute(text(user_query), {"email": email_clean})
    row = result.mappings().first()

    if row is None:
        return True

    user_id = int(row["id"])
    reset_id = str(uuid.uuid4())
    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = _hash_verification_code(reset_id, code)
    now_naive = _utcnow_naive()
    expires_at = now_naive + timedelta(minutes=settings.PASSWORD_RESET_CODE_TTL_MINUTES)

    await session.execute(
        text(
            """
            UPDATE password_reset_requests
            SET used_at = :used_at,
                updated_at = :updated_at
            WHERE user_id = :user_id
              AND used_at IS NULL
            """
        ),
        {
            "used_at": now_naive,
            "updated_at": now_naive,
            "user_id": user_id,
        },
    )

    await session.execute(
        text(
            """
            INSERT INTO password_reset_requests (
                id, user_id, email, code_hash, expires_at,
                attempt_count, used_at, created_at, updated_at
            )
            VALUES (
                :id, :user_id, :email, :code_hash, :expires_at,
                0, NULL, :created_at, :updated_at
            )
            """
        ),
        {
            "id": reset_id,
            "user_id": user_id,
            "email": email_clean,
            "code_hash": code_hash,
            "expires_at": expires_at,
            "created_at": now_naive,
            "updated_at": now_naive,
        },
    )
    await session.commit()

    sent, provider_error = await send_password_reset_code_async(email_clean, code)
    if not sent:
        logger.warning("Password reset email send failed for %s: %s", email_clean, provider_error)
    return True


async def reset_password_with_code(
    session: AsyncSession,
    *,
    email: str,
    code: str,
    new_password: str,
) -> bool:
    await _ensure_password_reset_table(session)

    email_clean = email.strip().lower()
    query = """
    SELECT id, user_id, code_hash, expires_at, attempt_count, used_at
    FROM password_reset_requests
    WHERE LOWER(email) = LOWER(:email)
      AND used_at IS NULL
    ORDER BY created_at DESC
    LIMIT 1
    """
    result = await session.execute(text(query), {"email": email_clean})
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset code is invalid or expired")

    reset_id = str(row["id"])
    expires_at = _to_utc_datetime(row.get("expires_at"))
    if expires_at is None or expires_at < _utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset code is invalid or expired")

    expected_hash = str(row.get("code_hash") or "")
    provided_hash = _hash_verification_code(reset_id, code.strip())
    if provided_hash != expected_hash:
        attempts = int(row.get("attempt_count") or 0) + 1
        await session.execute(
            text(
                """
                UPDATE password_reset_requests
                SET attempt_count = :attempt_count,
                    updated_at = :updated_at
                WHERE id = :id
                """
            ),
            {
                "attempt_count": attempts,
                "updated_at": _utcnow_naive(),
                "id": reset_id,
            },
        )
        await session.commit()

        if attempts >= settings.PASSWORD_RESET_MAX_ATTEMPTS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many invalid code attempts")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset code is invalid or expired")

    user_id = int(row["user_id"])
    await session.execute(
        text(
            """
            UPDATE users
            SET password_hash = :password_hash,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :user_id
            """
        ),
        {
            "password_hash": hash_password(new_password),
            "user_id": user_id,
        },
    )

    now_naive = _utcnow_naive()
    await session.execute(
        text(
            """
            UPDATE password_reset_requests
            SET used_at = :used_at,
                updated_at = :updated_at
            WHERE id = :id
            """
        ),
        {
            "used_at": now_naive,
            "updated_at": now_naive,
            "id": reset_id,
        },
    )
    await session.commit()
    return True


def issue_access_token(user: dict[str, Any]) -> str:
    return create_access_token(
        {"sub": str(user["id"]), "username": user.get("username")},
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    )
