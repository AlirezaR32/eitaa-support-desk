"""Agents management endpoints (RBAC-guarded)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import AuthContext, DbSession, PageParams, require
from app.schemas.common import AgentCreate, AgentOut, AgentUpdate, Page, RoleOut
from app.services import agent_service, audit_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/agents", tags=["agents"])


async def _to_out(db, user, permissions: set[str], account_ids: set[int]) -> AgentOut:
    from sqlalchemy import select

    from app.models import Role

    if "role" in user.__dict__ and user.role is not None:
        role_name = user.role.name
    else:
        role_name = (
            await db.execute(select(Role.name).where(Role.id == user.role_id))
        ).scalar_one_or_none()
    return AgentOut(
        id=user.id,
        name=user.name,
        username=user.username,
        email=user.email,
        role=role_name or "",
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        permissions=sorted(permissions),
        eitaa_account_ids=sorted(account_ids),
    )


@router.get("", response_model=Page)
async def list_agents(
    db: DbSession,
    auth: AuthContext = Depends(require("agent.view")),
    q: str | None = None,
    include_inactive: bool = True,
    page_params: PageParams = None,
):
    users = await agent_service.list_agents(db, q=q, include_inactive=include_inactive)
    items = [
        await _to_out(
            db,
            user,
            await agent_service.resolve_permissions(db, user),
            await agent_service.agent_account_ids(db, user.id),
        )
        for user in users
    ]
    start = (page_params.page - 1) * page_params.page_size
    items_page = items[start : start + page_params.page_size]
    return Page(
        items=items_page,
        total=len(items),
        page=page_params.page,
        page_size=page_params.page_size,
        pages=max(1, -(-len(items) // page_params.page_size)),
    )


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(db: DbSession, auth: AuthContext = Depends(require("agent.view"))):
    from sqlalchemy import select

    from app.models import Role

    roles = (await db.execute(select(Role).order_by(Role.id))).scalars().unique().all()
    return [RoleOut(id=r.id, name=r.name, description=r.description) for r in roles]


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(
    body: AgentCreate,
    db: DbSession,
    auth: AuthContext = Depends(require("agent.manage")),
):
    # only the owner may mint owners
    if body.role == "owner" and auth.user.role_name != "owner":
        raise ValidationError("Only an Owner can create another Owner")
    user = await agent_service.create_agent(
        db,
        name=body.name,
        email=body.email,
        username=body.username,
        password=body.password,
        role_name=body.role,
        is_active=body.is_active,
        account_ids=body.eitaa_account_ids,
    )
    await audit_service.record(
        db,
        action=audit_service.AGENT_CREATED,
        actor_id=auth.user.id,
        actor_name=auth.user.name,
        target_type="agent",
        target_id=user.id,
        meta={"role": body.role},
    )
    await db.commit()
    permissions = await agent_service.resolve_permissions(db, user)
    account_ids = await agent_service.agent_account_ids(db, user.id)
    return await _to_out(db, user, permissions, account_ids)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: int,
    db: DbSession,
    auth: AuthContext = Depends(require("agent.view")),
):
    user = await agent_service.get_agent(db, agent_id)
    permissions = await agent_service.resolve_permissions(db, user)
    account_ids = await agent_service.agent_account_ids(db, user.id)
    return await _to_out(db, user, permissions, account_ids)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: int,
    body: AgentUpdate,
    db: DbSession,
    auth: AuthContext = Depends(require("agent.manage")),
):
    user = await agent_service.get_agent(db, agent_id)
    if user.role_name == "owner" and auth.user.role_name != "owner":
        raise ValidationError("Only an Owner can modify an Owner")
    was_active = user.is_active
    user = await agent_service.update_agent(
        db,
        user,
        name=body.name,
        username=body.username,
        email=body.email,
        password=body.password,
        role=body.role,
        is_active=body.is_active,
        account_ids=body.eitaa_account_ids,
    )
    await audit_service.record(
        db,
        action=audit_service.AGENT_UPDATED,
        actor_id=auth.user.id,
        actor_name=auth.user.name,
        target_type="agent",
        target_id=user.id,
        meta={"disabled": was_active and body.is_active is False},
    )
    await db.commit()
    permissions = await agent_service.resolve_permissions(db, user)
    account_ids = await agent_service.agent_account_ids(db, user.id)
    return await _to_out(db, user, permissions, account_ids)


@router.delete("/{agent_id}", status_code=200)
async def deactivate_agent(
    agent_id: int,
    db: DbSession,
    auth: AuthContext = Depends(require("agent.manage")),
):
    """Soft-delete: agents are deactivated, never removed (audit integrity)."""
    user = await agent_service.get_agent(db, agent_id)
    if user.id == auth.user.id:
        raise ValidationError("You cannot deactivate your own account")
    if user.role_name == "owner" and auth.user.role_name != "owner":
        raise ValidationError("Only an Owner can deactivate an Owner")
    user = await agent_service.update_agent(db, user, is_active=False)
    await audit_service.record(
        db,
        action=audit_service.AGENT_DISABLED,
        actor_id=auth.user.id,
        actor_name=auth.user.name,
        target_type="agent",
        target_id=user.id,
    )
    await db.commit()
    return {"ok": True, "deactivated": user.id}
