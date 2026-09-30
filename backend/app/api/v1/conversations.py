"""Conversation endpoints: inbox, filters, actions (read/claim/assign/skip/close)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import Auth, DbSession, PageParams
from app.schemas.common import (
    AssignRequest,
    ConversationDetail,
    ConversationOut,
    NoteCreate,
    NoteOut,
    Page,
    SkipRequest,
)
from app.services import (
    conversation_service,
    note_service,
    serializer,
)
from app.services.errors import ForbiddenError

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _visible_account_ids(db, auth) -> set[int] | None:
    return conversation_service.permitted_account_ids(db, auth.user, auth.permissions)


async def _to_out(
    db, conversation, account_phones: dict[int, str] | None = None
) -> ConversationOut:
    payload = await serializer.conversation_payload(db, conversation)
    return ConversationOut(**payload)


@router.get("", response_model=Page)
async def list_conversations(
    db: DbSession,
    auth: Auth,
    page_params: PageParams,
    q: str | None = None,
    status: list[str] | None = Query(default=None),
    read_state: str | None = None,
    answer_state: str | None = None,
    assigned: str | None = None,
    account_id: int | None = None,
    peer_kind: str | None = None,
    sort: str = "recent",
):
    if not (auth.has("conversation.view.all") or auth.has("conversation.view.account")):
        raise ForbiddenError("No conversation access")
    account_ids = await _visible_account_ids(db, auth)
    rows, total = await conversation_service.list_conversations(
        db,
        account_ids=account_ids,
        q=q,
        status=status,
        read_state=read_state,
        answer_state=answer_state,
        assigned=assigned,
        current_user=auth.user,
        account_id=account_id,
        peer_kind=peer_kind,
        sort=sort,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    phones = await _account_phones(db, rows)
    items = []
    for conversation in rows:
        item = ConversationOut(
            **{
                k: v
                for k, v in (await serializer.conversation_payload(db, conversation)).items()
                if k in ConversationOut.model_fields
            }
        )
        item.eitaa_account_phone = phones.get(conversation.eitaa_account_id)
        items.append(item)
    return Page(
        items=items,
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
        pages=max(1, -(-total // page_params.page_size)),
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: int, db: DbSession, auth: Auth):
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    payload = await serializer.conversation_payload(db, conversation)
    payload.pop("deep_link", None)
    previous = await conversation_service.previous_conversations(db, conversation)
    return ConversationDetail(
        **payload,
        deep_link=conversation.deep_link,
        first_inbound_at=conversation.first_inbound_at,
        first_agent_reply_at=conversation.first_agent_reply_at,
        closed_at=conversation.closed_at,
        previous_conversations=[
            ConversationOut(**await serializer.conversation_payload(db, p)) for p in previous
        ],
    )


@router.post("/{conversation_id}/read", response_model=ConversationOut)
async def mark_read(conversation_id: int, db: DbSession, auth: Auth):
    auth.require("conversation.read.mark")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    await conversation_service.mark_read(
        db, conversation, actor=auth.user, permissions=auth.permissions
    )
    await db.commit()
    return ConversationOut(**await serializer.conversation_payload(db, conversation))


@router.post("/{conversation_id}/claim", response_model=ConversationOut)
async def claim(conversation_id: int, db: DbSession, auth: Auth):
    auth.require("conversation.claim")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    await conversation_service.claim(db, conversation, actor=auth.user)
    await db.commit()
    return ConversationOut(**await serializer.conversation_payload(db, conversation))


@router.post("/{conversation_id}/release", response_model=ConversationOut)
async def release(conversation_id: int, db: DbSession, auth: Auth):
    auth.require("conversation.release")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    await conversation_service.release(
        db, conversation, actor=auth.user, permissions=auth.permissions
    )
    await db.commit()
    return ConversationOut(**await serializer.conversation_payload(db, conversation))


@router.post("/{conversation_id}/assign", response_model=ConversationOut)
async def assign(conversation_id: int, body: AssignRequest, db: DbSession, auth: Auth):
    auth.require("conversation.assign")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    await conversation_service.assign(
        db, conversation, target_agent_id=body.agent_id, actor=auth.user
    )
    await db.commit()
    return ConversationOut(**await serializer.conversation_payload(db, conversation))


@router.post("/{conversation_id}/skip", response_model=ConversationOut)
async def skip(conversation_id: int, body: SkipRequest, db: DbSession, auth: Auth):
    auth.require("conversation.skip")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    await conversation_service.skip(
        db, conversation, actor=auth.user, reason=body.reason, note=body.note
    )
    await db.commit()
    return ConversationOut(**await serializer.conversation_payload(db, conversation))


@router.post("/{conversation_id}/close", response_model=ConversationOut)
async def close(conversation_id: int, db: DbSession, auth: Auth):
    auth.require("conversation.status.manage")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    await conversation_service.close(db, conversation, actor=auth.user)
    await db.commit()
    return ConversationOut(**await serializer.conversation_payload(db, conversation))


@router.post("/{conversation_id}/reopen", response_model=ConversationOut)
async def reopen(conversation_id: int, db: DbSession, auth: Auth):
    auth.require("conversation.status.manage")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    await conversation_service.reopen(db, conversation, actor=auth.user)
    await db.commit()
    return ConversationOut(**await serializer.conversation_payload(db, conversation))


@router.post("/{conversation_id}/waiting-user", response_model=ConversationOut)
async def set_waiting_user(conversation_id: int, db: DbSession, auth: Auth):
    auth.require("conversation.status.manage")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    await conversation_service.set_waiting_user(db, conversation, actor=auth.user)
    await db.commit()
    return ConversationOut(**await serializer.conversation_payload(db, conversation))


# ------------------------------------------------------------------ notes
@router.get("/{conversation_id}/notes", response_model=list[NoteOut])
async def list_notes(conversation_id: int, db: DbSession, auth: Auth):
    auth.require("note.create")
    account_ids = await _visible_account_ids(db, auth)
    await conversation_service.get_conversation(db, conversation_id, account_ids=account_ids)
    notes = await note_service.list_notes(db, conversation_id)

    from sqlalchemy import select

    from app.models import User

    authors = {
        u.id: u.name
        for u in (
            await db.execute(
                select(User).where(User.id.in_({n.author_id for n in notes if n.author_id}))
            )
        )
        .scalars()
        .all()
    }
    return [
        NoteOut(
            id=n.id,
            conversation_id=n.conversation_id,
            author_id=n.author_id,
            author_name=authors.get(n.author_id) if n.author_id else None,
            body=n.body,
            created_at=n.created_at,
        )
        for n in notes
    ]


@router.post("/{conversation_id}/notes", response_model=NoteOut, status_code=201)
async def add_note(conversation_id: int, body: NoteCreate, db: DbSession, auth: Auth):
    auth.require("note.create")
    account_ids = await _visible_account_ids(db, auth)
    conversation = await conversation_service.get_conversation(
        db, conversation_id, account_ids=account_ids
    )
    note = await note_service.add_note(db, conversation, author=auth.user, body=body.body)
    await db.commit()
    return NoteOut(
        id=note.id,
        conversation_id=note.conversation_id,
        author_id=note.author_id,
        author_name=auth.user.name,
        body=note.body,
        created_at=note.created_at,
    )


async def _account_phones(db, rows) -> dict[int, str]:
    from sqlalchemy import select

    from app.models import EitaaAccount

    ids = {c.eitaa_account_id for c in rows}
    if not ids:
        return {}
    result = await db.execute(
        select(EitaaAccount.id, EitaaAccount.phone_number).where(EitaaAccount.id.in_(ids))
    )
    return {row[0]: row[1] for row in result.all()}
