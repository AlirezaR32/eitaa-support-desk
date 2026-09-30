"""Test fixtures: real PostgreSQL (eitaa_desk_test) + FakeEitaaAdapter.

The fake adapter is a TEST DOUBLE implementing the same EitaaClientAdapter
protocol as the real eitaa-cli adapter — it lets integration tests exercise
the full API surface offline. Production code never uses it.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

# --- test database (real PostgreSQL; tests skip if unreachable) ---
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres@127.0.0.1:5432/eitaa_desk_test",
)

os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["UPLOADS_DIR"] = "/tmp/eitaa-uploads-test"
os.environ["RUN_SYNC_WORKER"] = "false"
os.environ["RUN_NOTIFICATION_WORKER"] = "false"
os.environ["EITAA_SYNC_ENABLED"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-0123456789")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-for-unit-tests-only-9876543210")

import app.models  # noqa: E402,F401 — registers every model on Base.metadata
from app.core.config import settings as _settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, get_engine, get_session_factory  # noqa: E402

# Force settings regardless of import order / cached .env
_settings.database_url = TEST_DB_URL
_settings.uploads_dir = "/tmp/eitaa-uploads-test"
_settings.run_sync_worker = False
_settings.run_notification_worker = False
_settings.eitaa_sync_enabled = False
_settings.log_level = "WARNING"
_settings.secret_key = os.environ["SECRET_KEY"]
_settings.jwt_secret = os.environ["JWT_SECRET"]


def _pg_reachable() -> bool:
    import socket

    try:
        parts = TEST_DB_URL.split("//", 1)[1].split("@")
        host_port = parts[-1].split("/")[0]
        host, port = (host_port.split(":") + ["5432"])[:2]
        with socket.create_connection((host, int(port)), timeout=2):
            return True
    except Exception:  # noqa: BLE001
        return False


PG_AVAILABLE = _pg_reachable()

pytestmark = pytest.mark.asyncio


# ------------------------------------------------------------------ fake adapter
class FakeEitaaAdapter:
    """In-memory EitaaClientAdapter implementation for tests."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.dialogs: list[dict] = []
        self.history: dict[str, list[dict]] = {}  # peer_ref -> messages
        self.next_message_id = 1000
        self.sent: list[dict] = []
        self.fail_sends = False
        self.fail_media_sends = False
        self.read_marks: list[tuple[str, int]] = []

    def seed_dialog(
        self, peer_id: int, title: str, *, username=None, top=1, unread=0, kind="private"
    ):
        self.dialogs.append(
            {
                "peer_type": "user",
                "peer_id": peer_id,
                "access_hash": 9000 + peer_id,
                "kind": kind,
                "title": title,
                "username": username,
                "phone": f"98912000{peer_id:04d}",
                "top_message_id": top,
                "unread_count": unread,
                "last_message_date": 1700000000,
            }
        )

    def seed_message(self, peer_id: int, *, text="hello", is_out=False, date=None, media=None):
        import time

        self.next_message_id += 1  # same allocation scheme as send_text — no collisions
        peer_ref = f"user:{peer_id}:{9000 + peer_id}"
        msg = {
            "message_id": self.next_message_id,
            "date": date or int(time.time()),
            "text": text,
            "is_out": is_out,
            "sender_user_id": None if is_out else peer_id,
            "reply_to_message_id": None,
            "media": media,
        }
        self.history.setdefault(peer_ref, []).append(msg)
        # keep the dialog cursor in sync so the worker picks the message up
        for dialog in self.dialogs:
            if dialog["peer_id"] == peer_id:
                dialog["top_message_id"] = msg["message_id"]
                dialog["last_message_date"] = msg["date"]
        return msg["message_id"]

    # ---- login lifecycle
    async def request_login_challenge(self, phone_number: str):
        from app.eitaa.base import EitaaLoginChallenge

        return EitaaLoginChallenge(
            challenge_id="fake-challenge",
            phone_number=phone_number,
            phone_code_hash="fake-hash",
            delivery="sms",
            next_delivery="call",
            timeout_seconds=900,
            code_length=5,
        )

    async def resend_login_challenge(self, phone_number: str, phone_code_hash: str):
        return await self.request_login_challenge(phone_number)

    async def complete_login(self, phone_number: str, phone_code_hash: str, otp_code: str):
        from app.eitaa.base import EitaaSession

        if otp_code != "12345":
            from app.eitaa.exceptions import EitaaLoginError

            raise EitaaLoginError("bad code", reason="invalid-code")
        return EitaaSession(
            phone_number=phone_number, token="fake-token", imei="fake-imei", user={"id": 555}
        )

    async def verify_session(self, session):
        from app.eitaa.base import EitaaAccountInfo

        return EitaaAccountInfo(
            user_id=555,
            first_name="Support",
            last_name="Bot",
            username="support_bot",
            phone=session.phone_number,
        )

    async def logout(self, session) -> None:
        pass

    # ---- dialogs / history
    async def list_dialogs(self, session, limit: int = 100):
        from app.eitaa.base import EitaaDialog

        return [EitaaDialog(**d) for d in self.dialogs[:limit]]

    async def get_history(self, session, peer_reference: str, *, limit: int = 50, min_id: int = 0):
        from app.eitaa.base import EitaaMessage

        rows = self.history.get(peer_reference, [])
        return [EitaaMessage(**{**m, "media": None}) for m in rows if m["message_id"] > min_id][
            :limit
        ]

    async def get_message(self, session, peer_reference: str, message_id: int):
        return None

    # ---- sending
    async def send_text(self, session, peer_reference: str, text: str, *, reply_to=None):
        from app.eitaa.base import SendResult
        from app.eitaa.exceptions import EitaaSendError

        if self.fail_sends:
            raise EitaaSendError("Eitaa rejected the message (simulated)")
        self.next_message_id += 1
        self.sent.append({"peer": peer_reference, "text": text, "reply_to": reply_to})
        return SendResult(message_id=self.next_message_id)

    async def send_media(
        self,
        session,
        peer_reference,
        file_path,
        *,
        caption="",
        reply_to=None,
        as_voice=False,
        duration_seconds=0,
    ):
        from app.eitaa.base import SendResult
        from app.eitaa.exceptions import EitaaMediaError

        if self.fail_media_sends:
            raise EitaaMediaError("upload failed (simulated)")
        self.next_message_id += 1
        self.sent.append({"peer": peer_reference, "text": caption, "file": str(file_path)})
        return SendResult(message_id=self.next_message_id)

    async def download_message_media(self, session, peer_reference, message_id, destination):
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / f"fake-{message_id}.bin"
        target.write_bytes(b"fake-media-bytes")
        return target

    async def mark_read(self, session, peer_reference, max_message_id) -> bool:
        self.read_marks.append((peer_reference, max_message_id))
        return True

    @staticmethod
    def peer_deep_link(username):
        return f"https://eitaa.com/{username}" if username else None


# ------------------------------------------------------------------ fixtures
@pytest_asyncio.fixture(scope="session")
async def test_db():
    if not PG_AVAILABLE:
        pytest.skip("PostgreSQL test database unreachable")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await dispose_engine()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(test_db):
    """Truncate all tables between tests (fast, keeps schema)."""
    yield
    async with test_db.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))


@pytest_asyncio.fixture
async def fake_adapter():
    return FakeEitaaAdapter()


@pytest_asyncio.fixture
async def app_client(fake_adapter, test_db):
    """App + HTTP client wired to the fake adapter.

    Patching `app.eitaa.registry.registry` is sufficient: every module calls
    get_registry() which resolves the module-global at call time.
    """
    import app.eitaa.registry as registry_module
    from app.eitaa.registry import EitaaRegistry
    from app.main import create_app

    original_registry = registry_module.registry
    registry_module.registry = EitaaRegistry(adapter=fake_adapter)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    registry_module.registry = original_registry


@pytest_asyncio.fixture
async def seeded_users(test_db):
    """Owner + admin + agent, seeded via the real seed logic."""
    from app.core.security import hash_password
    from app.db.seed import seed
    from app.models import Role, User

    await seed(owner_email="owner@test.local", owner_password="OwnerPass!1", owner_name="Owner")
    factory = get_session_factory()
    async with factory() as db:
        admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
        agent_role = (await db.execute(select(Role).where(Role.name == "agent"))).scalar_one()
        db.add_all(
            [
                User(
                    name="Admin User",
                    email="admin@test.local",
                    password_hash=hash_password("AdminPass!1"),
                    role_id=admin_role.id,
                ),
                User(
                    name="Support Agent",
                    email="agent@test.local",
                    password_hash=hash_password("AgentPass!1"),
                    role_id=agent_role.id,
                ),
                User(
                    name="Second Agent",
                    email="agent2@test.local",
                    password_hash=hash_password("Agent2Pass!1"),
                    role_id=agent_role.id,
                ),
            ]
        )
        await db.commit()
        return {
            "owner": "owner@test.local",
            "admin": "admin@test.local",
            "agent": "agent@test.local",
            "agent2": "agent2@test.local",
        }


async def login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def agent_id_by_email(client: AsyncClient, admin_token: str, email: str) -> int:
    response = await client.get("/api/v1/agents", headers=auth_header(admin_token))
    assert response.status_code == 200
    for item in response.json()["items"]:
        if item["email"] == email:
            return item["id"]
    raise AssertionError(f"agent {email} not found")


async def link_agents(
    client: AsyncClient, owner_token: str, account_id: int, agent_ids: list[int]
) -> None:
    response = await client.patch(
        f"/api/v1/eitaa/accounts/{account_id}",
        json={"agent_ids": agent_ids},
        headers=auth_header(owner_token),
    )
    assert response.status_code == 200, response.text


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def owner_token(app_client, seeded_users):
    return await login(app_client, "owner@test.local", "OwnerPass!1")


@pytest_asyncio.fixture
async def admin_token(app_client, seeded_users):
    return await login(app_client, "admin@test.local", "AdminPass!1")


@pytest_asyncio.fixture
async def agent_token(app_client, seeded_users):
    return await login(app_client, "agent@test.local", "AgentPass!1")


@pytest_asyncio.fixture
async def agent2_token(app_client, seeded_users):
    return await login(app_client, "agent2@test.local", "Agent2Pass!1")


@pytest_asyncio.fixture
async def connected_account(app_client, owner_token, fake_adapter):
    """One Eitaa account connected through the (fake) OTP flow."""
    response = await app_client.post(
        "/api/v1/eitaa/accounts/request-code",
        json={"phone_number": "09120000001"},
        headers=auth_header(owner_token),
    )
    assert response.status_code == 200, response.text
    challenge_id = response.json()["challenge_id"]

    response = await app_client.post(
        "/api/v1/eitaa/accounts/verify",
        json={"challenge_id": challenge_id, "otp_code": "12345"},
        headers=auth_header(owner_token),
    )
    assert response.status_code == 201, response.text
    return response.json()
