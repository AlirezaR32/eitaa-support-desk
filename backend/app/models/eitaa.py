"""Eitaa accounts, login challenges (OTP flow) and agent-account links."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EitaaAccountStatus(str, enum.Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class EitaaAccount(Base):
    """A connected Eitaa account (support identity).

    `session_encrypted` holds a Fernet-encrypted JSON payload with the fields
    eitaa-cli needs to operate the account: {phone_number, token, imei, user}.
    It is NEVER stored or logged in plaintext.
    """

    __tablename__ = "eitaa_accounts"
    __table_args__ = (UniqueConstraint("phone_number", name="uq_eitaa_accounts_phone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    eitaa_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=EitaaAccountStatus.PENDING.value, nullable=False, index=True
    )
    session_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    agent_links: Mapped[list["EitaaAccountLink"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )
    conversations: Mapped[list["Conversation"]] = relationship(  # noqa: F821
        back_populates="eitaa_account"
    )

    @property
    def is_connected(self) -> bool:
        return (
            self.status == EitaaAccountStatus.CONNECTED.value and self.session_encrypted is not None
        )


class EitaaAccountLink(Base):
    """Which agents serve conversations of which Eitaa account (multi-account)."""

    __tablename__ = "agent_eitaa_accounts"
    __table_args__ = (UniqueConstraint("agent_id", "eitaa_account_id", name="uq_agent_account"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    eitaa_account_id: Mapped[int] = mapped_column(
        ForeignKey("eitaa_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    agent: Mapped["User"] = relationship(back_populates="eitaa_account_links")  # noqa: F821
    account: Mapped[EitaaAccount] = relationship(back_populates="agent_links")


class AuthChallenge(Base):
    """A pending Eitaa OTP challenge (phone + encrypted phone_code_hash).

    phone_code_hash is temporary sensitive authentication state — stored
    encrypted, auto-expiring, never logged.
    """

    __tablename__ = "auth_challenges"
    __table_args__ = (Index("ix_auth_challenges_expires", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_code_hash_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    delivery: Mapped[str] = mapped_column(String(20), default="sms", nullable=False)
    next_delivery: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
