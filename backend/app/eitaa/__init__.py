"""Eitaa adapter layer — the single boundary for all Eitaa traffic."""

from app.eitaa.base import (
    EitaaAccountInfo,
    EitaaClientAdapter,
    EitaaDialog,
    EitaaLoginChallenge,
    EitaaMediaInfo,
    EitaaMessage,
    EitaaSession,
    SendResult,
)
from app.eitaa.exceptions import (
    EitaaAdapterError,
    EitaaAuthRequiredError,
    EitaaLoginError,
    EitaaMediaError,
    EitaaPeerError,
    EitaaSendError,
)
from app.eitaa.registry import EitaaRegistry, get_registry

__all__ = [
    "EitaaAccountInfo",
    "EitaaClientAdapter",
    "EitaaDialog",
    "EitaaLoginChallenge",
    "EitaaMediaInfo",
    "EitaaMessage",
    "EitaaSession",
    "SendResult",
    "EitaaAdapterError",
    "EitaaAuthRequiredError",
    "EitaaLoginError",
    "EitaaMediaError",
    "EitaaPeerError",
    "EitaaSendError",
    "EitaaRegistry",
    "get_registry",
]
