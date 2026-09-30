"""Notifications, dashboard, audit logs, capabilities, health."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Auth, AuthContext, DbSession, PageParams, require
from app.schemas.common import (
    AuditLogOut,
    Capabilities,
    DashboardStats,
    NotificationOut,
    Page,
    UnreadCount,
)
from app.services import audit_service, conversation_service, dashboard_service, note_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page)
async def list_notifications(db: DbSession, auth: Auth, page_params: PageParams):
    auth.require("notification.view")
    rows, total = await note_service.list_notifications(
        db, auth.user.id, page=page_params.page, page_size=page_params.page_size
    )
    return Page(
        items=[NotificationOut.model_validate(n) for n in rows],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
        pages=max(1, -(-total // page_params.page_size)),
    )


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(db: DbSession, auth: Auth):
    auth.require("notification.view")
    return UnreadCount(count=await note_service.unread_count(db, auth.user.id))


@router.post("/read-all")
async def read_all(db: DbSession, auth: Auth):
    auth.require("notification.view")
    await note_service.mark_all_read(db, auth.user.id)
    await db.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
async def read_one(notification_id: int, db: DbSession, auth: Auth):
    auth.require("notification.view")
    await note_service.mark_notification_read(db, auth.user.id, notification_id)
    await db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ dashboard
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@dashboard_router.get("/stats", response_model=DashboardStats)
async def stats(db: DbSession, auth: Auth):
    if not (auth.has("dashboard.view") or auth.has("dashboard.view.own")):
        from app.services.errors import ForbiddenError

        raise ForbiddenError("No dashboard access")
    account_ids = await conversation_service.permitted_account_ids(db, auth.user, auth.permissions)
    return DashboardStats(
        **await dashboard_service.dashboard_stats(db, viewer=auth.user, account_ids=account_ids)
    )


# ------------------------------------------------------------------ audit logs
audit_router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@audit_router.get("", response_model=Page)
async def list_audit_logs(
    db: DbSession,
    page_params: PageParams,
    auth: AuthContext = Depends(require("audit.view")),
    actor_id: int | None = None,
    action: str | None = None,
    q: str | None = None,
):
    rows, total = await audit_service.list_logs(
        db,
        page=page_params.page,
        page_size=page_params.page_size,
        actor_id=actor_id,
        action=action,
        q=q,
    )
    return Page(
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
        pages=max(1, -(-total // page_params.page_size)),
    )


# ------------------------------------------------------------------ capabilities
capabilities_router = APIRouter(prefix="/capabilities", tags=["meta"])


@capabilities_router.get("", response_model=Capabilities)
async def capabilities():
    from app.core.config import settings

    return Capabilities(
        sync_interval_seconds=settings.eitaa_sync_interval,
        max_upload_size_mb=settings.max_upload_size_mb,
        allowed_extensions=sorted(settings.allowed_extension_list),
    )
