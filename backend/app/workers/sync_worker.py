"""Sync worker — polls Eitaa accounts for new messages.

eitaa-cli has NO real-time update stream (verified limitation), so the worker
polls `messages.getDialogs` per connected account every EITAA_SYNC_INTERVAL
seconds and pulls history for dialogs whose top_message advanced.

Concurrency safety:
  * PostgreSQL advisory locks (pg_try_advisory_lock) guarantee a single sync
    pass per account at any time — even with multiple worker processes.
  * The (conversation_id, eitaa_message_id) unique constraint makes duplicate
    ingestion impossible even if a pass re-runs after a crash.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.events import bus
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.eitaa.exceptions import EitaaAdapterError, EitaaAuthRequiredError
from app.eitaa.registry import get_registry
from app.models import (
    Conversation,
    EitaaAccount,
    EitaaAccountStatus,
    SyncState,
)
from app.services import audit_service, message_service

logger = get_logger("app.sync")

_LOCK_NAMESPACE = 791_732_100  # arbitrary but fixed namespace for this app


def _lock_key(account_id: int) -> int:
    return _LOCK_NAMESPACE + account_id


class SyncWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.in_progress: set[int] = set()

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run_forever(), name="eitaa-sync-worker")
            logger.info("sync worker started (interval=%ss)", settings.eitaa_sync_interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
            logger.info("sync worker stopped")

    async def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self.sync_all()
            except Exception:  # noqa: BLE001 — keep the loop alive
                logger.exception("sync pass crashed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.eitaa_sync_interval)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------- one pass
    async def sync_all(self) -> int:
        """Sync every connected + enabled account. Returns accounts synced."""
        async with session_scope() as db:
            accounts = list(
                (
                    await db.execute(
                        select(EitaaAccount).where(
                            EitaaAccount.status == EitaaAccountStatus.CONNECTED.value,
                            EitaaAccount.sync_enabled.is_(True),
                        )
                    )
                )
                .scalars()
                .unique()
                .all()
            )
        synced = 0
        for account in accounts:
            try:
                if await self.sync_account(account.id):
                    synced += 1
            except Exception:  # noqa: BLE001
                logger.exception("account %s sync failed", account.id)
        return synced

    async def sync_account(self, account_id: int) -> bool:
        """Sync a single account under an advisory lock. False = skipped.

        The advisory lock lives on ONE dedicated connection for the whole
        pass — PostgreSQL advisory locks are session-scoped, so acquiring and
        releasing on different pooled connections would leak the lock.
        """
        from sqlalchemy import text as sa_text

        from app.db.session import get_engine

        engine = get_engine()
        lock_key = _lock_key(account_id)
        async with engine.connect() as lock_conn:
            got_lock = (
                await lock_conn.execute(
                    sa_text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
                )
            ).scalar_one()
            if not got_lock:
                logger.debug("account %s is being synced elsewhere; skipping", account_id)
                return False
            try:
                return await self._sync_account_locked(account_id)
            finally:
                await lock_conn.execute(
                    sa_text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
                )

    async def _sync_account_locked(self, account_id: int) -> bool:
        async with session_scope() as db:
            account = (
                await db.execute(select(EitaaAccount).where(EitaaAccount.id == account_id))
            ).scalar_one_or_none()
            if account is None or not account.is_connected or not account.sync_enabled:
                return False
            state = await self._ensure_state(db, account_id)
            state.last_run_at = datetime.now(timezone.utc)
            new_messages = 0
            try:
                session = get_registry().session_for(account)
                dialogs = await get_registry().adapter.list_dialogs(
                    session, limit=settings.eitaa_sync_dialog_limit
                )
                wanted_kinds = settings.sync_kind_list
                for dialog in dialogs:
                    if dialog.kind not in wanted_kinds:
                        continue
                    new_messages += await self._sync_dialog(db, account, dialog)
                account.last_sync_at = datetime.now(timezone.utc)
                account.last_sync_ok = True
                account.last_error = None
                state.last_success_at = account.last_sync_at
                state.consecutive_failures = 0
                state.new_messages_last_run = new_messages
                await db.commit()
                return True
            except EitaaAuthRequiredError as exc:
                account.status = EitaaAccountStatus.DISCONNECTED.value
                account.last_error = "Session expired or revoked — reconnect required"
                state.consecutive_failures += 1
                state.last_error = str(exc)[:400]
                await audit_service.record(
                    db,
                    action=audit_service.EITAA_SYNC_FAILED,
                    target_type="eitaa_account",
                    target_id=account.id,
                    meta={"reason": "auth_required"},
                )
                await db.commit()
                await bus.publish(
                    "eitaa_account.updated",
                    {"id": account.id, "status": account.status},
                )
                logger.warning("account %s session invalid — marked disconnected", account_id)
                return False
            except (EitaaAdapterError, SQLAlchemyError, Exception) as exc:  # noqa: BLE001
                state.consecutive_failures += 1
                state.last_error = str(exc)[:400]
                account.last_sync_ok = False
                account.last_error = str(exc)[:500]
                await db.commit()
                logger.warning("account %s sync error: %s", account_id, exc, exc_info=exc)
                return False

    async def _ensure_state(self, db, account_id: int) -> SyncState:
        state = (
            await db.execute(select(SyncState).where(SyncState.eitaa_account_id == account_id))
        ).scalar_one_or_none()
        if state is None:
            state = SyncState(eitaa_account_id=account_id)
            db.add(state)
            await db.flush()
        return state

    async def _sync_dialog(self, db, account: EitaaAccount, dialog) -> int:
        """Upsert the conversation and pull new messages. Returns new count."""
        conversation = (
            await db.execute(
                select(Conversation).where(
                    Conversation.eitaa_account_id == account.id,
                    Conversation.peer_type == dialog.peer_type,
                    Conversation.peer_id == dialog.peer_id,
                )
            )
        ).scalar_one_or_none()

        is_new = conversation is None
        if is_new:
            conversation = Conversation(
                eitaa_account_id=account.id,
                peer_type=dialog.peer_type,
                peer_id=dialog.peer_id,
                access_hash=dialog.access_hash,
                peer_kind=dialog.kind,
                title=dialog.title or str(dialog.peer_id),
                username=dialog.username,
                phone=dialog.phone,
            )
            db.add(conversation)
            await db.flush()

        # keep the denormalized profile fresh
        conversation.title = dialog.title or conversation.title
        conversation.username = dialog.username
        conversation.phone = dialog.phone
        if dialog.access_hash is not None:
            conversation.access_hash = dialog.access_hash
        conversation.unread_eitaa_count = dialog.unread_count

        if not is_new and dialog.top_message_id <= (conversation.last_message_id or 0):
            return 0  # nothing new since last pass

        session = get_registry().session_for(account)
        history = await get_registry().adapter.get_history(
            session,
            conversation.peer_reference,
            limit=settings.eitaa_sync_history_limit,
            min_id=conversation.last_message_id or 0,
        )

        new_count = 0
        for msg in sorted(history, key=lambda m: m.message_id):
            if not is_new and msg.message_id <= (conversation.last_message_id or 0):
                continue  # belt & suspenders next to the DB unique constraint
            if msg.is_out:
                created = await message_service.ingest_outbound_from_app(
                    db,
                    conversation,
                    eitaa_message_id=msg.message_id,
                    sent_at=datetime.fromtimestamp(msg.date, tz=timezone.utc) if msg.date else None,
                    text=msg.text,
                    reply_to_eitaa_id=msg.reply_to_message_id,
                    media_info=msg.media,
                )
            else:
                created = await message_service.ingest_inbound(
                    db,
                    conversation,
                    eitaa_message_id=msg.message_id,
                    sent_at=datetime.fromtimestamp(msg.date, tz=timezone.utc) if msg.date else None,
                    text=msg.text,
                    sender_user_id=msg.sender_user_id,
                    reply_to_eitaa_id=msg.reply_to_message_id,
                    media_info=msg.media,
                )
            if created is not None:
                new_count += 1
        if new_count:
            await db.commit()
        return new_count


sync_worker = SyncWorker()
