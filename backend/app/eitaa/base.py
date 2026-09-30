"""Eitaa adapter contract.

EVERY interaction with Eitaa goes through `EitaaClientAdapter`. The concrete
implementation (EitaaCliAdapter) wraps the `eitaa-cli` Python library; if that
library changes — or a different transport appears — only the implementation
file changes. Services and workers depend exclusively on this contract.

Capability notes (verified against eitaa-cli 0.5.0, commit 685a71e):
  * No real-time event stream exists  -> the sync worker polls (see workers/).
  * `mark_read` uses the layer-135 `messages.readHistory` TL method through the
    library's generic `invoke()` — a real schema method, best-effort at runtime.
  * Deep links exist ONLY for public usernames (https://eitaa.com/USERNAME).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class EitaaSession:
    """Serializable account session — stored encrypted (Fernet) in the DB."""

    phone_number: str
    token: str
    imei: str
    user: dict | None = None


@dataclass(slots=True)
class EitaaLoginChallenge:
    challenge_id: str  # our own opaque id
    phone_number: str
    phone_code_hash: str = ""  # SENSITIVE: never serialize to API responses or logs
    delivery: str = "sms"  # sms | call | flash-call | app | unknown
    next_delivery: str | None = None
    timeout_seconds: int | None = None
    code_length: int | None = None


@dataclass(slots=True)
class EitaaAccountInfo:
    user_id: int | None
    first_name: str
    last_name: str
    username: str | None
    phone: str | None


@dataclass(slots=True)
class EitaaDialog:
    peer_type: str  # user | chat | channel
    peer_id: int
    access_hash: int | None
    kind: str  # private | group | supergroup | channel
    title: str
    username: str | None
    phone: str | None
    top_message_id: int
    unread_count: int
    last_message_date: int | None


@dataclass(slots=True)
class EitaaMediaInfo:
    kind: str  # photo | voice | audio | video | document
    file_name: str | None
    mime_type: str | None
    size_bytes: int | None
    duration_seconds: int | None
    width: int | None
    height: int | None
    eitaa_file_id: int | None


@dataclass(slots=True)
class EitaaMessage:
    message_id: int
    date: int  # unix
    text: str
    is_out: bool  # sent BY the account
    sender_user_id: int | None
    reply_to_message_id: int | None
    media: EitaaMediaInfo | None = None


@dataclass(slots=True)
class SendResult:
    message_id: int | None  # None when the API did not echo an id
    raw_ok: bool = True


@runtime_checkable
class EitaaClientAdapter(Protocol):
    """Contract implemented by EitaaCliAdapter (and by test doubles)."""

    # ---- login lifecycle -------------------------------------------------
    async def request_login_challenge(self, phone_number: str) -> EitaaLoginChallenge: ...
    async def resend_login_challenge(
        self, phone_number: str, phone_code_hash: str
    ) -> EitaaLoginChallenge: ...
    async def complete_login(
        self, phone_number: str, phone_code_hash: str, otp_code: str
    ) -> EitaaSession: ...
    async def verify_session(self, session: EitaaSession) -> EitaaAccountInfo: ...
    async def logout(self, session: EitaaSession) -> None: ...

    # ---- conversations ----------------------------------------------------
    async def list_dialogs(self, session: EitaaSession, limit: int = 100) -> list[EitaaDialog]: ...
    async def get_history(
        self,
        session: EitaaSession,
        peer_reference: str,
        *,
        limit: int = 50,
        min_id: int = 0,
    ) -> list[EitaaMessage]: ...
    async def get_message(
        self, session: EitaaSession, peer_reference: str, message_id: int
    ) -> EitaaMessage | None: ...

    # ---- messaging ----------------------------------------------------------
    async def send_text(
        self,
        session: EitaaSession,
        peer_reference: str,
        text: str,
        *,
        reply_to: int | None = None,
    ) -> SendResult: ...
    async def send_media(
        self,
        session: EitaaSession,
        peer_reference: str,
        file_path: Path,
        *,
        caption: str = "",
        reply_to: int | None = None,
        as_voice: bool = False,
        duration_seconds: int = 0,
    ) -> SendResult: ...
    async def download_message_media(
        self, session: EitaaSession, peer_reference: str, message_id: int, destination: Path
    ) -> Path: ...

    # ---- best-effort ---------------------------------------------------------
    async def mark_read(
        self, session: EitaaSession, peer_reference: str, max_message_id: int
    ) -> bool:
        """Best-effort: layer-135 `messages.readHistory` via generic invoke."""
        ...

    # ---- links -----------------------------------------------------------------
    @staticmethod
    def peer_deep_link(username: str | None) -> str | None:
        """Only for real usernames — never guess a link."""
        ...
