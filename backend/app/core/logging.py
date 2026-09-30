"""Logging setup with sensitive-value sanitization.

Any logged mapping that contains keys such as `token`, `otp`, `password`,
`phone_code_hash`, `session` or `authorization` has the corresponding values
masked before formatting, so tokens/OTPs never leak into logs.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

SENSITIVE_KEYS = {
    "password",
    "new_password",
    "old_password",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "otp",
    "phone_code",
    "phone_code_hash",
    "code",
    "session",
    "session_encrypted",
    "authorization",
    "cookie",
    "secret",
    "secret_key",
    "jwt_secret",
    "encryption_key",
    "session_token",
    "session_payload",
    "password_hash",
}

_MASK = "***"


def sanitize_value(value: Any, _depth: int = 0) -> Any:
    if _depth > 4:
        return "…"
    if isinstance(value, dict):
        return {
            k: (_MASK if str(k).lower() in SENSITIVE_KEYS else sanitize_value(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_value(v, _depth + 1) for v in value]
    return value


class SanitizingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for attr in ("message", "msg"):
            value = getattr(record, attr, None)
            if isinstance(value, dict):
                setattr(record, attr, sanitize_value(value))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("conversation_id", "account_id", "agent_id", "method", "path", "status_code"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings_level())
    handler = logging.StreamHandler(sys.stdout)
    from app.core.config import settings

    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
        )
    handler.addFilter(SanitizingFilter())
    root.handlers.clear()
    root.addHandler(handler)
    # quiet noisy third-party loggers
    for name in ("httpx", "httpcore", "apscheduler", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def settings_level() -> int:
    from app.core.config import settings

    return getattr(logging, settings.log_level.upper(), logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
