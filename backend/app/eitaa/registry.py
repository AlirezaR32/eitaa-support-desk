"""Account registry: resolves a DB EitaaAccount into an EitaaSession (decrypted,
in-memory only) and exposes the active adapter.

The adapter is injectable: tests substitute a fake; production uses EitaaCliAdapter.
"""

from __future__ import annotations

from app.core.security import session_vault
from app.eitaa.adapter import EitaaCliAdapter
from app.eitaa.base import EitaaClientAdapter, EitaaSession
from app.eitaa.exceptions import EitaaAuthRequiredError
from app.models import EitaaAccount


class EitaaRegistry:
    def __init__(self, adapter: EitaaClientAdapter | None = None) -> None:
        self.adapter: EitaaClientAdapter = adapter or EitaaCliAdapter()

    # ------------------------------------------------------------------ session
    def session_for(self, account: EitaaAccount) -> EitaaSession:
        if not account.session_encrypted:
            raise EitaaAuthRequiredError(
                f"Eitaa account {account.id} has no stored session (not connected)"
            )
        payload = session_vault.decrypt(account.session_encrypted)
        if payload is None:
            raise EitaaAuthRequiredError(
                f"Eitaa account {account.id} session could not be decrypted — "
                "EITAA_SESSION_ENCRYPTION_KEY changed or data corrupted"
            )
        return EitaaSession(
            phone_number=payload.get("phone_number") or account.phone_number,
            token=payload.get("token", ""),
            imei=payload.get("imei", ""),
            user=payload.get("user"),
        )

    def store_session(self, account: EitaaAccount, session: EitaaSession) -> None:
        account.session_encrypted = session_vault.encrypt(
            {
                "phone_number": session.phone_number,
                "token": session.token,
                "imei": session.imei,
                "user": session.user,
            }
        )

    def drop_session(self, account: EitaaAccount) -> None:
        account.session_encrypted = None


# module-level default; the FastAPI app may replace it (tests do)
registry = EitaaRegistry()


def get_registry() -> EitaaRegistry:
    return registry
