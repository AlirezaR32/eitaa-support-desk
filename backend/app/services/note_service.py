"""Internal notes (never sent to Eitaa) + notifications + dashboard stats."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import bus
from app.models import (
    AnswerState,
    Conversation,
    ConversationStatus,
    InternalNote,
    Notification,
    User,
)
from app.services import audit_service
from app.services.errors import ForbiddenError, NotFoundError


# ------------------------------------------------------------------ notes
async def add_note(
    db: AsyncSession, conversation: Conversation, *, author: User, body: str
) -> InternalNote:
    note = InternalNote(conversation_id=conversation.id, author_id=author.id, body=body.strip())
    db.add(note)
    await db.flush()
    await audit_service.record(
        db,
        action=audit_service.NOTE_ADDED,
        actor_id=author.id,
        actor_name=author.name,
        target_type="conversation",
        target_id=conversation.id,
    )
    return note


async def delete_note(db: AsyncSession, note_id: int, *, actor: User, is_manager: bool) -> None:
    note = (
        await db.execute(select(InternalNote).where(InternalNote.id == note_id))
    ).scalar_one_or_none()
    if note is None:
        raise NotFoundError("Note not found")
    if note.author_id != actor.id and not is_manager:
        raise ForbiddenError("You can only delete your own notes")
    await db.delete(note)
    await audit_service.record(
        db,
        action=audit_service.NOTE_DELETED,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="note",
        target_id=note_id,
    )


async def list_notes(db: AsyncSession, conversation_id: int) -> list[InternalNote]:
    return list(
        (
            await db.execute(
                select(InternalNote)
                .where(InternalNote.conversation_id == conversation_id)
                .order_by(InternalNote.created_at.asc(), InternalNote.id.asc())
            )
        )
        .scalars()
        .unique()
        .all()
    )


# ------------------------------------------------------------------ notifications
async def notify_unanswered_conversations(db: AsyncSession, *, older_than_seconds: int) -> int:
    """Create deduplicated 'unanswered' notifications. Returns rows created.

    Dedup key = unanswered:{conversation_id}:{last inbound eitaa message id},
    so one notification per conversation per user-message, never duplicates (§20).
    """
    threshold = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    candidates = list(
        (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.answer_state == AnswerState.UNANSWERED,
                    Conversation.status == ConversationStatus.ACTIVE,
                    Conversation.last_inbound_message_at.is_not(None),
                    Conversation.last_inbound_message_at < threshold,
                )
                .limit(200)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    created = 0
    for conversation in candidates:
        dedupe_key = f"unanswered:{conversation.id}:{conversation.last_message_id}"
        recipients: list[User] = []
        if conversation.assigned_agent_id is not None:
            assignee = (
                await db.execute(
                    select(User).where(
                        User.id == conversation.assigned_agent_id, User.is_active.is_(True)
                    )
                )
            ).scalar_one_or_none()
            if assignee is not None:
                recipients.append(assignee)
        else:
            # unassigned -> alert users who oversee everything (admins & owner)
            from app.models import Role

            recipients = list(
                (
                    await db.execute(
                        select(User)
                        .join(Role, Role.id == User.role_id)
                        .where(User.is_active.is_(True), Role.name.in_(["admin", "owner"]))
                    )
                )
                .scalars()
                .unique()
                .all()
            )
        for user in recipients:
            existing = (
                await db.execute(
                    select(func.count())
                    .select_from(Notification)
                    .where(
                        Notification.user_id == user.id,
                        Notification.dedupe_key == dedupe_key,
                    )
                )
            ).scalar_one()
            if existing:
                continue
            db.add(
                Notification(
                    user_id=user.id,
                    type="unanswered_conversation",
                    conversation_id=conversation.id,
                    title="گفتگوی بدون پاسخ",
                    body=f"«{conversation.title}» هنوز پاسخ داده نشده است.",
                    dedupe_key=dedupe_key,
                )
            )
            created += 1
            await bus.publish(
                "notification.created",
                {
                    "type": "unanswered_conversation",
                    "conversation_id": conversation.id,
                    "title": "گفتگوی بدون پاسخ",
                    "body": f"«{conversation.title}» هنوز پاسخ داده نشده است.",
                },
                target_user_ids={user.id},
            )
    if created:
        await db.flush()
    return created


async def list_notifications(
    db: AsyncSession, user_id: int, *, unread_only: bool = False, page: int = 1, page_size: int = 30
) -> tuple[list[Notification], int]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return list(rows), total


async def unread_count(db: AsyncSession, user_id: int) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        )
    ).scalar_one()


async def mark_notification_read(db: AsyncSession, user_id: int, notification_id: int) -> None:
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Notification not found")
    row.is_read = True
    row.read_at = datetime.now(timezone.utc)


async def mark_all_read(db: AsyncSession, user_id: int) -> None:
    rows = list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.user_id == user_id, Notification.is_read.is_(False)
                )
            )
        )
        .scalars()
        .unique()
        .all()
    )
    for row in rows:
        row.is_read = True
        row.read_at = datetime.now(timezone.utc)
