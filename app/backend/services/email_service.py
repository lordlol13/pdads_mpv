from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.backend.core.config import settings

logger = logging.getLogger(__name__)


def send_verification_code(email: str, code: str) -> bool:
    """Send verification code via SMTP.

    Returns True when SMTP send is successful. Returns False when SMTP is not configured
    or send fails; caller decides whether to block flow or keep dev fallback.
    """
    if not settings.SMTP_HOST.strip():
        logger.info("SMTP is not configured, verification code for %s is %s", email, code)
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
