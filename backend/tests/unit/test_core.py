"""Unit tests: state machine logic, phone normalization, sanitization, RBAC registry."""

from __future__ import annotations

import pytest

from app.core.logging import sanitize_value
from app.core.permissions import ALL_PERMISSION_CODES, PERMISSIONS, default_roles_for
from app.services.eitaa_account_service import normalize_phone
from app.services.errors import ValidationError


# ------------------------------------------------------------------ phone
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+989121234567", "989121234567"),
        ("00989121234567", "989121234567"),
        ("09121234567", "989121234567"),
        ("989121234567", "989121234567"),
        ("+1 555 010 2030", "15550102030"),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["123", "", "abc"])
def test_normalize_phone_invalid(raw):
    with pytest.raises(ValidationError):
        normalize_phone(raw)


# ------------------------------------------------------------------ sanitizer
def test_sanitize_masks_tokens_and_otps():
    payload = {
        "password": "super-secret",
        "otp": "12345",
        "nested": {"phone_code_hash": "abc", "fine": "ok"},
        "items": [{"token": "t1"}, {"name": "ali"}],
    }
    out = sanitize_value(payload)
    assert out["password"] == "***"
    assert out["otp"] == "***"
    assert out["nested"]["phone_code_hash"] == "***"
    assert out["nested"]["fine"] == "ok"
    assert out["items"][0]["token"] == "***"
    assert out["items"][1]["name"] == "ali"


def test_sanitize_depth_limit():
    deep = {"a": {"b": {"c": {"d": {"e": {"f": "x"}}}}}}
    out = sanitize_value(deep)
    assert out is not None  # no crash


# ------------------------------------------------------------------ RBAC catalogue
def test_owner_gets_every_permission():
    for code in ALL_PERMISSION_CODES:
        assert "owner" in default_roles_for(code), f"owner missing {code}"


def test_agent_cannot_manage_agents():
    assert "agent" not in default_roles_for("agent.manage")
    assert "agent" not in default_roles_for("eitaa.account.manage")


def test_agent_can_reply_and_note():
    assert "agent" in default_roles_for("message.send")
    assert "agent" in default_roles_for("note.create")
    assert "agent" in default_roles_for("conversation.claim")


def test_permission_registry_is_consistent():
    for code, (_desc, roles) in PERMISSIONS.items():
        assert isinstance(roles, tuple) and all(r in {"owner", "admin", "agent"} for r in roles), (
            code
        )
