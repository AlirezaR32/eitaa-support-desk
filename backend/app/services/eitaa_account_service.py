"""Eitaa account management: OTP connect flow, status, sync toggle, deletion.

The Eitaa `phone_code_hash` is temporary sensitive authentication state:
it is stored Fernet-encrypted in `auth_challenges`, auto-expires, and is never
included in API responses or logs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import bus
from app.core.logging import get_logger
from app.core.security import session_vault
from app.eitaa.base import EitaaSession
from app.eitaa.exceptions import EitaaAuthRequiredError, EitaaLoginError
from app.eitaa.registry import EitaaRegistry
from app.models import AuthChallenge, EitaaAccount, EitaaAccountLink, EitaaAccountStatus
from app.services import audit_service
from app.services.errors import ConflictError, NotFoundError, ValidationError

logger = get_logger("app.eitaa_accounts")

CHALLENGE_TTL = timedelta(minutes=20)


def _encrypt_secret(value: str) -> bytes:
    return session_vault.encrypt({"value": value})


def _decrypt_secret(blob: bytes) -> str | None:
    payload = session_vault.decrypt(blob)
    return payload.get("value") if payload else None


async def _purge_expired_challenges(db: AsyncSession) -> None:
    await db.execute(
        delete(AuthChallenge).where(AuthChallenge.expires_at < datetime.now(timezone.utc))
    )


def normalize_phone(phone_number: str) -> str:
    phone = "".join(c for c in phone_number if c.isdigit())
    if phone.startswith("00"):
        phone = phone[2:]
    if phone.startswith("0") and len(phone) == 11:
        phone = "98" + phone[1:]
    if len(phone) < 8:
        raise ValidationError("Phone number looks invalid")
    return phone


async def request_login_challenge(
    db: AsyncSession,
    registry: EitaaRegistry,
    *,
    phone_number: str,
    created_by_id: int,
) -> AuthChallenge:
    await _purge_expired_challenges(db)

    normalized = normalize_phone(phone_number)
    existing = (
        await db.execute(select(EitaaAccount).where(EitaaAccount.phone_number == normalized))
    ).scalar_one_or_none()
    if existing is not None and existing.is_connected:
        raise ConflictError("This phone number is already connected as an Eitaa account")

    # talk to Eitaa FIRST; only persist the challenge if the request succeeded
    challenge = await registry.adapter.request_login_challenge(normalized)

    row = AuthChallenge(
        id=challenge.challenge_id,
        phone_number=challenge.phone_number,
        phone_code_hash_encrypted=_encrypt_secret(challenge.phone_code_hash),
        delivery=challenge.delivery,
        next_delivery=challenge.next_delivery,
        timeout_seconds=challenge.timeout_seconds,
        code_length=challenge.code_length,
        expires_at=datetime.now(timezone.utc) + CHALLENGE_TTL,
        created_by_id=created_by_id,
    )
    db.add(row)
    await db.flush()

    await audit_service.record(
        db,
        action=audit_service.LOGIN_CHALLENGE_REQUESTED,
        actor_id=created_by_id,
        meta={"delivery": challenge.delivery, "phone_number_tail": normalized[-4:]},
    )
    return row


async def resend_login_challenge(
    db: AsyncSession, registry: EitaaRegistry, *, challenge_id: str
) -> AuthChallenge:
    row = await _get_challenge(db, challenge_id)
    stored_hash = _decrypt_secret(row.phone_code_hash_encrypted)
    if not stored_hash:
        raise ValidationError("Challenge state lost — request a new code")

    challenge = await registry.adapter.resend_login_challenge(row.phone_number, stored_hash)

    row.phone_code_hash_encrypted = _encrypt_secret(challenge.phone_code_hash)
    row.delivery = challenge.delivery
    row.next_delivery = challenge.next_delivery
    row.timeout_seconds = challenge.timeout_seconds
    row.code_length = challenge.code_length
    row.expires_at = datetime.now(timezone.utc) + CHALLENGE_TTL
    row.consumed = False
    await db.flush()
    return row


async def _get_challenge(db: AsyncSession, challenge_id: str) -> AuthChallenge:
    row = (
        await db.execute(select(AuthChallenge).where(AuthChallenge.id == challenge_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Login challenge not found or expired")
    if row.expires_at < datetime.now(timezone.utc):
        raise ValidationError("Login challenge expired — request a new code")
    if row.consumed:
        raise ValidationError("Login challenge already used")
    return row


async def verify_login(
    db: AsyncSession,
    registry: EitaaRegistry,
    *,
    challenge_id: str,
    otp_code: str,
) -> EitaaAccount:
    row = await _get_challenge(db, challenge_id)
    stored_hash = _decrypt_secret(row.phone_code_hash_encrypted)
    if not stored_hash:
        raise ValidationError("Challenge state lost — request a new code")

    try:
        session = await registry.adapter.complete_login(row.phone_number, stored_hash, otp_code)
    except EitaaLoginError as exc:
        # wrong/expired code does NOT consume the challenge — the agent may retry
        if exc.reason in {"invalid-code", "expired-code", "invalid-challenge"}:
            raise ValidationError(
                f"OTP verification failed: {exc.reason.replace('-', ' ')}"
            ) from exc
        raise ValidationError(exc.message) from exc

    info = await registry.adapter.verify_session(session)

    account = (
        await db.execute(
            select(EitaaAccount).where(EitaaAccount.phone_number == session.phone_number)
        )
    ).scalar_one_or_none()
    if account is None:
        account = EitaaAccount(phone_number=session.phone_number, created_by_id=row.created_by_id)
        db.add(account)

    account.display_name = (
        " ".join(p for p in [info.first_name, info.last_name] if p) or account.display_name
    )
    account.username = info.username
    account.eitaa_user_id = info.user_id
    account.status = EitaaAccountStatus.CONNECTED.value
    account.last_error = None
    registry.store_session(account, session)

    row.consumed = True
    await db.flush()

    await audit_service.record(
        db,
        action=audit_service.EITAA_ACCOUNT_CONNECTED,
        actor_id=row.created_by_id,
        target_type="eitaa_account",
        target_id=account.id,
        meta={"phone_number_tail": account.phone_number[-4:]},
    )
    await bus.publish("eitaa_account.updated", {"id": account.id, "status": account.status})
    return account


async def get_account(db: AsyncSession, account_id: int) -> EitaaAccount:
    account = (
        await db.execute(select(EitaaAccount).where(EitaaAccount.id == account_id))
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("Eitaa account not found")
    return account


async def disconnect_account(
    db: AsyncSession, registry: EitaaRegistry, account: EitaaAccount, *, actor_id: int
) -> None:
    session: EitaaSession | None = None
    if account.session_encrypted:
        try:
            session = registry.session_for(account)
        except EitaaAuthRequiredError:
            session = None
    if session is not None:
        await registry.adapter.logout(session)  # best-effort server-side logout
    registry.drop_session(account)
    account.status = EitaaAccountStatus.DISCONNECTED.value
    await audit_service.record(
        db,
        action=audit_service.EITAA_ACCOUNT_DISCONNECTED,
        actor_id=actor_id,
        target_type="eitaa_account",
        target_id=account.id,
    )
    await bus.publish("eitaa_account.updated", {"id": account.id, "status": account.status})


async def set_account_agents(db: AsyncSession, account: EitaaAccount, agent_ids: list[int]) -> None:
    await db.execute(
        delete(EitaaAccountLink).where(EitaaAccountLink.eitaa_account_id == account.id)
    )
    for agent_id in agent_ids:
        db.add(EitaaAccountLink(agent_id=agent_id, eitaa_account_id=account.id))
    await db.flush()
