"""Integration: auth (login, refresh rotation, reuse detection, password change)."""

from __future__ import annotations

import pytest

from tests.conftest import auth_header, login

pytestmark = pytest.mark.asyncio


async def test_login_returns_tokens_and_permissions(app_client, seeded_users):
    data = (
        await app_client.post(
            "/api/v1/auth/login", json={"email": "owner@test.local", "password": "OwnerPass!1"}
        )
    ).json()
    assert data["user"]["role"] == "owner"
    assert "agent.manage" in data["user"]["permissions"]
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(app_client, seeded_users):
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@test.local", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_login_disabled_agent(app_client, seeded_users, owner_token):
    # create then disable an agent, then attempt login
    created = await app_client.post(
        "/api/v1/agents",
        json={
            "name": "Temp",
            "email": "temp@test.local",
            "password": "TempPass!1",
            "role": "agent",
        },
        headers=auth_header(owner_token),
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]
    deleted = await app_client.delete(
        f"/api/v1/agents/{agent_id}", headers=auth_header(owner_token)
    )
    assert deleted.status_code == 200
    response = await app_client.post(
        "/api/v1/auth/login", json={"email": "temp@test.local", "password": "TempPass!1"}
    )
    assert response.status_code == 401


async def test_refresh_rotation_and_reuse_detection(app_client, seeded_users):
    login_response = await app_client.post(
        "/api/v1/auth/login", json={"email": "owner@test.local", "password": "OwnerPass!1"}
    )
    cookie = login_response.headers["set-cookie"].split(";")[0]

    first = await app_client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": cookie, "Origin": "http://localhost:5173"},
    )
    assert first.status_code == 200

    # replaying the SAME (now rotated) token must be rejected + family revoked
    replay = await app_client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": cookie, "Origin": "http://localhost:5173"},
    )
    assert replay.status_code == 401


async def test_me_requires_token(app_client, seeded_users):
    response = await app_client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_change_password_invalidates_tokens(app_client, seeded_users, agent_token):
    changed = await app_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "AgentPass!1", "new_password": "NewAgentPass!1"},
        headers=auth_header(agent_token),
    )
    assert changed.status_code == 200

    stale = await app_client.get("/api/v1/auth/me", headers=auth_header(agent_token))
    assert stale.status_code == 401  # token_version bumped -> revoked

    fresh = await login(app_client, "agent@test.local", "NewAgentPass!1")
    me = await app_client.get("/api/v1/auth/me", headers=auth_header(fresh))
    assert me.status_code == 200
