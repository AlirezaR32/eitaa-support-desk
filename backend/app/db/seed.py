"""Seed roles, permissions and the bootstrap Owner.

Usage:
    python -m app.db.seed                # uses env BOOTSTRAP_OWNER_*
    python -m app.db.seed --email a@b.c --password '...' --name 'Owner'
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.permissions import (
    ALL_PERMISSION_CODES,
    PERMISSIONS,
    ROLE_DESCRIPTIONS,
    SYSTEM_ROLES,
)
from app.core.security import hash_password
from app.db.session import dispose_engine, get_session_factory
from app.models import Permission, Role, RolePermission, User


async def seed(
    *,
    owner_email: str | None,
    owner_password: str | None,
    owner_name: str | None,
) -> int:
    """Idempotent. Returns the owner user id (existing or created)."""
    factory = get_session_factory()
    async with factory() as db:
        # permissions
        for code in ALL_PERMISSION_CODES:
            existing = (
                await db.execute(select(Permission).where(Permission.code == code))
            ).scalar_one_or_none()
            if existing is None:
                db.add(Permission(code=code, description=PERMISSIONS[code][0]))
        await db.flush()

        # roles + role_permissions
        for role_name in SYSTEM_ROLES:
            role = (
                await db.execute(select(Role).where(Role.name == role_name))
            ).scalar_one_or_none()
            if role is None:
                role = Role(
                    name=role_name,
                    description=ROLE_DESCRIPTIONS.get(role_name),
                    is_system=True,
                )
                db.add(role)
                await db.flush()
            codes = {c for c in ALL_PERMISSION_CODES if role_name in PERMISSIONS[c][1]}
            existing_codes = set(
                (
                    await db.execute(
                        select(Permission.code)
                        .join(RolePermission, RolePermission.permission_id == Permission.id)
                        .where(RolePermission.role_id == role.id)
                    )
                )
                .scalars()
                .all()
            )
            for code in codes - existing_codes:
                perm = (
                    await db.execute(select(Permission).where(Permission.code == code))
                ).scalar_one()
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await db.flush()

        # bootstrap owner
        owner_role = (await db.execute(select(Role).where(Role.name == "owner"))).scalar_one()
        owner = (
            await db.execute(select(User).where(User.role_id == owner_role.id))
        ).scalar_one_or_none()
        if owner is not None:
            await db.commit()
            print(f"Owner already exists: {owner.email} (id={owner.id})")
            return owner.id

        email = (owner_email or settings.bootstrap_owner_email or "").strip().lower()
        password = owner_password or settings.bootstrap_owner_password
        name = owner_name or settings.bootstrap_owner_name or "Owner"
        if not email or not password:
            print(
                "No owner exists. Provide credentials:\n"
                "  python -m app.db.seed --email owner@example.com --password 'StrongPass!' --name 'Owner'\n"
                "or set BOOTSTRAP_OWNER_EMAIL / BOOTSTRAP_OWNER_PASSWORD in the environment."
            )
            await db.commit()
            return -1
        owner = User(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role_id=owner_role.id,
            is_active=True,
        )
        db.add(owner)
        await db.commit()
        print(f"Owner created: {email} (id={owner.id})")
        return owner.id


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed roles/permissions/owner")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--name")
    args = parser.parse_args()

    configure_logging()

    async def _run() -> int:
        try:
            return await seed(
                owner_email=args.email,
                owner_password=args.password,
                owner_name=args.name,
            )
        finally:
            await dispose_engine()

    code = asyncio.run(_run())
    sys.exit(0 if code >= 0 else 1)


if __name__ == "__main__":
    main()
