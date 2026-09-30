"""Authentication: login, JWT issue, refresh rotation with reuse detection."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.models import RefreshToken, User
from app.services import agent_service, audit_service
from app.services.errors import AuthenticationError, ValidationError


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User:
    user = (
        await db.execute(
            select(User)
            .options(selectinload(User.role), selectinload(User.eitaa_account_links))
            .where(User.email == email.strip().lower())
        )
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid email or password")
    if not user.is_active:
        raise AuthenticationError("This account is disabled")
    return user


async def issue_tokens(
    db: AsyncSession,
    user: User,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, datetime, str]:
    """Return (access_token, access_expires_at, refresh_token)."""
    permissions = sorted(await agent_service.resolve_permissions(db, user))
    access, expires_at = create_access_token(
        subject=str(user.id),
        role=user.role_name,
        permissions=permissions,
        token_version=user.token_version,
    )
    refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=uuid.uuid4().hex,
            token_hash=hash_refresh_token(refresh),
            expires_at=refresh_token_expiry(),
            created_ip=ip,
            created_user_agent=user_agent[:250] if user_agent else None,
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    return access, expires_at, refresh


async def rotate_refresh(
    db: AsyncSession, raw_refresh_token: str, *, ip: str | None = None
) -> tuple[User, str, datetime, str]:
    """Validate + rotate a refresh token. Reuse of an already-rotated token
    revokes the entire family (steal detection)."""
    token_hash = hash_refresh_token(raw_refresh_token)
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if row is None:
        raise AuthenticationError("Invalid refresh token")

    now = datetime.now(timezone.utc)
    if row.revoked_at is not None:
        # REUSE DETECTED — kill the whole family
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == row.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await audit_service.record(
            db,
            action=audit_service.AGENT_LOGIN_FAILED,
            actor_id=row.user_id,
            meta={"reason": "refresh_token_reuse_detected"},
            ip=ip,
        )
        raise AuthenticationError("Refresh token reuse detected — please login again")

    if row.expires_at < now:
        raise AuthenticationError("Refresh token expired")

    user = (
        await db.execute(
            select(User)
            .options(selectinload(User.role), selectinload(User.eitaa_account_links))
            .where(User.id == row.user_id)
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("Account is disabled")

    # rotate: revoke old, issue new within the same family
    row.revoked_at = now
    new_raw = generate_refresh_token()
    new_token = RefreshToken(
        user_id=user.id,
        family_id=row.family_id,
        token_hash=hash_refresh_token(new_raw),
        expires_at=refresh_token_expiry(),
        created_ip=ip,
    )
    db.add(new_token)
    await db.flush()
    row.replaced_by_id = new_token.id

    permissions = sorted(await agent_service.resolve_permissions(db, user))
    access, expires_at = create_access_token(
        subject=str(user.id),
        role=user.role_name,
        permissions=permissions,
        token_version=user.token_version,
    )
    return user, access, expires_at, new_raw


async def revoke_refresh_family(db: AsyncSession, raw_refresh_token: str) -> None:
    token_hash = hash_refresh_token(raw_refresh_token)
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if row is None:
        return
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == row.family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def revoke_all_user_tokens(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def change_password(
    db: AsyncSession, user: User, *, current_password: str, new_password: str
) -> None:
    from app.core.security import hash_password

    if not verify_password(current_password, user.password_hash):
        raise ValidationError("Current password is incorrect")
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    await revoke_all_user_tokens(db, user.id)
