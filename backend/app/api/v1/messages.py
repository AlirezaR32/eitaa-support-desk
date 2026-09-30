"""Message endpoints: paginated history, send (text/media), retry, attachments."""

from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    File,
    Form,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import Auth, DbSession, PageParams
from app.eitaa.registry import get_registry
from app.models import Message, MessageAttachment
from app.schemas.common import MessageOut, Page
from app.services import conversation_service, message_service, upload_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="", tags=["messages"])  # mounted under /conversations too

messages_router = APIRouter(prefix="/messages", tags=["messages"])


# ------------------------------------------------------------------ history
async def list_messages(
    conversation_id: int,
    db: DbSession,
    auth: Auth,
    page_params: PageParams,
):
    auth.require("message.view")
    account_ids = await conversation_service.permitted_account_ids(db, auth.user, auth.permissions)
    await conversation_service.get_conversation(db, conversation_id, account_ids=account_ids)

    total = (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(page_params.page_size)
                .offset(page_params.offset)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    rows = list(reversed(rows))  # chronological in page

    from app.models import User

    agent_ids = {m.sender_agent_id for m in rows if m.sender_agent_id}
    names = {}
    if agent_ids:
        names = {
            u.id: u.name
            for u in (await db.execute(select(User).where(User.id.in_(agent_ids)))).scalars().all()
        }

    items = []
    for m in rows:
        payload = await _message_payload(db, m, names)
        items.append(MessageOut(**payload))
    return Page(
        items=items,
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
        pages=max(1, -(-total // page_params.page_size)),
    )


async def _message_payload(db, m: Message, agent_names: dict[int, str] | None = None) -> dict:
    from app.services.serializer import message_payload

    payload = await message_payload(db, m)
    payload["sender_agent_name"] = (
        agent_names.get(m.sender_agent_id) if m.sender_agent_id and agent_names else None
    )
    return payload


# ------------------------------------------------------------------ send
async def send_message_endpoint(
    conversation_id: int,
    db: DbSession,
    auth: Auth,
    text: str = Form(default=""),
    reply_to_message_id: int | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    as_voice: bool = Form(default=False),
    duration_seconds: int = Form(default=0),
):
    """Send a reply. Accepts multipart (with file) or form-encoded (text only)."""
    auth.require("message.send")
    account_ids = await conversation_service.permitted_account_ids(db, auth.user, auth.permissions)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )

    attachment_path: Path | None = None
    attachment_meta: dict | None = None
    if file is not None and file.filename:
        content = await file.read()
        if len(content) > 1024 * 1024:  # stream-guard: real limit checked in service
            pass
        attachment_path, attachment_meta = upload_service.validate_and_store(
            file_name=file.filename,
            content=content,
            declared_mime=file.content_type or "",
            as_voice=as_voice,
        )
        if duration_seconds and attachment_meta is not None:
            attachment_meta["duration_seconds"] = duration_seconds

    message = await message_service.send_message(
        db,
        get_registry(),
        conversation,
        actor=auth.user,
        text=text or "",
        reply_to_message_id=reply_to_message_id,
        attachment_path=attachment_path,
        attachment_meta=attachment_meta,
        as_voice=as_voice,
    )
    await db.commit()
    payload = await _message_payload(db, message)
    return MessageOut(**payload)


# ------------------------------------------------------------------ retry
@messages_router.post("/{message_id}/retry", response_model=MessageOut)
async def retry_message(message_id: int, db: DbSession, auth: Auth):
    auth.require("message.send")
    message = (
        await db.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()
    if message is None:
        raise NotFoundError("Message not found")
    message = await message_service.retry_message(db, get_registry(), message, actor=auth.user)
    await db.commit()
    return MessageOut(**await _message_payload(db, message))


# ------------------------------------------------------------------ attachments
attachments_router = APIRouter(prefix="/attachments", tags=["attachments"])


@attachments_router.get("/{attachment_id}/download")
async def download_attachment(attachment_id: int, db: DbSession, auth: Auth):
    auth.require("attachment.download")
    attachment = (
        await db.execute(select(MessageAttachment).where(MessageAttachment.id == attachment_id))
    ).scalar_one_or_none()
    if attachment is None:
        raise NotFoundError("Attachment not found")

    message = (
        await db.execute(select(Message).where(Message.id == attachment.message_id))
    ).scalar_one()
    account_ids = await conversation_service.permitted_account_ids(db, auth.user, auth.permissions)
    await conversation_service.get_conversation(
        db, message.conversation_id, account_ids=account_ids
    )

    # Case 1: panel-uploaded file — already on disk
    if attachment.storage_path and Path(attachment.storage_path).exists():
        return FileResponse(
            Path(attachment.storage_path),
            media_type=attachment.mime_type or "application/octet-stream",
            filename=attachment.file_name or "file",
        )

    # Case 2: inbound media — lazily fetch from Eitaa (file_reference may have
    # expired; the adapter refetches the message to get a fresh one)
    if attachment.download_status in {"failed", "not_downloaded", "downloading"}:
        conversation = (
            await db.execute(
                select(Message.conversation_id).where(Message.id == attachment.message_id)
            )
        ).scalar_one()
        from app.models import Conversation

        conversation_row = (
            await db.execute(select(Conversation).where(Conversation.id == conversation))
        ).scalar_one()
        account = conversation_row.eitaa_account_id
        from app.models import EitaaAccount

        account_row = (
            await db.execute(select(EitaaAccount).where(EitaaAccount.id == account))
        ).scalar_one()

        attachment.download_status = "downloading"
        await db.commit()

        from app.core.config import settings

        settings.uploads_path.mkdir(parents=True, exist_ok=True)
        dest_dir = settings.uploads_path / f"media-{attachment.id}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            session = get_registry().session_for(account_row)
            path = await get_registry().adapter.download_message_media(
                session,
                conversation_row.peer_reference,
                message.eitaa_message_id or 0,
                dest_dir,
            )
            attachment.storage_path = str(path)
            attachment.download_status = "downloaded"
            attachment.downloaded_at = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            )
            await db.commit()
            return FileResponse(
                path,
                media_type=attachment.mime_type or "application/octet-stream",
                filename=attachment.file_name or path.name,
            )
        except Exception as exc:  # noqa: BLE001
            attachment.download_status = "failed"
            await db.commit()
            raise NotFoundError(f"Could not fetch media from Eitaa: {str(exc)[:150]}") from exc

    raise NotFoundError("Attachment content unavailable")
