"""search indexes: pg_trgm + GIN (best effort)

Revision ID: b1f2c3d4e5f6
Revises: 7a87c1488ada
Create Date: 2026-09-30

pg_trgm accelerates ILIKE/substring search (including Persian text) on names
and message bodies. The extension is available on virtually every managed
PostgreSQL (Neon/Supabase/Render/Railway/RDS); if the host disallows it, the
migration logs a warning and continues — search still works via plain ILIKE,
just without the trigram index.
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1f2c3d4e5f6"
down_revision: Union[str, None] = "7a87c1488ada"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.search_indexes")


def upgrade() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    conn = op.get_bind()
    try:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        conn.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - host dependent
        logger.warning("pg_trgm extension unavailable, skipping GIN trgm indexes: %s", exc)
        return

    try:
        op.create_index(
            "ix_conversations_title_trgm",
            "conversations",
            [sa.text("title gin_trgm_ops")],
            postgresql_using="gin",
        )
        op.create_index(
            "ix_messages_text_trgm",
            "messages",
            [sa.text("text gin_trgm_ops")],
            postgresql_using="gin",
        )
    except SQLAlchemyError as exc:  # pragma: no cover
        logger.warning("trigram index creation failed (non-fatal): %s", exc)


def downgrade() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    for index in ("ix_messages_text_trgm", "ix_conversations_title_trgm"):
        try:
            op.drop_index(index)
        except SQLAlchemyError:  # pragma: no cover
            pass
