import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

_PBKDF2_ITERATIONS = 390000


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(password: str, salt: str | None = None) -> str:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return f"{salt_value}${_b64url_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    # FIX: Validate inputs are strings - prevent AttributeError on .split()
    if not isinstance(password_hash, str):
        return False
    if not isinstance(password, str):
        return False
    
    try:
        salt_value, stored_digest = password_hash.split("$", 1)
    except (ValueError, AttributeError):
        # ValueError: split returns single element (no "$")
        # AttributeError: password_hash not a string (defensive)
        return False
    
    try:
        calculated_hash = hash_password(password, salt_value)
        return hmac.compare_digest(calculated_hash, password_hash)
    except (AttributeError, TypeError):
        # Prevent crashes if hash_password receives unexpected types
        return False


def create_access_token(payload: dict[str, Any], secret_key: str, algorithm: str, expires_minutes: int) -> str:
    if algorithm.upper() != "HS256":
        raise ValueError("Only HS256 is supported")

    now = datetime.now(timezone.utc)
    token_payload = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        "typ": "access",
    }
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_part = _b64url_encode(json.dumps(token_payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}"
    signature = hmac.new(secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str, secret_key: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc

    signing_input = f"{header_part}.{payload_part}"
    expected_signature = hmac.new(
        secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(_b64url_encode(expected_signature), signature_part):
        raise ValueError("Invalid token signature")

    payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    if payload.get("typ") != "access":
        raise ValueError("Invalid token type")

    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise ValueError("Invalid token expiration")
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if exp < now_ts:
        raise ValueError("Token expired")

    return payload
