"""EitaaCliAdapter — the ONLY module that talks to eitaa-cli.

Mapping between eitaa-cli and our domain types happens here. Everything above
this layer works with the dataclasses from app/eitaa/base.py.

Implementation notes (verified against eitaa-cli 0.5.0 source):
  * `EitaaClient(settings, _loaded_profile=SessionProfile(...))` builds a
    client from an in-memory session — no session file on disk.
  * `auth.sign_in(..., save=False)` keeps the session out of eitaa-cli's own
    session store; we persist it ourselves (encrypted) via SessionVault.
  * Dialog/message shapes come from `messages.getDialogs` / `messages.getHistory`
    TL responses: dicts with `dialogs`, `messages`, `users`, `chats`.
  * `messages.readHistory` exists in the bundled layer-135 schema and is called
    through the documented generic `invoke()`; failures are swallowed (best-effort).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from eitaa_cli import EitaaClient
from eitaa_cli.config import EitaaSettings
from eitaa_cli.errors import AuthenticationRequired, EitaaError, EitaaRPCError, OtpError
from eitaa_cli.services.dialogs import dialog_entity_map, entity_kind
from eitaa_cli.session import SessionProfile

from app.core.config import settings as app_settings
from app.eitaa.base import (
    EitaaAccountInfo,
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


def _eitaa_settings() -> EitaaSettings:
    return EitaaSettings(
        timeout=app_settings.eitaa_api_timeout,
        # keep eitaa-cli's own session file inert: point it at a private dir we
        # never read; sessions live encrypted in OUR database.
        session_file=Path(app_settings.uploads_path).parent / "eitaa-cli" / "unused-sessions.json",
    )


def _profile_from_session(session: EitaaSession, name: str = "desk") -> SessionProfile:
    return SessionProfile(
        name=name,
        phone_number=session.phone_number,
        token=session.token,
        imei=session.imei,
        user=session.user,
    )


def _client(session: EitaaSession) -> EitaaClient:
    return EitaaClient(_eitaa_settings(), _loaded_profile=_profile_from_session(session))


def _user_name(entity: dict) -> str:
    parts = [entity.get("first_name") or "", entity.get("last_name") or ""]
    return " ".join(p for p in parts if p).strip()


class EitaaCliAdapter:
    """Async adapter over the `eitaa-cli` library (in-process, no subprocess)."""

    # ------------------------------------------------------------- login flow
    async def request_login_challenge(self, phone_number: str) -> EitaaLoginChallenge:
        client = EitaaClient(_eitaa_settings())  # unauthenticated, throwaway profile
        try:
            async with client:
                challenge = await client.auth.request_code(phone_number)
                return EitaaLoginChallenge(
                    challenge_id=uuid.uuid4().hex,
                    phone_number=challenge.phone_number,
                    phone_code_hash=challenge.phone_code_hash,
                    delivery=challenge.delivery.value,
                    next_delivery=challenge.next_delivery.value
                    if challenge.next_delivery
                    else None,
                    timeout_seconds=challenge.timeout_seconds,
                    code_length=challenge.code_length,
                )
        except OtpError as exc:
            raise EitaaLoginError(
                f"OTP request failed: {exc.reason.value}",
                reason=exc.reason.value,
                retry_after=exc.retry_after_seconds,
            ) from exc
        except EitaaError as exc:
            raise EitaaLoginError(f"OTP request failed: {exc}") from exc

    async def resend_login_challenge(
        self, phone_number: str, phone_code_hash: str
    ) -> EitaaLoginChallenge:
        client = EitaaClient(_eitaa_settings())
        try:
            async with client:
                challenge = await client.auth.resend_code(phone_number, phone_code_hash)
                return EitaaLoginChallenge(
                    challenge_id=uuid.uuid4().hex,
                    phone_number=challenge.phone_number,
                    phone_code_hash=challenge.phone_code_hash,
                    delivery=challenge.delivery.value,
                    next_delivery=challenge.next_delivery.value
                    if challenge.next_delivery
                    else None,
                    timeout_seconds=challenge.timeout_seconds,
                    code_length=challenge.code_length,
                )
        except OtpError as exc:
            raise EitaaLoginError(
                f"Resend failed: {exc.reason.value}",
                reason=exc.reason.value,
                retry_after=exc.retry_after_seconds,
            ) from exc
        except EitaaError as exc:
            raise EitaaLoginError(f"Resend failed: {exc}") from exc

    async def complete_login(
        self, phone_number: str, phone_code_hash: str, otp_code: str
    ) -> EitaaSession:
        client = EitaaClient(_eitaa_settings())
        try:
            async with client:
                response = await client.auth.sign_in(
                    phone_number, phone_code_hash, otp_code, save=False
                )
                predicate = response.get("_")
                if predicate == "auth.authorizationSignUpRequired":
                    raise EitaaLoginError(
                        "This phone number is not registered on Eitaa; sign up in the "
                        "Eitaa app first, then connect it here",
                        reason="signup_required",
                        signup_required=True,
                    )
                if predicate != "auth.authorization":
                    raise EitaaLoginError(
                        "Eitaa did not return an authorization", reason="unexpected_response"
                    )
                profile = client.profile
                if not profile.token:
                    raise EitaaLoginError("No token in authorization", reason="no_token")
                return EitaaSession(
                    phone_number=profile.phone_number or phone_number,
                    token=profile.token,
                    imei=profile.imei,
                    user=dict(profile.user) if profile.user else None,
                )
        except OtpError as exc:
            raise EitaaLoginError(
                f"Sign-in failed: {exc.reason.value}",
                reason=exc.reason.value,
                retry_after=exc.retry_after_seconds,
            ) from exc
        except EitaaError as exc:
            raise EitaaLoginError(f"Sign-in failed: {exc}") from exc

    async def verify_session(self, session: EitaaSession) -> EitaaAccountInfo:
        try:
            async with _client(session) as client:
                try:
                    full = await client.invoke_object(
                        "users.getFullUser", {"id": {"_": "inputUserSelf"}}
                    )
                    user = full.get("user") or {}
                    return EitaaAccountInfo(
                        user_id=user.get("id"),
                        first_name=user.get("first_name") or "",
                        last_name=user.get("last_name") or "",
                        username=user.get("username"),
                        phone=user.get("phone"),
                    )
                except EitaaRPCError:
                    user = session.user or {}
                    return EitaaAccountInfo(
                        user_id=user.get("id"),
                        first_name=user.get("first_name") or "",
                        last_name=user.get("last_name") or "",
                        username=user.get("username"),
                        phone=user.get("phone"),
                    )
        except AuthenticationRequired as exc:
            raise EitaaAuthRequiredError("Eitaa session is no longer valid") from exc
        except EitaaError as exc:
            raise EitaaAuthRequiredError(f"Session check failed: {exc}") from exc

    async def logout(self, session: EitaaSession) -> None:
        try:
            async with _client(session) as client:
                await client.invoke("auth.logOut")
        except EitaaError:
            # server-side logout is best-effort; the local session is dropped regardless
            pass

    # ------------------------------------------------------------- dialogs
    async def list_dialogs(self, session: EitaaSession, limit: int = 100) -> list[EitaaDialog]:
        try:
            async with _client(session) as client:
                result = await client.dialogs.list(limit)
        except AuthenticationRequired as exc:
            raise EitaaAuthRequiredError("Eitaa session is no longer valid") from exc
        except EitaaError as exc:
            raise EitaaAdapterError(f"list dialogs failed: {exc}", retryable=True) from exc

        entities = dialog_entity_map(result)
        by_top_id = {m.get("id"): m for m in result.get("messages", [])}
        dialogs: list[EitaaDialog] = []
        for dialog in result.get("dialogs", []):
            peer = dialog.get("peer") or {}
            predicate = peer.get("_", "")
            if predicate in {"peerUser", "inputPeerUser"}:
                peer_type, peer_id = "user", peer.get("user_id", 0)
                entity = entities.get(("user", peer_id)) or {}
                access_hash = entity.get("access_hash")
            elif predicate in {"peerChat", "inputPeerChat"}:
                peer_type, peer_id = "chat", peer.get("chat_id", 0)
                entity = entities.get(("chat", peer_id)) or {}
                access_hash = None
            elif predicate in {"peerChannel", "inputPeerChannel"}:
                peer_type, peer_id = "channel", peer.get("channel_id", 0)
                entity = entities.get(("channel", peer_id)) or {}
                access_hash = entity.get("access_hash")
            else:
                continue
            top_id = dialog.get("top_message", 0)
            top = by_top_id.get(top_id) or {}
            dialogs.append(
                EitaaDialog(
                    peer_type=peer_type,
                    peer_id=peer_id,
                    access_hash=access_hash,
                    kind=entity_kind(entity) if entity else "unknown",
                    title=_user_name(entity) or entity.get("title") or str(peer_id),
                    username=entity.get("username"),
                    phone=entity.get("phone"),
                    top_message_id=top_id,
                    unread_count=dialog.get("unread_count", 0),
                    last_message_date=top.get("date"),
                )
            )
        return dialogs

    # ------------------------------------------------------------- history
    async def get_history(
        self,
        session: EitaaSession,
        peer_reference: str,
        *,
        limit: int = 50,
        min_id: int = 0,
    ) -> list[EitaaMessage]:
        try:
            async with _client(session) as client:
                result = await client.messages.history(peer_reference, limit=limit, min_id=min_id)
        except AuthenticationRequired as exc:
            raise EitaaAuthRequiredError("Eitaa session is no longer valid") from exc
        except EitaaRPCError as exc:
            raise EitaaPeerError(f"history failed for peer: {exc.text}") from exc
        except EitaaError as exc:
            raise EitaaAdapterError(f"history failed: {exc}", retryable=True) from exc
        return [self._to_message(m) for m in result.get("messages", [])]

    async def get_message(
        self, session: EitaaSession, peer_reference: str, message_id: int
    ) -> EitaaMessage | None:
        try:
            async with _client(session) as client:
                message = await client.messages.get_by_id(peer_reference, message_id)
        except AuthenticationRequired as exc:
            raise EitaaAuthRequiredError("Eitaa session is no longer valid") from exc
        except EitaaError as exc:
            raise EitaaAdapterError(f"get_message failed: {exc}") from exc
        return self._to_message(message) if message else None

    # ------------------------------------------------------------- sending
    async def send_text(
        self,
        session: EitaaSession,
        peer_reference: str,
        text: str,
        *,
        reply_to: int | None = None,
    ) -> SendResult:
        try:
            async with _client(session) as client:
                result = await client.messages.send_text(peer_reference, text, reply_to=reply_to)
        except AuthenticationRequired as exc:
            raise EitaaAuthRequiredError("Eitaa session is no longer valid") from exc
        except EitaaError as exc:
            retryable = getattr(exc, "retryable", False)
            raise EitaaSendError(
                f"send failed: {exc}",
                retryable=retryable,
                retry_after=getattr(exc, "retry_after_seconds", None),
            ) from exc
        message_id = result.get("id") or self._extract_message_id(result)
        return SendResult(message_id=message_id)

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
    ) -> SendResult:
        try:
            async with _client(session) as client:
                result = await client.media.send_file(
                    peer_reference,
                    file_path,
                    caption=caption,
                    reply_to=reply_to,
                    voice=as_voice,
                    duration=duration_seconds,
                )
        except AuthenticationRequired as exc:
            raise EitaaAuthRequiredError("Eitaa session is no longer valid") from exc
        except EitaaError as exc:
            retryable = getattr(exc, "retryable", False)
            raise EitaaMediaError(
                f"media send failed: {exc}",
                retryable=retryable,
                retry_after=getattr(exc, "retry_after_seconds", None),
            ) from exc
        return SendResult(message_id=self._extract_message_id(result))

    async def download_message_media(
        self, session: EitaaSession, peer_reference: str, message_id: int, destination: Path
    ) -> Path:
        try:
            async with _client(session) as client:
                return await client.media.download_message(peer_reference, message_id, destination)
        except AuthenticationRequired as exc:
            raise EitaaAuthRequiredError("Eitaa session is no longer valid") from exc
        except EitaaError as exc:
            raise EitaaMediaError(f"media download failed: {exc}") from exc

    # ------------------------------------------------------------- best-effort
    async def mark_read(
        self, session: EitaaSession, peer_reference: str, max_message_id: int
    ) -> bool:
        """messages.readHistory via the documented generic invoke (layer-135).
        Returns False on any failure — read state in OUR database remains the
        source of truth for the panel."""
        try:
            async with _client(session) as client:
                peer = await client.peers.resolve(peer_reference)
                await client.invoke(
                    "messages.readHistory", {"peer": peer, "max_id": max_message_id}
                )
                return True
        except EitaaError:
            return False

    # ------------------------------------------------------------- links
    @staticmethod
    def peer_deep_link(username: str | None) -> str | None:
        if not username:
            return None
        clean = username.strip().lstrip("@")
        return f"https://eitaa.com/{clean}" if clean else None

    # ------------------------------------------------------------- internal
    def _to_message(self, raw: dict) -> EitaaMessage:
        reply_to = None
        if raw.get("reply_to") and isinstance(raw["reply_to"], dict):
            reply_to = raw["reply_to"].get("reply_to_msg_id")
        elif raw.get("reply_to_msg_id"):
            reply_to = raw["reply_to_msg_id"]

        from_id = raw.get("from_id") or {}
        sender_user_id = None
        if isinstance(from_id, dict):
            sender_user_id = (
                from_id.get("user_id") or from_id.get("channel_id") or from_id.get("chat_id")
            )

        return EitaaMessage(
            message_id=raw.get("id", 0),
            date=raw.get("date", 0),
            text=raw.get("message") or "",
            is_out=bool(raw.get("out")),
            sender_user_id=sender_user_id,
            reply_to_message_id=reply_to,
            media=self._media_info(raw.get("media")),
        )

    def _media_info(self, media: dict | None) -> EitaaMediaInfo | None:
        if not isinstance(media, dict):
            return None
        predicate = media.get("_", "")
        if predicate == "messageMediaPhoto":
            photo = media.get("photo") or {}
            best = None
            for size in photo.get("sizes") or []:
                if isinstance(size, dict) and size.get("_") != "photoSizeEmpty":
                    if best is None or (size.get("size") or 0) > (best.get("size") or 0):
                        best = size
            return EitaaMediaInfo(
                kind="photo",
                file_name=None,
                mime_type="image/jpeg",
                size_bytes=(best or {}).get("size"),
                duration_seconds=None,
                width=(best or {}).get("w"),
                height=(best or {}).get("h"),
                eitaa_file_id=photo.get("id"),
            )
        if predicate == "messageMediaDocument":
            document = media.get("document") or {}
            mime = document.get("mime_type") or "application/octet-stream"
            file_name = None
            duration = None
            width = height = None
            kind = "document"
            for attr in document.get("attributes") or []:
                if not isinstance(attr, dict):
                    continue
                a = attr.get("_", "")
                if a == "documentAttributeFilename":
                    file_name = attr.get("file_name")
                elif a == "documentAttributeAudio":
                    duration = attr.get("duration")
                    kind = "voice" if attr.get("voice") else "audio"
                elif a == "documentAttributeVideo":
                    duration = attr.get("duration")
                    width, height = attr.get("w"), attr.get("h")
                    kind = "video"
            if kind == "document" and mime.startswith("image/"):
                kind = "photo"
            return EitaaMediaInfo(
                kind=kind,
                file_name=file_name,
                mime_type=mime,
                size_bytes=document.get("size"),
                duration_seconds=duration,
                width=width,
                height=height,
                eitaa_file_id=document.get("id"),
            )
        # unsupported media (sticker, geo, contact, poll, ...)
        return EitaaMediaInfo(
            kind="unsupported",
            file_name=None,
            mime_type=None,
            size_bytes=None,
            duration_seconds=None,
            width=None,
            height=None,
            eitaa_file_id=None,
        )

    def _extract_message_id(self, result: dict) -> int | None:
        """messages.sendMessage/sendMedia return updates; dig out the message id."""

        def _walk(value: object) -> int | None:
            if isinstance(value, dict):
                if value.get("_") in {"updateNewMessage", "updateNewChannelMessage"}:
                    msg = value.get("message") or {}
                    if isinstance(msg, dict) and msg.get("id"):
                        return msg["id"]
                if value.get("_") == "messageMediaEmpty":
                    return None
                for child in value.values():
                    found = _walk(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = _walk(child)
                    if found:
                        return found
            return None

        return _walk(result)
