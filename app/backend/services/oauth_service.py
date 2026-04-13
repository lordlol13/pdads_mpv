from __future__ import annotations

import hashlib
import secrets
from typing import Any
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.backend.core.config import settings
from app.backend.services.auth_service import issue_access_token, upsert_oauth_user


oauth = OAuth()
_registered = False


def get_enabled_oauth_providers() -> list[str]:
    enabled: list[str] = []
    if settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET:
        enabled.append("google")
    if settings.MICROSOFT_OAUTH_CLIENT_ID and settings.MICROSOFT_OAUTH_CLIENT_SECRET:
        enabled.append("microsoft")
    return enabled


def _register_oauth_clients() -> None:
    global _registered
    if _registered:
        return

    if settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET:
        oauth.register(
            name="google",
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    if settings.MICROSOFT_OAUTH_CLIENT_ID and settings.MICROSOFT_OAUTH_CLIENT_SECRET:
        oauth.register(
            name="microsoft",
            client_id=settings.MICROSOFT_OAUTH_CLIENT_ID,
            client_secret=settings.MICROSOFT_OAUTH_CLIENT_SECRET,
            server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email User.Read"},
        )


    _registered = True


def _get_client(provider: str):
    _register_oauth_clients()
    client = oauth.create_client(provider)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OAuth provider '{provider}' is not configured",
        )
    return client


def build_oauth_success_redirect(access_token: str, provider: str) -> str:
    base = (settings.OAUTH_FRONTEND_SUCCESS_URL or "http://localhost:3000").strip()
    token_part = quote(access_token, safe="")
    provider_part = quote(provider, safe="")
    return f"{base}#access_token={token_part}&provider={provider_part}"


def build_oauth_error_redirect(error_message: str, provider: str) -> str:
    base = (settings.OAUTH_FRONTEND_ERROR_URL or settings.OAUTH_FRONTEND_SUCCESS_URL or "http://localhost:3000").strip()
    message_part = quote(error_message, safe="")
    provider_part = quote(provider, safe="")
    return f"{base}#oauth_error={message_part}&provider={provider_part}"


async def begin_oauth_login(request: Request, provider: str):
    provider_clean = provider.strip().lower()
    client = _get_client(provider_clean)
    redirect_uri = str(request.url_for("oauth_callback", provider=provider_clean))
    nonce = secrets.token_urlsafe(24)
    return await client.authorize_redirect(request, redirect_uri, nonce=nonce)


def _fallback_email(provider: str, subject: str, email: str | None) -> str:
    candidate = (email or "").strip().lower()
    if candidate:
        return candidate
    digest = hashlib.sha256(f"{provider}:{subject}".encode("utf-8")).hexdigest()[:24]
    return f"{provider}-{digest}@oauth.local"


async def _extract_identity(provider: str, token: dict[str, Any], client: Any, request: Request) -> dict[str, str | None]:
    payload: dict[str, Any] = {}

    token_userinfo = token.get("userinfo")
    if isinstance(token_userinfo, dict):
        payload.update(token_userinfo)

    try:
        claims = await client.parse_id_token(request, token)
        if isinstance(claims, dict):
            payload.update(claims)
    except Exception:
        pass

    if provider == "microsoft":
        if "sub" not in payload:
            try:
                extra = await client.userinfo(token=token)
                if isinstance(extra, dict):
                    payload.update(extra)
            except Exception:
                pass

        subject = str(payload.get("sub") or payload.get("oid") or payload.get("id") or "").strip() or None
        email = (
            payload.get("email")
            or payload.get("preferred_username")
            or payload.get("upn")
            or payload.get("mail")
        )
        display_name = payload.get("name") or payload.get("preferred_username") or email
        avatar_url = payload.get("picture")
    else:
        subject = str(payload.get("sub") or payload.get("id") or "").strip() or None
        email = payload.get("email")
        display_name = payload.get("name") or payload.get("given_name") or email
        avatar_url = payload.get("picture")

    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OAuth identity not found")

    normalized_email = _fallback_email(provider, subject, email if isinstance(email, str) else None)

    return {
        "subject": subject,
        "email": normalized_email,
        "display_name": str(display_name).strip() if display_name else None,
        "avatar_url": str(avatar_url).strip() if avatar_url else None,
        "profile": payload,
    }


async def handle_oauth_callback(
    request: Request,
    session: AsyncSession,
    provider: str,
) -> tuple[str, dict[str, Any]]:
    provider_clean = provider.strip().lower()
    client = _get_client(provider_clean)

    try:
        token = await client.authorize_access_token(request)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"OAuth exchange failed: {exc}") from exc

    identity = await _extract_identity(provider_clean, token, client, request)
    user = await upsert_oauth_user(
        session,
        provider=provider_clean,
        subject=str(identity["subject"]),
        email=identity.get("email"),
        display_name=identity.get("display_name"),
        avatar_url=identity.get("avatar_url"),
        profile=identity.get("profile") if isinstance(identity.get("profile"), dict) else {},
    )
    access_token = issue_access_token(user)
    return access_token, user
