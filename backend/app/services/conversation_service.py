"""Conversation domain: inbox queries, visibility, the READ/UNANSWERED state
machine, and race-free assignment operations.

State machine (server-side, never trusted to the frontend):

    user sends message      -> read_state=UNREAD   answer_state=UNANSWERED
    agent opens thread      -> read_state=READ     (answer_state unchanged!)
    agent replies           -> answer_state=ANSWERED
    agent asks user sth     -> status=WAITING_USER
    agent skips             -> status=SKIPPED (+ skipped_by/at/reason)
    conversation finished   -> status=CLOSED (+ closed_by/at)

The canonical "UNANSWERED" filter = answer_state == 'unanswered' (last message
is from the user), INDEPENDENT of read_state. An opened-but-unanswered thread
stays READ + UNANSWERED (spec §11, §38).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy import column as _column
from sqlalchemy import table as _sa_table
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import bus
from app.models import (
    AnswerState,
    Conversation,
    ConversationStatus,
    EitaaAccount,
    EitaaAccountLink,
    InternalNote,
    ReadState,
    User,
)
from app.services import audit_service
from app.services.errors import ConflictError, ForbiddenError, NotFoundError


# ------------------------------------------------------------------ visibility
async def permitted_account_ids(
    db: AsyncSession, user: User, permissions: set[str]
) -> set[int] | None:
    """None = may see ALL accounts (conversation.view.all); otherwise a set of ids."""
    if "conversation.view.all" in permissions:
        return None
    rows = (
        (
            await db.execute(
                select(EitaaAccountLink.eitaa_account_id).where(
                    EitaaAccountLink.agent_id == user.id
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


def _scope(stmt: Select, account_ids: set[int] | None) -> Select:
    if account_ids is None:
        return stmt
    return stmt.where(Conversation.eitaa_account_id.in_(account_ids))


# ------------------------------------------------------------------ queries
async def list_conversations(
    db: AsyncSession,
    *,
    account_ids: set[int] | None,
    q: str | None = None,
    status: list[str] | None = None,
    read_state: str | None = None,
    answer_state: str | None = None,
    assigned: str | None = None,  # me | unassigned | all | agent:<id>
    current_user: User | None = None,
    account_id: int | None = None,
    peer_kind: str | None = None,
    sort: str = "recent",  # recent | oldest | unread_first
    page: int = 1,
    page_size: int = 30,
) -> tuple[list[Conversation], int]:
    stmt = select(Conversation)
    stmt = _scope(stmt, account_ids)

    if status:
        valid = {s.value for s in ConversationStatus}
        wanted = [s for s in status if s in valid]
        if wanted:
            stmt = stmt.where(Conversation.status.in_(wanted))
    if read_state in {"unread", "read"}:
        stmt = stmt.where(Conversation.read_state == ReadState(read_state))
    if answer_state in {"unanswered", "answered"}:
        stmt = stmt.where(Conversation.answer_state == AnswerState(answer_state))
    if assigned == "me" and current_user is not None:
        stmt = stmt.where(Conversation.assigned_agent_id == current_user.id)
    elif assigned == "unassigned":
        stmt = stmt.where(Conversation.assigned_agent_id.is_(None))
    elif assigned and assigned.startswith("agent:"):
        try:
            stmt = stmt.where(Conversation.assigned_agent_id == int(assigned.split(":", 1)[1]))
        except ValueError:
            pass
    if account_id is not None:
        stmt = stmt.where(Conversation.eitaa_account_id == account_id)
    if peer_kind:
        stmt = stmt.where(Conversation.peer_kind == peer_kind)
    if q:
        like = f"%{q.strip()}%"
        conditions = [
            Conversation.title.ilike(like),
            Conversation.username.ilike(like),
            Conversation.phone.ilike(like),
        ]
        # search by conversation id or peer id when the query is numeric (§22)
        if q.strip().isdigit():
            conditions.append(Conversation.id == int(q.strip()))
            conditions.append(Conversation.peer_id == int(q.strip()))
        # message-text search (§22)
        conditions.append(
            Conversation.id.in_(
                select(func.distinct(_messages_table.c.conversation_id)).where(
                    _messages_table.c.text.ilike(like)
                )
            )
        )
        stmt = stmt.where(or_(*conditions))

    order = {
        "recent": Conversation.last_message_at.desc().nullslast(),
        "oldest": Conversation.last_message_at.asc().nullsfirst(),
        "unread_first": Conversation.read_state.asc(),  # unread < read alphabetically
    }.get(sort, Conversation.last_message_at.desc().nullslast())
    stmt = stmt.order_by(order, Conversation.id.desc())

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (await db.execute(stmt.limit(page_size).offset((page - 1) * page_size)))
        .scalars()
        .unique()
        .all()
    )
    return list(rows), total


async def get_conversation(
    db: AsyncSession, conversation_id: int, *, account_ids: set[int] | None
) -> Conversation:
    conversation = (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if conversation is None:
        raise NotFoundError("Conversation not found")
    if account_ids is not None and conversation.eitaa_account_id not in account_ids:
        raise ForbiddenError("You do not have access to this conversation")
    return conversation


async def previous_conversations(
    db: AsyncSession, conversation: Conversation
) -> list[Conversation]:
    """Other threads of the same Eitaa peer (across accounts) — spec §23."""
    return list(
        (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.peer_id == conversation.peer_id,
                    Conversation.peer_type == conversation.peer_type,
                    Conversation.id != conversation.id,
                )
                .order_by(Conversation.last_message_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .unique()
        .all()
    )


# ------------------------------------------------------------------ state ops
async def mark_read(
    db: AsyncSession,
    conversation: Conversation,
    *,
    actor: User,
    permissions: set[str],
    peer_max_message_id: int | None = None,
) -> Conversation:
    """Agent opened the thread: UNREAD -> READ. answer_state is NOT touched."""
    if conversation.read_state == ReadState.READ:
        return conversation
    conversation.read_state = ReadState.READ
    await audit_service.record(
        db,
        action=audit_service.CONVERSATION_READ,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="conversation",
        target_id=conversation.id,
    )
    # best-effort: also clear unread badge inside the Eitaa account
    if peer_max_message_id:
        from app.eitaa.registry import get_registry

        try:
            session = get_registry().session_for(
                await _account_of(db, conversation.eitaa_account_id)
            )
            await get_registry().adapter.mark_read(
                session, conversation.peer_reference, peer_max_message_id
            )
            conversation.unread_eitaa_count = 0
        except Exception:  # noqa: BLE001 — best effort only, never fail the request
            pass
    await _publish_conversation(db, conversation)
    return conversation


async def claim(db: AsyncSession, conversation: Conversation, *, actor: User) -> Conversation:
    """Atomically claim an UNASSIGNED conversation.

    The UPDATE ... WHERE assigned_agent_id IS NULL guard makes double-claim
    impossible at the database level: exactly one concurrent request wins,
    every other request sees the conversation already taken (HTTP 409).
    """
    result = await db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation.id,
            Conversation.assigned_agent_id.is_(None),  # the atomic guard
        )
        .values(
            assigned_agent_id=actor.id,
            assigned_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount == 0:
        await db.refresh(conversation)
        current = conversation.assigned_agent_id
        raise ConflictError(
            "This conversation was just claimed by another agent"
            if current is not None and current != actor.id
            else "Conversation could not be claimed"
        )
    await db.refresh(conversation)
    await audit_service.record(
        db,
        action=audit_service.CONVERSATION_CLAIMED,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="conversation",
        target_id=conversation.id,
    )
    await _publish_conversation(db, conversation)
    return conversation


async def release(
    db: AsyncSession, conversation: Conversation, *, actor: User, permissions: set[str]
) -> Conversation:
    if conversation.assigned_agent_id is None:
        return conversation
    if conversation.assigned_agent_id != actor.id and "conversation.assign" not in permissions:
        raise ForbiddenError("Only the assignee or a manager can release this conversation")
    conversation.assigned_agent_id = None
    conversation.assigned_at = None
    await audit_service.record(
        db,
        action=audit_service.CONVERSATION_RELEASED,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="conversation",
        target_id=conversation.id,
    )
    await _publish_conversation(db, conversation)
    return conversation


async def assign(
    db: AsyncSession,
    conversation: Conversation,
    *,
    target_agent_id: int | None,
    actor: User,
) -> Conversation:
    """Assign / reassign / take over — requires conversation.assign permission."""
    if target_agent_id is not None:
        target = (
            await db.execute(select(User).where(User.id == target_agent_id))
        ).scalar_one_or_none()
        if target is None or not target.is_active:
            raise NotFoundError("Target agent not found or inactive")
    previous = conversation.assigned_agent_id
    conversation.assigned_agent_id = target_agent_id
    conversation.assigned_at = datetime.now(timezone.utc) if target_agent_id else None
    await audit_service.record(
        db,
        action=audit_service.CONVERSATION_ASSIGNED,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="conversation",
        target_id=conversation.id,
        meta={"from_agent_id": previous, "to_agent_id": target_agent_id},
    )
    await _publish_conversation(db, conversation)
    return conversation


async def skip(
    db: AsyncSession,
    conversation: Conversation,
    *,
    actor: User,
    reason: str,
    note: str | None = None,
) -> Conversation:
    conversation.status = ConversationStatus.SKIPPED
    conversation.skipped_by_id = actor.id
    conversation.skipped_at = datetime.now(timezone.utc)
    conversation.skip_reason = reason
    if note:
        db.add(
            InternalNote(
                conversation_id=conversation.id,
                author_id=actor.id,
                body=f"[skip:{reason}] {note}",
            )
        )
    await audit_service.record(
        db,
        action=audit_service.CONVERSATION_SKIPPED,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="conversation",
        target_id=conversation.id,
        meta={"reason": reason},
    )
    await _publish_conversation(db, conversation)
    return conversation


async def close(db: AsyncSession, conversation: Conversation, *, actor: User) -> Conversation:
    if conversation.status == ConversationStatus.CLOSED:
        return conversation
    conversation.status = ConversationStatus.CLOSED
    conversation.closed_at = datetime.now(timezone.utc)
    conversation.closed_by_id = actor.id
    await audit_service.record(
        db,
        action=audit_service.CONVERSATION_CLOSED,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="conversation",
        target_id=conversation.id,
    )
    await _publish_conversation(db, conversation)
    return conversation


async def reopen(db: AsyncSession, conversation: Conversation, *, actor: User) -> Conversation:
    if conversation.status != ConversationStatus.CLOSED:
        return conversation
    conversation.status = ConversationStatus.ACTIVE
    conversation.closed_at = None
    conversation.closed_by_id = None
    conversation.skip_reason = None
    await audit_service.record(
        db,
        action=audit_service.CONVERSATION_REOPENED,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="conversation",
        target_id=conversation.id,
    )
    await _publish_conversation(db, conversation)
    return conversation


async def set_waiting_user(
    db: AsyncSession, conversation: Conversation, *, actor: User
) -> Conversation:
    conversation.status = ConversationStatus.WAITING_USER
    await audit_service.record(
        db,
        action=audit_service.CONVERSATION_WAITING_USER,
        actor_id=actor.id,
        actor_name=actor.name,
        target_type="conversation",
        target_id=conversation.id,
    )
    await _publish_conversation(db, conversation)
    return conversation


# ------------------------------------------------------------------ helpers
_messages_table = _sa_table("messages", _column("conversation_id"), _column("text"))


async def _account_of(db: AsyncSession, account_id: int) -> EitaaAccount:
    return (
        await db.execute(select(EitaaAccount).where(EitaaAccount.id == account_id))
    ).scalar_one()


async def _publish_conversation(db: AsyncSession, conversation: Conversation) -> None:
    from app.services.serializer import conversation_payload

    await bus.publish(
        "conversation.updated",
        await conversation_payload(db, conversation),
        account_id=conversation.eitaa_account_id,
        conversation_id=conversation.id,
    )
