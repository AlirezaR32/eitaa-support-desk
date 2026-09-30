"""All SQLAlchemy models — import everything so Alembic sees the full metadata."""

from app.db.base import Base
from app.models.conversation import (
    AnswerState,
    Conversation,
    ConversationStatus,
    InternalNote,
    Message,
    MessageAttachment,
    MessageDirection,
    MessageSource,
    ReadState,
    SendStatus,
    SkipReason,
)
from app.models.eitaa import AuthChallenge, EitaaAccount, EitaaAccountLink, EitaaAccountStatus
from app.models.misc import AuditLog, Notification, SyncState
from app.models.user import Permission, RefreshToken, Role, RolePermission, User, UserPermission

__all__ = [
    "Base",
    "Permission",
    "RefreshToken",
    "Role",
    "RolePermission",
    "User",
    "UserPermission",
    "AuthChallenge",
    "EitaaAccount",
    "EitaaAccountLink",
    "EitaaAccountStatus",
    "AnswerState",
    "Conversation",
    "ConversationStatus",
    "InternalNote",
    "Message",
    "MessageAttachment",
    "MessageDirection",
    "MessageSource",
    "ReadState",
    "SendStatus",
    "SkipReason",
    "AuditLog",
    "Notification",
    "SyncState",
]
