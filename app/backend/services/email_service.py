from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.backend.core.config import settings

logger = logging.getLogger(__name__)


def _send_with_resend(*, to_email: str, subject: str, html: str) -> bool:
    if not settings.RESEND_API_KEY.strip():
        return False
    # Try a robust multi-tiered approach in preferred order:
    # 1) HTTP request via `httpx` (sync), 2) `requests` fallback, 3) official SDK `resend`.
    payload = {
        "from": settings.RESEND_FROM_EMAIL,
        "to": to_email,
        "subject": subject,
        "html": html,
    }

    # 1) httpx (preferred; already in requirements)
    try:
        import httpx

        try:
            resp = httpx.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                timeout=10.0,
            )
            if 200 <= resp.status_code < 300:
                return True
            logger.error(
                "Resend httpx request failed for %s: status=%s body=%s",
                to_email,
                resp.status_code,
                (resp.text[:200] if resp is not None else ""),
            )
        except Exception as exc_httpx:
            logger.exception("Resend httpx request error for %s: %s", to_email, exc_httpx)
    except Exception:
        # httpx not available; try next option
        logger.debug("httpx not available for Resend HTTP send, will try requests or SDK")

    # 2) requests fallback
    try:
        import requests

        try:
            resp = requests.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                timeout=10,
            )
            if 200 <= resp.status_code < 300:
                return True
            logger.error(
                "Resend requests request failed for %s: status=%s body=%s",
                to_email,
                resp.status_code,
                (resp.text[:200] if resp is not None else ""),
            )
        except Exception as exc_requests:
            logger.exception("Resend requests error for %s: %s", to_email, exc_requests)
    except Exception:
        logger.debug("requests not available for Resend HTTP send, will try SDK if present")

    # 3) Official SDK as last resort (may be missing in lightweight environments)
    try:
        from resend import Resend

        try:
            client = Resend(settings.RESEND_API_KEY)
            client.emails.send(payload)
            return True
        except Exception as exc_sdk_call:
            logger.exception("Resend SDK send failed for %s: %s", to_email, exc_sdk_call)
            return False
    except Exception:
        logger.exception("No available method succeeded to send email via Resend to %s", to_email)
        return False


def send_verification_code(email: str, code: str) -> bool:
    """Send verification code via SMTP.

    Returns True when SMTP send is successful. Returns False when SMTP is not configured
    or send fails; caller decides whether to block flow or keep dev fallback.
    """
    resend_html = (
        "<p>Your PDADS verification code is: "
        f"<strong>{code}</strong></p>"
        f"<p>Code expires in {settings.AUTH_VERIFICATION_CODE_TTL_MINUTES} minutes.</p>"
    )
    if _send_with_resend(
        to_email=email,
        subject="PDADS verification code",
        html=resend_html,
    ):
        return True

    if not settings.SMTP_HOST.strip():
        logger.info("Email provider is not configured, verification code for %s is %s", email, code)
        return False

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

            if settings.SMTP_USERNAME.strip():
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)

            smtp.send_message(message)
        return True
    except Exception:
        logger.exception("Failed to send verification email to %s", email)
        return False


def send_password_reset_code(email: str, code: str) -> bool:
    resend_html = (
        "<p>Your PDADS password reset code is: "
        f"<strong>{code}</strong></p>"
        f"<p>Code expires in {settings.PASSWORD_RESET_CODE_TTL_MINUTES} minutes.</p>"
    )
    if _send_with_resend(
        to_email=email,
        subject="PDADS password reset code",
        html=resend_html,
    ):
        return True

    if not settings.SMTP_HOST.strip():
        logger.info("Email provider is not configured, password reset code for %s is %s", email, code)
        return False

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
            if settings.SMTP_USERNAME.strip():
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        return True
    except Exception:
        logger.exception("Failed to send password reset email to %s", email)
        return False
