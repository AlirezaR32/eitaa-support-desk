"""Agents & RBAC resolution."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permissions import ALL_PERMISSION_CODES
from app.core.security import hash_password
from app.models import EitaaAccountLink, Permission, Role, User, UserPermission
from app.services.errors import ConflictError, NotFoundError, ValidationError


async def get_role_by_name(db: AsyncSession, name: str) -> Role | None:
    return (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()


async def resolve_permissions(db: AsyncSession, user: User) -> set[str]:
    """Role permissions + per-user additive overrides."""
    codes: set[str] = set()

    # permissions granted via the user's role (role_permissions join)
    rp = Role.permissions.property.secondary
    stmt = (
        select(Permission.code)
        .join(rp, rp.c.permission_id == Permission.id)
        .where(rp.c.role_id == user.role_id)
    )
    codes.update((await db.execute(stmt)).scalars().all())

    # per-user additive overrides
    overrides = (
        (
            await db.execute(
                select(Permission.code)
                .join(UserPermission, UserPermission.permission_id == Permission.id)
                .where(UserPermission.user_id == user.id, UserPermission.granted.is_(True))
            )
        )
        .scalars()
        .all()
    )
    codes.update(overrides)
    return codes & set(ALL_PERMISSION_CODES)


async def get_agent(db: AsyncSession, agent_id: int) -> User:
    user = (
        await db.execute(
            select(User)
            .options(selectinload(User.role), selectinload(User.eitaa_account_links))
            .where(User.id == agent_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("Agent not found")
    return user


async def list_agents(
    db: AsyncSession, *, q: str | None = None, include_inactive: bool = True
) -> list[User]:
    stmt = (
        select(User)
        .options(selectinload(User.role), selectinload(User.eitaa_account_links))
        .order_by(User.id)
    )
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.name.ilike(like)) | (User.email.ilike(like)))
    return list((await db.execute(stmt)).scalars().unique().all())


async def agent_account_ids(db: AsyncSession, user_id: int) -> set[int]:
    rows = (
        (
            await db.execute(
                select(EitaaAccountLink.eitaa_account_id).where(
                    EitaaAccountLink.agent_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def create_agent(
    db: AsyncSession,
    *,
    name: str,
    email: str,
    username: str | None,
    password: str,
    role_name: str,
    is_active: bool,
    account_ids: list[int],
    actor_id: int | None = None,
) -> User:
    email_norm = email.strip().lower()
    exists = (
        await db.execute(select(func.count()).select_from(User).where(User.email == email_norm))
    ).scalar_one()
    if exists:
        raise ConflictError("An agent with this email already exists")
    role = await get_role_by_name(db, role_name)
    if role is None:
        raise ValidationError(f"Unknown role: {role_name}")
    user = User(
        name=name.strip(),
        email=email_norm,
        username=(username or None) and username.strip() or None,
        password_hash=hash_password(password),
        role_id=role.id,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    for account_id in account_ids:
        db.add(EitaaAccountLink(agent_id=user.id, eitaa_account_id=account_id))
    await db.flush()
    return user


async def update_agent(
    db: AsyncSession,
    user: User,
    *,
    name: str | None = None,
    username: str | None = None,
    email: str | None = None,
    password: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    account_ids: list[int] | None = None,
) -> User:
    if email is not None:
        email_norm = email.strip().lower()
        clash = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.email == email_norm, User.id != user.id)
            )
        ).scalar_one()
        if clash:
            raise ConflictError("Another agent already uses this email")
        user.email = email_norm
    if name is not None:
        user.name = name.strip()
    if username is not None:
        user.username = username.strip() or None
    if password:
        user.password_hash = hash_password(password)
        user.token_version += 1  # force re-login everywhere
    if role is not None:
        role_obj = await get_role_by_name(db, role)
        if role_obj is None:
            raise ValidationError(f"Unknown role: {role}")
        user.role_id = role_obj.id
    if is_active is not None:
        user.is_active = is_active
        if not is_active:
            user.token_version += 1
    if account_ids is not None:
        await db.execute(
            EitaaAccountLink.__table__.delete().where(EitaaAccountLink.agent_id == user.id)
        )
        for account_id in account_ids:
            db.add(EitaaAccountLink(agent_id=user.id, eitaa_account_id=account_id))
    await db.flush()
    return user
