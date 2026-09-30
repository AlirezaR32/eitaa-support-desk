"""FastAPI dependencies: auth, permissions, pagination.

NOTE: no `from __future__ import annotations` here — FastAPI's dependency
analysis needs real (non-forward-ref) annotations for Query() params.
"""

from typing import Annotated

from fastapi import Depends, Query, Request, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.services import agent_service
from app.services.errors import AuthenticationError, ForbiddenError

DbSession = Annotated[AsyncSession, Depends(get_db)]


class AuthContext:
    """Resolved identity + effective permissions for the current request."""

    def __init__(self, user: User, permissions: set[str]):
        self.user = user
        self.permissions = permissions

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise ForbiddenError(f"Missing permission: {permission}")

    def has(self, permission: str) -> bool:
        return permission in self.permissions


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def get_auth_context(request: Request, db: DbSession) -> AuthContext:
    token = _extract_token(request)
    if not token:
        raise AuthenticationError("Not authenticated")
    payload = decode_access_token(token)
    if payload is None:
        raise AuthenticationError("Invalid or expired token")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise AuthenticationError("Invalid token subject")

    user = (
        await db.execute(
            select(User)
            .options(
                selectinload(User.role),
                selectinload(User.eitaa_account_links),
            )
            .where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("Account not found or disabled")
    if payload.get("ver", 0) < user.token_version:
        raise AuthenticationError("Token revoked — please login again")
    permissions = await agent_service.resolve_permissions(db, user)
    return AuthContext(user, permissions)


Auth = Annotated[AuthContext, Depends(get_auth_context)]


def require(permission: str):
    """Endpoint guard: `Depends(require('agent.manage'))`."""

    async def _guard(auth: Auth) -> AuthContext:
        auth.require(permission)
        return auth

    return _guard


class Pagination:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 30,
    ):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


PageParams = Annotated[Pagination, Depends()]


async def ws_auth(websocket: WebSocket, db: AsyncSession | None = None) -> AuthContext | None:
    """Authenticate a WebSocket connection from the ?token= query param."""
    from app.db.session import get_session_factory

    token = websocket.query_params.get("token") or ""
    payload = decode_access_token(token)
    if payload is None:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        return None

    owns_session = db is not None
    session = db
    if not owns_session:
        factory = get_session_factory()
        session = factory()
    try:
        import sqlalchemy as sa

        user = (
            await session.execute(sa.select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        if payload.get("ver", 0) < user.token_version:
            return None
        permissions = await agent_service.resolve_permissions(session, user)
        return AuthContext(user, permissions)
    finally:
        if not owns_session:
            await session.close()
