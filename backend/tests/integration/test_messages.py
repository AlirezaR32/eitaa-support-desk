"""Integration: message sending pipeline — success, failure, retry, assignment guard."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import Conversation
from app.workers.sync_worker import sync_worker
from tests.conftest import FakeEitaaAdapter, agent_id_by_email, auth_header, link_agents

pytestmark = pytest.mark.asyncio


@pytest.fixture
def seeded_adapter(fake_adapter: FakeEitaaAdapter) -> FakeEitaaAdapter:
    fake_adapter.seed_dialog(201, "Reza", top=1, unread=1)
    fake_adapter.seed_message(201, text="پیام تست")
    return fake_adapter


async def _setup(app_client, owner_token, seeded_adapter):
    assert await sync_worker.sync_all() >= 1
    factory = get_session_factory()
    async with factory() as db:
        conversation = (
            await db.execute(select(Conversation).where(Conversation.peer_id == 201))
        ).scalar_one()
        return conversation.id


async def test_send_text_success_and_auto_claim(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    conversation_id = await _setup(app_client, owner_token, seeded_adapter)
    response = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        data={"text": "سلام، پاسخ پشتیبانی"},
        headers=auth_header(owner_token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["send_status"] == "sent"
    assert body["direction"] == "outbound"
    assert body["eitaa_message_id"]  # adapter echoed an id

    detail_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["answer_state"] == "answered"
    assert detail["assigned_agent_id"] is not None  # auto-claim on first reply


async def test_send_failure_marks_failed_and_retry_works(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    conversation_id = await _setup(app_client, owner_token, seeded_adapter)
    seeded_adapter.fail_sends = True

    failed = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        data={"text": "این پیام fail می‌شود"},
        headers=auth_header(owner_token),
    )
    assert failed.status_code == 201  # the row exists...
    body = failed.json()
    assert body["send_status"] == "failed"
    assert body["error_message"]

    # conversation stays unanswered after a failed send
    detail_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=auth_header(owner_token)
    )
    detail = detail_response.json()
    assert detail["answer_state"] == "unanswered"

    # provider recovers -> retry flips it to sent
    seeded_adapter.fail_sends = False
    retried = await app_client.post(
        f"/api/v1/messages/{body['id']}/retry", headers=auth_header(owner_token)
    )
    assert retried.status_code == 200
    assert retried.json()["send_status"] == "sent"


async def test_reply_references_original(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    conversation_id = await _setup(app_client, owner_token, seeded_adapter)
    messages_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=auth_header(owner_token),
    )
    messages = messages_response.json()
    original = messages["items"][0]

    reply = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        data={"text": "پاسخ به پیام شما", "reply_to_message_id": original["id"]},
        headers=auth_header(owner_token),
    )
    assert reply.status_code == 201
    assert reply.json()["reply_to_message_id"] == original["id"]
    assert reply.json()["reply_preview"] == "پیام تست"


async def test_send_blocked_when_assigned_to_another_agent(
    app_client,
    seeded_users,
    connected_account,
    seeded_adapter,
    owner_token,
    agent_token,
    agent2_token,
):
    """§39 — server-side assignment re-validation before sending."""
    agent1_id = await agent_id_by_email(app_client, owner_token, "agent@test.local")
    agent2_id = await agent_id_by_email(app_client, owner_token, "agent2@test.local")
    await link_agents(app_client, owner_token, connected_account["id"], [agent1_id, agent2_id])
    conversation_id = await _setup(app_client, owner_token, seeded_adapter)

    claimed = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/claim", headers=auth_header(agent_token)
    )
    assert claimed.status_code == 200

    blocked = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        data={"text": "should be rejected"},
        headers=auth_header(agent2_token),
    )
    assert blocked.status_code == 409
    assert "assigned to another agent" in blocked.json()["error"]["message"]


async def test_send_media_with_upload(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    conversation_id = await _setup(app_client, owner_token, seeded_adapter)

    # a tiny valid PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d4944415478da63fcffff3f0300050201cfa02d0f0000000049454e44ae426082"
    )
    response = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        files={"file": ("chart.png", png, "image/png")},
        data={"text": "نمودار مورد نظر"},
        headers=auth_header(owner_token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["send_status"] == "sent"
    assert body["attachment"]["kind"] == "photo"
    assert body["attachment"]["mime_type"] == "image/png"


async def test_upload_rejects_oversize(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    conversation_id = await _setup(app_client, owner_token, seeded_adapter)
    big = b"x" * (26 * 1024 * 1024)  # MAX_UPLOAD_SIZE_MB default = 25
    response = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        files={"file": ("big.zip", big, "application/zip")},
        data={"text": ""},
        headers=auth_header(owner_token),
    )
    assert response.status_code == 422
    assert "too large" in response.json()["error"]["message"].lower()


async def test_upload_rejects_bad_extension(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    conversation_id = await _setup(app_client, owner_token, seeded_adapter)
    response = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        files={"file": ("malware.exe", b"MZ...", "application/x-msdownload")},
        headers=auth_header(owner_token),
    )
    assert response.status_code == 422
    assert "not allowed" in response.json()["error"]["message"]


async def test_internal_note_never_sent_to_eitaa(
    app_client, seeded_users, connected_account, seeded_adapter, owner_token
):
    conversation_id = await _setup(app_client, owner_token, seeded_adapter)
    note = await app_client.post(
        f"/api/v1/conversations/{conversation_id}/notes",
        json={"body": "این کاربر باید به آموزش ارجاع شود"},
        headers=auth_header(owner_token),
    )
    assert note.status_code == 201

    notes_response = await app_client.get(
        f"/api/v1/conversations/{conversation_id}/notes",
        headers=auth_header(owner_token),
    )
    notes = notes_response.json()
    assert len(notes) == 1

    # the fake adapter saw NO send for the note
    assert all("ارجاع" not in (s.get("text") or "") for s in seeded_adapter.sent)
