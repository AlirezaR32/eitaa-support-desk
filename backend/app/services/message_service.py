"""Message pipeline: ingest from the sync worker, send from the panel, retry.

Send flow (§39): assignment is re-validated SERVER-SIDE right before sending —
if the thread is assigned to another agent, the send is rejected with 409.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import bus
from app.core.logging import get_logger
from app.eitaa.registry import EitaaRegistry
from app.models import (
    AnswerState,
    Conversation,
    ConversationStatus,
    Message,
    MessageAttachment,
    MessageDirection,
    MessageSource,
    ReadState,
    SendStatus,
    User,
)
from app.services import audit_service
from app.services.errors import ConflictError, ValidationError
from app.services.serializer import conversation_payload, message_payload

logger = get_logger("app.messages")


# ------------------------------------------------------------------ ingest (sync)
async def ingest_inbound(
    db: AsyncSession,
    conversation: Conversation,
    *,
    eitaa_message_id: int,
    sent_at: datetime,
    text: str,
    sender_user_id: int | None,
    reply_to_eitaa_id: int | None,
    media_info: object | None,
) -> Message | None:
    """Insert an inbound message discovered by the sync worker.

    Returns None when the message already exists (dedup via the
    (conversation_id, eitaa_message_id) unique constraint) — duplicate
    processing is thereby impossible even across concurrent sync passes.
    """
    message = Message(
        conversation_id=conversation.id,
        eitaa_message_id=eitaa_message_id,
        direction=MessageDirection.INBOUND,
        source=MessageSource.SYNC.value,
        text=text or "",
        sender_eitaa_user_id=sender_user_id,
        send_status=SendStatus.SENT,
        sent_at=sent_at,
    )
    if reply_to_eitaa_id:
        reply_row = (
            await db.execute(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.eitaa_message_id == reply_to_eitaa_id,
                )
            )
        ).scalar_one_or_none()
        if reply_row is not None:
            message.reply_to_message_id = reply_row.id
    if media_info is not None:
        message.attachment = MessageAttachment(
            kind=media_info.kind,
            file_name=media_info.file_name,
            mime_type=media_info.mime_type,
            size_bytes=media_info.size_bytes,
            duration_seconds=media_info.duration_seconds,
            width=media_info.width,
            height=media_info.height,
            eitaa_file_id=media_info.eitaa_file_id,
            download_status="not_downloaded",
        )
    db.add(message)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return None  # already ingested by a concurrent pass — not an error

    await _apply_message_side_effects(db, conversation, message, direction=MessageDirection.INBOUND)
    return message


async def ingest_outbound_from_app(
    db: AsyncSession,
    conversation: Conversation,
    *,
    eitaa_message_id: int,
    sent_at: datetime,
    text: str,
    reply_to_eitaa_id: int | None,
    media_info: object | None,
) -> Message | None:
    """The account owner replied from the Eitaa app itself — still counts as
    an answer (answer_state=ANSWERED) so SLA tracking stays honest."""
    message = Message(
        conversation_id=conversation.id,
        eitaa_message_id=eitaa_message_id,
        direction=MessageDirection.OUTBOUND,
        source=MessageSource.EITAA_APP.value,
        text=text or "",
        send_status=SendStatus.SENT,
        sent_at=sent_at,
    )
    if reply_to_eitaa_id:
        reply_row = (
            await db.execute(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.eitaa_message_id == reply_to_eitaa_id,
                )
            )
        ).scalar_one_or_none()
        if reply_row is not None:
            message.reply_to_message_id = reply_row.id
    if media_info is not None:
        message.attachment = MessageAttachment(
            kind=media_info.kind,
            file_name=media_info.file_name,
            mime_type=media_info.mime_type,
            size_bytes=media_info.size_bytes,
            duration_seconds=media_info.duration_seconds,
            width=media_info.width,
            height=media_info.height,
            eitaa_file_id=media_info.eitaa_file_id,
            download_status="not_downloaded",
        )
    db.add(message)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return None
    await _apply_message_side_effects(
        db, conversation, message, direction=MessageDirection.OUTBOUND
    )
    return message


# ------------------------------------------------------------------ send (panel)
async def send_message(
    db: AsyncSession,
    registry: EitaaRegistry,
    conversation: Conversation,
    *,
    actor: User,
    text: str,
    reply_to_message_id: int | None = None,
    attachment_path: Path | None = None,
    attachment_meta: dict | None = None,
    as_voice: bool = False,
    duration_seconds: int = 0,
) -> Message:
    # --- server-side assignment re-validation right before sending (§39) ---
    if conversation.assigned_agent_id is not None and conversation.assigned_agent_id != actor.id:
        raise ConflictError("This conversation is assigned to another agent — take it over first")
    if conversation.assigned_agent_id is None:
        # auto-claim on first reply (atomic, same guard as claim())
        from sqlalchemy import update

        result = await db.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation.id,
                Conversation.assigned_agent_id.is_(None),
            )
            .values(
                assigned_agent_id=actor.id,
                assigned_at=datetime.now(timezone.utc),
            )
        )
        if result.rowcount == 0:
            await db.refresh(conversation)
            raise ConflictError("Another agent just took this conversation")

    if not text.strip() and attachment_path is None:
        raise ValidationError("Message text or an attachment is required")

    reply_to_eitaa_id: int | None = None
    if reply_to_message_id is not None:
        reply_row = (
            await db.execute(
                select(Message).where(
                    Message.id == reply_to_message_id,
                    Message.conversation_id == conversation.id,
                )
            )
        ).scalar_one_or_none()
        if reply_row is None:
            raise ValidationError("Reply target message not found in this conversation")
        reply_to_eitaa_id = reply_row.eitaa_message_id

    message = Message(
        conversation_id=conversation.id,
        direction=MessageDirection.OUTBOUND,
        source=MessageSource.PANEL.value,
        text=text.strip(),
        sender_agent_id=actor.id,
        send_status=SendStatus.PENDING,
        reply_to_message_id=reply_to_message_id,
    )
    if attachment_path is not None and attachment_meta:
        message.attachment = MessageAttachment(
            kind=attachment_meta.get("kind", "document"),
            file_name=attachment_meta.get("file_name"),
            mime_type=attachment_meta.get("mime_type"),
            size_bytes=attachment_meta.get("size_bytes"),
            duration_seconds=attachment_meta.get("duration_seconds"),
            storage_path=str(attachment_path),
            download_status="downloaded",  # panel uploads are already on disk
        )
    db.add(message)
    await db.flush()

    await _deliver(
        db,
        registry,
        conversation,
        message,
        reply_to_eitaa_id,
        as_voice,
        duration_seconds,
        attachment_path=attachment_path,
    )
    if message.send_status == SendStatus.SENT:
        # state effects only for successful sends — a failed attempt must NOT
        # mark the conversation answered
        await _apply_message_side_effects(
            db, conversation, message, direction=MessageDirection.OUTBOUND
        )
    return message


async def retry_message(
    db: AsyncSession,
    registry: EitaaRegistry,
    message: Message,
    *,
    actor: User,
) -> Message:
    if message.direction != MessageDirection.OUTBOUND or message.send_status != SendStatus.FAILED:
        raise ValidationError("Only failed outgoing messages can be retried")
    conversation = (
        await db.execute(select(Conversation).where(Conversation.id == message.conversation_id))
    ).scalar_one()
    if conversation.assigned_agent_id is not None and conversation.assigned_agent_id != actor.id:
        raise ConflictError("This conversation is assigned to another agent")

    message.send_status = SendStatus.PENDING
    message.error_message = None
    await db.flush()
    await audit_service.record(
        db,
        action=audit_service.MESSAGE_RETRIED,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="message",
        target_id=message.id,
    )

    reply_to_eitaa_id = None
    if message.reply_to_message_id:
        reply_row = (
            await db.execute(select(Message).where(Message.id == message.reply_to_message_id))
        ).scalar_one_or_none()
        reply_to_eitaa_id = reply_row.eitaa_message_id if reply_row else None

    attachment_row = (
        await db.execute(
            select(MessageAttachment).where(MessageAttachment.message_id == message.id)
        )
    ).scalar_one_or_none()
    attachment_path = (
        Path(attachment_row.storage_path)
        if attachment_row and attachment_row.storage_path
        else None
    )
    as_voice = bool(attachment_row and attachment_row.kind == "voice")
    duration = (attachment_row.duration_seconds or 0) if attachment_row else 0

    await _deliver(
        db,
        registry,
        conversation,
        message,
        reply_to_eitaa_id,
        as_voice,
        duration,
        attachment_path=attachment_path,
    )
    if message.send_status == SendStatus.SENT:
        await _apply_message_side_effects(
            db, conversation, message, direction=MessageDirection.OUTBOUND
        )
    return message


async def _deliver(
    db: AsyncSession,
    registry: EitaaRegistry,
    conversation: Conversation,
    message: Message,
    reply_to_eitaa_id: int | None,
    as_voice: bool,
    duration_seconds: int,
    attachment_path: Path | None = None,
) -> None:
    """Actually call Eitaa; record outcome + audit either way."""
    session = registry.session_for(await _account(db, conversation.eitaa_account_id))
    try:
        if attachment_path is not None:
            result = await registry.adapter.send_media(
                session,
                conversation.peer_reference,
                attachment_path,
                caption=message.text,
                reply_to=reply_to_eitaa_id,
                as_voice=as_voice,
                duration_seconds=duration_seconds,
            )
        else:
            result = await registry.adapter.send_text(
                session, conversation.peer_reference, message.text, reply_to=reply_to_eitaa_id
            )
        message.send_status = SendStatus.SENT
        message.eitaa_message_id = result.message_id
        message.sent_at = datetime.now(timezone.utc)
        await db.flush()
        await audit_service.record(
            db,
            action=audit_service.MESSAGE_SENT,
            actor_id=message.sender_agent_id,
            target_type="conversation",
            target_id=conversation.id,
            meta={"message_id": message.id, "with_attachment": attachment_path is not None},
        )
    except Exception as exc:  # noqa: BLE001 — delivery failures are data, not crashes
        message.send_status = SendStatus.FAILED
        message.error_message = _sanitize_error(exc)
        await db.flush()
        await audit_service.record(
            db,
            action=audit_service.MESSAGE_FAILED,
            actor_id=message.sender_agent_id,
            target_type="conversation",
            target_id=conversation.id,
            meta={"message_id": message.id, "error": message.error_message},
        )


def _sanitize_error(exc: Exception) -> str:
    """Short, log-safe error text (no tokens / internal details)."""
    text = str(exc) or exc.__class__.__name__
    return text[:280]


# ------------------------------------------------------------------ state effects
async def _apply_message_side_effects(
    db: AsyncSession,
    conversation: Conversation,
    message: Message,
    *,
    direction: MessageDirection,
) -> None:
    """Server-side state machine — the single source of truth (§10, §11, §38)."""
    now = message.sent_at or datetime.now(timezone.utc)

    if direction == MessageDirection.INBOUND:
        conversation.read_state = ReadState.UNREAD
        conversation.answer_state = AnswerState.UNANSWERED
        conversation.last_inbound_message_at = now
        if conversation.first_inbound_at is None:
            conversation.first_inbound_at = now
        # a new user message re-activates waiting/skipped/closed threads
        if conversation.status in (
            ConversationStatus.WAITING_USER,
            ConversationStatus.SKIPPED,
            ConversationStatus.CLOSED,
        ):
            conversation.status = ConversationStatus.ACTIVE
            conversation.skip_reason = None
    else:
        conversation.answer_state = AnswerState.ANSWERED
        conversation.last_outbound_message_at = now
        if conversation.first_agent_reply_at is None:
            conversation.first_agent_reply_at = now
        if conversation.status == ConversationStatus.ACTIVE:
            conversation.status = (
                ConversationStatus.ACTIVE
            )  # answered threads stay active until closed

    conversation.last_message_at = now
    conversation.last_message_preview = (message.text or "")[:200]
    if message.eitaa_message_id and message.eitaa_message_id > (conversation.last_message_id or 0):
        conversation.last_message_id = message.eitaa_message_id
    await db.flush()

    # real-time fan-out
    await bus.publish(
        "message.created",
        await message_payload(db, message),
        account_id=conversation.eitaa_account_id,
        conversation_id=conversation.id,
    )
    await bus.publish(
        "conversation.updated",
        await conversation_payload(db, conversation),
        account_id=conversation.eitaa_account_id,
        conversation_id=conversation.id,
    )


async def _account(db: AsyncSession, account_id: int):
    from app.models import EitaaAccount

    return (
        await db.execute(select(EitaaAccount).where(EitaaAccount.id == account_id))
    ).scalar_one()
