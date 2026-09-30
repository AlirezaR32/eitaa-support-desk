"""Conversations, messages, attachments, internal notes.

State model (three INDEPENDENT dimensions — see ARCHITECTURE.md §state-machine):

  read_state   : unread | read          — did any agent OPEN the conversation?
  answer_state : unanswered | answered  — is the LAST message from the user?
  status       : active | waiting_user | skipped | closed  — workflow status

Example: agent opens the thread but does not reply  ->  READ + UNANSWERED
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    WAITING_USER = "waiting_user"
    SKIPPED = "skipped"
    CLOSED = "closed"


class ReadState(str, enum.Enum):
    UNREAD = "unread"
    READ = "read"


class AnswerState(str, enum.Enum):
    UNANSWERED = "unanswered"
    ANSWERED = "answered"


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"  # from the Eitaa user
    OUTBOUND = "outbound"  # from the panel (agent) or from the Eitaa app itself


class MessageSource(str, enum.Enum):
    SYNC = "sync"  # discovered by the sync worker
    PANEL = "panel"  # sent through the support panel
    EITAA_APP = "eitaa_app"  # the account owner replied from the Eitaa app directly


class SendStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class SkipReason(str, enum.Enum):
    SPAM = "spam"
    WRONG_MESSAGE = "wrong_message"
    NOT_RELEVANT = "not_relevant"
    HANDLED_ELSEWHERE = "handled_elsewhere"
    OTHER = "other"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # identity of an Eitaa chat inside one account — the dedup anchor
        UniqueConstraint("eitaa_account_id", "peer_type", "peer_id", name="uq_conversation_peer"),
        Index("ix_conversations_status_answer", "status", "answer_state"),
        Index("ix_conversations_assigned", "assigned_agent_id"),
        Index("ix_conversations_last_message", "last_message_at"),
        Index("ix_conversations_account_status", "eitaa_account_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eitaa_account_id: Mapped[int] = mapped_column(
        ForeignKey("eitaa_accounts.id", ondelete="CASCADE"), nullable=False
    )

    # Eitaa peer identity
    peer_type: Mapped[str] = mapped_column(String(10), nullable=False)  # user|chat|channel
    peer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    access_hash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    peer_kind: Mapped[str] = mapped_column(
        String(12), default="private", nullable=False
    )  # private|group|supergroup|channel

    # denormalized user profile (kept fresh by the sync worker)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    username: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- the three state dimensions ---
    status: Mapped[str] = mapped_column(
        Enum(ConversationStatus), default=ConversationStatus.ACTIVE, nullable=False
    )
    read_state: Mapped[str] = mapped_column(
        Enum(ReadState), default=ReadState.UNREAD, nullable=False
    )
    answer_state: Mapped[str] = mapped_column(
        Enum(AnswerState), default=AnswerState.UNANSWERED, nullable=False
    )

    # assignment
    assigned_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # skip metadata (§12)
    skipped_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # message aggregates (maintained server-side, source of truth for filters)
    last_message_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_preview: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    last_inbound_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_outbound_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unread_eitaa_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # SLA metrics
    first_inbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_agent_reply_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # close metadata
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    eitaa_account: Mapped["EitaaAccount"] = relationship(  # noqa: F821
        back_populates="conversations"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )
    notes: Mapped[list["InternalNote"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    assigned_agent: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[assigned_agent_id]
    )

    # ---------------------------------------------------------------- helpers
    @property
    def peer_reference(self) -> str:
        """A reusable eitaa-cli peer reference string."""
        if self.peer_type == "user":
            return f"user:{self.peer_id}:{self.access_hash or 0}"
        if self.peer_type == "channel":
            return f"channel:{self.peer_id}:{self.access_hash or 0}"
        return f"chat:{self.peer_id}"

    @property
    def deep_link(self) -> str | None:
        """https://eitaa.com/USERNAME — only when Eitaa gave us a real username.
        Never guess a link (spec §7)."""
        return f"https://eitaa.com/{self.username}" if self.username else None


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # duplicate protection: one row per Eitaa message per conversation.
        # conversation_id is 1:1 with (eitaa_account_id, peer_type, peer_id),
        # so this is exactly the (account, peer, message_id) uniqueness required
        # by the spec, enforced with a tighter key.
        UniqueConstraint("conversation_id", "eitaa_message_id", name="uq_message_eitaa"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_direction", "conversation_id", "direction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    eitaa_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    direction: Mapped[Enum] = mapped_column(Enum(MessageDirection), nullable=False)
    source: Mapped[str] = mapped_column(
        String(12), default=MessageSource.SYNC.value, nullable=False
    )

    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sender_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sender_eitaa_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # reply relationship (§17)
    reply_to_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    send_status: Mapped[str] = mapped_column(
        Enum(SendStatus), default=SendStatus.SENT, nullable=False, index=True
    )
    error_message: Mapped[str | None] = mapped_column(String(300), nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    reply_to: Mapped["Message | None"] = relationship(
        remote_side=[id], foreign_keys=[reply_to_message_id]
    )
    attachment: Mapped["MessageAttachment | None"] = relationship(
        back_populates="message", cascade="all, delete-orphan", uselist=False
    )


class MessageAttachment(Base):
    """Media metadata for a message. Binary content is fetched lazily from
    Eitaa (file_reference tokens expire) and cached in UPLOADS_DIR."""

    __tablename__ = "message_attachments"
    __table_args__ = (Index("ix_attachments_download_status", "download_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String(12), nullable=False
    )  # photo|voice|audio|video|document
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eitaa_file_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    download_status: Mapped[str] = mapped_column(
        String(16), default="not_downloaded", nullable=False
    )  # not_downloaded | downloading | downloaded | failed
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    message: Mapped["Message"] = relationship(back_populates="attachment")


class InternalNote(Base):
    """Internal note — never sent to the Eitaa user (§14)."""

    __tablename__ = "internal_notes"
    __table_args__ = (Index("ix_notes_conversation", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="notes")
