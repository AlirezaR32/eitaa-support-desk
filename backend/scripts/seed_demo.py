"""DEVELOPMENT-ONLY demo data seeder.

Creates sample conversations/messages/notes directly in the database so the
panel can be explored without a real Eitaa connection. This does NOT touch the
Eitaa API and does NOT fake any adapter capability — it writes local rows only.
Never use in production.

Usage:
    python -m scripts.seed_demo --email owner@desk.local
"""

from __future__ import annotations

import argparse
import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.logging import configure_logging
from app.db.session import dispose_engine, get_session_factory
from app.models import (
    AnswerState,
    Conversation,
    ConversationStatus,
    EitaaAccount,
    EitaaAccountStatus,
    EitaaAccountLink,
    InternalNote,
    Message,
    MessageDirection,
    MessageSource,
    ReadState,
    SendStatus,
    User,
)

NAMES = [
    ("علی رضایی", "ali_rezaei", 989121110001),
    ("سارا محمدی", "sara_m", 989121110002),
    ("محمد کریمی", "m_karimi", 989121110003),
    ("نگار احمدی", "negar_a", 989121110004),
    ("حسین موسوی", "h_mousavi", 989121110005),
    ("مریم صادقی", "maryam_s", 989121110006),
    ("رضا نوری", "reza_nouri", 989121110007),
    ("فاطمه جعفری", "f_jafari", 989121110008),
]

SCRIPTS = [
    ["سلام، وقتتون بخیر", "ببخشید چطور می‌تونم ثبت‌نام کنم؟"],
    ["سلام", "پکیجم هنوز نرسیده امکانش هست پیگیری کنید؟"],
    ["سلام خسته نباشید", "برای تغییر شماره موبایل باید چیکار کنم؟"],
    ["درود", "لینک پرداخت برای من باز نمی‌شه"],
    ["سلام", "امکان ارسال فاکتور رسمی هست؟"],
    ["ببخشید مزاحم شدم", "اکانتم مسدود شده دلیلش چیه؟"],
    ["سلام وقت بخیر", "چند روز طول می‌کشه تا سفارش ارسال بشه؟"],
    ["سلام", "کد تخفیف ندارید؟"],
]

REPLIES = [
    "سلام، در خدمت شما هستیم 🌸",
    "حالا بررسی می‌کنم و نتیجه را همین‌جا اعلام می‌کنم.",
    "لطفًا شماره سفارش را ارسال کنید.",
]


async def seed_demo(owner_email: str) -> None:
    factory = get_session_factory()
    async with factory() as db:
        owner = (
            await db.execute(select(User).where(User.email == owner_email))
        ).scalar_one_or_none()
        if owner is None:
            print(f"owner {owner_email} not found — run app.db.seed first")
            return

        account = (
            await db.execute(select(EitaaAccount).where(EitaaAccount.phone_number == "09120009999"))
        ).scalar_one_or_none()
        if account is None:
            account = EitaaAccount(
                phone_number="09120009999",
                display_name="پشتیبانی دمو",
                username="demo_support",
                eitaa_user_id=999,
                status=EitaaAccountStatus.CONNECTED.value,
                sync_enabled=False,  # demo rows only — no real sync
            )
            db.add(account)
            await db.flush()
            db.add(EitaaAccountLink(agent_id=owner.id, eitaa_account_id=account.id))

        rng = random.Random(42)
        now = datetime.now(timezone.utc)

        existing = (
            await db.execute(select(Conversation).where(Conversation.eitaa_account_id == account.id))
        ).scalar_one_or_none()
        if existing:
            print("demo conversations already exist — skipping")
            await db.commit()
            return

        for index, (name, username, phone) in enumerate(NAMES):
            style = index % 4
            conversation = Conversation(
                eitaa_account_id=account.id,
                peer_type="user",
                peer_id=5000 + index,
                access_hash=7000 + index,
                peer_kind="private",
                title=name,
                username=username,
                phone=f"+{phone}",
                status=ConversationStatus.ACTIVE,
                read_state=ReadState.READ if style in (1, 3) else ReadState.UNREAD,
                answer_state=AnswerState.ANSWERED if style == 3 else AnswerState.UNANSWERED,
                assigned_agent_id=owner.id if style == 2 else None,
                assigned_at=now - timedelta(hours=1) if style == 2 else None,
            )
            if style == 3:
                conversation.status = ConversationStatus.CLOSED
                conversation.closed_at = now - timedelta(hours=2)
            db.add(conversation)
            await db.flush()

            base = now - timedelta(hours=8 - index, minutes=rng.randint(0, 50))
            script = SCRIPTS[index % len(SCRIPTS)]
            message_id = 100
            first_inbound = None
            for line_index, line in enumerate(script):
                sent_at = base + timedelta(minutes=5 * line_index)
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        eitaa_message_id=message_id,
                        direction=MessageDirection.INBOUND,
                        source=MessageSource.SYNC.value,
                        text=line,
                        sender_eitaa_user_id=5000 + index,
                        send_status=SendStatus.SENT,
                        sent_at=sent_at,
                        created_at=sent_at,
                    )
                )
                message_id += 1
                if first_inbound is None:
                    first_inbound = sent_at

            last_at = base + timedelta(minutes=5 * len(script))
            if style in (1, 3):  # answered
                reply_at = last_at + timedelta(minutes=3)
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        eitaa_message_id=message_id,
                        direction=MessageDirection.OUTBOUND,
                        source=MessageSource.PANEL.value,
                        text=REPLIES[index % len(REPLIES)],
                        sender_agent_id=owner.id,
                        send_status=SendStatus.SENT,
                        sent_at=reply_at,
                        created_at=reply_at,
                    )
                )
                conversation.first_agent_reply_at = reply_at
                last_at = reply_at

            conversation.first_inbound_at = first_inbound
            conversation.last_inbound_message_at = last_at if style != 3 else first_inbound
            conversation.last_message_at = last_at
            conversation.last_message_preview = script[-1]
            conversation.last_message_id = message_id

            if index == 4:
                db.add(
                    InternalNote(
                        conversation_id=conversation.id,
                        author_id=owner.id,
                        body="این کاربر درباره ثبت‌نام سوال دارد. احتمالاً باید به بخش آموزش ارجاع شود.",
                        created_at=now - timedelta(minutes=30),
                    )
                )

        await db.commit()
        print("demo data seeded: 8 conversations, 1 demo account (sync disabled)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="owner@desk.local")
    args = parser.parse_args()
    configure_logging()

    async def run() -> None:
        try:
            await seed_demo(args.email)
        finally:
            await dispose_engine()

    asyncio.run(run())


if __name__ == "__main__":
    main()
