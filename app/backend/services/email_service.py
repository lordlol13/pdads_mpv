from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.backend.core.config import settings

logger = logging.getLogger(__name__)


def _send_with_resend(*, to_email: str, subject: str, html: str) -> bool:
    if not settings.RESEND_API_KEY.strip():
        return False

    try:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send(
            {
                "from": settings.RESEND_FROM_EMAIL,
                "to": to_email,
                "subject": subject,
                "html": html,
            }
        )
        return True
    except Exception as exc:
        # Resend SDK exceptions often include HTTP status/message (e.g. 401/403/422).
        # Log the exception details without leaking any secrets.
        logger.exception("Failed to send email via Resend to %s: %s", to_email, exc)
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
