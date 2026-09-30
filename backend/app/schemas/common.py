"""Pydantic v2 schemas — API contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

try:
    import re

    _EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

    def _email_syntax_only(value: str) -> str:
        """Syntax-validated email (no DNS/deliverability/special-use checks) —
        private deployments may use intranet domains like owner@desk.local."""
        normalized = value.strip().lower()
        if not _EMAIL_RE.match(normalized) or len(normalized) > 254:
            raise ValueError("Invalid email address")
        return normalized

    EmailStr = Annotated[str, AfterValidator(_email_syntax_only)]
except ImportError:  # pragma: no cover
    from pydantic import EmailStr  # type: ignore[assignment]


# ---------------------------------------------------------------- shared
class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


# ---------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: "AgentOut"


class RefreshResult(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UpdateProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    username: str | None = Field(default=None, min_length=2, max_length=60)


# ---------------------------------------------------------------- agents
class RoleOut(ORMModel):
    id: int
    name: str
    description: str | None


class AgentOut(ORMModel):
    id: int
    name: str
    username: str | None
    email: EmailStr
    role: str = ""
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    permissions: list[str] = []
    eitaa_account_ids: list[int] = []


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    username: Annotated[str, StringConstraints(min_length=2, max_length=60)] | None = None
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["owner", "admin", "agent"] = "agent"
    is_active: bool = True
    eitaa_account_ids: list[int] = []


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    username: str | None = Field(default=None, min_length=2, max_length=60)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: Literal["owner", "admin", "agent"] | None = None
    is_active: bool | None = None
    eitaa_account_ids: list[int] | None = None


# ---------------------------------------------------------------- eitaa accounts
class EitaaAccountOut(ORMModel):
    id: int
    phone_number: str
    display_name: str | None
    username: str | None
    eitaa_user_id: int | None
    status: str
    sync_enabled: bool
    last_sync_at: datetime | None
    last_sync_ok: bool | None
    last_error: str | None
    agent_ids: list[int] = []
    deep_link: str | None = None


class RequestCodeRequest(BaseModel):
    phone_number: str = Field(min_length=6, max_length=20)


class ResendCodeRequest(BaseModel):
    challenge_id: str


class VerifyCodeRequest(BaseModel):
    challenge_id: str
    otp_code: str = Field(min_length=3, max_length=12)


class LoginChallengeOut(BaseModel):
    challenge_id: str
    phone_number: str
    delivery: str
    next_delivery: str | None
    timeout_seconds: int | None
    code_length: int | None


class EitaaAccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    sync_enabled: bool | None = None
    agent_ids: list[int] | None = None


# ---------------------------------------------------------------- conversations
class AttachmentOut(ORMModel):
    id: int
    kind: str
    file_name: str | None
    mime_type: str | None
    size_bytes: int | None
    duration_seconds: int | None
    width: int | None
    height: int | None
    download_status: str
    download_url: str | None = None


class MessageOut(ORMModel):
    id: int
    conversation_id: int
    eitaa_message_id: int | None
    direction: str
    source: str
    text: str
    sender_agent_id: int | None
    sender_agent_name: str | None = None
    send_status: str
    error_message: str | None
    sent_at: datetime | None
    created_at: datetime
    reply_to_message_id: int | None
    reply_preview: str | None = None
    attachment: AttachmentOut | None = None


class NoteOut(ORMModel):
    id: int
    conversation_id: int
    author_id: int | None
    author_name: str | None = None
    body: str
    created_at: datetime


class ConversationOut(ORMModel):
    id: int
    eitaa_account_id: int
    eitaa_account_phone: str | None = None
    peer_type: str
    peer_id: int
    peer_kind: str
    title: str
    username: str | None
    phone: str | None
    status: str
    read_state: str
    answer_state: str
    assigned_agent_id: int | None
    assigned_agent_name: str | None = None
    last_message_at: datetime | None
    last_message_preview: str
    last_inbound_message_at: datetime | None
    unread_eitaa_count: int
    skip_reason: str | None
    deep_link: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    first_inbound_at: datetime | None
    first_agent_reply_at: datetime | None
    closed_at: datetime | None
    previous_conversations: list["ConversationOut"] = []


class SkipRequest(BaseModel):
    reason: Literal["spam", "wrong_message", "not_relevant", "handled_elsewhere", "other"] = "other"
    note: str | None = Field(default=None, max_length=300)


class AssignRequest(BaseModel):
    agent_id: int | None = None  # None = unassign


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class SendMessageRequest(BaseModel):
    text: str = Field(default="", max_length=4096)
    reply_to_message_id: int | None = None


# ---------------------------------------------------------------- notifications
class NotificationOut(ORMModel):
    id: int
    type: str
    conversation_id: int | None
    title: str
    body: str
    is_read: bool
    created_at: datetime


class UnreadCount(BaseModel):
    count: int


# ---------------------------------------------------------------- dashboard
class DashboardStats(BaseModel):
    unread: int
    unanswered: int
    answered_today: int
    waiting_user: int
    skipped: int
    closed: int
    my_conversations: int
    unassigned: int
    total_conversations: int
    avg_first_response_seconds: float | None
    avg_resolution_seconds: float | None
    messages_today: int
    active_agents: int


# ---------------------------------------------------------------- audit
class AuditLogOut(ORMModel):
    id: int
    actor_id: int | None
    actor_name: str
    action: str
    target_type: str | None
    target_id: str | None
    meta: dict | None
    ip: str | None
    created_at: datetime


# ---------------------------------------------------------------- capabilities
class Capabilities(BaseModel):
    """What the backend (and thereby Eitaa) can actually do — the UI adapts."""

    send_text: bool = True
    send_media: bool = True
    send_voice: bool = True
    receive_media: bool = True
    reply_to: bool = True
    mark_read_best_effort: bool = True
    real_time: bool = False  # eitaa-cli has no update stream; panel realtime is via WebSocket push from the sync worker
    sync_interval_seconds: int
    max_upload_size_mb: int
    allowed_extensions: list[str]
    deep_link_supported: bool = True  # only for peers with a public username


TokenPair.model_rebuild()
ConversationDetail.model_rebuild()
