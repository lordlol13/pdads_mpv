from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Optional, Tuple

from app.backend.core.config import settings

logger = logging.getLogger(__name__)


def _send_with_resend(*, to_email: str, subject: str, html: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Attempt to send via Resend using httpx -> requests -> SDK.

    Returns (True, None) on success. On failure returns (False, error_dict)
    where error_dict contains provider/status/message for easier debugging.
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

    last_error: Optional[Dict[str, Any]] = None

    # 1) httpx (preferred)
    try:
        import httpx

        try:
            resp = httpx.post(
                "https://api.resend.com/emails",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
            if 200 <= resp.status_code < 300:
                return True, None
            try:
                body = resp.json()
                message = body.get("message") or body.get("error") or str(body)
            except Exception:
                message = resp.text
            logger.error(
                "Resend httpx request failed for %s: status=%s body=%s",
                to_email,
                resp.status_code,
                message,
            )
            last_error = {"provider": "resend", "status": resp.status_code, "message": message}
        except Exception as exc_httpx:
            logger.exception("Resend httpx request error for %s: %s", to_email, exc_httpx)
            last_error = {"provider": "resend", "error": str(exc_httpx)}
    except Exception:
        logger.debug("httpx not available for Resend HTTP send, will try requests")

    # 2) requests fallback
    try:
        import requests

        try:
            resp = requests.post(
                "https://api.resend.com/emails",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if 200 <= resp.status_code < 300:
                return True, None
            try:
                body = resp.json()
                message = body.get("message") or body.get("error") or str(body)
            except Exception:
                message = resp.text
            logger.error(
                "Resend requests request failed for %s: status=%s body=%s",
                to_email,
                resp.status_code,
                message,
            )
            last_error = {"provider": "resend", "status": resp.status_code, "message": message}
        except Exception as exc_requests:
            logger.exception("Resend requests error for %s: %s", to_email, exc_requests)
            last_error = {"provider": "resend", "error": str(exc_requests)}
    except Exception:
        logger.debug("requests not available for Resend HTTP send")

    # Stop after HTTP attempts; SDK imports are fragile in deployed environments.
    if last_error is None:
        last_error = {"provider": "resend", "error": "unknown_error"}
    return False, last_error


def send_verification_code(email: str, code: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Send verification code via Resend or SMTP fallback.

    Returns (sent: bool, provider_error: dict|None).
    """
    resend_html = (
        "<p>Your PDADS verification code is: "
        f"<strong>{code}</strong></p>"
        f"<p>Code expires in {settings.AUTH_VERIFICATION_CODE_TTL_MINUTES} minutes.</p>"
    )
    sent, provider_error = _send_with_resend(
        to_email=email,
        subject="PDADS verification code",
        html=resend_html,
    )
    if sent:
        return True, None

    if not (settings.SMTP_HOST or "").strip():
        logger.info("Email provider is not configured, verification code for %s is %s", email, code)
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
        logger.exception("Failed to send verification email to %s", email)
        return False, {"provider": "smtp", "error": str(exc)}


def send_password_reset_code(email: str, code: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    resend_html = (
        "<p>Your PDADS password reset code is: "
        f"<strong>{code}</strong></p>"
        f"<p>Code expires in {settings.PASSWORD_RESET_CODE_TTL_MINUTES} minutes.</p>"
    )
    sent, provider_error = _send_with_resend(
        to_email=email,
        subject="PDADS password reset code",
        html=resend_html,
    )
    if sent:
        return True, None

    if not (settings.SMTP_HOST or "").strip():
        logger.info("Email provider is not configured, password reset code for %s is %s", email, code)
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
        logger.exception("Failed to send password reset email to %s", email)
        return False, {"provider": "smtp", "error": str(exc)}


async def send_verification_code_async(email: str, code: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    return await asyncio.to_thread(send_verification_code, email, code)


async def send_password_reset_code_async(email: str, code: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    return await asyncio.to_thread(send_password_reset_code, email, code)
