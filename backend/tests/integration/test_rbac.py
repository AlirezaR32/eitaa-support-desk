"""Integration: RBAC / agent management / IDOR protection."""

from __future__ import annotations

import pytest

from tests.conftest import auth_header

pytestmark = pytest.mark.asyncio


async def test_agent_cannot_list_agents(app_client, seeded_users, agent_token):
    response = await app_client.get("/api/v1/agents", headers=auth_header(agent_token))
    assert response.status_code == 403


async def test_admin_can_list_and_create_agents(app_client, seeded_users, admin_token):
    listed = await app_client.get("/api/v1/agents", headers=auth_header(admin_token))
    assert listed.status_code == 200
    assert listed.json()["total"] >= 3

    created = await app_client.post(
        "/api/v1/agents",
        json={
            "name": "New Agent",
            "email": "newagent@test.local",
            "password": "NewAgent!23",
            "role": "agent",
        },
        headers=auth_header(admin_token),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["role"] == "agent"
    assert "password" not in body and "password_hash" not in body


async def test_admin_cannot_create_owner(app_client, seeded_users, admin_token):
    response = await app_client.post(
        "/api/v1/agents",
        json={
            "name": "Escalate",
            "email": "esc@test.local",
            "password": "Escalate!23",
            "role": "owner",
        },
        headers=auth_header(admin_token),
    )
    assert response.status_code in (403, 422)  # privilege escalation blocked


async def test_agent_cannot_connect_eitaa_account(app_client, seeded_users, agent_token):
    response = await app_client.post(
        "/api/v1/eitaa/accounts/request-code",
        json={"phone_number": "09120000009"},
        headers=auth_header(agent_token),
    )
    assert response.status_code == 403


async def test_duplicate_email_rejected(app_client, seeded_users, admin_token):
    response = await app_client.post(
        "/api/v1/agents",
        json={
            "name": "Dup",
            "email": "admin@test.local",
            "password": "Whatever!23",
            "role": "agent",
        },
        headers=auth_header(admin_token),
    )
    assert response.status_code == 409


async def test_agent_cannot_view_audit_logs(app_client, seeded_users, agent_token):
    response = await app_client.get("/api/v1/audit-logs", headers=auth_header(agent_token))
    assert response.status_code == 403


async def test_agent_dashboard_scoped_not_admin(app_client, seeded_users, agent_token):
    # agent has dashboard.view.own — endpoint must still answer 200
    response = await app_client.get("/api/v1/dashboard/stats", headers=auth_header(agent_token))
    assert response.status_code == 200
