"""Model -> dict serializers shared by REST responses and WebSocket payloads.

Every related field is fetched with an explicit SELECT — never through ORM
lazy loading — so payloads are safe to build on freshly flushed objects.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, EitaaAccount, Message, MessageAttachment, User


async def conversation_payload(db: AsyncSession, conversation: Conversation) -> dict[str, Any]:
    agent_name = None
    if conversation.assigned_agent_id is not None:
        agent_name = (
            await db.execute(select(User.name).where(User.id == conversation.assigned_agent_id))
        ).scalar_one_or_none()
    account_phone = (
        await db.execute(
            select(EitaaAccount.phone_number).where(
                EitaaAccount.id == conversation.eitaa_account_id
            )
        )
    ).scalar_one_or_none()

    def _val(value: Any) -> Any:
        return value.value if hasattr(value, "value") else value

    return {
        "id": conversation.id,
        "eitaa_account_id": conversation.eitaa_account_id,
        "eitaa_account_phone": account_phone,
        "peer_type": conversation.peer_type,
        "peer_id": conversation.peer_id,
        "peer_kind": conversation.peer_kind,
        "title": conversation.title,
        "username": conversation.username,
        "phone": conversation.phone,
        "status": _val(conversation.status),
        "read_state": _val(conversation.read_state),
        "answer_state": _val(conversation.answer_state),
        "assigned_agent_id": conversation.assigned_agent_id,
        "assigned_agent_name": agent_name,
        "last_message_at": conversation.last_message_at.isoformat()
        if conversation.last_message_at
        else None,
        "last_message_preview": conversation.last_message_preview,
        "last_inbound_message_at": conversation.last_inbound_message_at.isoformat()
        if conversation.last_inbound_message_at
        else None,
        "unread_eitaa_count": conversation.unread_eitaa_count,
        "skip_reason": conversation.skip_reason,
        "deep_link": conversation.deep_link,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }


async def message_payload(db: AsyncSession, message: Message) -> dict[str, Any]:
    sender_name = None
    if message.sender_agent_id is not None:
        sender_name = (
            await db.execute(select(User.name).where(User.id == message.sender_agent_id))
        ).scalar_one_or_none()

    reply_preview = None
    if message.reply_to_message_id is not None:
        reply_text = (
            await db.execute(select(Message.text).where(Message.id == message.reply_to_message_id))
        ).scalar_one_or_none()
        reply_preview = (reply_text or "")[:80] or None

    attachment = None
    attachment_row = (
        await db.execute(
            select(MessageAttachment).where(MessageAttachment.message_id == message.id)
        )
    ).scalar_one_or_none()
    if attachment_row is not None:
        attachment = {
            "id": attachment_row.id,
            "kind": attachment_row.kind,
            "file_name": attachment_row.file_name,
            "mime_type": attachment_row.mime_type,
            "size_bytes": attachment_row.size_bytes,
            "duration_seconds": attachment_row.duration_seconds,
            "width": attachment_row.width,
            "height": attachment_row.height,
            "download_status": attachment_row.download_status,
            "download_url": f"/api/v1/attachments/{attachment_row.id}/download",
        }

    def _val(value: Any) -> Any:
        return value.value if hasattr(value, "value") else value

    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "eitaa_message_id": message.eitaa_message_id,
        "direction": _val(message.direction),
        "source": message.source,
        "text": message.text,
        "sender_agent_id": message.sender_agent_id,
        "sender_agent_name": sender_name,
        "send_status": _val(message.send_status),
        "error_message": message.error_message,
        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "reply_to_message_id": message.reply_to_message_id,
        "reply_preview": reply_preview,
        "attachment": attachment,
    }
