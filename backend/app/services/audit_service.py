"""Audit logging service — every important action lands here (§25)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import sanitize_value
from app.models import AuditLog

# Canonical action names
AGENT_LOGIN = "AGENT_LOGIN"
AGENT_LOGIN_FAILED = "AGENT_LOGIN_FAILED"
AGENT_LOGOUT = "AGENT_LOGOUT"
AGENT_CREATED = "AGENT_CREATED"
AGENT_UPDATED = "AGENT_UPDATED"
AGENT_DISABLED = "AGENT_DISABLED"
AGENT_ENABLED = "AGENT_ENABLED"
CONVERSATION_CLAIMED = "CONVERSATION_CLAIMED"
CONVERSATION_RELEASED = "CONVERSATION_RELEASED"
CONVERSATION_ASSIGNED = "CONVERSATION_ASSIGNED"
CONVERSATION_SKIPPED = "CONVERSATION_SKIPPED"
CONVERSATION_CLOSED = "CONVERSATION_CLOSED"
CONVERSATION_REOPENED = "CONVERSATION_REOPENED"
CONVERSATION_WAITING_USER = "CONVERSATION_WAITING_USER"
CONVERSATION_READ = "CONVERSATION_READ"
MESSAGE_SENT = "MESSAGE_SENT"
MESSAGE_FAILED = "MESSAGE_FAILED"
MESSAGE_RETRIED = "MESSAGE_RETRIED"
NOTE_ADDED = "NOTE_ADDED"
NOTE_DELETED = "NOTE_DELETED"
EITAA_ACCOUNT_CONNECTED = "EITAA_ACCOUNT_CONNECTED"
EITAA_ACCOUNT_DISCONNECTED = "EITAA_ACCOUNT_DISCONNECTED"
EITAA_ACCOUNT_UPDATED = "EITAA_ACCOUNT_UPDATED"
EITAA_SYNC_FAILED = "EITAA_SYNC_FAILED"
PASSWORD_CHANGED = "PASSWORD_CHANGED"
LOGIN_CHALLENGE_REQUESTED = "LOGIN_CHALLENGE_REQUESTED"


async def record(
    db: AsyncSession,
    *,
    action: str,
    actor_id: int | None = None,
    actor_name: str = "",
    target_type: str | None = None,
    target_id: Any = None,
    meta: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Persist an audit entry. `meta` is sanitized — tokens/OTPs never land here."""
    entry = AuditLog(
        actor_id=actor_id,
        actor_name=actor_name or "",
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        meta=sanitize_value(meta or {}) if meta else None,
        ip=ip,
        user_agent=(user_agent[:250] if user_agent else None),
    )
    db.add(entry)
    # caller commits with the request transaction


async def list_logs(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 50,
    actor_id: int | None = None,
    action: str | None = None,
    q: str | None = None,
) -> tuple[list[AuditLog], int]:
    stmt: Select = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if q:
        stmt = stmt.where(AuditLog.actor_name.ilike(f"%{q}%"))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (await db.execute(stmt.limit(page_size).offset((page - 1) * page_size)))
        .scalars()
        .unique()
        .all()
    )
    return list(rows), total
