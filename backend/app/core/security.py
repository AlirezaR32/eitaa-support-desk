"""Security primitives: password hashing, JWT, refresh-token rotation, Fernet session vault.

Sensitive values (passwords, OTP codes, session tokens) must never reach logs —
see app/core/logging.py for the sanitizer that enforces this.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings

# ----------------------------------------------------------------- passwords
_password_hasher = PasswordHash((Argon2Hasher(),))


def hash_password(raw: str) -> str:
    return _password_hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _password_hasher.verify(raw, hashed)
    except Exception:  # malformed hash — never crash auth flows
        return False


# ----------------------------------------------------------------- JWT access
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def create_access_token(
    *,
    subject: str,
    role: str,
    permissions: list[str],
    token_version: int = 0,
    expires_minutes: int | None = None,
) -> tuple[str, datetime]:
    """Return (token, expires_at_utc)."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "perms": permissions,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    token = jwt.encode(payload, settings.effective_jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Return the payload or None (invalid/expired). Never raises."""
    try:
        payload = jwt.decode(
            token,
            settings.effective_jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload


# ----------------------------------------------------------------- refresh tokens
# Refresh tokens are opaque random strings; only their SHA-256 digest is stored.
REFRESH_TOKEN_TTL_DAYS = settings.refresh_token_expire_days


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS)


# ----------------------------------------------------------------- session vault (Eitaa)
class SessionVault:
    """Encrypts/decrypts Eitaa session payloads (token, imei, user) at rest.

    A dev fallback key (derived from SECRET_KEY) keeps local development usable;
    production deployments MUST set EITAA_SESSION_ENCRYPTION_KEY (validated at startup).
    """

    def __init__(self, key: str | None = None) -> None:
        self._fernet: Fernet | None = None
        self._key_source: Literal["env", "derived"] = "env"
        raw = key or settings.eitaa_session_encryption_key
        if raw:
            try:
                self._fernet = Fernet(raw.encode())
                return
            except (ValueError, TypeError):
                # not a valid Fernet key — derive one deterministically
                pass
        self._key_source = "derived"
        digest = hashlib.sha256(
            f"eitaa-desk:{settings.secret_key}".encode(), usedforsecurity=True
        ).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    @property
    def using_derived_key(self) -> bool:
        return self._key_source == "derived"

    def encrypt(self, payload: dict[str, Any]) -> bytes:
        import json

        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        return self._fernet.encrypt(data)

    def decrypt(self, blob: bytes) -> dict[str, Any] | None:
        import json

        try:
            data = self._fernet.decrypt(bytes(blob))
            value = json.loads(data)
            return value if isinstance(value, dict) else None
        except (InvalidToken, ValueError):
            return None


session_vault = SessionVault()


# ----------------------------------------------------------------- misc
def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
