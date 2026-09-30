"""Eitaa account endpoints: OTP connect wizard, list, update, disconnect, sync."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import AuthContext, DbSession, require
from app.eitaa.registry import get_registry
from app.schemas.common import (
    EitaaAccountOut,
    EitaaAccountUpdate,
    LoginChallengeOut,
    RequestCodeRequest,
    ResendCodeRequest,
    VerifyCodeRequest,
)
from app.services import audit_service, eitaa_account_service
from app.services.errors import ForbiddenError

router = APIRouter(prefix="/eitaa/accounts", tags=["eitaa-accounts"])


async def _to_out(db, account) -> EitaaAccountOut:
    from sqlalchemy import select

    from app.eitaa.adapter import EitaaCliAdapter
    from app.models import EitaaAccountLink

    agent_ids = list(
        (
            await db.execute(
                select(EitaaAccountLink.agent_id).where(
                    EitaaAccountLink.eitaa_account_id == account.id
                )
            )
        )
        .scalars()
        .all()
    )
    return EitaaAccountOut(
        id=account.id,
        phone_number=account.phone_number,
        display_name=account.display_name,
        username=account.username,
        eitaa_user_id=account.eitaa_user_id,
        status=account.status,
        sync_enabled=account.sync_enabled,
        last_sync_at=account.last_sync_at,
        last_sync_ok=account.last_sync_ok,
        last_error=account.last_error,
        agent_ids=agent_ids,
        deep_link=EitaaCliAdapter.peer_deep_link(account.username),
    )


def _challenge_out(row) -> LoginChallengeOut:
    return LoginChallengeOut(
        challenge_id=row.id,
        phone_number=row.phone_number,
        delivery=row.delivery,
        next_delivery=row.next_delivery,
        timeout_seconds=row.timeout_seconds,
        code_length=row.code_length,
    )


@router.get("", response_model=list[EitaaAccountOut])
async def list_accounts(db: DbSession, auth: AuthContext = Depends(require("eitaa.account.view"))):
    from sqlalchemy import select

    from app.models import EitaaAccount

    accounts = (
        (await db.execute(select(EitaaAccount).order_by(EitaaAccount.id))).scalars().unique().all()
    )
    return [await _to_out(db, a) for a in accounts]


@router.post("/request-code", response_model=LoginChallengeOut)
async def request_code(
    body: RequestCodeRequest,
    db: DbSession,
    auth: AuthContext = Depends(require("eitaa.account.manage")),
):
    row = await eitaa_account_service.request_login_challenge(
        db,
        get_registry(),
        phone_number=body.phone_number,
        created_by_id=auth.user.id,
    )
    await db.commit()
    return _challenge_out(row)


@router.post("/resend-code", response_model=LoginChallengeOut)
async def resend_code(
    body: ResendCodeRequest,
    db: DbSession,
    auth: AuthContext = Depends(require("eitaa.account.manage")),
):
    row = await eitaa_account_service.resend_login_challenge(
        db, get_registry(), challenge_id=body.challenge_id
    )
    await db.commit()
    return _challenge_out(row)


@router.post("/verify", response_model=EitaaAccountOut, status_code=201)
async def verify_code(
    body: VerifyCodeRequest,
    db: DbSession,
    auth: AuthContext = Depends(require("eitaa.account.manage")),
):
    account = await eitaa_account_service.verify_login(
        db, get_registry(), challenge_id=body.challenge_id, otp_code=body.otp_code
    )
    await db.commit()
    return await _to_out(db, account)


@router.get("/{account_id}", response_model=EitaaAccountOut)
async def get_account(
    account_id: int, db: DbSession, auth: AuthContext = Depends(require("eitaa.account.view"))
):
    account = await eitaa_account_service.get_account(db, account_id)
    return await _to_out(db, account)


@router.patch("/{account_id}", response_model=EitaaAccountOut)
async def update_account(
    account_id: int,
    body: EitaaAccountUpdate,
    db: DbSession,
    auth: AuthContext = Depends(require("eitaa.account.manage")),
):
    account = await eitaa_account_service.get_account(db, account_id)
    if body.display_name is not None:
        account.display_name = body.display_name
    if body.sync_enabled is not None:
        account.sync_enabled = body.sync_enabled
    if body.agent_ids is not None:
        await eitaa_account_service.set_account_agents(db, account, body.agent_ids)
    await audit_service.record(
        db,
        action=audit_service.EITAA_ACCOUNT_UPDATED,
        actor_id=auth.user.id,
        actor_name=auth.user.name,
        target_type="eitaa_account",
        target_id=account.id,
    )
    await db.commit()
    await db.refresh(account)
    return await _to_out(db, account)


@router.delete("/{account_id}")
async def disconnect_account(
    account_id: int,
    db: DbSession,
    auth: AuthContext = Depends(require("eitaa.account.manage")),
):
    account = await eitaa_account_service.get_account(db, account_id)
    await eitaa_account_service.disconnect_account(
        db, get_registry(), account, actor_id=auth.user.id
    )
    await db.commit()
    return {"ok": True}


@router.post("/{account_id}/test")
async def test_connection(
    account_id: int,
    db: DbSession,
    auth: AuthContext = Depends(require("eitaa.account.manage")),
):
    """Verify the stored session still works (users.getFullUser via adapter)."""
    account = await eitaa_account_service.get_account(db, account_id)
    if not account.is_connected:
        return {"ok": False, "status": account.status, "error": "Not connected"}
    try:
        info = await get_registry().adapter.verify_session(get_registry().session_for(account))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": account.status, "error": str(exc)[:200]}
    return {
        "ok": True,
        "status": account.status,
        "account": {
            "name": " ".join(p for p in [info.first_name, info.last_name] if p),
            "username": info.username,
        },
    }


@router.post("/{account_id}/sync")
async def trigger_sync(
    account_id: int,
    background: BackgroundTasks,
    db: DbSession,
    auth: AuthContext = Depends(require("eitaa.account.manage")),
):
    from app.workers.sync_worker import sync_worker

    account = await eitaa_account_service.get_account(db, account_id)
    if not account.is_connected:
        raise ForbiddenError("Account is not connected")
    background.add_task(sync_worker.sync_account, account_id)
    return {"ok": True, "queued": True}
