from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Optional, Tuple

import httpx

from app.backend.core.config import settings

logger = logging.getLogger(__name__)


async def _send_with_resend_async(*, to_email: str, subject: str, html: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Async Resend email send using httpx.

    Returns (True, None) on success. On failure returns (False, error_dict).
    """
    if not (settings.RESEND_API_KEY or "").strip():
        return False, {"provider": "resend", "error": "no_api_key"}

    payload = {
        "from": settings.RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers=headers,
            )
        if 200 <= resp.status_code < 300:
            return True, None
        try:
            body = resp.json()
            message = body.get("message") or body.get("error") or str(body)
        except Exception:
            message = resp.text
        logger.error(
            "Resend async request failed for %s: status=%s body=%s",
            to_email,
            resp.status_code,
            message,
        )
        return False, {"provider": "resend", "status": resp.status_code, "message": message}
    except Exception as exc:
        logger.exception(f"Resend async error for {to_email}: {exc}")
        return False, {"provider": "resend", "error": str(exc)}


async def send_verification_code_async(email: str, code: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Send verification code via Resend (async).

    Returns (sent: bool, provider_error: dict|None).
    """
    resend_html = (
        "<p>Your PDADS verification code is: "
        f"<strong>{code}</strong></p>"
        f"<p>Code expires in {settings.AUTH_VERIFICATION_CODE_TTL_MINUTES} minutes.</p>"
    )
    sent, provider_error = await _send_with_resend_async(
        to_email=email,
        subject="PDADS verification code",
        html=resend_html,
    )
    if sent:
        return True, None

    if not (settings.SMTP_HOST or "").strip():
        logger.info(f"Email provider not configured, verification code for {email} is {code}")
        return False, provider_error

    message = EmailMessage()
    message["Subject"] = "PDADS verification code"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = email
    message.set_content(
        "Your PDADS verification code is: "
        f"{code}\n\n"
        f"Code expires in {settings.AUTH_VERIFICATION_CODE_TTL_MINUTES} minutes."
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()

            if (settings.SMTP_USERNAME or "").strip():
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)

            smtp.send_message(message)
        return True, None
    except Exception as exc:
        logger.exception(f"Failed to send verification email to {email}")
        return False, {"provider": "smtp", "error": str(exc)}


async def send_password_reset_code(email: str, code: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    resend_html = (
        "<p>Your PDADS password reset code is: "
        f"<strong>{code}</strong></p>"
        f"<p>Code expires in {settings.PASSWORD_RESET_CODE_TTL_MINUTES} minutes.</p>"
    )
    sent, provider_error = await _send_with_resend_async(
        to_email=email,
        subject="PDADS password reset code",
        html=resend_html,
    )
    if sent:
        return True, None

    if not (settings.SMTP_HOST or "").strip():
        logger.info(f"Email provider is not configured, password reset code for {email} is {code}")
        return False, provider_error

    message = EmailMessage()
    message["Subject"] = "PDADS password reset code"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = email
    message.set_content(
        "Your PDADS password reset code is: "
        f"{code}\n\n"
        f"Code expires in {settings.PASSWORD_RESET_CODE_TTL_MINUTES} minutes."
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if (settings.SMTP_USERNAME or "").strip():
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        return True, None
    except Exception as exc:
        logger.exception(f"Failed to send password reset email to {email}")
        return False, {"provider": "smtp", "error": str(exc)}


async def send_password_reset_code_async(email: str, code: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Send password reset code via Resend (async)."""
    resend_html = (
        "<p>Your PDADS password reset code is: "
        f"<strong>{code}</strong></p>"
        f"<p>Code expires in {settings.PASSWORD_RESET_CODE_TTL_MINUTES} minutes.</p>"
    )
    sent, provider_error = await _send_with_resend_async(
        to_email=email,
        subject="PDADS password reset code",
        html=resend_html,
    )
    if sent:
        return True, None

    if not (settings.SMTP_HOST or "").strip():
        logger.info(f"Email provider not configured, reset code for {email} is {code}")
        return False, provider_error
