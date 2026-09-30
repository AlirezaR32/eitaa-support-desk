"""Integration: Eitaa account OTP flow + notifications dedup + dashboard numbers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import Conversation
from app.services import note_service
from app.workers.sync_worker import sync_worker
from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


async def test_otp_flow_creates_connected_account(
    app_client, seeded_users, fake_adapter, owner_token
):
    request = await app_client.post(
        "/api/v1/eitaa/accounts/request-code",
        json={"phone_number": "09123334455"},
        headers=auth_header(owner_token),
    )
    assert request.status_code == 200
    challenge = request.json()
    assert challenge["delivery"] == "sms"
    assert "phone_code_hash" not in challenge  # sensitive value never leaks

    wrong = await app_client.post(
        "/api/v1/eitaa/accounts/verify",
        json={"challenge_id": challenge["challenge_id"], "otp_code": "00000"},
        headers=auth_header(owner_token),
    )
    assert wrong.status_code == 422  # invalid code does NOT consume the challenge

    right = await app_client.post(
        "/api/v1/eitaa/accounts/verify",
        json={"challenge_id": challenge["challenge_id"], "otp_code": "12345"},
        headers=auth_header(owner_token),
    )
    assert right.status_code == 201
    account = right.json()
    assert account["status"] == "connected"
    assert account["username"] == "support_bot"
    assert account["deep_link"] == "https://eitaa.com/support_bot"
    assert "session" not in account  # no session material in responses

    # session is stored encrypted, not plaintext
    from app.models import EitaaAccount

    factory = get_session_factory()
    async with factory() as db:
        row = (
            await db.execute(select(EitaaAccount).where(EitaaAccount.id == account["id"]))
        ).scalar_one()
        assert row.session_encrypted
        assert b"fake-token" not in row.session_encrypted  # encrypted at rest


async def test_duplicate_phone_rejected(app_client, seeded_users, connected_account, owner_token):
    response = await app_client.post(
        "/api/v1/eitaa/accounts/request-code",
        json={"phone_number": "09120000001"},  # already connected
        headers=auth_header(owner_token),
    )
    assert response.status_code == 409


async def test_notifications_deduplicated(
    app_client, seeded_users, connected_account, fake_adapter, owner_token, agent_token
):
    fake_adapter.seed_dialog(301, "Nima", top=1, unread=1)
    fake_adapter.seed_message(301, text="چرا جواب نمی‌دید؟")
    assert await sync_worker.sync_all() >= 1

    factory = get_session_factory()
    async with factory() as db:
        conversation = (
            await db.execute(select(Conversation).where(Conversation.peer_id == 301))
        ).scalar_one()
        # make the inbound message look 20 minutes old
        old = datetime.now(timezone.utc) - timedelta(minutes=20)
        conversation.last_inbound_message_at = old
        conversation.last_message_at = old
        await db.commit()

    # assign to agent (user id 3 = first agent)
    assigned = await app_client.post(
        f"/api/v1/conversations/{conversation.id}/assign",
        json={"agent_id": 3},
        headers=auth_header(owner_token),
    )
    assert assigned.status_code == 200

    # run the sweeper twice — notifications must NOT duplicate
    async with factory() as db:
        created1 = await note_service.notify_unanswered_conversations(db, older_than_seconds=600)
        await db.commit()
        created2 = await note_service.notify_unanswered_conversations(db, older_than_seconds=600)
        await db.commit()
    assert created1 == 1
    assert created2 == 0

    unread_response = await app_client.get(
        "/api/v1/notifications/unread-count", headers=auth_header(agent_token)
    )
    unread = unread_response.json()
    assert unread["count"] == 1

    # mark all read
    await app_client.post("/api/v1/notifications/read-all", headers=auth_header(agent_token))
    unread_response = await app_client.get(
        "/api/v1/notifications/unread-count", headers=auth_header(agent_token)
    )
    unread = unread_response.json()
    assert unread["count"] == 0


async def test_dashboard_numbers_from_real_rows(
    app_client, seeded_users, connected_account, fake_adapter, owner_token
):
    fake_adapter.seed_dialog(401, "A", top=1, unread=1)
    fake_adapter.seed_dialog(402, "B", top=1, unread=1)
    fake_adapter.seed_message(401, text="salam")
    fake_adapter.seed_message(402, text="hello")
    assert await sync_worker.sync_all() >= 1

    stats_response = await app_client.get(
        "/api/v1/dashboard/stats", headers=auth_header(owner_token)
    )
    stats = stats_response.json()
    assert stats["total_conversations"] == 2
    assert stats["unanswered"] == 2
    assert stats["unassigned"] == 2
    assert stats["unread"] == 2
    assert stats["messages_today"] >= 2
    assert stats["active_agents"] >= 1
    assert stats["avg_first_response_seconds"] is None  # nobody replied yet


async def test_deep_link_only_with_real_username(
    app_client, seeded_users, connected_account, fake_adapter, owner_token
):
    """§7 — links are built ONLY from usernames Eitaa actually returned."""
    fake_adapter.seed_dialog(501, "WithUsername", username="has_username", top=1)
    fake_adapter.seed_dialog(502, "NoUsername", username=None, top=1)
    assert await sync_worker.sync_all() >= 1

    factory = get_session_factory()
    async with factory() as db:
        with_link = (
            await db.execute(select(Conversation).where(Conversation.peer_id == 501))
        ).scalar_one()
        without_link = (
            await db.execute(select(Conversation).where(Conversation.peer_id == 502))
        ).scalar_one()

    detail_response = await app_client.get(
        f"/api/v1/conversations/{with_link.id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["deep_link"] == "https://eitaa.com/has_username"

    detail_response = await app_client.get(
        f"/api/v1/conversations/{without_link.id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["deep_link"] is None  # never guess a link
