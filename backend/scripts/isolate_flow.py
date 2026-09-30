"""Isolation: exercise the exact flow of test_messages WITHOUT pytest."""
import asyncio
import logging
import os
import sys
import traceback

os.environ.update(
    DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/eitaa_desk_test",
    UPLOADS_DIR="/tmp/eitaa-uploads-test",
    RUN_SYNC_WORKER="false",
    RUN_NOTIFICATION_WORKER="false",
    EITAA_SYNC_ENABLED="false",
    LOG_LEVEL="ERROR",
    SECRET_KEY="test-secret-key-for-unit-tests-only-0123456789",
    JWT_SECRET="test-jwt-secret-key-for-unit-tests-only-9876543210",
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import ASGITransport, AsyncClient  # noqa: E402

import app.models  # noqa
from app.db.base import Base  # noqa
from app.db.session import dispose_engine, get_engine, get_session_factory  # noqa
from app.eitaa.registry import EitaaRegistry  # noqa


class SyncTBHandler(logging.Handler):
    def emit(self, record):
        if record.exc_info:
            print("=== SYNC TB ===")
            text = "".join(traceback.format_exception(*record.exc_info))
            for line in text.splitlines():
                if "app/" in line or "Error" in line:
                    print(line.strip()[:170])


logging.getLogger("app.sync").addHandler(SyncTBHandler())


class FakeAdapter:
    def __init__(self):
        self.dialogs = []
        self.history = {}
        self.next_id = 1000
        self.sent = []

    async def request_login_challenge(self, phone):
        from app.eitaa.base import EitaaLoginChallenge
        return EitaaLoginChallenge(
            challenge_id="c1", phone_number=phone, phone_code_hash="h1",
            delivery="sms", next_delivery=None, timeout_seconds=900, code_length=5,
        )

    async def resend_login_challenge(self, phone, h):
        return await self.request_login_challenge(phone)

    async def complete_login(self, phone, h, code):
        from app.eitaa.base import EitaaSession
        assert code == "12345"
        return EitaaSession(phone_number=phone, token="tok", imei="im", user={"id": 555})

    async def verify_session(self, s):
        from app.eitaa.base import EitaaAccountInfo
        return EitaaAccountInfo(555, "Support", "Bot", "support_bot", s.phone_number)

    async def logout(self, s): ...

    async def list_dialogs(self, session, limit=100):
        from app.eitaa.base import EitaaDialog
        return [EitaaDialog(**d) for d in self.dialogs]

    async def get_history(self, session, ref, *, limit=50, min_id=0):
        from app.eitaa.base import EitaaMessage
        return [
            EitaaMessage(
                message_id=m["message_id"], date=m["date"], text=m["text"],
                is_out=False, sender_user_id=1, reply_to_message_id=None, media=None,
            )
            for m in self.history.get(ref, []) if m["message_id"] > min_id
        ]

    async def get_message(self, s, r, mid):
        return None

    async def send_text(self, session, ref, txt, *, reply_to=None):
        from app.eitaa.base import SendResult
        self.next_id += 1
        self.sent.append(txt)
        return SendResult(message_id=self.next_id)

    async def send_media(self, session, ref, path, *, caption="", reply_to=None,
                         as_voice=False, duration_seconds=0):
        return await self.send_text(session, ref, caption)

    async def download_message_media(self, s, r, mid, dest): ...

    async def mark_read(self, s, r, mid):
        return True

    @staticmethod
    def peer_deep_link(u):
        return None


async def main():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    import app.eitaa.registry as rm
    fake = FakeAdapter()
    rm.registry = EitaaRegistry(adapter=fake)

    from app.main import create_app
    app = create_app()

    from app.db.seed import seed
    await seed(owner_email="owner@test.local", owner_password="OwnerPass!1", owner_name="Owner")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@test.local", "password": "OwnerPass!1"},
        )
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("login:", r.status_code)

        r = await client.post(
            "/api/v1/eitaa/accounts/request-code",
            json={"phone_number": "09120000001"}, headers=headers,
        )
        print("request-code:", r.status_code)
        r = await client.post(
            "/api/v1/eitaa/accounts/verify",
            json={"challenge_id": r.json()["challenge_id"], "otp_code": "12345"},
            headers=headers,
        )
        print("verify:", r.status_code)

        fake.dialogs.append(
            dict(peer_type="user", peer_id=201, access_hash=9201, kind="private",
                 title="Reza", username=None, phone=None, top_message_id=1,
                 unread_count=1, last_message_date=1700000000)
        )
        fake.history["user:201:9201"] = [
            dict(message_id=1, date=1700000000, text="پیام تست", is_out=False,
                 sender_user_id=201, reply_to_message_id=None)
        ]

        from app.workers.sync_worker import sync_worker
        n = await sync_worker.sync_all()
        print("sync accounts:", n)

        from sqlalchemy import select
        from app.models import Conversation
        factory = get_session_factory()
        async with factory() as db:
            conv = (
                await db.execute(select(Conversation).where(Conversation.peer_id == 201))
            ).scalar_one()
            conv_id = conv.id
        print("conversation id:", conv_id)

        r = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"text": "پاسخ پشتیبانی"}, headers=headers,
        )
        print(
            "send message:", r.status_code, "->",
            r.json().get("send_status"), r.json().get("error_message"),
        )

    await dispose_engine()


asyncio.run(main())
