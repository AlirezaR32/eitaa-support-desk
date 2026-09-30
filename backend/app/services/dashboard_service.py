"""Dashboard statistics — computed exclusively from real database rows (§21)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnswerState, Conversation, ConversationStatus, Message, ReadState, User


async def dashboard_stats(db: AsyncSession, *, viewer: User, account_ids: set[int] | None) -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = now - timedelta(hours=24)

    async def _count(*conditions) -> int:
        stmt = select(func.count()).select_from(Conversation)
        if account_ids is not None:
            stmt = stmt.where(Conversation.eitaa_account_id.in_(account_ids))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        return (await db.execute(stmt)).scalar_one()

    unread = await _count(Conversation.read_state == ReadState.UNREAD)
    unanswered = await _count(
        Conversation.answer_state == AnswerState.UNANSWERED,
        Conversation.status != ConversationStatus.CLOSED,
    )
    answered_today = await _count(
        Conversation.last_outbound_message_at >= today_start,
        Conversation.answer_state == AnswerState.ANSWERED,
    )
    waiting_user = await _count(Conversation.status == ConversationStatus.WAITING_USER)
    skipped = await _count(Conversation.status == ConversationStatus.SKIPPED)
    closed = await _count(Conversation.status == ConversationStatus.CLOSED)
    mine = await _count(Conversation.assigned_agent_id == viewer.id)
    unassigned = await _count(Conversation.assigned_agent_id.is_(None))
    total = await _count()

    # average first response: first_agent_reply_at - first_inbound_at
    avg_response_row = (
        await db.execute(
            select(
                func.avg(
                    func.extract(
                        "epoch", Conversation.first_agent_reply_at - Conversation.first_inbound_at
                    )
                )
            ).where(
                Conversation.first_agent_reply_at.is_not(None),
                Conversation.first_inbound_at.is_not(None),
            )
        )
    ).scalar_one()
    avg_resolution_row = (
        await db.execute(
            select(
                func.avg(func.extract("epoch", Conversation.closed_at - Conversation.created_at))
            ).where(Conversation.closed_at.is_not(None))
        )
    ).scalar_one()

    messages_today_stmt = (
        select(func.count()).select_from(Message).where(Message.sent_at >= today_start)
    )
    if account_ids is not None:
        messages_today_stmt = messages_today_stmt.where(
            Message.conversation_id.in_(
                select(Conversation.id).where(Conversation.eitaa_account_id.in_(account_ids))
            )
        )
    messages_today = (await db.execute(messages_today_stmt)).scalar_one()

    active_agents = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.is_active.is_(True), User.last_login_at >= yesterday)
        )
    ).scalar_one()

    return {
        "unread": unread,
        "unanswered": unanswered,
        "answered_today": answered_today,
        "waiting_user": waiting_user,
        "skipped": skipped,
        "closed": closed,
        "my_conversations": mine,
        "unassigned": unassigned,
        "total_conversations": total,
        "avg_first_response_seconds": round(float(avg_response_row), 1)
        if avg_response_row
        else None,
        "avg_resolution_seconds": round(float(avg_resolution_row), 1)
        if avg_resolution_row
        else None,
        "messages_today": messages_today,
        "active_agents": active_agents,
    }
