"""Auth endpoints: login, refresh (cookie), logout, me."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import Auth, DbSession
from app.core.config import settings
from app.schemas.common import (
    AgentOut,
    ChangePasswordRequest,
    LoginRequest,
    RefreshResult,
    TokenPair,
    UpdateProfileRequest,
)
from app.services import agent_service, audit_service, auth_service
from app.services.errors import AuthenticationError

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "desk_refresh"


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _set_refresh_cookie(response: Response, token: str) -> None:
    cross_site = any(
        origin and not origin.startswith(("http://localhost", "http://127.0.0.1"))
        for origin in settings.cors_origin_list
    )
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if (cross_site and settings.is_production) else "lax",
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path=f"{settings.api_prefix}/auth",
    )


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, request: Request, response: Response, db: DbSession):
    try:
        user = await auth_service.authenticate(db, email=body.email, password=body.password)
    except AuthenticationError as exc:
        await audit_service.record(
            db,
            action=audit_service.AGENT_LOGIN_FAILED,
            actor_name=body.email[:120],
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            meta={"reason": "invalid_credentials"},
        )
        await db.commit()
        raise exc

    access, expires_at, refresh = await auth_service.issue_tokens(
        db,
        user,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await audit_service.record(
        db,
        action=audit_service.AGENT_LOGIN,
        actor_id=user.id,
        actor_name=user.name,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    _set_refresh_cookie(response, refresh)
    permissions = await agent_service.resolve_permissions(db, user)
    account_ids = sorted(await agent_service.agent_account_ids(db, user.id))
    return TokenPair(
        access_token=access,
        expires_at=expires_at,
        user=_agent_out(user, permissions, account_ids),
    )


@router.post("/refresh", response_model=RefreshResult)
async def refresh(request: Request, response: Response, db: DbSession):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise AuthenticationError("No refresh token")
    _validate_origin(request)
    user, access, expires_at, new_refresh = await auth_service.rotate_refresh(
        db, raw, ip=_client_ip(request)
    )
    await db.commit()
    _set_refresh_cookie(response, new_refresh)
    return RefreshResult(access_token=access, expires_at=expires_at)


@router.post("/logout")
async def logout(request: Request, response: Response, db: DbSession, auth: Auth):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await auth_service.revoke_refresh_family(db, raw)
    response.delete_cookie(REFRESH_COOKIE, path=f"{settings.api_prefix}/auth")
    await audit_service.record(
        db,
        action=audit_service.AGENT_LOGOUT,
        actor_id=auth.user.id,
        actor_name=auth.user.name,
        ip=_client_ip(request),
    )
    await db.commit()
    return {"ok": True}


@router.get("/me", response_model=AgentOut)
async def me(db: DbSession, auth: Auth):
    account_ids = sorted(await agent_service.agent_account_ids(db, auth.user.id))
    return _agent_out(auth.user, auth.permissions, account_ids)


@router.patch("/me", response_model=AgentOut)
async def update_me(body: UpdateProfileRequest, db: DbSession, auth: Auth):
    if body.name is not None:
        auth.user.name = body.name
    if body.username is not None:
        auth.user.username = body.username or None
    await db.commit()
    await db.refresh(auth.user)
    account_ids = sorted(await agent_service.agent_account_ids(db, auth.user.id))
    return _agent_out(auth.user, auth.permissions, account_ids)


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, db: DbSession, auth: Auth):
    await auth_service.change_password(
        db, auth.user, current_password=body.current_password, new_password=body.new_password
    )
    await audit_service.record(
        db,
        action=audit_service.PASSWORD_CHANGED,
        actor_id=auth.user.id,
        actor_name=auth.user.name,
    )
    await db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ helpers
def _agent_out(user, permissions: set[str], account_ids: list[int]) -> AgentOut:
    return AgentOut(
        id=user.id,
        name=user.name,
        username=user.username,
        email=user.email,
        role=user.role_name,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        permissions=sorted(permissions or []),
        eitaa_account_ids=account_ids,
    )


def _validate_origin(request: Request) -> None:
    """CSRF hardening for the cookie-based refresh endpoint: the Origin header
    must be an allowed CORS origin (when present)."""
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = {o.rstrip("/") for o in settings.cors_origin_list}
    if origin.rstrip("/") not in allowed:
        raise AuthenticationError("Cross-origin refresh rejected")
