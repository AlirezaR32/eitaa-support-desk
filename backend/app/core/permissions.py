"""RBAC: extensible permission registry.

Permission *codes* live here as a vocabulary and are seeded into the database
(`permissions`, `roles`, `role_permissions`, `user_permissions`), so access
control is data-driven: new permissions/roles can be added without code changes
to endpoints — endpoints only declare the permission they need.

Roles seeded by default: owner (everything), admin, agent.
"""

from __future__ import annotations

# Permission catalogue -------------------------------------------------------
# Format: CODE -> (description, default_roles)
PERMISSIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    # conversations
    "conversation.view.all": ("See every conversation on every account", ("owner", "admin")),
    "conversation.view.account": (
        "See conversations of accounts linked to the agent",
        ("owner", "agent"),
    ),
    "conversation.read.mark": ("Mark a conversation as read", ("owner", "admin", "agent")),
    "conversation.claim": ("Claim an unassigned conversation", ("owner", "admin", "agent")),
    "conversation.release": ("Release an assigned conversation", ("owner", "admin", "agent")),
    "conversation.assign": ("Assign/reassign/take over any conversation", ("owner", "admin")),
    "conversation.status.manage": (
        "Skip / close / reopen / set waiting-for-user",
        ("owner", "admin", "agent"),
    ),
    "conversation.skip": ("Skip (ignore) a conversation", ("owner", "admin", "agent")),
    # messaging
    "message.send": ("Send replies to users", ("owner", "admin", "agent")),
    "message.view": ("View message history", ("owner", "admin", "agent")),
    "attachment.download": ("Download message media", ("owner", "admin", "agent")),
    # notes
    "note.create": ("Add internal notes", ("owner", "admin", "agent")),
    "note.delete": (
        "Delete internal notes (own notes, or any with admin)",
        ("owner", "admin", "agent"),
    ),
    # people
    "agent.manage": ("Create / edit / disable support agents", ("owner", "admin")),
    "agent.view": ("List agents and their connection status", ("owner", "admin")),
    # eitaa accounts
    "eitaa.account.manage": ("Connect / disconnect / configure Eitaa accounts", ("owner",)),
    "eitaa.account.view": ("View Eitaa accounts", ("owner", "admin")),
    # notifications & dashboard
    "notification.view": ("See own notifications", ("owner", "admin", "agent")),
    "dashboard.view": ("View dashboard statistics", ("owner", "admin")),
    "dashboard.view.own": ("View own personal statistics", ("owner", "agent")),
    # audit & settings
    "audit.view": ("View the audit log", ("owner", "admin")),
    "settings.manage": ("Manage system settings", ("owner",)),
    "role.manage": ("Manage roles and permission overrides", ("owner",)),
    "search.all": ("Search across all conversations", ("owner", "admin")),
    "search.account": ("Search within permitted conversations", ("owner", "agent")),
}

ALL_PERMISSION_CODES = tuple(PERMISSIONS.keys())

ROLE_DESCRIPTIONS: dict[str, str] = {
    "owner": "Full access — manages admins, agents, accounts, settings and sees everything.",
    "admin": "Manages support agents and conversations, assigns, views logs; limited settings.",
    "agent": "Answers users on permitted conversations; claims, notes, status changes.",
}

SYSTEM_ROLES: tuple[str, ...] = ("owner", "admin", "agent")


def default_roles_for(code: str) -> tuple[str, ...]:
    return PERMISSIONS[code][1]
