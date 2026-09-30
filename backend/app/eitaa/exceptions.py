"""EitaaAdapter exceptions — stable error surface independent of eitaa-cli."""

from __future__ import annotations


class EitaaAdapterError(Exception):
    """Base class for every adapter failure."""

    def __init__(self, message: str, *, retryable: bool = False, retry_after: int | None = None):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after


class EitaaAuthRequiredError(EitaaAdapterError):
    """The stored session is invalid/expired — the account must reconnect."""


class EitaaSendError(EitaaAdapterError):
    """Sending a message/media failed."""


class EitaaPeerError(EitaaAdapterError):
    """The peer could not be resolved."""


class EitaaMediaError(EitaaAdapterError):
    """Upload/download of media failed."""


class EitaaLoginError(EitaaAdapterError):
    """OTP login flow failed (invalid code, expired challenge, flood, signup required...)."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "unknown",
        retry_after: int | None = None,
        signup_required: bool = False,
    ):
        super().__init__(message, retryable=False, retry_after=retry_after)
        self.reason = reason
        self.signup_required = signup_required
