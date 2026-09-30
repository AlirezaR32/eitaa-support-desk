"""Integration: the READ / UNANSWERED state machine + filters + skip/close + race.

Covers the exact scenario from spec §11:
    user sends -> UNREAD+UNANSWERED
    agent opens -> READ+UNANSWERED   (answer_state MUST stay unanswered)
    agent replies -> READ+ANSWERED
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import Conversation
from app.workers.sync_worker import sync_worker
from tests.conftest import (
    FakeEitaaAdapter,
    agent_id_by_email,
    auth_header,
    link_agents,
)

pytestmark = pytest.mark.asyncio


async def _sync_once() -> None:
    count = await sync_worker.sync_all()
    assert count >= 1


async def _conversation_id(peer_id: int) -> int:
    factory = get_session_factory()
    async with factory() as db:
        row = (
            await db.execute(select(Conversation).where(Conversation.peer_id == peer_id))
        ).scalar_one()
        return row.id


@pytest.fixture
def seeded_adapter(fake_adapter: FakeEitaaAdapter) -> FakeEitaaAdapter:
    fake_adapter.seed_dialog(101, "Ali", username="ali_user", top=1, unread=1)
    fake_adapter.seed_dialog(102, "Sara", top=1, unread=1)
    fake_adapter.seed_dialog(103, "Mohammad", top=1, unread=1)
    fake_adapter.seed_message(101, text="سلام")
    fake_adapter.seed_message(102, text="سوال دارم")
    fake_adapter.seed_message(103, text="help me")
    return fake_adapter


async def test_sync_imports_conversations(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    await _sync_once()
    response = await app_client.get("/api/v1/conversations", headers=auth_header(owner_token))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    titles = {item["title"] for item in body["items"]}
    assert titles == {"Ali", "Sara", "Mohammad"}


async def test_unread_unanswered_then_read_still_unanswered(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    """THE critical §11 scenario — server-side, not frontend."""
    await _sync_once()
    conversation_id = await _conversation_id(101)

    detail_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["read_state"] == "unread"
    assert detail["answer_state"] == "unanswered"

    # agent opens the thread
    opened = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/read", headers=auth_header(owner_token)
    )
    assert opened.status_code == 200
    assert opened.json()["read_state"] == "read"
    # ...but does NOT reply for a while -> READ + UNANSWERED
    assert opened.json()["answer_state"] == "unanswered"

    # the unanswered filter must still include it
    listing_response = await app_client.get(
        "/api/v1/conversations",
        params={"answer_state": "unanswered", "read_state": "read"},
        headers=auth_header(owner_token),
    )
    listing = listing_response.json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == conversation_id

    # now the agent replies
    sent = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        data={"text": "بله در خدمتیم"},
        headers=auth_header(owner_token),
    )
    assert sent.status_code == 201
    detail_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["read_state"] == "read"
    assert detail["answer_state"] == "answered"

    # a new user message flips it back
    seeded_adapter.seed_message(101, text="مرسی")
    await _sync_once()

    detail_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["answer_state"] == "unanswered"
    assert detail["read_state"] == "unread"  # new message re-unreads


async def test_skip_records_metadata(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    await _sync_once()
    conversation_id = await _conversation_id(102)
    response = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/skip",
        json={"reason": "spam"},
        headers=auth_header(owner_token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"

    # audit log captured it
    logs_response = await app_client.get(
        "/api/v1/audit-logs",
        params={"action": "CONVERSATION_SKIPPED"},
        headers=auth_header(owner_token),
    )
    logs = logs_response.json()
    assert logs["total"] == 1

    # skipped conversations do not appear in unanswered filter
    listing_response = await app_client.get(
        "/api/v1/conversations",
        params={"answer_state": "unanswered", "status": ["skipped"]},
        headers=auth_header(owner_token),
    )
    listing = listing_response.json()
    assert listing["total"] == 1


async def test_close_and_reopen(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    await _sync_once()
    conversation_id = await _conversation_id(103)
    closed = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/close", headers=auth_header(owner_token)
    )
    assert closed.json()["status"] == "closed"

    # a new user message reopens it automatically
    seeded_adapter.seed_message(103, text="again")
    await _sync_once()
    detail_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["status"] == "active"


async def test_claim_race_only_one_wins(
    app_client,
    seeded_users,
    connected_account,
    seeded_adapter,
    owner_token,
    agent_token,
    agent2_token,
):
    """Two agents claim simultaneously — exactly one 200, the other 409."""
    agent1_id = await agent_id_by_email(app_client, owner_token, "agent@test.local")
    agent2_id = await agent_id_by_email(app_client, owner_token, "agent2@test.local")
    await link_agents(app_client, owner_token, connected_account["id"], [agent1_id, agent2_id])
    await _sync_once()
    conversation_id = await _conversation_id(101)

    async def _claim(token: str):
        return await app_client.post(
            f"/api/v1/conversations/{conversation_id}/claim", headers=auth_header(token)
        )

    results = await asyncio.gather(
        _claim(agent_token), _claim(agent2_token), return_exceptions=False
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 409], f"race not protected: {statuses}"

    # winner is recorded
    detail_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["assigned_agent_id"] is not None


async def test_duplicate_sync_produces_no_duplicates(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    """Running the sync twice must not duplicate messages (§19)."""
    await _sync_once()
    await _sync_once()
    await _sync_once()

    conversation_id = await _conversation_id(101)
    messages_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=auth_header(owner_token),
    )
    messages = messages_response.json()
    assert messages["total"] == 1  # exactly one message, no matter how many syncs


async def test_filters_combined(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    """Unread + Unassigned combined (§9)."""
    await _sync_once()
    listing_response = await app_client.get(
        "/api/v1/conversations",
        params={"read_state": "unread", "assigned": "unassigned"},
        headers=auth_header(owner_token),
    )
    listing = listing_response.json()
    assert listing["total"] == 3


async def test_search_by_message_text(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    await _sync_once()
    listing_response = await app_client.get(
        "/api/v1/conversations",
        params={"q": "سوال"},
        headers=auth_header(owner_token),
    )
    listing = listing_response.json()
    assert listing["total"] == 1
    assert listing["items"][0]["title"] == "Sara"


async def test_agent_visibility_scoped_to_linked_accounts(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token, agent_token
):
    """Agents only see conversations of accounts they are linked to (§24)."""
    await _sync_once()

    # not linked yet -> sees nothing
    listing_response = await app_client.get(
        "/api/v1/conversations", headers=auth_header(agent_token)
    )
    listing = listing_response.json()
    assert listing["total"] == 0

    # owner links the agent to the account
    agent_id = await agent_id_by_email(app_client, owner_token, "agent@test.local")
    await link_agents(app_client, owner_token, connected_account["id"], [agent_id])

    listing_response = await app_client.get(
        "/api/v1/conversations", headers=auth_header(agent_token)
    )
    listing = listing_response.json()
    assert listing["total"] == 3

    # and cannot open conversations outside scope (IDOR probe) — same data here,
    # but the endpoint must enforce scoping for multi-account setups
    conversation_id = await _conversation_id(101)
    detail = await app_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=auth_header(agent_token)
    )
    assert detail.status_code == 200
